# Mode 3 (ChaCha20) Encryption Research

Status: **SOLVED** — ChaCha8 (8 rounds, not 20). Three hardcoded keys for different file origins. Per-user key for .gif/.jpg mode 3 files.

---

## Known Keys

Three 32-byte keys exist in all versions of `libcocos2dcpp.so`:

### Key 1 — BGTEncryptionKeyConst (0xEC6790)
```
5C A5 6C 58 27 FA 15 CF 1E CE 2A 37 18 09 53 B8
01 DE BF D0 A7 1D D6 AA 6D D1 D4 F4 14 A5 FB C4
```
- Referenced by symbol `BGTEncryptionKeyConst`
- Used by `ReadBGIFile` (0xA18CB8) via `sub_A17B18` initialization
- Present in: v1.0.1, v1.2.3 (arm7, armeabi), v5 (arm64)
- Binary offsets: v1.0.1 @ 0xEC6790, v5 arm64 @ 0xEC6790

### Key 2 — V3 Key (0xE298B0)
```
FB 32 83 3C 8C C4 03 01 8A C1 EA B9 21 F5 6C 26
18 A4 AF 7E 38 CC C9 CF 52 67 AA 19 FD BA 32 0C
```
- Referenced as `unk_E298B0` (unnamed in IDA)
- Used by download/update code path in `libcocos2dcpp_0004.c:29863` and `:30016`
- Found in v5 runtime memory (6 copies) alongside active ChaCha20 contexts
- Present in: v1.0.1, v5. **NOT in v1.2.3**
- Binary offsets: v1.0.1 @ 0xE298B0, v5 arm64 @ 0xE298B0

### Key 3 — Integrity Key (0xE6EE54)
```
3C 84 99 BF 7E EE 43 BD 1B 4D DE 85 37 25 A1 10
F0 91 4C 76 C1 67 BE 9D 3C 90 2C BE E7 90 B0 3E
```
- Referenced as `unk_E6EE54` (unnamed in IDA)
- Used by `sub_691544` in `libcocos2dcpp_0016.c:4455` for integrity verification
- Decrypts the `"/"` entry in `.png` containers; result is validated (32-byte check)
- Present in: v5 arm64 @ 0xE6EE54

---

## Nonce XOR Constants

### BGAD Nonce XOR
```
62 C0 D9 49 9B 15 83 72
```
- Hardcoded in `DecryptBGAD` (0xA17378) at `libcocos2dcpp_0033.c:1784-1791`
- Confirmed by disassembling raw ARM64 instructions at 0xA173F0
- Applied: `derived_nonce[i] = raw_file_nonce[i] ^ BGAD_XOR[i]`

### BGI Nonce XOR
```
EA 74 35 0A 0F 34 DB C4
```
- Used in `ReadBGIFile` (0xA18CB8) at `libcocos2dcpp_0033.c:3407-3418`
- For encrypted BGI files (flags & 1)

---

## Cipher Implementations

Two distinct ChaCha20 implementations exist in the binary:

### ECRYPT ChaCha20 (eSTREAM variant)
- Functions: `ECRYPT_keysetup` (0xA81E5C), `ECRYPT_ivsetup` (0xA81FF8),
  `ECRYPT_encrypt_bytes` (0xA82040), `ECRYPT_decrypt_bytes` (0xA825D8)
- 8-byte nonce, 64-bit counter
- Constants string at binary offset 0xECDB26: `"expand 32-byte kexpand 16-byte k"`
- Confirmed ChaCha20 (not Salsa20) by rotation constants: 16, 12, 8, 7
- Called by `DecryptBGAD` for BGAD mode 3

### OpenSSL/BoringSSL ChaCha20 (IETF variant)
- Function: `ChaCha20_ctr32` (0xD15960)
- 12-byte nonce, 32-bit counter (IETF RFC 7539)
- Constants string at binary offset 0xD15900
- Used for TLS connections, NOT directly for BGAD

---

## Code Paths for BGAD Mode 3

