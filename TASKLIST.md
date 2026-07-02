# KHUx Tool — Missing Implementations & Open Tasks

## Critical — Blocks Newer Content

### ChaCha20 Mode 3 Decryption
- **Status**: Broken — key confirmed in binary, implementation passes test vectors, still produces garbage
- **Blocks**: All mode 3 BGAD entries (1.2.3+, assets/), all encrypted BGI indices
- **Tried**: Both keys (`5CA56C58...` and `FB32833C...`), both ciphers (ChaCha20/Salsa20), all nonce XOR orderings, raw nonces
- **Next steps**: Dump key from live game memory, diff decompiles across versions, check if server-side key rotation exists

### Encrypted BGI Index Parsing
- **Status**: Blocked by ChaCha20
- **Impact**: Can't resolve human-readable names for entries in mode 3 containers
- **Files affected**: `misc.png` (v5), `2016122207.png`, `2017011209.png`, `900003.png`, `aliud.png`

---

## Container Format Parsing

### PNG File Types (3 distinct uses of .png extension)
- [x] **Type 1 — BGAD Container**: `.png` files that are BGAD wrappers around a BGI index (e.g., `misc.png`, `900003.png`)
- [x] **Type 2 — BTF Image**: `.png` files that contain `\x89BTF` image data (e.g., `Input/png/Main/File_*.png`)
- [ ] **Type 3 — Auto-detection**: Need a unified opener that detects BGAD-container vs BTF-image vs actual-PNG based on magic bytes, currently requires user to know which type

### Non-UTF-8 Entry Names
- [x] Fixed — hash-based names (SHA-1) in update containers now fall back to hex display
- [ ] Cross-reference hash names with paired BGI index to show real paths (blocked by encrypted BGI)

---

## Data Format Parsers (inside BGAD entries)

### Implemented
- [x] **BTF** (`\x89BTF`) — Image decode (RGBA + indexed palette), canvas support
- [x] **LWF** (`LWF\0`) — Header parse + raw extraction
- [x] **AKB** (`AKB `) — Detection only, raw extraction
- [x] **Plist** (`\xEFBBBF<` or `<`) — Detection, text display

### Need Full Parser Implementation
- [ ] **STG** (`STG\0`) — Stage definition data. 898 entries in misc.mp4. All 64 bytes in 2016122207, variable in misc.mp4. Header is `magic(4) + version(4) + count(4) + offset(4)`, internal struct unknown
- [ ] **MAP** (`MAP\0`) — Map/level layout data. 1192 entries in misc.mp4. Sizes 176-4176 bytes. Header is `magic(4) + version(4) + entry_count(4)`, internal struct unknown
- [ ] **CHP** (`CHP\0`) — Chapter/story data. 141 entries in misc.mp4. Path pattern: `map/AG_xxxx_xx_xx/..._chp.bin`
- [ ] **CLS** (`CLS\0`) — Class data. 130 entries in misc.mp4. Path pattern: `map/AG_xxxx_xx_xx/..._cls.bin`
- [ ] **BMI** (`BMI\0`) — Battle/mission info. 124 entries in misc.mp4. Path pattern: `map/AG_xxxx_xx_xx/..._info.bin`
- [ ] **JMP** (`JMP\0`) — Jump table data. 47 entries in misc.mp4. Path pattern: `map/AG_xxxx_xx_xx/..._jmp.bin`

