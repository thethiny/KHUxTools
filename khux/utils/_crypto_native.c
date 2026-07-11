#include <stdint.h>
#include <string.h>

#ifdef _WIN32
#define EXPORT __declspec(dllexport)
#else
#define EXPORT
#endif

#define LCG_A 0x19660Du
#define LCG_C 0x3C6EF35Fu

EXPORT void lcg_xor_dwords(const uint8_t *in, uint8_t *out, uint32_t n, uint32_t seed) {
    uint32_t s = seed;
    uint32_t full = n & ~3u;
    uint32_t i;
    for (i = 0; i < full; i += 4) {
        s = LCG_A * s + LCG_C;
        uint32_t val;
        memcpy(&val, in + i, 4);
        val ^= s;
        memcpy(out + i, &val, 4);
    }
    if (i < n) {
        s = LCG_A * s + LCG_C;
        uint32_t tail = n - i;
        uint8_t tmp[4] = {0};
        memcpy(tmp, in + i, tail);
        uint32_t val;
        memcpy(&val, tmp, 4);
        val ^= s;
        memcpy(tmp, &val, 4);
        memcpy(out + i, tmp, tail);
    }
}

EXPORT void lcg_xor_bytes(const uint8_t *in, uint8_t *out, uint32_t n, uint32_t seed) {
    uint32_t s = seed;
    for (uint32_t i = 0; i < n; i++) {
        s = LCG_A * s + LCG_C;
        out[i] = in[i] ^ (uint8_t)(s & 0xFF);
    }
}

#define CHACHA_QR(a, b, c, d) \
    a += b; d ^= a; d = (d << 16) | (d >> 16); \
    c += d; b ^= c; b = (b << 12) | (b >> 20); \
    a += b; d ^= a; d = (d <<  8) | (d >> 24); \
    c += d; b ^= c; b = (b <<  7) | (b >> 25);

EXPORT void chacha8_xor(const uint8_t *in, uint8_t *out, uint32_t n,
                        const uint8_t *key, uint32_t key_len,
                        const uint8_t *nonce8) {
    uint32_t sigma[4] = {0x61707865, 0x3320646e, 0x79622d32, 0x6b206574};
    uint32_t tau[4]   = {0x61707865, 0x3120646e, 0x79622d36, 0x6b206574};
    uint32_t state[16];
    uint32_t k[8], nn[2];
    memcpy(k, key, key_len);
    memcpy(nn, nonce8, 8);

    if (key_len == 32) {
        memcpy(state, sigma, 16);
        memcpy(state + 4, k, 32);
    } else {
        memcpy(state, tau, 16);
        memcpy(state + 4, k, 16);
        memcpy(state + 8, k, 16);
    }
    state[14] = nn[0];
    state[15] = nn[1];

    uint64_t counter = 0;
    for (uint32_t off = 0; off < n; off += 64) {
        state[12] = (uint32_t)(counter & 0xFFFFFFFF);
        state[13] = (uint32_t)(counter >> 32);

        uint32_t w[16];
        memcpy(w, state, 64);
        for (int r = 0; r < 4; r++) {
            CHACHA_QR(w[0], w[4], w[ 8], w[12])
            CHACHA_QR(w[1], w[5], w[ 9], w[13])
            CHACHA_QR(w[2], w[6], w[10], w[14])
            CHACHA_QR(w[3], w[7], w[11], w[15])
            CHACHA_QR(w[0], w[5], w[10], w[15])
            CHACHA_QR(w[1], w[6], w[11], w[12])
            CHACHA_QR(w[2], w[7], w[ 8], w[13])
            CHACHA_QR(w[3], w[4], w[ 9], w[14])
        }

        uint8_t block[64];
        for (int i = 0; i < 16; i++) {
            uint32_t v = w[i] + state[i];
            memcpy(block + i * 4, &v, 4);
        }

        uint32_t chunk = n - off;
        if (chunk > 64) chunk = 64;
        for (uint32_t i = 0; i < chunk; i++) {
            out[off + i] = in[off + i] ^ block[i];
        }
        counter++;
    }
}
