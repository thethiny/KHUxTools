import struct
from typing import Optional

import numpy as _np

def _build_native():
    """Compile the C crypto extension for the current platform."""
    import os
    import shutil
    import cffi
    ffi = cffi.FFI()
    ffi.cdef('''
    void lcg_xor_dwords(const uint8_t *in, uint8_t *out, uint32_t n, uint32_t seed);
    void lcg_xor_bytes(const uint8_t *in, uint8_t *out, uint32_t n, uint32_t seed);
    void chacha8_xor(const uint8_t *in, uint8_t *out, uint32_t n,
                     const uint8_t *key, uint32_t key_len, const uint8_t *nonce8);
    ''')
    src_dir = os.path.dirname(os.path.abspath(__file__))
    c_path = os.path.join(src_dir, '_crypto_native.c')
    with open(c_path) as f:
        ffi.set_source('khux.utils._crypto_cffi', f.read())
    root = os.path.dirname(os.path.dirname(src_dir))
    ffi.compile(tmpdir=root, verbose=False)
    # Clean up build artifacts
    import glob
    gen_c = os.path.join(src_dir, '_crypto_cffi.c')
    if os.path.exists(gen_c):
        os.remove(gen_c)
    for pat in ('_crypto_cffi*.lib', '_crypto_cffi*.exp', '_crypto_cffi*.o', '_crypto_cffi*.obj'):
        for p in glob.glob(os.path.join(src_dir, pat)):
            os.remove(p)
    release_dir = os.path.join(root, 'Release')
    if os.path.isdir(release_dir):
        shutil.rmtree(release_dir, ignore_errors=True)

_HAS_NATIVE = False
try:
    from khux.utils._crypto_cffi import ffi as _ffi, lib as _clib
    _HAS_NATIVE = True
except (ImportError, OSError):
    try:
        _build_native()
        from khux.utils._crypto_cffi import ffi as _ffi, lib as _clib
        _HAS_NATIVE = True
    except Exception:
        pass

_LCG_A = 0x19660D
_LCG_C = 0x3C6EF35F
_LCG_M = 0xFFFFFFFF


def _khux_rand(seed: int) -> int:
    return (_LCG_A * seed + _LCG_C) & _LCG_M


def _lcg_keystream(seed: int, count: int) -> list:
    """Generate `count` LCG values as a list of uint32."""
    a, c, m = _LCG_A, _LCG_C, _LCG_M
    s = seed & m
    ks = [0] * count
    for i in range(count):
        s = (a * s + c) & m
        ks[i] = s
    return ks


def _decrypt_mode1(data: bytes, seed: int) -> bytes:
    n = len(data)
    if n == 0:
        return data
    if _HAS_NATIVE:
        buf_in = _ffi.from_buffer(data)
        buf_out = _ffi.new('uint8_t[]', n)
        _clib.lcg_xor_bytes(buf_in, buf_out, n, seed & _LCG_M)
        return _ffi.buffer(buf_out, n)[:]
    ks_ints = _lcg_keystream(seed, n)
    ks = bytes(v & 0xFF for v in ks_ints)
    arr = _np.frombuffer(data, dtype=_np.uint8)
    ks_arr = _np.frombuffer(ks, dtype=_np.uint8)
    return bytes(arr ^ ks_arr)


def _encrypt_mode1(data: bytes, seed: int) -> bytes:
    return _decrypt_mode1(data, seed)


def _decrypt_mode2(data: bytes, seed: int) -> bytes:
    n = len(data)
    if n == 0:
        return data
    if _HAS_NATIVE:
        buf_in = _ffi.from_buffer(data)
        buf_out = _ffi.new('uint8_t[]', n)
        _clib.lcg_xor_dwords(buf_in, buf_out, n, seed & _LCG_M)
        return _ffi.buffer(buf_out, n)[:]
    full = n & ~3
    n_dwords = full // 4
    need = n_dwords + (1 if n > full else 0)
    ks_ints = _lcg_keystream(seed, need)
    ks_bytes = struct.pack(f'<{n_dwords}I', *ks_ints[:n_dwords])
    arr = _np.frombuffer(data[:full], dtype=_np.uint32).copy()
    ks_arr = _np.frombuffer(ks_bytes, dtype=_np.uint32)
    arr ^= ks_arr
    result = arr.tobytes()
    if n > full:
        tail = n - full
        tmp = bytearray(data[full:]) + b"\x00" * (4 - tail)
        val = struct.unpack("<I", tmp)[0]
        dec = struct.pack("<I", (val ^ ks_ints[-1]) & _LCG_M)
        result += dec[:tail]
    return result


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

    n = len(data)
    if n == 0:
        return data
    if _HAS_NATIVE:
        buf_in = _ffi.from_buffer(data)
        buf_out = _ffi.new('uint8_t[]', n)
        buf_key = _ffi.from_buffer(key)
        buf_nonce = _ffi.from_buffer(nonce8)
        _clib.chacha8_xor(buf_in, buf_out, n, buf_key, len(key), buf_nonce)
        return _ffi.buffer(buf_out, n)[:]
    n_blocks = (n + 63) // 64
    ks_parts = []
    for counter in range(n_blocks):
        ks_parts.append(_chacha_block(key, counter, nonce8, rounds=8))
    ks_all = b"".join(ks_parts)
    arr = _np.frombuffer(data, dtype=_np.uint8)
    ks_arr = _np.frombuffer(ks_all[:n], dtype=_np.uint8)
    return bytes(arr ^ ks_arr)


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