### Path 1 — ReadBGIFile (Key 1)
```
sub_A17B18 → sets BGTEncryptionKeyConst
  → ReadBGIFile (0xA18CB8, libcocos2dcpp_0033.c:3264)
    → sub_A16F20 (reads BGAD entry)
      → DecryptBGAD (mode 3 ChaCha20)
```

### Path 2 — Download/Update Content (Key 2)
```
libcocos2dcpp_0004.c:29863 → sub_A174E0 (encrypt, uses unk_E298B0)
libcocos2dcpp_0004.c:30016 → sub_A16F20 (decrypt, uses unk_E298B0)
  → DecryptBGAD (mode 3 ChaCha20)
```

### Path 3 — Integrity Verification (Key 3)
```
sub_691544 (libcocos2dcpp_0016.c:4371)
  → sub_A16F20 (decrypts "/" entry with unk_E6EE54)
  → checks decrypted size == 32 bytes (integrity hash)
  → also reads "md5" and "size" entries
  → result used for file validation, NOT as encryption key
```

### Path 4 — General Asset Loading
```
libcocos2dcpp_0015.c:19469 → sub_A16F20 (key from context object + 544)
  → key source: sub_49CDE0() returns global context
  → offset 544 holds key structure (key_ptr at +8, key_len at +16)
  → sub_49CDE0 decompile returned None (opaque singleton)
```

---

## What We Tried

### Key + Cipher + Nonce Combinations
| Key | Cipher | Nonce | Result |
|-----|--------|-------|--------|
| Key 1 (BGT) | ChaCha20 | BGAD XOR | Garbage |
| Key 1 | ChaCha20 | BGI XOR | Garbage |
| Key 1 | ChaCha20 | Raw (no XOR) | Garbage |
| Key 1 | Salsa20 | All variants | Garbage |
| Key 2 (V3) | ChaCha20 | BGAD XOR | Garbage |
| Key 2 | ChaCha20 | Raw | Garbage |
| Key 2 | Salsa20 | All variants | Garbage |
| Key 3 | ChaCha20 | BGAD XOR | Garbage |
| Key 3 | Salsa20 | All variants | Garbage |
| All keys | IETF ChaCha20 (12-byte nonce) | Padded | Garbage |

### Key Transformations Tried
- Byte reverse, u32 byte-swap, word reverse
- XOR with nonce, XOR with other keys, XOR with 0xFF
- Half-swap, NOT, ROL/ROR each byte
- SHA-256(key), SHA-256(key+nonce), HMAC
- LCG-derived keys (KHUx LCG and MSVC LCG)
- Partial key (first 16 bytes, zeroed remainder)
- 128-bit key mode (repeated halves)

### Nonce Derivations Tried
- BGAD XOR constant (62 C0 D9 49 9B 15 83 72)
- V3 XOR constant (49 D9 C0 62 72 83 15 9B) — byte-swapped BGAD
- BGI XOR constant (EA 74 35 0A 0F 34 DB C4)
- Raw nonce (no XOR)
- Partial XOR (1-7 bytes)
- SHA-256 derived, MD5 derived

### Cipher Variants Tried
- ChaCha20 (8-byte nonce, our pure Python + PyCryptodome)
- Salsa20 (PyCryptodome)
- IETF ChaCha20 (12-byte nonce, PyCryptodome)
- Counter values 0-99

### Implementation Verification
- Pure Python ChaCha20 passes RFC test vector (all-zero key/nonce)
- Pure Python matches PyCryptodome byte-for-byte
- ECRYPT state layout confirmed from decompile (constants, key, counter, nonce)
- Nonce XOR bytes confirmed from raw ARM64 disassembly

---

## Known Plaintext Attack Results

### 1.2.3 Containers (Shared Nonce)

All entries in `Input/1.2.3/misc.mp4` share the same nonce (`089d156c87271968`)
and the same data keystream. This means one known-plaintext pair decrypts ALL
uncompressed entries.

**Keystream extraction method:**
1. `Input/1.0.1/misc.mp4` has the same entries as `1.2.3` but in mode 2 (decryptable)
2. XOR mode 2 plaintext with mode 3 ciphertext = keystream
3. Same keystream applies to all uncompressed entries in the container

