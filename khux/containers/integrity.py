import struct
from dataclasses import dataclass
from typing import Optional, Tuple

from khux.utils.crypto import _chacha20_crypt


INTEGRITY_KEY = bytes.fromhex(
    "3C8499BF7EEE43BD1B4DDE853725A110F0914C76C167BE9D3C902CBEE790B03E"
)

BGAD_NONCE_XOR = bytes([0x62, 0xC0, 0xD9, 0x49, 0x9B, 0x15, 0x83, 0x72])


@dataclass
class ContainerIntegrity:
    root_data: bytes
    md5_hash: Optional[str]
    declared_size: Optional[int]
    is_valid: bool


def verify_container_integrity(entries: list) -> ContainerIntegrity:
    root_data = b""
    md5_hash = None
    declared_size = None

    for entry in entries:
        if entry.name == "/" or entry.name == "<encrypted:>":
            root_data = entry.data
        elif entry.name == "md5":
            md5_hash = entry.data.decode("ascii", errors="replace")
        elif entry.name == "size":
            try:
                declared_size = int(entry.data.decode("ascii"))
            except (ValueError, UnicodeDecodeError):
                pass

    is_valid = len(root_data) > 0 and md5_hash is not None
    return ContainerIntegrity(
        root_data=root_data,
        md5_hash=md5_hash,
        declared_size=declared_size,
        is_valid=is_valid,
    )


def decrypt_integrity_entry(
    payload: bytes, nonce_raw: bytes, key: bytes = INTEGRITY_KEY
) -> bytes:
    nonce = bytes(a ^ b for a, b in zip(nonce_raw, BGAD_NONCE_XOR))
    return _chacha20_crypt(payload, key, nonce)
