import struct
from typing import Optional


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
BGI_NONCE_XOR = bytes([0xEA, 0x74, 0x35, 0x0A, 0x0F, 0x34, 0xDB, 0xC4])

CHACHA_SIGMA = [0x61707865, 0x3320646E, 0x79622D32, 0x6B206574]
CHACHA_TAU = [0x61707865, 0x3120646E, 0x79622D36, 0x6B206574]

KEY_APK = bytes.fromhex("5CA56C5827FA15CF1ECE2A37180953B801DEBFD0A71DD6AA6DD1D4F414A5FBC4")
KEY_DOWNLOAD = bytes.fromhex("3C8499BF7EEE43BD1B4DDE853725A110F0914C76C167BE9D3C902CBEE790B03E")
KEY_SAVE = bytes.fromhex("FB32833C8CC403018AC1EAB921F56C2618A4AF7E38CCC9CF5267AA19FDBA320C")


def _chacha_quarterround(x: list, a: int, b: int, c: int, d: int) -> None:
    m = 0xFFFFFFFF
    x[a] = (x[a] + x[b]) & m; x[d] ^= x[a]; x[d] = ((x[d] << 16) | (x[d] >> 16)) & m
    x[c] = (x[c] + x[d]) & m; x[b] ^= x[c]; x[b] = ((x[b] << 12) | (x[b] >> 20)) & m
    x[a] = (x[a] + x[b]) & m; x[d] ^= x[a]; x[d] = ((x[d] <<  8) | (x[d] >> 24)) & m
    x[c] = (x[c] + x[d]) & m; x[b] ^= x[c]; x[b] = ((x[b] <<  7) | (x[b] >> 25)) & m


def _chacha_block(key: bytes, counter: int, nonce8: bytes, rounds: int = 8) -> bytes:
    if len(key) == 16:
        state = list(CHACHA_TAU)
        state += list(struct.unpack("<4I", key))
        state += list(struct.unpack("<4I", key))
    elif len(key) == 32:
        state = list(CHACHA_SIGMA)
        state += list(struct.unpack("<8I", key))
    else:
        raise ValueError(f"Key must be 16 or 32 bytes, got {len(key)}")
    state += [counter & 0xFFFFFFFF, (counter >> 32) & 0xFFFFFFFF]
    state += list(struct.unpack("<2I", nonce8))

    w = state[:]
    double_rounds = rounds // 2
    for _ in range(double_rounds):
        _chacha_quarterround(w, 0, 4,  8, 12)
        _chacha_quarterround(w, 1, 5,  9, 13)
        _chacha_quarterround(w, 2, 6, 10, 14)
        _chacha_quarterround(w, 3, 7, 11, 15)
        _chacha_quarterround(w, 0, 5, 10, 15)
        _chacha_quarterround(w, 1, 6, 11, 12)
        _chacha_quarterround(w, 2, 7,  8, 13)
        _chacha_quarterround(w, 3, 4,  9, 14)

    out = [(w[i] + state[i]) & 0xFFFFFFFF for i in range(16)]
    return struct.pack("<16I", *out)


def chacha8_crypt(data: bytes, key: bytes, nonce8: bytes) -> bytes:
    if len(key) not in (16, 32):
        raise ValueError(f"Key must be 16 or 32 bytes, got {len(key)}")
    if len(nonce8) != 8:
        raise ValueError(f"Nonce must be 8 bytes, got {len(nonce8)}")

    out = bytearray(len(data))
    counter = 0
    for off in range(0, len(data), 64):
        keystream = _chacha_block(key, counter, nonce8, rounds=8)
        chunk = data[off:off + 64]
        for i in range(len(chunk)):
            out[off + i] = chunk[i] ^ keystream[i]
        counter += 1
    return bytes(out)


def _derive_nonce(raw_nonce: bytes, xor_mask: bytes) -> bytes:
    return bytes(b ^ m for b, m in zip(raw_nonce, xor_mask))


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
        derived = _derive_nonce(nonce, BGAD_NONCE_XOR)
        return chacha8_crypt(data, key, derived)
    else:
        raise ValueError(f"Unsupported decryption mode: {mode}")


def khux_encrypt(data: bytes, seed: int, mode: int,
                 key: Optional[bytes] = None, nonce: Optional[bytes] = None) -> bytes:
    return khux_decrypt(data, seed, mode, key=key, nonce=nonce)