### Text/Data Entries
- [ ] **text/drama/*.txt** — Dialog/story scripts (1-3 bytes, raw text like "Doc", "Oh!", "No.", "...")
- [ ] **text/ui/*.txt** — UI strings (1-3 bytes, strings like "OK", "ON", "OFF", "NEW", "Lux", "EXP", "MIN", "MAX", UTF-8 including Japanese: `e794b7`=男, `e5a5b3`=女)
- [ ] **text/misc/*.txt** — Misc text data
- [ ] **revision** — Single byte, version counter
- [ ] **4-byte index entries** — 88,952 entries in misc.mp4, each exactly 4 bytes (u32 LE). Purpose: likely offset/ID references into other tables

---

## Master Data Tables (m*.jpg)

### Implemented
- [x] **MSVC LCG decryption** — Works on all 52 m*.jpg files
- [x] **avatarParts** (m000.jpg) — Full 200-byte struct parsed with 14 fields

### Need Struct Definitions
- [ ] **badstatus** (m001.jpg) — 8 entries, 100B each
- [ ] **battleMisc** (m002.jpg) — 56 entries, 16B each
- [ ] **buff** (m003.jpg) — 56 entries, 96B each
- [ ] **burst** (m004.jpg) — 751 entries, 752B each
- [ ] **colosseum** (m005.jpg) — 176 entries, 228B each
- [ ] **colosseumStage** (m006.jpg) — 17 entries, 100B each
- [ ] **drawMedalType** (m007.jpg) — 88 entries, 1668B each
- [ ] **enemyAttack** (m008.jpg) — 294 entries, 244B each
- [ ] **enemy** (m009.jpg) — 665 entries, 1108B each
- [ ] **evCampaign** (m010.jpg) — 340 entries, 360B each
- [ ] **evMedalList** (m011.jpg) — 118 entries, 32B each
- [ ] **evResource** (m012.jpg) — 13 entries, 28B each
- [ ] **evScoreReward** (m013.jpg) — 140 entries, 260B each
- [ ] **evStage** (m014.jpg) — 423 entries, 1212B each
- [ ] **guiltProb** (m015.jpg) — 230 entries, 28B each
- [ ] **initItem** (m016.jpg) — 110 entries, 36B each
- [ ] **keyblade** (m017.jpg) — 288 entries, 388B each
- [ ] **loginBonus** (m018.jpg) — 101 entries, 2368B each
- [ ] **material** (m019.jpg) — 48 entries, 220B each
- [ ] **medal** (m020.jpg) — 522 entries, 1308B each (high priority — medals are core gameplay)
- [ ] **medalMisc** (m021.jpg) — 22 entries, 24B each
- [ ] **misc** (m022.jpg) — 81 entries, 16B each
- [ ] **mypageBackground** (m023.jpg) — 5 entries, 168B each
- [ ] **player** (m024.jpg) — 301 entries, 36B each
- [ ] **raidEnemyAttack** (m025.jpg) — 64 entries, 224B each
- [ ] **raidEnemy** (m026.jpg) — 106 entries, 884B each
- [ ] **raidReward** (m027.jpg) — 270 entries, 136B each
- [ ] **raidSetting** (m028.jpg) — 35 entries, 76B each
- [ ] **ranking** (m029.jpg) — 176 entries, 84B each
- [ ] **rankingReward** (m030.jpg) — 755 entries, 264B each
- [ ] **reward** (m031.jpg) — 1457 entries, 144B each
- [ ] **serialcodeReward** (m032.jpg) — 7 entries, 440B each
- [ ] **shop** (m033.jpg) — 24 entries, 716B each
- [ ] **skillExp** (m034.jpg) — 4 entries, 24B each
- [ ] **skill** (m035.jpg) — 25 entries, 324B each
- [ ] **sphereArray** (m036.jpg) — 232 entries, 192B each
- [ ] **sphere** (m037.jpg) — 193 entries, 192B each
- [ ] **sphereMasu** (m038.jpg) — 236 entries, 660B each
- [ ] **stage** (m039.jpg) — 1323 entries, 2088B each
- [ ] **stamp** (m040.jpg) — 179 entries, 40B each
- [ ] **title** (m041.jpg) — 864 entries, 352B each
- [ ] **tutorialMisc** (m042.jpg) — 22 entries, 40B each
- [ ] **world** (m043.jpg) — 6 entries, 956B each

---

## GUI App

### Implemented
- [x] PyQt6 3-pane layout (FModel-style)
- [x] File tree with folder hierarchy and format badges
- [x] BTF image preview with zoom
- [x] Text/plist preview
- [x] Hex dump view
- [x] Properties panel
- [x] Export functionality
- [x] Search/filter, recent files, keyboard shortcuts

### Missing
- [ ] BGI index display — show name→entry mapping when selecting a BGI entry (unencrypted ones)
- [ ] Master data display — decrypt and show parsed fields for m*.jpg entries (avatar parts, medals, etc.)
- [ ] Multi-container view — open .png + .mp4 pair together, resolve names via BGI
- [ ] Batch export — export all entries or filtered subset
- [ ] Image gallery — thumbnail grid view for BTF entries
- [ ] Audio playback — AKB preview (if format is understood)
- [ ] Save file editor — edit and re-encrypt save data entries
- [ ] Re-pack/import — create modified BGAD containers from extracted data

---

## Save Data

- [x] **Save file extraction** (.gif) — BGAD mode 2, works
- [x] **Cocos2dxPrefsFile.xml** — Base64 decode to BGAD, documented
- [ ] **Save field documentation** — Map the 168 entry names to their game meanings
- [ ] **Save editor** — Modify and re-encrypt save entries
- [ ] **Save repacker** — Re-encode to BGAD and base64-wrap back to XML

---

## Tooling

- [ ] **Speed-first optimized BGI/BGAD builder** — Fast, purpose-built toolkit for creating and packing game data files. Should support: building BGI indices from file lists, packing BGAD containers with correct encryption modes, batch operations for full game data rebuilds. Priority: performance over flexibility.

---

## Other Formats

- [ ] **Cut files** — Split archive format (like .001/.002 zip parts). Mentioned by user, location unknown in current Input/
- [ ] **Actual MP4 video** — `op_movie.mp4`, `tutorial_movie.mp4`, `dark_op_movie.mp4` are real MP4 videos (ftyp header), not BGAD containers. Should be detected and handled separately
- [ ] **AKB audio** — Internal structure not reverse-engineered. May be CRI middleware or custom format
- [ ] **iPhone binary** — `Input/iPhone5/KINGDOM HEARTS Unchained x` — iOS Mach-O binary, may contain different keys or structures
