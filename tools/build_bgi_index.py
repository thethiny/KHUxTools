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


def resolve_stub_chains(entries):
    """Follow 4-byte stub chains to find the real entry offset for each name.

    Stub values index into a table of REAL (non-stub) entries only — not the
    full sequential BGAD order. Build the real-entry table first, then resolve.
    Returns [(name, resolved_offset), ...] with stubs resolved to their final target.
    """
    # Build table of real (non-stub) entries in sequential order
    real_table = []  # [(name, offset, size, data), ...]
    for e in entries:
        if e[2] != 4:  # size != 4 → real entry
            real_table.append(e)

    print(f"  real entries: {len(real_table)}, stubs: {len(entries) - len(real_table)}")

    resolved = []
    stub_count = 0

    for i, (name, offset, size, data) in enumerate(entries):
        if size == 4:
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


def wrap_in_bgad(bgi_data):
    """Wrap BGI data in a BGAD entry with name '/', mode 2 LCG encryption + zlib."""
    import zlib

    name_raw = b"/"
    name_length = len(name_raw)  # 1
    decomp_size = len(bgi_data)

    # Compress with zlib
    compressed = zlib.compress(bgi_data)
    data_size = len(compressed)

    # Encrypt name with mode 2 LCG, seed = data_size
    from khux.utils.crypto import khux_encrypt
    name_encrypted = khux_encrypt(name_raw, seed=data_size, mode=2)

    # Encrypt data with mode 2 LCG, seed = name_length
    data_encrypted = khux_encrypt(compressed, seed=name_length, mode=2)

    # BGAD header: <4sHHHHHHII
    header = struct.pack("<4sHHHHHHII",
        b"BGAD",      # magic
        2,            # version
        0,            # flags
        24,           # header_size
        name_length,  # name_length (also LCG seed for data decryption)
        2,            # encryption_mode
        2,            # compression_mode (zlib)
        data_size,    # data_size (also LCG seed for name decryption)
        decomp_size,  # decompressed_size
    )

    return header + name_encrypted + data_encrypted


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

    print("Wrapping in BGAD (mode 2 LCG + zlib)...")
    bgad_data = wrap_in_bgad(bgi_data)
    print(f"  BGAD size: {len(bgad_data)} bytes")

    with open(out_path, "wb") as f:
        f.write(bgad_data)
    print(f"Saved to {out_path}")


if __name__ == "__main__":
    main()
