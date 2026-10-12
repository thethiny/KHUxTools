"""Convert raw date dicts in master-data JSONs to the string format the game parses.

Older master_tables.py / master.py output dumped 8-byte Date fields as {"_date_lo": .., "_date_hi": ..}.
The v1.0.1 JSON parsers (e.g. master::MypageBackground::parse) require a string accepted by
Date::init ("YYYY-MM-DD HH:MM:SS") and reject the whole table otherwise ("server error" during the
tutorial download). Fixed at the source in khux/formats; this rewrites already-generated files.

python tools/fix_master_dates.py [server/data]
"""
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from khux.formats.master_tables import format_date  # noqa: E402


def fix(v):
    if isinstance(v, dict) and set(v) == {"_date_lo", "_date_hi"}:
        return format_date(struct.pack("<II", v["_date_lo"], v["_date_hi"])), 1
    if isinstance(v, dict):
        n = 0
        for k in v:
            v[k], c = fix(v[k])
            n += c
        return v, n
    if isinstance(v, list):
        n = 0
        for i, x in enumerate(v):
            v[i], c = fix(x)
            n += c
        return v, n
    return v, 0


def main():
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "server/data")
    for p in sorted(root.glob("*.json")):
        text = p.read_text(encoding="utf-8")
        if "_date_lo" not in text:
            continue
        data, n = fix(json.loads(text))
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{p.name}: {n} dates converted")


if __name__ == "__main__":
    main()
