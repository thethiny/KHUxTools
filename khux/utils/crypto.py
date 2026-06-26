import struct
from typing import Optional, Union
from io import BytesIO, BufferedReader


def _khux_rand(seed: int) -> int:
    return (0x19660D * seed + 0x3C6EF35F) & 0xFFFFFFFF


def _decrypt_mode1(data: bytes, seed: int) -> bytes:
    out = bytearray(len(data))
    s = seed & 0xFFFFFFFF
    for i in range(len(data)):
        s = _khux_rand(s)
        out[i] = data[i] ^ (s & 0xFF)
    return bytes(out)


def _encrypt_mode1(data: bytes, seed: int) -> bytes:
    return _decrypt_mode1(data, seed)


def _decrypt_mode2(data: bytes, seed: int) -> bytes:
    out = bytearray(data)
    n = len(data)
    full = n & ~3
    s = seed & 0xFFFFFFFF

    for off in range(0, full, 4):
        s = _khux_rand(s)
        val = struct.unpack_from("<I", out, off)[0]
        struct.pack_into("<I", out, off, (val ^ s) & 0xFFFFFFFF)

    tail = n - full
    if tail:
        s = _khux_rand(s)
        tmp = bytes(out[full:]) + b"\x00" * (4 - tail)
        val = struct.unpack("<I", tmp)[0]
        dec = struct.pack("<I", (val ^ s) & 0xFFFFFFFF)
        out[full:n] = dec[:tail]

    return bytes(out)


def _encrypt_mode2(data: bytes, seed: int) -> bytes:
    return _decrypt_mode2(data, seed)


BGAD_NONCE_XOR = bytes([0x62, 0xC0, 0xD9, 0x49, 0x9B, 0x15, 0x83, 0x72])


def _chacha20_quarterround(x: list, a: int, b: int, c: int, d: int) -> None:
    m = 0xFFFFFFFF
    x[a] = (x[a] + x[b]) & m; x[d] ^= x[a]; x[d] = ((x[d] << 16) | (x[d] >> 16)) & m
    x[c] = (x[c] + x[d]) & m; x[b] ^= x[c]; x[b] = ((x[b] << 12) | (x[b] >> 20)) & m
    x[a] = (x[a] + x[b]) & m; x[d] ^= x[a]; x[d] = ((x[d] <<  8) | (x[d] >> 24)) & m
    x[c] = (x[c] + x[d]) & m; x[b] ^= x[c]; x[b] = ((x[b] <<  7) | (x[b] >> 25)) & m


def _chacha20_block(key: bytes, counter: int, nonce8: bytes) -> bytes:
    if len(key) == 16:
        # tau constant: "expand 16-byte k"
        state = [0x61707865, 0x3120646E, 0x79622D36, 0x6B206574]
        state += list(struct.unpack("<4I", key))
        state += list(struct.unpack("<4I", key))
    else:
        # sigma constant: "expand 32-byte k"
        state = [0x61707865, 0x3320646E, 0x79622D32, 0x6B206574]
        state += list(struct.unpack("<8I", key))
    state += [counter & 0xFFFFFFFF, (counter >> 32) & 0xFFFFFFFF]
    state += list(struct.unpack("<2I", nonce8))

    w = state[:]
    for _ in range(10):
        _chacha20_quarterround(w, 0, 4,  8, 12)
        _chacha20_quarterround(w, 1, 5,  9, 13)
        _chacha20_quarterround(w, 2, 6, 10, 14)
        _chacha20_quarterround(w, 3, 7, 11, 15)
        _chacha20_quarterround(w, 0, 5, 10, 15)
        _chacha20_quarterround(w, 1, 6, 11, 12)
        _chacha20_quarterround(w, 2, 7,  8, 13)
        _chacha20_quarterround(w, 3, 4,  9, 14)

    out = [(w[i] + state[i]) & 0xFFFFFFFF for i in range(16)]
    return struct.pack("<16I", *out)


def _chacha20_crypt(data: bytes, key: bytes, nonce8: bytes) -> bytes:
    if len(key) not in (16, 32):
        raise ValueError(f"ChaCha20 key must be 16 or 32 bytes, got {len(key)}")
    if len(nonce8) != 8:
        raise ValueError(f"ChaCha20 nonce must be 8 bytes, got {len(nonce8)}")

    out = bytearray(len(data))
    counter = 0
    for off in range(0, len(data), 64):
        keystream = _chacha20_block(key, counter, nonce8)
        chunk = data[off:off + 64]
        for i in range(len(chunk)):
            out[off + i] = chunk[i] ^ keystream[i]
        counter += 1
    return bytes(out)


def _derive_bgad_nonce(raw_nonce: bytes) -> bytes:
    return bytes(b ^ m for b, m in zip(raw_nonce, BGAD_NONCE_XOR))


def khux_decrypt(data: bytes, seed: int, mode: int,
                 key: Optional[bytes] = None, nonce: Optional[bytes] = None) -> bytes:
    if mode == 0:
        return data
    elif mode == 1:
        return _decrypt_mode1(data, seed)
    elif mode == 2:
        return _decrypt_mode2(data, seed)
    elif mode == 3:
        if key is None or nonce is None:
            raise ValueError("Mode 3 requires key and nonce")
        derived = _derive_bgad_nonce(nonce)
        return _chacha20_crypt(data, key, derived)
    else:
        raise ValueError(f"Unsupported decryption mode: {mode}")


def khux_encrypt(data: bytes, seed: int, mode: int,
                 key: Optional[bytes] = None, nonce: Optional[bytes] = None) -> bytes:
    return khux_decrypt(data, seed, mode, key=key, nonce=nonce)
