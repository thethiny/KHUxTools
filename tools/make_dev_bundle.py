"""Build dev_bundle/ (gitignored): the KHUx files shared with other preservation developers, one folder per task,
personal information removed from the copies, one zip per top-level folder in dev_bundle/zips/.

python tools/make_dev_bundle.py [--step copy|maps|scrub|zip|all]
"""
import os
import re
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IN = ROOT / "Input"
OUT = ROOT / "dev_bundle"
PKG = "com.square_enix.android_googleplay.khuxww"
JP = Path(r"D:\Downloads\KHUX JP 4.3.1 Extracted.zip\Extract JP 4.3.1")
M_113 = Path(r"D:\Modding\KHUx\m")
SKIP_NAMES = {"Thumbs.db", "desktop.ini", "debug.keystore"}
SKIP_SUFFIX = (" - Copy.i64",)

# (source, destination inside dev_bundle); a folder source is copied recursively
COPY = [
    # ---- data: the game's own data files per version
    (ROOT / f"recomp/fs/data/data/{PKG}/files/m", "data/1.0.1/m"),
    (IN / "1.0.1/misc.mp4", "data/1.0.1/apk_assets/misc.mp4"),
    (IN / "1.0.1/misc.png", "data/1.0.1/apk_assets/misc.png"),
    (M_113, "data/1.1.3/m"),
    (IN / "1.2.3/misc.mp4", "data/1.2.3/apk_assets/misc.mp4"),
    (IN / "1.2.3/misc.png", "data/1.2.3/apk_assets/misc.png"),
    (IN / "1.2.3/op_movie.mp4", "data/1.2.3/apk_assets/op_movie.mp4"),
    (IN / "1.2.3/tutorial_movie.mp4", "data/1.2.3/apk_assets/tutorial_movie.mp4"),
    (IN / f"main.76.{PKG}.obb", f"data/4.4.0/main.76.{PKG}.obb"),
    (IN / f"patch.87.{PKG}.obb", f"data/4.4.0/patch.87.{PKG}.obb"),
    (JP, "data/jp_final_4.3.1"),
    # ---- map: the resource bundle that holds every story map and room (extract with KHUxTools)
    (IN / "mp4/misc.mp4", "map/resource_bundle_2016/misc.mp4"),
    (IN / "mp4/misc.png", "map/resource_bundle_2016/misc.png"),
    # ---- decompile: IDA databases and exports per version
    (IN / "1.0.1/libcocos2dcpp_decompile", "decompile/1.0.1/libcocos2dcpp_decompile"),
    (IN / "1.0.1/server_api.json", "decompile/1.0.1/server_api.json"),
    (IN / "1.0.1/libcocos2dcpp_memdump_decompile", "decompile/1.0.1/runtime_memdump/libcocos2dcpp_memdump_decompile"),
    (IN / "1.1.3/lib", "decompile/1.1.3/lib"),
    (IN / "khux_1.1.3_decompiled", "decompile/1.1.3/apktool"),
    (IN / "1.2.3/libcocos2dcpp.armebi_decompile", "decompile/1.2.3/libcocos2dcpp.armebi_decompile"),
    # ---- builds: original APKs and the patched libraries (no modified APKs)
    (IN / "Kingdom Hearts Unchained χ (1.0.1).apk", "builds/1.0.1/original/khux_1.0.1.apk"),
    (IN / f"{PKG}_1.1.3.apk", "builds/1.1.3/original/khux_1.1.3.apk"),
    (IN / "Kingdom Hearts Unchained χ (1.2.3).apk", "builds/1.2.3/original/khux_1.2.3.apk"),
    (IN / f"{PKG}_4.4.0.apk", "builds/4.4.0/original/khux_4.4.0.apk"),
]
for f in sorted((IN / "1.0.1").glob("libcocos2dcpp_patched*.so")) + [IN / "1.0.1/libcocos2dcpp_gadget.so"]:
    COPY.append((f, f"builds/1.0.1/patched_libs/{f.name}"))
for f in sorted((IN / "1.1.3").glob("lib__57d5___*.so")) + sorted((IN / "1.1.3").glob("unpacked_*.bin")):
    COPY.append((f, f"builds/1.1.3/protection_lib_experiments/{f.name}"))
# not copied from inside a copied folder (they have their own place)
EXCLUDE_UNDER = {IN / "1.1.3" / "lib"} | {f for f in (IN / "1.1.3").glob("lib__57d5___*.so")} | \
    {f for f in (IN / "1.1.3").glob("unpacked_*.bin")}


def log(msg):
    print(msg, flush=True)


# decompile/: only the IDA export text (C, headers, index/strings/names/... lists); no binaries or databases
EXPORT_EXT = {".c", ".h", ".txt", ".json"}
EXPORT_SRC = [IN / "1.0.1/libcocos2dcpp_decompile", IN / "1.0.1/libcocos2dcpp_memdump_decompile", IN / "1.1.3/lib",
              IN / "1.2.3/libcocos2dcpp.armebi_decompile"]


def skip(p: Path):
    if any(src in p.parents for src in EXPORT_SRC) and p.is_file() and p.suffix.lower() not in EXPORT_EXT:
        return True
    return _skip(p)


def _skip(p: Path):
    # *_out = KHUxTools output (decrypted/extracted copies): the recipients have the tools
    return p.name in SKIP_NAMES or p.name.endswith(SKIP_SUFFIX) or p.name.endswith("_out") or p in EXCLUDE_UNDER