**Extracted keystream (first 64 bytes, counter=0 block):**
```
a2fc41a45a1408bb f069c3d9a69a65e0
1bb8354b3453e2fc 39b4f9f5aae55365
7a85a14fc30dcd79 55dd589c8569e4b1
5f066c7cb750b463 72e09bae1d215250
```

**Name keystream** is DIFFERENT per entry (entries 0 and 1 have different name
keystreams). Name encryption uses a separate cipher instance.

**Compressed entries** (comp=2) have different keystreams because zlib output
differs between versions even for identical input.

### BGI Decryption via Known Structure

The BGI inside `Input/1.2.3/misc.png` was decrypted by exploiting known
structure:
- BGI header: `\x89BGI\x03\x00\x00\x00\x00\x00\x00\x00` (12 known bytes)
- `name_to_entry_index` table is sequential: `00000000 01000000 02000000 ...`
- Verified: entry_count=1214, name_count=1433 (same as v1.0.1)
- Result: all 1433 file names successfully decrypted

### Assets Containers (Per-Entry Nonce)

`Input/assets/misc.mp4` uses a DIFFERENT nonce for each entry (2799 unique
nonces across 2799 entries). Crib-dragging across entries is not possible.

Per-entry crib (4-byte magic) can identify format type but not decrypt full
content.

---

## Runtime Analysis (Frida on BlueStacks)

