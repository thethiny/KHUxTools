from math import ceil
from typing import overload, Union, BinaryIO, Optional
import io
import struct

def khux_rand(seed: int) -> int:
    return (0x19660D * seed + 0x3C6EF35F) & 0xFFFFFFFF


@overload
def khux_decrypt(data: bytes, seed: int, mode: int, length: Optional[int] = None) -> bytes: ...

@overload
def khux_decrypt(data: bytearray, seed: int, mode: int, length: Optional[int] = None) -> bytes: ...

@overload
def khux_decrypt(data: BinaryIO, seed: int, mode: int, length: Optional[int] = None) -> bytes: ...


def khux_decrypt(data: Union[bytes, bytearray, BinaryIO], seed: int, mode: int, length: Optional[int] = None) -> bytes:
    if isinstance(data, (bytes, bytearray)):
        stream = io.BytesIO(data)
        max_len = length if length is not None else len(data)
    else:
        stream: io.BytesIO = data # type: ignore
        if length is None:
            raise ValueError("Length must be specified when data is a stream.")
        max_len = length

    output = bytearray(max_len)  # preallocate
    s = seed & 0xFFFFFFFF
    bytes_processed = 0

    chunk_size = 1 << 20 # 1 MB
    chunk_size -= (chunk_size % 4) # align to 4 bytes

    if mode == 1:
        s = seed & 0xFFFFFFFF
        pos = 0
        while pos < max_len:
            chunk = stream.read(min(chunk_size, max_len - pos))
            if not chunk:
                break
            for i in range(len(chunk)):
                s = khux_rand(s) & 0xFFFFFFFF
                output[pos + i] = chunk[i] ^ (s & 0xFF)
            pos += len(chunk)
    elif mode == 2:
        while bytes_processed < max_len:
            want = min(chunk_size, max_len - bytes_processed)
            chunk = stream.read(want)
            n = len(chunk)
            if n == 0:
                break
            
            full = n & ~3
            mv = memoryview(chunk)
            
            for off in range(0, full, 4):
                s = khux_rand(s) & 0xFFFFFFFF
                val = struct.unpack_from("<I", mv, off)[0]
                struct.pack_into("<I", output, bytes_processed + off, (val ^ s) & 0xFFFFFFFF)

            tail = n - full
            if tail:
                s = khux_rand(s) & 0xFFFFFFFF
                tmp = mv[full:full+tail].tobytes() + b"\x00" * (4 - tail)
                val = struct.unpack("<I", tmp)[0]
                dec = struct.pack("<I", (val ^ s) & 0xFFFFFFFF)
                output[bytes_processed + full:bytes_processed + n] = dec[:tail]
                
            bytes_processed += n
    else:
        raise ValueError(f"Unsupported decryption mode: {mode}")

    return bytes(output)
