"""
Build a BGI index (misc.png) for a given misc.mp4 BGAD container.
Scans the BGAD to get entry names and file offsets, then creates a BGI archive.
"""
import io
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from khux.containers.bgad import KHUxBGADContainer, KHUxBGAD
from khux.models.bgad import BGADHeader
from khux.utils.crypto import chacha8_crypt, KEY_APK, KEY_DOWNLOAD, BGAD_NONCE_XOR, BGI_NONCE_XOR


def scan_bgad_entries(mp4_path):
    """Scan a misc.mp4 BGAD and return [(name, file_offset, data_size, data), ...]"""
    entries = []
    container = KHUxBGADContainer(mp4_path)
    count = 0
    for entry in container.iter_entries():
        data = entry.data
        entries.append((entry.name, entry.offset, len(data), data))
        count += 1
        if count % 1000 == 0:
            print(f"  scanned {count} entries...", flush=True)
    container.close()
    print(f"  total: {count} entries")
    return entries


def _is_stub(name, size, data):
    """A 4-byte entry is a stub UNLESS it's a .txt with valid printable ASCII."""
    if size != 4:
        return False
    if os.path.splitext(name)[1].lower() == ".txt":
        try:
            text = data.decode("utf-8")
            if all(32 <= ord(c) < 127 or c in "\n\r\t" for c in text):
                return False
        except (UnicodeDecodeError, ValueError):
            pass
    return True


def resolve_stub_chains(entries):
    """Follow 4-byte stub chains to find the real entry offset for each name.

    Stub values index into a table of REAL (non-stub) entries only — not the
    full sequential BGAD order. Build the real-entry table first, then resolve.

    4-byte .txt entries with valid ASCII content are treated as real data,
    not stubs — short strings like "Name", "Home", "SKIP" are legitimate.

    Returns [(name, resolved_offset), ...] with stubs resolved to their final target.
    """
    real_table = []
    txt_kept = 0
    for e in entries:
        if not _is_stub(e[0], e[2], e[3]):
            real_table.append(e)
            if e[2] == 4:
                txt_kept += 1

    stub_count_total = len(entries) - len(real_table)
    print(f"  real entries: {len(real_table)} ({txt_kept} are 4-byte .txt with ASCII content)")
    print(f"  stubs: {stub_count_total}")

    resolved = []
    stub_count = 0

    for i, (name, offset, size, data) in enumerate(entries):
        if _is_stub(name, size, data):
            target_idx = struct.unpack("<I", data[:4])[0]
            if target_idx < len(real_table):
                resolved.append((name, real_table[target_idx][1]))
                stub_count += 1
            else:
                resolved.append((name, offset))
        else:
            resolved.append((name, offset))

    print(f"  resolved {stub_count} stubs via real-entry table")
    return resolved


def build_bgi_payload(entries):
    """Build the plaintext BGI payload from (name, offset) pairs.

    Format:
      entry_count (u32)
      name_count (u32)
      entries[entry_count]: (offset u32, size u32) — size=0
      name_to_entry[name_count]: u32 — maps name index to entry index
      name_offsets[name_count]: u32 — offset into string blob
      string_blob: null-terminated strings
    """
    # Deduplicate entries by offset (some names map to the same entry)
    unique_offsets = {}
    name_list = []
    for name, offset in entries:
        if offset not in unique_offsets:
            unique_offsets[offset] = len(unique_offsets)
        entry_idx = unique_offsets[offset]
        name_list.append((name, entry_idx))

    entry_count = len(unique_offsets)
    name_count = len(name_list)

    # Build entry table (sorted by offset)
    offset_to_idx = {}
    sorted_offsets = sorted(unique_offsets.keys())
    entry_table = []
    for i, off in enumerate(sorted_offsets):
        entry_table.append((off, 0))  # size=0 like the original
        offset_to_idx[off] = i

    # Remap name_list entry indices to sorted order
    remapped_names = []
    for name, old_idx in name_list:
        orig_offset = [k for k, v in unique_offsets.items() if v == old_idx][0]
        new_idx = offset_to_idx[orig_offset]
        remapped_names.append((name, new_idx))

    # Build binary
    buf = io.BytesIO()

    # entry_count, name_count
    buf.write(struct.pack("<II", entry_count, name_count))

    # entries
    for offset, size in entry_table:
        buf.write(struct.pack("<II", offset, size))

    # name_to_entry
    for name, entry_idx in remapped_names:
        buf.write(struct.pack("<I", entry_idx))

    # Build string blob and name offsets
    string_blob = io.BytesIO()
    name_offsets = []
    for name, _ in remapped_names:
        name_offsets.append(string_blob.tell())
        string_blob.write(name.encode("utf-8") + b"\x00")

    # name_offsets
    for off in name_offsets:
        buf.write(struct.pack("<I", off))

    # string blob
    buf.write(string_blob.getvalue())

    return buf.getvalue()