### Setup
- BlueStacks x86_64 emulator, rooted
- v5.0.1 APK + OBBs installed
- frida-server running as root
- ARM code translated via libhoudini (Frida can't see libcocos2dcpp.so as a module)

### Memory Scan Results
- **BGTEncryptionKeyConst** found 1x in mapped .so read-only data
- **V3 Key** found 6x in writable memory (3 pairs = 3 ChaCha20 contexts)
- **ChaCha20 contexts** with V3 key had live nonces and counter=1
- **Decrypted asset paths** found in memory: `cocostudio/publish/Av_Make_Panel_01_M.png` etc. — confirming mode 3 decryption DID happen
- **No decrypted BGI** found in writable memory (already processed and freed)
- V3 key contexts may be TLS-related (BoringSSL), not BGAD

### Limitation
Game reaches title screen but cannot progress (server dead). Mode 3 asset
loading for actual game content could not be triggered.

---

## SOLUTION: Per-User Personal Key

### How Mode 3 Actually Works

The ChaCha20 key is a **per-user 16-byte key** stored in the save data as the
`"personal"` entry. It is NOT any of the three hardcoded keys in the binary.

### Key Extraction

The `"personal"` entry in save files (.gif / Cocos2dxPrefsFile.xml) has the
format:
```
Offset  Size  Field
0x00    4     MSVC LCG seed (u32 LE)
0x04    4     Payload size (u32 LE) = 16
0x08    16    MSVC LCG encrypted key
```

Decrypt with: `key[i] = ((214013 * (i + seed) + 2531011) >> 16) & 0xFF`

The resulting 16 bytes are the ChaCha20 key, used with the **tau constant**
("expand 16-byte k"), NOT sigma ("expand 32-byte k").

### ChaCha20 State Layout for 16-byte Key

```
state[0..3]  = "expand 16-byte k"  (tau: 0x61707865, 0x3120646E, 0x79622D36, 0x6B206574)
state[4..7]  = key[0..15]          (first 16 bytes)
state[8..11] = key[0..15]          (SAME 16 bytes repeated)
state[12..13] = counter (starts at 0)
state[14..15] = nonce (from file, XOR'd with BGAD constant)
```

### Verified Examples

From HTCSave.gif:
```
personal entry:  bbc8e16510000000202309576e23517fa85a78ce2165debf
decrypted key:   2324035a7f374665b67b5ce90a4bef8b
```

From EmptySave.gif:
```
personal entry:  31570c391000000075ea5de225399b656ee36df8cde0f188
decrypted key:   c82a9925eff44ab1b938b31929081a66
```

These keys are device-specific — they only decrypt files from the same device.

### Why Previous Attempts Failed

1. The three hardcoded keys serve different purposes (BGI init, config decryption, integrity)
2. The runtime key is per-user, not a binary constant
3. Our Python ChaCha20 used sigma ("expand 32-byte k") for 16-byte keys
   instead of tau ("expand 16-byte k") — this was a bug, now fixed
4. The personal key is 16 bytes, not 32

### Complete Decryption Chain (from decompile analysis)

```
Save file (.gif) → "personal" entry → MSVC LCG decrypt → 16-byte key
                                                              ↓
BGAD mode 3 entry → extract nonce (last 8 bytes) → XOR with 62C0D9499B158372
                                                              ↓
                    ChaCha20(key=personal_16, nonce=derived, tau constant)
                                                              ↓
                    Decrypted payload → optional zlib decompress → output
```

### Code References (from decompiled sub_4A0800, libcocos2dcpp_0004.c:3598)

```c
// Reads 16 bytes from "personal" container
sub_3937EC(...)  // LCG deobfuscation
malloc(0x10)     // 16-byte key allocation
// Creates key wrapper with v3[5] = key_ptr, v3[6] = 16
// Stored at singleton offset 544/552
```

---

## Breakthrough: sharedSecurityKey

The actual ChaCha20 key is the `sharedSecurityKey` — a 32-byte value received
from the server API response (found at `libcocos2dcpp_0002.c:26043`).

**Discovery chain:**
1. v1.0.1 has NO ChaCha20 — only LCG XOR + AES-256-CBC
2. v1.0.1's `Cipher` class gets its AES key from `sharedSecurityKey` in JSON
3. v5 still reads `sharedSecurityKey` from server response (line 26043)
4. The 32-byte key is stored via `sub_489B04` which OBFUSCATES it with MSVC LCG
5. The key structure uses a vtable (`off_1212378`) for transparent de-obfuscation
6. When `sub_A16F20` reads the key, it goes through the vtable accessor

**Why our static analysis failed:** The three keys in .rodata are NOT the
runtime decryption key. The actual key comes from the server response and is
stored obfuscated in a `SafeBuffer` object. Even in "offline" mode, the key
was cached from a previous server session.

**Why Frida memory scan found the wrong key:** The V3 key (`FB32833C...`) found
in memory was from BoringSSL TLS contexts, not from BGAD decryption. The actual
BGAD key is MSVC-LCG-obfuscated in memory, so scanning for raw key bytes
wouldn't find it.

**Next steps:**
- Find where the `sharedSecurityKey` is cached locally (possibly in
  `Cocos2dxPrefsFile.xml` or a local database)
- Or use Frida to hook `sub_489B04` / `sub_489B7C` to capture the raw key
  before/after obfuscation
- Or find the MSVC LCG seed used for obfuscation and reverse the process

---

## Cross-Version Comparison

v1.0.1: NO ChaCha20/ECRYPT at all. Only LCG XOR + AES-256-CBC (for network API).
v1.2.3: ChaCha20 added. Same ECRYPT implementation as v5 (identical rotation constants,
        identical nonce XOR bytes, identical ECRYPT_keysetup).
v5:     Same ChaCha20 as v1.2.3. Two ECRYPT call sites (DecryptBGAD + ReadBGIFile).
        Also has OpenSSL/BoringSSL ChaCha20_ctr32 (IETF variant) for TLS.

## Unsolved Questions

1. **Which key does the global context at sub_49CDE0 + offset 544 actually hold?**
   sub_49CDE0 decompile returned None. The key structure is set up somewhere
   we can't see.

2. **Is there a fourth key?** The three known keys are in .rodata. But the
   actual runtime key might be derived, downloaded, or computed.

3. **Is there a pre/post processing step?** DecryptBGAD looks straightforward
   (memcpy key, XOR nonce, ECRYPT calls), but maybe the caller transforms
   the data before or after.

4. **Key-of-keys possibility:** Key 3 decrypts the "/" entry and checks for
   32 bytes. If a specific container has a 32-byte "/" entry, its content
   could be the real key. No such container found in our files yet.

5. **Does the v1.2.3 decompile show a different code path?** We now have
   all 3 decompiles but haven't diffed them yet.
