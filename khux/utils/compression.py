from typing import Generator
import zlib

def decompress(data: bytes) -> bytes:
    try:
        return zlib.decompress(data)
    except zlib.error as e:
        raise ValueError(f"Decompression failed: {e}")