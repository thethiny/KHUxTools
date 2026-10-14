"""Read files out of the late-version OBBs (main.76 + patch.87, 4.4.0 / 5.0.1) by path.

The OBB records' names are per-build encrypted paths (not computable), but the client never uses them: it finds
files through an index, `aliud.png` (5.0.1 assets/aliud.png covers main.76 + patch.87 completely; the 4.4.0 APK's is
older). Format (5.0.1 decompile, libcocos2dcpp_0016.c / _0033.c):
- aliud.png is a BGAD wrapper; its record holding `\\x89BGI` v3 is the index: ChaCha8 (KEY_DOWNLOAD, nonce = last 8
  bytes XOR BGI_NONCE_XOR) of `u32 nEntries, u32 nNames, u64 offset[nEntries], u32 nameToEntry[nNames],
  u32 nameOff[nNames], names blob` (the client hashes names with XXH32, seed 0).
- an entry offset is a byte position in main.76 + patch.87 concatenated.
- a record: BGAD header `<4sHHHHHHII` (magic, ver, flags, header size, name len, mode, compressed, data size,
  decompressed size); data after header + name. mode 1/2: LCG seeded by the name length; mode 3: ChaCha8
  (KEY_DOWNLOAD) with nonce = trailing 8 bytes; then zlib when compressed.

    python tools/obb_read.py list <aliud.png> [regex]          list paths
    python tools/obb_read.py get <aliud.png> <path> [out]       extract one file
OBB paths default to Input/main.76...obb and Input/patch.87...obb (KHUX_OBB_MAIN / KHUX_OBB_PATCH override).
"""
import os
import re
import struct
import sys
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from khux.containers.bgad import KHUxBGADContainer  # noqa: E402
from khux.utils.crypto import BGI_NONCE_XOR, KEY_APK, KEY_DOWNLOAD, KEY_SAVE, chacha8_crypt, khux_decrypt  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..", "Input")
MAIN = os.environ.get("KHUX_OBB_MAIN", os.path.join(ROOT, "main.76.com.square_enix.android_googleplay.khuxww.obb"))
PATCH = os.environ.get("KHUX_OBB_PATCH", os.path.join(ROOT, "patch.87.com.square_enix.android_googleplay.khuxww.obb"))
HDR = struct.Struct("<4sHHHHHHII")


def load_index(aliud_path):
    """{path: offset} from an aliud.png index."""
    c = KHUxBGADContainer(aliud_path)
    raw = next(e.data for e in c.iter_entries() if e.data[:4] == b"\x89BGI")
    c.close()
    body, nonce = raw[12:-8], bytes(a ^ b for a, b in zip(raw[-8:], BGI_NONCE_XOR))
    for key in (KEY_DOWNLOAD, KEY_APK, KEY_SAVE):
        p = chacha8_crypt(body, key, nonce)
        ne, nn = struct.unpack_from("<II", p, 0)
        if ne < 10 ** 7 and nn < 10 ** 7 and 8 + ne * 8 + nn * 8 <= len(p):
            off = 8
            offs = struct.unpack_from("<%dQ" % ne, p, off)
            off += 8 * ne
            n2e = struct.unpack_from("<%dI" % nn, p, off)
            off += 4 * nn
            noff = struct.unpack_from("<%dI" % nn, p, off)
            blob = p[off + 4 * nn:]
            out = {}
            for i in range(nn):
                s = noff[i]
                out[blob[s:blob.index(0, s)].decode("utf-8", "replace")] = offs[n2e[i]]
            return out
    raise ValueError("could not decrypt the index")


def read(offset):
    """The decoded file at a joined main+patch offset."""
    main_size = os.path.getsize(MAIN)
    path, o = (MAIN, offset) if offset < main_size else (PATCH, offset - main_size)
    with open(path, "rb") as f:
        f.seek(o)
        _m, _v, _fl, hs, nl, mode, cmp, ds, _dsz = HDR.unpack(f.read(HDR.size))
        f.seek(o + hs + nl)
        d = f.read(ds)
    if mode in (1, 2):
        d = khux_decrypt(d, nl, mode)
    elif mode == 3:
        d = khux_decrypt(d[:-8], 0, 3, key=KEY_DOWNLOAD, nonce=d[-8:])
    return zlib.decompress(d) if cmp else d


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ("list", "get"):
        sys.exit(__doc__)
    idx = load_index(sys.argv[2])
    if sys.argv[1] == "list":
        pat = re.compile(sys.argv[3]) if len(sys.argv) > 3 else None
        for p in sorted(idx):
            if not pat or pat.search(p):
                print(p)
    else:
        data = read(idx[sys.argv[3]])
        out = sys.argv[4] if len(sys.argv) > 4 else os.path.basename(sys.argv[3])
        open(out, "wb").write(data)
        print(f"{sys.argv[3]} -> {out} ({len(data)} bytes)")


if __name__ == "__main__":
    main()
