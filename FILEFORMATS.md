# KHUx File Formats Reference

Complete documentation of all known file formats in Kingdom Hearts Union Cross
(KHUx / KHUX / Kingdom Hearts Unchained X).

---

## Table of Contents

- [Container Formats](#container-formats)
  - [BGAD](#bgad---binary-game-asset-data)
  - [BGI](#bgi---binary-game-index)
- [Encryption Schemes](#encryption-schemes)
  - [KHUx LCG (Modes 1 & 2)](#khux-lcg-modes-1--2)
  - [MSVC LCG (Master Data)](#msvc-lcg-master-data)
  - [ChaCha8 (Mode 3)](#chacha20-mode-3)
- [Image Formats](#image-formats)
  - [BTF](#btf---binary-texture-format)
- [Animation Formats](#animation-formats)
  - [LWF](#lwf---lightweight-swf)
- [Game Data Formats](#game-data-formats)
  - [Master Data (m*.jpg)](#master-data-mjpg)
  - [AvatarParts](#avatarparts)
  - [STG](#stg---stage-data)
  - [MAP](#map---map-data)
  - [CHP](#chp)
  - [CLS](#cls)
  - [BMI](#bmi)
  - [JMP](#jmp)
- [Audio Formats](#audio-formats)
  - [AKB](#akb---audio-bank)
- [Configuration Formats](#configuration-formats)
  - [Plist](#plist)
- [Save Data](#save-data)
  - [Save File (.gif)](#save-file-gif)
  - [Cocos2dxPrefsFile.xml](#cocos2dxprefsfilexml)
- [File Distribution](#file-distribution)
  - [Container File Extensions](#container-file-extensions)
  - [Format Distribution (161K sample)](#format-distribution)
- [Magic Bytes Summary](#magic-bytes-summary)

---

## Container Formats

### BGAD - Binary Game Asset Data

The universal container/wrapper format. Every game asset is stored inside one
or more BGAD entries. Container files (`.mp4`, `.png`, `.jpg`, `.gif`) are
sequences of concatenated BGAD entries.

#### Header (24 bytes)

```
Offset  Size  Type    Field             Description
0x00    4     char[4] magic             "BGAD" (0x42474144)
0x04    2     u16     version           Must be 1 or 2
0x06    2     u16     flags             Bit 2 (0x04): has 8-byte nonce (mode 3)
0x08    2     u16     header_size       Always 24 (0x18)
0x0A    2     u16     name_length       Length of the name field in bytes
0x0C    2     u16     encryption_mode   0=none, 1=byte LCG, 2=dword LCG, 3=ChaCha8
0x0E    2     u16     compression_mode  0=none, 2=zlib
0x10    4     u32     data_size         Size of data section (includes 8-byte nonce for mode 3)
0x14    4     u32     decompressed_size Original size before compression
```

#### Entry Layout

```
[BGAD Header - 24 bytes]
[Encrypted Name - name_length bytes]
[Encrypted Data - data_size bytes]
  (for mode 3: last 8 bytes of data section are the nonce)
```

#### Name Decryption

- **Mode 0**: No decryption
- **Modes 1, 2**: Same LCG cipher as data, seed = `data_size`
- **Mode 3**: Unsolved (see [ChaCha8 section](#chacha20-mode-3))

#### Data Decryption

- **Mode 0**: No decryption
- **Mode 1**: Byte-wise KHUx LCG XOR, seed = `name_length`
- **Mode 2**: DWORD-wise KHUx LCG XOR, seed = `name_length`
- **Mode 3**: ChaCha8, nonce = last 8 bytes of data section XOR'd with
  `0x62C0D9499B158372`

After decryption, if `compression_mode != 0`, the data is zlib-decompressed.

#### Container Structure

A container file is simply concatenated BGAD entries read sequentially until EOF
or an invalid magic. Each BGAD entry is self-contained with its own header.

**Source**: Decompiled from `sub_A16F20` (ea=0xA16F20) in libcocos2dcpp v5.

---

### BGI - Binary Game Index

An index/manifest file that maps file names to entry indices within a
corresponding BGAD container. Typically stored as the `"/"` or `"@root"` entry
inside a `.png` container paired with a `.mp4` container.

#### Header (12 bytes)

```
Offset  Size  Type    Field     Description
0x00    4     char[4] magic     "\x89BGI" (0x89424749)
0x04    4     u32     version   Must be 3
0x08    4     u32     flags     Bit 0: encrypted with ChaCha8
```

#### Data Layout (after header, or after decryption)

```
Offset                              Size              Field
0x00                                4                 entry_count (u32)
0x04                                4                 name_count (u32)
0x08                                entry_count * 8   entries[] (offset u32 + reserved u32)
0x08 + entry_count*8                name_count * 4    name_to_entry_index[] (u32 per name)
0x08 + entry_count*8 + name_count*4 name_count * 4    name_offsets[] (u32, relative to string blob)
<after name_offsets>                 variable          string_blob (null-terminated UTF-8 strings)
```

#### Entry Table

Each entry is 8 bytes: a u32 byte offset and a u32 reserved field (always 0 in
observed files). The offset represents the cumulative byte position in the
paired BGAD container.

#### Name Lookup

For each name index `i`:
- `name_to_entry_index[i]` gives the entry index in the paired container
- `name_offsets[i]` is the byte offset into the string blob for the name string
- Names are null-terminated UTF-8

#### Hash Table (runtime)

At runtime, the game builds an XXH32-based hash table for O(1) name lookups.
XXH32 is computed with seed 0. The hash table uses power-of-two or prime bucket
counts with libc++-style rehashing.

#### Encryption

When `flags & 1`:
- Last 8 bytes of the file (after header) are the nonce
- Nonce is XOR'd with `0xC4DB340F0A3574EA` (bytes: `EA 74 35 0A 0F 34 DB C4`)
- Decryption uses ChaCha8 with the BGTEncryptionKeyConst key
- Decryption covers all bytes between the header and the nonce

**Source**: Decompiled from `ReadBGIFile` (ea=0xA18CB8) in libcocos2dcpp v5.

---

## Encryption Schemes

### KHUx LCG (Modes 1 & 2)

Used for BGAD entries with encryption_mode 1 or 2.

**Linear Congruential Generator:**
```
next_seed = (0x19660D * seed + 0x3C6EF35F) & 0xFFFFFFFF
```

Constants: multiplier = 1,664,525 (`0x19660D`), increment = 1,013,904,223
(`0x3C6EF35F`).

**Mode 1 (byte XOR):**
```
for each byte in data:
    seed = LCG(seed)
    byte ^= seed & 0xFF
```

**Mode 2 (DWORD XOR):**
```
for each 4-byte DWORD in data (rounded up):
    seed = LCG(seed)
    dword ^= seed
```

**Seed values:**
- Name decryption: seed = `header.data_size`
- Data decryption: seed = `header.name_length`

**Status**: Fully working. Confirmed against original C source code
(DecryptV2.c) and all game versions.

---

### MSVC LCG (Master Data)

Used for the payload encryption in master data files (m*.jpg entries). This is a
completely different LCG from the KHUx BGAD LCG.

**Formula:**
```
key[i] = ((214013 * (i + seed) + 2531011) >> 16) & 0xFF
```

Constants: multiplier = 214,013 (`0x343FD`), increment = 2,531,011
(`0x269EC3`). These are the standard MSVC C runtime `rand()` constants.

The seed is the u32 at offset 0x00 of each numbered entry (originally
`std::chrono::system_clock::now()` at serialization time).

**Source**: Decompiled from `sub_3933B4` (ea=0x3933B4) in libcocos2dcpp v5.

**Status**: Fully working. Verified on 1,581 avatar parts with correct name
extraction.

---

### ChaCha8 (Mode 3)

Used for BGAD mode 3 and encrypted BGI files. The implementation is the
original Bernstein ChaCha with **8 rounds** (4 double-rounds), eSTREAM variant
with 8-byte nonce and 64-bit counter. NOT ChaCha20 (which uses 20 rounds).

Credit: bnnm (khuxdecrypt3) identified the round count as 8.

**Keys**: Three 32-byte keys in the binary, selected by file origin:

| Key | Name | Hex | Use |
|-----|------|-----|-----|
| KEY_APK | BGTEncryptionKeyConst | `5CA56C58...` | misc.mp4/misc.png (APK-bundled) |
| KEY_DOWNLOAD | unk_E6EE54 | `3C8499BF...` | Downloaded files in r/ folder, extra.* |
| KEY_SAVE | unk_E298B0 | `FB32833C...` | Saved/cache files |

Key selection logic (from bnnm's khuxdecrypt3):
- `misc.*` files (small, APK-bundled) → KEY_APK
- Other `.mp4`/`.png` files → KEY_DOWNLOAD
- `.gif`/`.jpg` files with mode 3 → per-user personal key (unsolved for arbitrary files)

**BGAD nonce XOR**: `62 C0 D9 49 9B 15 83 72`
**BGI nonce XOR**: `EA 74 35 0A 0F 34 DB C4`

**State layout** (standard ChaCha):
```
[ "expa"  "nd 3"  "2-by"  "te k" ]   constants (sigma for 32-byte key)
[ key[0]  key[1]  key[2]  key[3]  ]   key words 0-3
[ key[4]  key[5]  key[6]  key[7]  ]   key words 4-7
[ ctr_lo  ctr_hi  nonce0  nonce1  ]   counter + nonce
```

For 16-byte keys, uses tau constant ("expand 16-byte k") and key repeated.

**ECRYPT functions** in libcocos2dcpp v5:
- `ECRYPT_init` (0xA81E58) — no-op
- `ECRYPT_keysetup` (0xA81E5C) — sets up state with key + constants
- `ECRYPT_ivsetup` (0xA81FF8) — sets counter to 0, loads 8-byte nonce
- `ECRYPT_encrypt_bytes` (0xA82040) — ChaCha8 block cipher (8 rounds)
- `ECRYPT_decrypt_bytes` (0xA825D8) — same as encrypt (stream cipher)

**Status**: **SOLVED.** All hardcoded-key files decrypt correctly. Per-user
personal key files (.gif/.jpg with mode 3) require the user's save data.

---

## Image Formats

### BTF - Binary Texture Format

KHUx's custom image format. Files use `.png` extension but contain BTF data
(magic `\x89BTF`). Can be losslessly converted to standard PNG.

#### Header (34+ bytes)

```
Offset  Size  Type  Field           Description
0x00    4     -     magic           "\x89BTF" (0x89425446)
0x04    2     -     skip            Always 0x0000
0x06    4     u32   unknown1        Usually 0 or 1
0x0A    4     u32   unknown2        Usually 0
0x0E    4     u32   image_format    0x080000 = RGBA, 0x090000 = indexed palette
0x12    4     u32   unknown4        Usually 0
0x16    2     u16   canvas_width    Full canvas width in pixels
0x18    2     u16   canvas_height   Full canvas height in pixels
0x1A    2     u16   canvas_offset_x Image X offset within canvas
0x1C    2     u16   canvas_offset_y Image Y offset within canvas
0x1E    2     u16   image_width     Actual image width in pixels
0x20    2     u16   image_height    Actual image height in pixels
```

If `image_format == 0x090000` (indexed):
```
0x22    2     u16   palette_size    Number of palette entries
```

Then:
```
+0      4     u32   compressed_size Size of zlib-compressed pixel data
+4      N     -     compressed_data zlib-compressed pixel data
```

#### Pixel Data (after decompression)

**RGBA (0x080000):**
Raw RGBA pixel data, 4 bytes per pixel, row-major order.

**Indexed (0x090000):**
```
[palette_size * 4 bytes]  RGBA palette (4 bytes per color)
[width * height bytes]    Pixel indices into palette
```

#### Canvas vs Image

The image may be smaller than the canvas. The `canvas_offset_x/y` values
specify where the image is placed within the larger canvas. When extracting,
you can either:
- Extract just the image (image_width x image_height)
- Extract with canvas (canvas_width x canvas_height, image pasted at offset)

**Status**: Fully working. Both RGBA and indexed palette formats verified.

---

## Animation Formats

### LWF - Lightweight SWF

An open-source animation format used by the cocos2d game engine. KHUx uses LWF
for UI animations, effects, and battle result screens.

#### Header (16 bytes)

```
Offset  Size  Type    Field       Description
0x00    4     char[4] magic       "LWF\0" (0x4C574600) or variant 0x5DF90000
0x04    4     u32     version     Format version
0x08    4     u32     data_size   Size of data section
0x0C    4     u32     total_size  Total file size
```

LWF is a standard format with existing documentation and tools. KHUx stores LWF
files as-is inside BGAD entries.

**Usage paths** (from decompiled strings):
- `lwf/battleresult/Result_Reward/Result_Reward.lwf`
- `lwf/effects/LoadingAnimation/LoadingAnimation.lwf`
- `lwf/avatar/%s/%05d/%s/%s.lwf`

**Status**: Detection and raw extraction working. Full LWF parsing not
implemented (standard format, external tools available).

---

## Game Data Formats

### Master Data (m*.jpg)

The `m*.jpg` files are BGAD containers holding game master data tables. Despite
the `.jpg` extension, they contain no JPEG data. Each file represents a
different data table (avatar parts, medals, skills, stages, etc.).

#### Container Structure

Each m*.jpg BGAD container has:
1. `"avatarParts"` (or similar table name) — u32 total count
2. `"hash"` — SHA-1 hash string (40 hex chars) for integrity verification
3. Numbered entries (`"1"`, `"2"`, ...) — one per record

#### Numbered Entry Layout

```
Offset  Size  Type  Field          Description
0x00    4     u32   seed           MSVC LCG seed (also a timestamp)
0x04    4     u32   payload_size   Byte length of decrypted payload
0x08    N     -     encrypted      XOR'd with MSVC LCG keystream
```

The payload is encrypted using the [MSVC LCG](#msvc-lcg-master-data) scheme.
The struct size varies by table type and game version:
- m000.jpg (avatar parts, early): 208 bytes (200 payload)
- m020.jpg (later version): 1308 bytes (1300 payload)
- m048.jpg (latest): 956 bytes (948 payload)

---

### AvatarParts

**Container**: m000.jpg (and versioned equivalents)
**Entry size**: 208 bytes (8 header + 200 payload)

#### Decrypted Struct (200 bytes)

```
Offset  Size  Type       Field             Description
0x00    4     int32      avatarPartsId     Unique part ID (matches entry name)
0x04    129   char[129]  name              UTF-8 name, null-terminated
0x85    3     -          (padding)         Alignment to 4-byte boundary
0x88    4     int32      partsType         Part category (see below)
0x8C    4     int32      gender            1 = Male, 2 = Female
0x90    4     int32      combinationType   Combination group index
0x94    4     int32      combinationFlag   Usually 0
0x98    4     int32      position          Equip slot (0-9)
0x9C    4     int32      luxCategory       Lux bonus category (0-6)
0xA0    4     int32      luxAddRate        Lux bonus rate (1000 = base)
0xA4    4     int32      setKind           Set/outfit group identifier
0xA8    4     int32      fixedFlag         1 = default part, 0 = unlockable
0xAC    4     int32      validSetCloth     Count of valid setCloth entries (0-5)
0xB0    20    int32[5]   setCloth          Related part IDs for outfit set
0xC4    4     int32      status            1 = active, 0 = disabled
```

#### partsType Values

| Value | Name        | ID Range      |
|-------|-------------|---------------|
| 2     | Clothes     | 1 - 282       |
| 3     | Hairstyle   | 40001 - 41xxx |
| 4     | Expression  | 20001 - 20036 |
| 5     | Skin Color  | 30001 - 30012 |
| 6     | Hair Color  | 50001 - 51xxx |
| 7     | Accessory   | 101xxx-209xxx |

#### Related Structs

**UserAvatarParts** (per-user ownership, 24 bytes):
```
0x00  int64  userAvatarPartsId   Unique ownership record ID
0x08  int32  partsType           Category (same as master data)
0x0C  int32  avatarPartsId       References master AvatarParts
0x10  int64  getDatetime         Acquisition timestamp
```

**MyCoordinate** (equipped outfit, 48 bytes):
```
0x00  int32  myCoordinateNo      Outfit slot number
0x04  int32  gender
0x08  int32  hairPartsId
0x0C  int32  hairColorPartsId
0x10  int32  facePartsId
0x14  int32  bodyPartsId
0x18  int32  skinPartsId
0x1C  int32[5]  accessoriesPartsIds
```

**Extended MyCoordinate** (detailed accessory slots, 48 bytes):
Indices: myCoordinateNo, accessoryMask, accessoryHat, earPartsId, facePartsId,
accessoryNecklace, legPartsId, accessoryBackpack, bodyPartsId, tailPartsId,
accessorySpecial, accessoryMouth.

**Sprite paths**: `img/avatarParts/%sai%03d.png` and `img/avatarParts/%sai%d.png`

**Source**: Decompiled from `sub_6CF7C8` (ea=0x6CF7C8) in libcocos2dcpp v5.

---

### STG - Stage Data

```
Offset  Size  Type    Field       Description
0x00    4     char[4] magic       "STG\0" (0x53544700)
0x04    4     u32     version
0x08    4     u32     count       Number of entries
0x0C    4     u32     data_offset
```

Stage definition data. Internal structure beyond the header is not yet fully
reverse-engineered. Extracted as raw binary.

---

### MAP - Map Data

```
Offset  Size  Type    Field       Description
0x00    4     char[4] magic       "MAP\0" (0x4D415000)
0x04    4     u32     version
0x08    4     u32     entry_count
```

Map/level layout data. Internal structure beyond the header is not yet fully
reverse-engineered. Extracted as raw binary.

---

### CHP

**Magic**: `CHP\0` (0x43485000). Chapter/story progression data. Structure
unknown. Extracted as raw binary.

---

### CLS

**Magic**: `CLS\0` (0x434C5300). Class/medal class definition data. Structure
unknown. Extracted as raw binary.

---

### BMI

**Magic**: `BMI\0` (0x424D4900). Battle/mission info data. Structure unknown.
Extracted as raw binary.

---

### JMP

**Magic**: `JMP\0` (0x4A4D5000). Jump table or transition data. Structure
unknown. Extracted as raw binary.

---

## Audio Formats

### AKB - Audio Bank

**Magic**: `AKB ` (0x414B4220, note trailing space).

#### Header

```
Offset  Size  Type  Field        Description
0x00    4     -     magic        "AKB " (0x414B4220)
0x04    2     u16   version      Format version (2 in known files)
0x06    2     u16   header_size  Size of AKB header (68 in known files)
0x08    4     u32   total_size   Total file size including header
```

#### Audio Data

OGG Vorbis audio data starts at offset 204 (after a 204-byte header block).
The OGG data can be extracted directly and played in any audio player.

To extract: strip the first 204 bytes (or find the `OggS` magic) and save
the remainder as `.ogg`.

---

## Configuration Formats

### Plist

Standard Apple property list XML format, used by the cocos2d engine for
configuration, sprite sheet definitions, and UI layouts.

**Detection**: UTF-8 BOM (`0xEFBBBF`) followed by `<`, or bare `<` as first
byte.

Stored as plain UTF-8 text inside BGAD entries.

---

## Save Data

### Save File (.gif)

Despite the `.gif` extension, save files are standard BGAD containers with
mode 2 encryption. Each entry represents a game state variable.

**Typical structure**: 168 entries including:
- `pop_benefit_stone_flag` (1 byte)
- `tracking_events` (variable, JSON-like)
- `new_avatar_board_ids`, `new_avatar_parts_ids`, `new_usermedal_ids`
- Various game state flags and counters

---

### Cocos2dxPrefsFile.xml

The game stores its save data as a base64-encoded BGAD blob inside an XML file:

```xml
<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <string name="data">BASE64_ENCODED_BGAD_DATA</string>
</map>
```

To extract: base64-decode the `<string>` content to get the raw BGAD data, then
parse as a standard BGAD container.

---

## File Distribution

### Container File Extensions

| Extension | Content                              | Encryption     |
|-----------|--------------------------------------|----------------|
| `.mp4`    | Large asset container (audio, images, animations) | Mode 2 or 3 |
| `.png`    | BGI index file (single entry: "/")   | Mode 2 or 3    |
| `.jpg`    | Master data tables (avatar, medals)  | Mode 2         |
| `.gif`    | Save data                            | Mode 2         |

All are BGAD containers regardless of extension.

### Format Distribution

From a 161,651-entry container (mp4/misc.mp4):

| Format  | Count  | Percentage | Description              |
|---------|--------|------------|--------------------------|
| index   | 88,952 | 55.0%      | 4-byte u32 references    |
| btf     | 63,152 | 39.1%      | Images                   |
| lwf     | 5,474  | 3.4%       | Animations               |
| map     | 1,192  | 0.7%       | Map data                 |
| akb     | 1,113  | 0.7%       | Audio                    |
| stg     | 898    | 0.6%       | Stage data               |
| plist   | 376    | 0.2%       | Configuration XML        |
| chp     | 141    | 0.1%       | Chapter data             |
| cls     | 130    | 0.1%       | Class data               |
| bmi     | 124    | 0.1%       | Battle/mission data      |
| unknown | 52     | <0.1%      | Unrecognized formats     |
| jmp     | 47     | <0.1%      | Jump tables              |

---

## Magic Bytes Summary

| Magic (hex)    | Magic (ASCII) | Format | Notes                      |
|----------------|---------------|--------|----------------------------|
| `42 47 41 44`  | `BGAD`        | BGAD   | Container wrapper          |
| `89 42 47 49`  | `\x89BGI`     | BGI    | Index/manifest             |
| `89 42 54 46`  | `\x89BTF`     | BTF    | Image                      |
| `4C 57 46 00`  | `LWF\0`       | LWF    | Animation                  |
| `5D F9 00 00`  | -             | LWF    | LWF variant                |
| `41 4B 42 20`  | `AKB `        | AKB    | Audio (note trailing space)|
| `53 54 47 00`  | `STG\0`       | STG    | Stage data                 |
| `4D 41 50 00`  | `MAP\0`       | MAP    | Map data                   |
| `4A 4D 50 00`  | `JMP\0`       | JMP    | Jump table                 |
| `42 4D 49 00`  | `BMI\0`       | BMI    | Battle/mission info        |
| `43 4C 53 00`  | `CLS\0`       | CLS    | Class data                 |
| `43 48 50 00`  | `CHP\0`       | CHP    | Chapter data               |
| `EF BB BF 3C`  | BOM+`<`       | Plist  | XML config (with BOM)      |

---

## Binary References

Key functions in the decompiled libcocos2dcpp (v5, IDA9):

| Function          | Address    | File                       | Purpose                    |
|-------------------|------------|----------------------------|----------------------------|
| `sub_A16F20`      | 0xA16F20   | libcocos2dcpp_0033.c:1535  | BGAD read + decrypt        |
| `DecryptBGAD`     | 0xA17378   | libcocos2dcpp_0033.c:1766  | ChaCha8 decrypt for mode 3|
| `sub_A174E0`      | 0xA174E0   | libcocos2dcpp_0033.c:1803  | BGAD write + encrypt       |
| `sub_A17B18`      | 0xA17B18   | libcocos2dcpp_0033.c:2117  | Key initialization         |
| `ReadBGIFile`     | 0xA18CB8   | libcocos2dcpp_0033.c:3017  | BGI read + parse           |
| `sub_3933B4`      | 0x3933B4   | libcocos2dcpp_0000.c:4680  | MSVC LCG encryption        |
| `sub_39311C`      | 0x39311C   | libcocos2dcpp_0000.c       | Buffer alloc + seed gen    |
| `sub_6CF7C8`      | 0x6CF7C8   | libcocos2dcpp_0005.c       | AvatarParts struct parse   |
| `ECRYPT_keysetup` | 0xA81E5C   | libcocos2dcpp_0035.c:8997  | ChaCha8 key setup         |
| `ECRYPT_ivsetup`  | 0xA81FF8   | libcocos2dcpp_0035.c:9065  | ChaCha8 IV setup          |
| `ECRYPT_encrypt`  | 0xA82040   | libcocos2dcpp_0035.c:9075  | ChaCha8 cipher            |

**Key location in binaries:**
- v1.0.1 (IDA7): `libcocos2dcpp.so` offset 0xEC6790
- v1.2.3 (arm7): `libcocos2dcpp.arm7.so` offset 0xA9EB14
- v1.2.3 (armeabi): `libcocos2dcpp.armebi.so` offset 0xBDE204
