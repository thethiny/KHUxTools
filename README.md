# KHUx revival

Tools to play **Kingdom Hearts Union χ** (KHUx / Kingdom Hearts Unchained χ) again. Square Enix shut the game
down in 2021, and nobody recorded the server's traffic. This repository rebuilds what is needed from the game's
own code:

| Part | Folder | What it is |
|---|---|---|
| Private server | [`server/`](server/README.md) | A replacement for the official server, written for the v1.0.1 client. Every response was worked out from the client's code. |
| Native PC build and rewrite | [`recomp/`](recomp/README.md) (submodule, [KHUx-Recomp](https://github.com/thethiny/KHUx-Recomp)) | The v1.0.1 Android library translated to C and run natively on Windows, plus a hand-written C++ rewrite of the game's code, checked against the original call by call. |
| File toolkit | `khux/`, `gui/` | Python library and asset browser for the game's files: containers, encryption, images, master data. |

The target client is **v1.0.1**, the first release, before anti-tamper and the 2021 shutdown notice. Later
versions serve as references: the v5.0.1 offline build shows the master data format, a v1.1.3 dump provides the
2015-era values, and v4.x supplies later assets and field names.

## Playing

1. Start the server (see [server/README.md](server/README.md)):
   `cd server && KHUX_VERSION_RES=1 python run.py`
2. Install the game files from your own v1.0.1 APK and build the native game (see
   [recomp/README.md](recomp/README.md)), then run `recomp/out/host/khux.exe`.

The native build redirects every server name to the local server by itself. A real Android device or emulator
works too, with its DNS pointed at the server (`server/SETUP.md`).

Game files and assets are not included; you need your own copy of the APK.

## File toolkit

```python
from khux.containers.bgad import KHUxBGADContainer
from khux.utils.crypto import KEY_APK, KEY_DOWNLOAD
from khux.detect import detect_format

# Mode 2 containers (v1.0.1, OBBs, save files): no key needed
container = KHUxBGADContainer("misc.mp4")
entries = container.iter_entries()

# Mode 3 containers: pass the matching key
container = KHUxBGADContainer("misc.mp4", encryption_key=KEY_APK)       # APK-bundled files
container = KHUxBGADContainer("misc.mp4", encryption_key=KEY_DOWNLOAD)  # downloaded files
```

```bash
python -m gui.app      # FModel-style 3-pane asset browser (PyQt6)
```

- **BGAD containers**: modes 0 (none), 1 (byte LCG), 2 (DWORD LCG), 3 (ChaCha8)
- **BGI index**: maps file names to container entries
- **BTF images** to PNG (RGBA and indexed palette)
- **Master data**: encrypted game tables, with the v1.0.1 and v1.1.3 layouts (`khux/formats/master_tables.py`)
- **LWF, STG, MAP, AKB** and others: detection and extraction
- **Save files**: `.gif` save data and `Cocos2dxPrefsFile.xml`

| Key | Use | Value |
|-----|-----|-------|
| KEY_APK | Small APK files (misc.mp4/misc.png) | `5CA56C5827FA15CF1ECE2A37180953B801DEBFD0A71DD6AA6DD1D4F414A5FBC4` |
| KEY_DOWNLOAD | Downloaded files in the "r" folder | `3C8499BF7EEE43BD1B4DDE853725A110F0914C76C167BE9D3C902CBEE790B03E` |
| KEY_SAVE | Saved/cache files | `FB32833C8CC403018AC1EAB921F56C2618A4AF7E38CCC9CF5267AA19FDBA320C` |

Mode 3 uses **ChaCha8** (8 rounds), not ChaCha20. The nonce is the last 8 bytes of each BGAD entry's data
section, XOR'd with `62 C0 D9 49 9B 15 83 72`. All formats are documented in [FILEFORMATS.md](FILEFORMATS.md).

## Other folders

`tools/`: helper scripts: reading master data layouts from the client's parsers (`master_layout_asm.py`),
regenerating the served tables (`regen_master.py`), index builders, and the tap automation from the phone-based
phase.

## Credits

- **bnnm**: identified the cipher as ChaCha8 (not ChaCha20) and created
  [khuxdecrypt3](https://hcs64.com/mboard/forum.php?showthread=59144) with working mode 3 decryption and key
  selection logic
- **xlash123**: API encryption research (khux-re-api)
- **thethiny**: project author, initial BGAD/BTF reverse engineering

## License

MIT, see [LICENSE](LICENSE). Credit is required: keep the copyright notice in copies and
derived work. Game data and assets are not covered (they belong to Square Enix).
