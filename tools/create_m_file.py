"""Create v1.0.1 BGAD m files from JSON data.

Bypasses the game's broken save function by directly creating
BGAD files with LCG-encrypted binary structs.

Usage:
    python tools/create_m_file.py server/data/stage.json stage m044.jpg
    python tools/create_m_file.py server/data/enemy.json enemy m009.jpg
"""
import json
import os
import struct
import sys
import time
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from khux.utils.crypto import khux_encrypt
from khux.formats.avatar import _msvc_lcg_keystream


def _make_bgad_header(name_len, data_size, decomp_size, enc_mode=2, comp_mode=2):
    return struct.pack("<4sHHHHHHII",
        b"BGAD", 2, 0, 24, name_len, enc_mode, comp_mode, data_size, decomp_size)


def _encrypt_master_payload(struct_bytes):
    """Wrap struct bytes in seed + size + LCG-encrypted payload."""
    seed = int(time.time()) & 0xFFFFFFFF
    payload_size = len(struct_bytes)
    keystream = _msvc_lcg_keystream(seed, payload_size)
    encrypted = bytes(a ^ b for a, b in zip(struct_bytes, keystream))
    return struct.pack("<II", seed, payload_size) + encrypted


def write_bgad_entry(f, name, raw_data, enc_mode=2, compress=True):
    """Write a single BGAD entry to file f."""
    name_bytes = name.encode("utf-8")
    name_len = len(name_bytes)

    if compress:
        compressed = zlib.compress(raw_data)
        data_on_disk = compressed
        decomp_size = len(raw_data)
        comp_mode = 2
    else:
        data_on_disk = raw_data
        decomp_size = len(raw_data)
        comp_mode = 0

    enc_name = khux_encrypt(name_bytes, len(data_on_disk), enc_mode)
    enc_data = khux_encrypt(data_on_disk, name_len, enc_mode)

    header = _make_bgad_header(name_len, len(enc_data), decomp_size, enc_mode, comp_mode)
    f.write(header)
    f.write(enc_name)
    f.write(enc_data)


def build_struct_from_json(entry, schema):
    """Convert a JSON entry to a binary struct using the schema."""
    buf = bytearray()
    prev_was_str = False
    for field_def in schema:
        name = field_def[0]
        ftype = field_def[1]
        val = entry.get(name, 0)

        if ftype not in ("str", "str[]") and prev_was_str:
            while len(buf) % 4:
                buf += b"\x00"
            prev_was_str = False

        if ftype == "int":
            buf += struct.pack("<i", val if isinstance(val, int) else 0)
        elif ftype == "uint":
            buf += struct.pack("<I", val if isinstance(val, int) else 0)
        elif ftype == "str":
            size = field_def[2]
            s = (val or "").encode("utf-8")[:size-1]
            buf += s.ljust(size, b"\x00")
            prev_was_str = True
        elif ftype == "str[]":
            count = field_def[2]
            size = field_def[3]
            arr = val if isinstance(val, list) else [""] * count
            for i in range(count):
                s = (arr[i] if i < len(arr) else "").encode("utf-8")[:size-1]
                buf += s.ljust(size, b"\x00")
            prev_was_str = True
        elif ftype == "int[]":
            count = field_def[2]
            arr = val if isinstance(val, list) else [0] * count
            for i in range(count):
                v = arr[i] if i < len(arr) else 0
                buf += struct.pack("<i", v)

    while len(buf) % 4:
        buf += b"\x00"
    return bytes(buf)


def create_m_file(json_path, table_name, output_path, schema=None):
    with open(json_path, encoding="utf-8") as f:
        entries = json.load(f)

    # Find primary key field (first field ending in "Id" or "id")
    if entries:
        pk = None
        for k in entries[0]:
            if k.endswith("Id") or k == "id":
                pk = k
                break
        if not pk:
            pk = list(entries[0].keys())[0]
    else:
        pk = "id"

    with open(output_path, "wb") as f:
        # Write table name entry
        write_bgad_entry(f, table_name, struct.pack("<I", 1))

        # Write revision entry
        write_bgad_entry(f, "revision", struct.pack("<I", 27))

        # Write each data entry
        for entry in entries:
            entry_id = str(entry.get(pk, 0))
            if schema:
                struct_bytes = build_struct_from_json(entry, schema)
                payload = _encrypt_master_payload(struct_bytes)
            else:
                # No schema — store raw JSON as the entry data
                payload = json.dumps(entry, separators=(",", ":")).encode("utf-8")

            write_bgad_entry(f, entry_id, payload)

    print(f"Created {output_path}: {len(entries)} entries ({os.path.getsize(output_path)} bytes)")


if __name__ == "__main__":
    from khux.formats.master import SCHEMAS

    json_path = sys.argv[1]
    table_name = sys.argv[2] if len(sys.argv) > 2 else None
    output_path = sys.argv[3] if len(sys.argv) > 3 else "output.jpg"

    schema = SCHEMAS.get(table_name) if table_name else None
    if not table_name:
        table_name = os.path.splitext(os.path.basename(json_path))[0]

    create_m_file(json_path, table_name, output_path, schema)