def _make_bgad_entry(name_str, data, compress=True):
    """Create a single BGAD entry with mode 2 LCG encryption."""
    import zlib
    from khux.utils.crypto import khux_encrypt

    name_raw = name_str.encode("utf-8")
    name_length = len(name_raw)

    if compress:
        payload = zlib.compress(data)
        comp_mode = 2
        decomp_size = len(data)
    else:
        payload = data
        comp_mode = 0
        decomp_size = len(data)

    data_size = len(payload)
    name_encrypted = khux_encrypt(name_raw, seed=data_size, mode=2)
    data_encrypted = khux_encrypt(payload, seed=name_length, mode=2)

    header = struct.pack("<4sHHHHHHII",
        b"BGAD", 2, 0, 24,
        name_length, 2, comp_mode,
        data_size, decomp_size,
    )
    return header + name_encrypted + data_encrypted


def wrap_in_bgad(bgi_data, mp4_md5=None, mp4_size=None):
    """Wrap BGI data in BGAD entries: '/' + optional 'md5' + 'size' metadata."""
    result = _make_bgad_entry("/", bgi_data, compress=True)
    if mp4_md5:
        result += _make_bgad_entry("md5", mp4_md5.encode("ascii"), compress=False)
    if mp4_size is not None:
        result += _make_bgad_entry("size", str(mp4_size).encode("ascii"), compress=False)
    return result


ALIASES = {
    "lwf/avatar/costume/001/left_forearm_c/left_forearm_c.lwf": "lwf/avatar/costume/001/left_upperarm_c/left_upperarm_c.lwf",
    "lwf/avatar/costume/001/right_forearm_c/right_forearm_c.lwf": "lwf/avatar/costume/001/right_upperarm_c/right_upperarm_c.lwf",
    "lwf/avatar/costume/001/skart1/skart1.lwf": "lwf/avatar/costume/001/skart3/skart3.lwf",
    "lwf/avatar/costume/001/skart2/skart2.lwf": "lwf/avatar/costume/001/skart3/skart3.lwf",
    "lwf/avatar/keyblade/keyblade_0000_00/keyblade_0000_00.lwf": "lwf/avatar/keyblade/keyblade_0001_01/keyblade_0001_01.lwf",
}


def main():
    _data_dir = os.environ["KHUX_DATA_DIR"]
    _repo_dir = os.getenv("KHUX_REPO_DIR", os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    mp4_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_data_dir, "misc.mp4")
    out_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(_repo_dir, "Input/1.0.1/misc_generated.png")

    print(f"Scanning {mp4_path}...")
    raw_entries = scan_bgad_entries(mp4_path)

    print("Resolving stub chains...")
    entries = resolve_stub_chains(raw_entries)

    name_to_offset = {name: off for name, off in entries}
    alias_count = 0
    for alias_name, target_name in ALIASES.items():
        if target_name in name_to_offset and alias_name not in name_to_offset:
            entries.append((alias_name, name_to_offset[target_name]))
            alias_count += 1
            print(f"  ALIAS: {alias_name} -> {target_name} (offset {name_to_offset[target_name]})")
    print(f"  Added {alias_count} aliases")

    print(f"Building BGI payload ({len(entries)} names)...")
    bgi_payload = build_bgi_payload(entries)
    print(f"  BGI payload size: {len(bgi_payload)} bytes")

    # Prepend BGI header (unencrypted, version 3, flags=0)
    bgi_header = struct.pack("<4sII", b"\x89BGI", 3, 0)
    bgi_data = bgi_header + bgi_payload
    print(f"  BGI total size: {len(bgi_data)} bytes (unencrypted, will compress in BGAD)")

    import hashlib
    print(f"Computing MP4 MD5...")
    h = hashlib.md5()
    with open(mp4_path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    mp4_md5 = h.hexdigest()
    mp4_size = os.path.getsize(mp4_path)
    print(f"  MP4 md5={mp4_md5}, size={mp4_size}")

    print("Wrapping in BGAD (mode 2 LCG + zlib)...")
    bgad_data = wrap_in_bgad(bgi_data, mp4_md5=mp4_md5, mp4_size=mp4_size)
    print(f"  BGAD size: {len(bgad_data)} bytes")

    with open(out_path, "wb") as f:
        f.write(bgad_data)
    print(f"Saved to {out_path}")


if __name__ == "__main__":
    main()
