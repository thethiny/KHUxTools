"""Keys that the v1.0.1 master::X::parse functions type-check as JSON arrays.

The layout extractors decide a field's kind from its SafeBuffer write size, so a one-element array (4 bytes)
looks like a plain int - e.g. drawMedalType.warrantMedalListIds, which the client rejects unless it is an
array. The parser's type check tells them apart: after `operator[](v, "key")` an array is tested on the
value's type tag at +12 (`+ 12) != 4` / `[3] == 4`), a number on the flag byte at +13.

Time fields are found the same way: keys whose string goes to Time::init ("HH:MM:SS"; stored as 4 bytes h, m,
s, flags) - the layout tools report them as int.

  python tools/master_array_keys.py   # writes tools/master_array_keys_1.0.1.json and master_time_keys_1.0.1.json
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DECOMP = ROOT / "Input/1.0.1/libcocos2dcpp_decompile/decompile"
OUT = ROOT / "tools/master_array_keys_1.0.1.json"
OUT_TIME = ROOT / "tools/master_time_keys_1.0.1.json"

FUNC = re.compile(r"^[\w ]*__fastcall master::(\w+)::parse\(", re.M)
KEY = re.compile(r'"([A-Za-z][A-Za-z0-9]*)"\)')


def table_name(cls):
    return cls[0].lower() + cls[1:]


def main():
    result, times = {}, {}
    for f in sorted(DECOMP.glob("*.c")):
        text = f.read_text(encoding="utf-8", errors="replace")
        starts = [(m.start(), m.group(1)) for m in FUNC.finditer(text)]
        for i, (pos, cls) in enumerate(starts):
            end = text.find("\n}\n", pos)
            body = text[pos:end if end > 0 else len(text)]
            arrays = set()
            for m in KEY.finditer(body):
                after = body[m.end():m.end() + 160]
                if re.match(r"\s*\+\s*12\)", after) or re.match(r"\s*\[3\]\s*[!=]=\s*4", after) or \
                        re.match(r"\s*;\s*\n\s*if \( v\d+\[3\] [!=]= 4", after):
                    arrays.add(m.group(1))
            # `v = operator[](x, "key"); if ( v[3] == 4 )` (key then a separate check line)
            for m in re.finditer(r'(v\d+) = \([^)]*\)rapidjson[^;]*?"([A-Za-z][A-Za-z0-9]*)"\);\s*\n\s*if \( \1\[3\] [!=]= 4',
                                 body):
                arrays.add(m.group(2))
            if arrays:
                result.setdefault(table_name(cls), set()).update(arrays)
            for m in KEY.finditer(body):
                if "Time::init" in body[m.end():m.end() + 400].split("operator[]")[0]:
                    times.setdefault(table_name(cls), set()).add(m.group(1))
    out = {k: sorted(v) for k, v in sorted(result.items())}
    OUT.write_text(json.dumps(out, indent=1))
    OUT_TIME.write_text(json.dumps({k: sorted(v) for k, v in sorted(times.items())}, indent=1))
    print(f"{len(out)} tables with array keys -> {OUT.name}; time keys {times} -> {OUT_TIME.name}")
    return out


if __name__ == "__main__":
    main()
