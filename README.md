# KHUx File Extractor

A Python toolkit for extracting and decrypting game assets from
**Kingdom Hearts Union Cross** (KHUx / KHUX / Kingdom Hearts Unchained X).

Supports all encryption modes including the ChaCha8 encryption used in later
game versions.

## Features

- **BGAD Container Extraction** — modes 0 (none), 1 (byte LCG), 2 (DWORD LCG), 3 (ChaCha8)
- **BGI Index Parsing** — maps file names to container entries
- **BTF Image Decoding** — converts KHUx's custom image format to PNG (RGBA + indexed palette)
- **Master Data Decryption** — MSVC LCG encrypted game tables (avatars, medals, skills, etc.)
- **LWF/STG/MAP/AKB** — format detection and raw extraction
- **Save File Extraction** — .gif save data and Cocos2dxPrefsFile.xml
- **PyQt6 GUI** — FModel-style 3-pane asset browser

## Quick Start

```python
from khux.containers.bgad import KHUxBGADContainer
from khux.utils.crypto import KEY_APK, KEY_DOWNLOAD
from khux.detect import detect_format

# Mode 2 containers (v1.0.1, OBBs, save files) — no key needed
container = KHUxBGADContainer("misc.mp4")
entries = container.iter_entries()

# Mode 3 containers — pass the appropriate key
container = KHUxBGADContainer("misc.mp4", encryption_key=KEY_APK)       # APK-bundled files
container = KHUxBGADContainer("misc.mp4", encryption_key=KEY_DOWNLOAD)  # downloaded files
```

## Encryption Keys

| Key | Use | Value |
|-----|-----|-------|
| KEY_APK | Small APK files (misc.mp4/misc.png) | `5CA56C5827FA15CF1ECE2A37180953B801DEBFD0A71DD6AA6DD1D4F414A5FBC4` |
| KEY_DOWNLOAD | Downloaded files in "r" folder | `3C8499BF7EEE43BD1B4DDE853725A110F0914C76C167BE9D3C902CBEE790B03E` |
| KEY_SAVE | Saved/cache files | `FB32833C8CC403018AC1EAB921F56C2618A4AF7E38CCC9CF5267AA19FDBA320C` |

Mode 3 uses **ChaCha8** (8 rounds), not ChaCha20. The nonce is the last 8 bytes
of each BGAD entry's data section, XOR'd with `62 C0 D9 49 9B 15 83 72`.

## GUI

```bash
python -m gui.app
```

## File Formats

See [FILEFORMATS.md](FILEFORMATS.md) for complete documentation of all formats.

## Credits

- **bnnm** — identified the cipher as ChaCha8 (not ChaCha20) and created
  [khuxdecrypt3](https://hcs64.com/mboard/forum.php?showthread=59144) with
  working mode 3 decryption and key selection logic
- **thethiny** — project author, initial BGAD/BTF reverse engineering

## License

See individual file headers for attribution.