def copy_all():
    for src, dst in COPY:
        if not src.exists():
            sys.exit(f"missing source: {src}")
        d = OUT / dst
        if src.is_file():
            if not d.exists() or d.stat().st_size != src.stat().st_size:
                d.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, d)
            continue
        n = 0
        for dirpath, dirnames, filenames in os.walk(src):
            dp = Path(dirpath)
            dirnames[:] = [x for x in dirnames if not skip(dp / x)]
            for name in filenames:
                s = dp / name
                if skip(s):
                    continue
                t = d / s.relative_to(src)
                if t.exists() and t.stat().st_size == s.stat().st_size:
                    continue
                t.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(s, t)
                n += 1
        log(f"copied {src} -> {dst} ({n} files)")


def extract_maps():
    """Every stage/ and map/ entry of the 2016 resource bundle, under their own names."""
    sys.path.insert(0, str(ROOT))
    from khux.containers.bgad import KHUxBGADContainer
    dest = OUT / "map/extracted"
    n = 0
    for e in KHUxBGADContainer(str(IN / "mp4/misc.mp4")).iter_entries_lazy():
        name = e.name or ""
        if not (name.startswith("stage/") or name.startswith("map/")):
            continue
        t = dest / name
        t.parent.mkdir(parents=True, exist_ok=True)
        t.write_bytes(e.data)
        n += 1
    log(f"extracted {n} stage/ and map/ entries")


# ---- scrubbing: personal information in text files of the copies
TEXT_EXT = {".c", ".h", ".txt", ".md", ".json", ".yml", ".yaml", ".xml", ".smali", ".asm", ".py", ".log", ".csv",
            ".ini", ".cfg", ".html", ".js"}
PATTERNS = [
    (re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s\"']+", re.I), r"<home>"),
    (re.compile(r"[A-Za-z]:[\\/]+(?:Modding|Downloads)[\\/][^\s\"'<>|]*", re.I), r"<path>"),
    (re.compile(r"[\w.+-]+@(?:gmail\.com|first\.tech)", re.I), r"<email>"),
    (re.compile(r"\b(?:192\.168|10\.\d{1,3})\.\d{1,3}\.\d{1,3}(?::\d+)?\b"), r"<ip>"),
]


# Only text we produced is scrubbed: our docs and the IDA exports (which can record the analyst's file paths).
# Game files (data/, map/, builds/, the apktool output) are never altered.
SCRUB_ROOTS = ["README.md", "JOURNAL.md", "builds/README.md", "decompile/1.0.1", "decompile/1.1.3/lib", "decompile/1.2.3"]


def scrub_targets():
    for r in SCRUB_ROOTS:
        p = OUT / r
        if p.is_file():
            yield p
        elif p.is_dir():
            yield from (f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in TEXT_EXT)


def restore():
    """Recopy any copied text file that differs from its source (undoes an earlier over-broad scrub)."""
    fixed = 0
    for src, dst in COPY:
        pairs = [(src, OUT / dst)] if src.is_file() else [
            (s, OUT / dst / s.relative_to(src)) for s in src.rglob("*") if s.is_file() and not skip(s)]
        for s, d in pairs:
            if s.suffix.lower() in TEXT_EXT and d.exists() and d.read_bytes() != s.read_bytes():
                shutil.copy2(s, d)
                fixed += 1
    log(f"restored {fixed} files to their original bytes")


def scrub():
    changed = 0
    hits = {}
    for p in scrub_targets():
        try:
            s = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            s = p.read_text(encoding="latin-1")
        t = s
        for rx, rep in PATTERNS:
            t, k = rx.subn(rep, t)
            if k:
                hits[rep] = hits.get(rep, 0) + k
        if t != s:
            p.write_text(t, encoding="utf-8")
            changed += 1
    log(f"scrubbed {changed} text files: {hits}")


STORED = {".apk", ".obb", ".mp4", ".png", ".jpg", ".gif", ".ogg", ".zip", ".7z", ".xapk"}


def zip_all():
    zdir = OUT / "zips"
    zdir.mkdir(exist_ok=True)
    # one zip per top-level folder; the JP dump (huge) gets a zip of its own, outside the data zip
    jp = OUT / "data/jp_final_4.3.1"
    units = [(p.name, p, jp if p.name == "data" else None)
             for p in sorted(OUT.iterdir()) if p.is_dir() and p.name != "zips"]
    units.append(("jp_final_4.3.1", jp, None))
    docs = [p for p in sorted(OUT.iterdir()) if p.is_file() and p.suffix == ".md"]
    for name, top, exclude in units:
        z = zdir / f"khux_dev_{name}.zip"
        with zipfile.ZipFile(z, "w", allowZip64=True) as zf:
            for f in sorted(top.rglob("*")):
                if exclude is not None and exclude in f.parents:
                    continue
                if f.is_file():
                    method = zipfile.ZIP_STORED if f.suffix.lower() in STORED else zipfile.ZIP_DEFLATED
                    zf.write(f, f.relative_to(OUT), compress_type=method, compresslevel=6)
            for d in docs:                       # README / JOURNAL in every zip
                zf.write(d, d.name)
        log(f"{z.name}: {z.stat().st_size / 2**30:.2f} GB")


def main():
    step = sys.argv[sys.argv.index("--step") + 1] if "--step" in sys.argv else "all"
    OUT.mkdir(exist_ok=True)
    if step in ("copy", "all"):
        copy_all()
    if step == "maps":
        extract_maps()
    if step == "restore":
        restore()
    if step in ("scrub", "all"):
        scrub()
    if step in ("zip",):
        zip_all()


if __name__ == "__main__":
    main()
