"""Read-only scan of dev_bundle/ for personal information (paths, emails, private IPs, user names). Reports, never
changes anything. python tools/check_dev_bundle.py"""
import re
from collections import defaultdict
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "dev_bundle"
PATTERNS = {
    "home path": re.compile(rb"[A-Za-z]:[\\/]+Users[\\/]+\w+", re.I),
    "drive path": re.compile(rb"[A-Za-z]:[\\/]+(?:Modding|Downloads|Ridhwan)[\\/]", re.I),
    "email": re.compile(rb"[\w.+-]+@(?:gmail\.com|first\.tech)", re.I),
    "private ip": re.compile(rb"\b192\.168\.\d{1,3}\.\d{1,3}\b"),
    "name": re.compile(rb"rdebsi|Ridhwan", re.I),
}


def main():
    hits = defaultdict(list)
    files = 0
    for p in OUT.rglob("*"):
        if not p.is_file() or "zips" in p.parts:
            continue
        files += 1
        with open(p, "rb") as f:
            prev = b""
            while True:
                chunk = f.read(1 << 24)
                if not chunk:
                    break
                buf = prev + chunk
                for kind, rx in PATTERNS.items():
                    for m in rx.finditer(buf):
                        hits[kind].append((p.relative_to(OUT).as_posix(), m.group(0)[:80]))
                prev = chunk[-256:]
    print(f"scanned {files} files")
    for kind, lst in hits.items():
        uniq = sorted(set(lst))
        print(f"== {kind}: {len(uniq)} distinct matches")
        for path, text in uniq[:40]:
            print(f"   {path}: {text!r}")


if __name__ == "__main__":
    main()
