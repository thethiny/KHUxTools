from typing import Generator
import zlib

# def decompress(data: bytes) -> Generator[bytes, None, None]:
#     """Decompresses the given data using zlib's deflate algorithm."""
#     try:
#         data_size = len(data)
        
#         out = b""
#         has_remaining = True
#         d = zlib.decompressobj()
#         while has_remaining:
#             out = d.decompress(data)
#             out += d.flush()

#             bytes_consumed = data_size - len(d.unused_data)
#             has_remaining = d.unconsumed_tail != b""
#             yield out
#             data = data[bytes_consumed:]

#         if has_remaining or d.unused_data:
#             raise ValueError("Decompression did not consume all input data!")

#     except zlib.error as e:
#         raise ValueError(f"Decompression failed: {e}")

def decompress(data: bytes) -> bytes:
    try:
        return zlib.decompress(data)
    except zlib.error as e:
        raise ValueError(f"Decompression failed: {e}")