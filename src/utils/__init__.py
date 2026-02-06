from math import ceil
from typing import overload, Union, BinaryIO, Optional
import io
import struct

def khux_rand(seed: int) -> int:
    return (0x19660D * seed + 0x3C6EF35F) & 0xFFFFFFFF


@overload
def khux_decrypt(data: bytes, key: int, length: Optional[int] = None) -> bytes: ...

@overload
def khux_decrypt(data: bytearray, key: int, length: Optional[int] = None) -> bytes: ...

@overload
def khux_decrypt(data: BinaryIO, key: int, length: Optional[int] = None) -> bytes: ...


def khux_decrypt(data: Union[bytes, bytearray, BinaryIO], key: int, length: Optional[int] = None) -> bytes:
    if isinstance(data, (bytes, bytearray)):
        stream = io.BytesIO(data)
        max_len = length if length is not None else len(data)
    else:
        stream: io.BytesIO = data # type: ignore
        if length is None:
            raise ValueError("Length must be specified when data is a stream.")
        max_len = length

    output = bytearray(max_len)  # preallocate
    current_key = key
    bytes_processed = 0

    while bytes_processed < max_len:
        chunk = stream.read(4)
        actual_len = len(chunk)
        if actual_len == 0:
            break

        if actual_len < 4:
            chunk = chunk.ljust(4, b"\x00")

        current_key = khux_rand(current_key) & 0xFFFFFFFF
        val = int.from_bytes(chunk, "little")
        decrypted = ((val ^ current_key) & 0xFFFFFFFF).to_bytes(4, "little")

        output[bytes_processed : bytes_processed + actual_len] = decrypted[:actual_len]
        bytes_processed += actual_len

    return bytes(output)
