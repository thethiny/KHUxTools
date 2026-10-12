"""Derive master-table binary layouts from the game's own JSON parsers (IDA decompiles).

Every v1.x table has a `master::<Name>::parse(rapidjson value)` that type-checks the JSON keys and writes each
value into a SafeBuffer record with `SafeBuffer::write(buf, ptr, src, size, offset)`; the record size is the
SafeBuffer constructor argument. Following that dataflow gives, per table and per game version, the exact
key -> (offset, size, kind) layout - no guessing from data.

  python tools/master_layout.py                 # extract 1.0.1 + 1.1.3 (+ 1.2.3) layouts -> tools/master_layouts.json
  python tools/master_layout.py --show stage    # print one table side by side

Kinds: int (4 bytes), date (8 bytes, "YYYY-MM-DD HH:MM:SS"), str (fixed char[N]), int[] (N*4), str[] (N*len).
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DECOMPILES = {
    "1.0.1": ROOT / "Input/1.0.1/libcocos2dcpp_decompile",
    "1.1.3": ROOT / "Input/1.1.3/lib/armeabi/libcocos2dcpp_decompile/decompile",
    "1.2.3": ROOT / "Input/1.2.3/libcocos2dcpp.armebi_decompile",
}
OUT = ROOT / "tools/master_layouts.json"

FUNC_RE = re.compile(r"^// ==== (\S+) \(ea=(0x[0-9A-Fa-f]+)\) ====$", re.M)
KEY_RE = re.compile(r'operator\[\]\(\s*\w+,\s*"(\w+)"\s*\)')
WRITE_RE = re.compile(r"SafeBuffer::write\(")
CTOR_RE = re.compile(r"SafeBuffer::SafeBuffer\([^,]+,\s*(0x[0-9A-Fa-f]+|\d+)u?,\s*1\)")
ASSIGN_KEY_RE = re.compile(r"(v\d+)\s*=\s*(?:\([^()]*\)\s*)?rapidjson::")
ALIAS_RE = re.compile(r"(?:^|[{}]\s*|\)\s*)(v\d+)\s*=\s*(?:\([^()]*\)\s*)?(v\d+)\s*$")
DERIVE_RE = re.compile(r"^\s*(v\d+)\s*=\s*\*\s*(?:\([^()]*\)\s*)?(v\d+)\s*$")
STRCPY_RE = re.compile(r"\b(?:strncpy|strlcpy|sub_[0-9A-F]+)\(\s*([^,]+),\s*\*\s*\(const char \*\*\)\s*(v\d+)\s*,\s*(0x[0-9A-Fa-f]+|\d+)u?\s*\)")


def num(s):
    s = s.strip().rstrip("uU")
    try:
        return int(s, 16) if s.lower().startswith("0x") else int(s)
    except ValueError:
        return None   # computed (loop-indexed) size/offset


def split_args(s):
    """Split the argument list starting right after '(' up to the matching ')'."""
    depth, cur, out = 0, "", []
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            if depth == 0:
                out.append(cur)
                return out
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    return out


def load_functions(folder):
    funcs = {}
    files = sorted(Path(folder).glob("*.c"))
    for f in files:
        text = f.read_text(errors="replace")
        marks = list(FUNC_RE.finditer(text))
        for k, m in enumerate(marks):
            end = marks[k + 1].start() if k + 1 < len(marks) else len(text)
            funcs[(m.group(1), m.group(2))] = text[m.end():end]
    return funcs


def extract(body):
    """Return (record_size, [field dicts in write order]) for one parse function body."""
    ctor = CTOR_RE.search(body)
    if not ctor:
        return None, []
    size = num(ctor.group(1))
    # statement stream (keep order); ';' separates statements, braces are noise
    stmts = [s.strip() for s in re.split(r";", body)]
    var_key = {}          # var -> key whose value it holds (or whose rapidjson node it is)
    key_type = {}         # key -> type flag from its check
    key_order = []
    last_key = None       # most recently accessed key since the previous write
    pending_date = pending_str = None
    fields, seen_write_keys = [], set()
    started = False
    for s in stmts:
        if CTOR_RE.search(s):
            started = True
        for km in KEY_RE.finditer(s):
            key = km.group(1)
            if key not in key_order:
                key_order.append(key)
            last_key = key
            am = ASSIGN_KEY_RE.search(s[:km.start()])
            if am:
                var_key[am.group(1)] = key
            tail = s[km.end():km.end() + 60]
            t = None
            if re.search(r"\+\s*14\)?\s*&\s*0x10", tail):
                t = "str"
            elif (re.search(r"\+\s*12\)?\s*[!=]=\s*4", tail) or re.search(r"\+\s*3\)?\s*[!=]=\s*4", tail)
                  or re.search(r"\[3\]\s*[!=]=\s*4", s)):
                t = "array"
            elif re.search(r"\+\s*12\)?\s*[!=]=\s*3", tail) or re.search(r"\+\s*3\)?\s*[!=]=\s*3", tail):
                t = "object"
            elif re.search(r"\+\s*13\)?\s*&\s*(4|0x20|8|0x40|0x10)", tail):
                t = "num"
            if t and key not in key_type:
                key_type[key] = t
        dm = DERIVE_RE.match(s.split("\n")[-1]) or DERIVE_RE.match(s)
        if dm and dm.group(2) in var_key:
            var_key[dm.group(1)] = var_key[dm.group(2)]
        for vm in re.finditer(r"\(\s*\(?(?:_DWORD \*\)\s*)?(v\d+)\s*\+\s*(12|3)\)\s*[!=]=\s*4|\b(v\d+)\[3\]\s*[!=]=\s*4", s):
            v = vm.group(1) or vm.group(3)
            if v in var_key:
                key_type.setdefault(var_key[v], "array")
        al = ALIAS_RE.search(s)
        if al and al.group(2) in var_key:
            var_key[al.group(1)] = var_key[al.group(2)]
        if "Date::init" in s:
            pending_date = last_key
        sm = STRCPY_RE.search(s)
        if sm:
            pending_str = (var_key.get(sm.group(2), last_key), num(sm.group(3)))
        if not started:
            continue
        wm = WRITE_RE.search(s)
        if not wm:
            continue
        args = split_args(s[wm.end():])
        if len(args) < 5:
            continue
        src, wsize, woff = args[2].strip(), num(args[3]), num(args[4])
        if wsize is None or woff is None:
            fields.append({"key": last_key, "offset": None, "size": None, "kind": "computed",
                           "expr": f"size={args[3].strip()} off={args[4].strip()}"})
            continue
        scalar = re.search(r"&\s*(v\d+)\s*$", src)
        key = None
        kind = None
        if scalar and scalar.group(1) in var_key:
            key = var_key[scalar.group(1)]
            kind = "int"
        elif pending_date and wsize == 8:
            key, kind = pending_date, "date"
        elif pending_str and pending_str[0]:
            key = pending_str[0]
            elen = pending_str[1]
            kind = "str" if elen >= wsize else "str[]"
            if kind == "str[]":
                kind = f"str[{wsize // elen}x{elen}]"
            else:
                kind = f"str[{wsize}]"
        else:
            key = last_key
            if key_type.get(key) == "array":
                kind = f"int[{wsize // 4}]"
            elif key_type.get(key) == "str":
                kind = f"str[{wsize}]"
            else:
                kind = "int" if wsize == 4 else f"bytes[{wsize}]"
        if kind == "int" and wsize != 4:
            kind = f"bytes[{wsize}]"
        fields.append({"key": key, "offset": woff, "size": wsize, "kind": kind})
        seen_write_keys.add(key)
        last_key = None
        pending_date = pending_str = None
    unwritten = [k for k in key_order if k not in seen_write_keys]
    return size, fields, unwritten


def table_name_101(fname):
    m = re.match(r"_ZN6master(\d+)(\w+?)5parseE", fname)
    if not m:
        return None
    n = int(m.group(1))
    cls = m.group(2)[:n]
    return cls[0].lower() + cls[1:]


def main():
    if "--show" in sys.argv:
        data = json.loads(OUT.read_text())
        t = sys.argv[sys.argv.index("--show") + 1]
        for ver, tabs in data.items():
            if t in tabs:
                print(f"== {ver} size={tabs[t]['size']}")
                for f in tabs[t]["fields"]:
                    print(f"  {f['offset']:5} {f['size']:4} {f['kind']:<12} {f['key']}")
                if tabs[t].get("unwritten"):
                    print("  unwritten keys:", tabs[t]["unwritten"])
        return

    result = {}
    f101 = load_functions(DECOMPILES["1.0.1"])
    tables = {}
    for (fname, ea), body in f101.items():
        t = table_name_101(fname)
        if t and "SafeBuffer::SafeBuffer" in body:
            size, fields, unwritten = extract(body)
            tables[t] = {"ea": ea, "size": size, "fields": fields, "unwritten": unwritten}
    result["1.0.1"] = tables
    print(f"1.0.1: {len(tables)} tables")

    # other versions: match parse functions by their key sets
    for ver in ("1.1.3", "1.2.3"):
        folder = DECOMPILES[ver]
        if not folder.exists():
            continue
        funcs = load_functions(folder)
        cands = []
        for (fname, ea), body in funcs.items():
            if "SafeBuffer::SafeBuffer" not in body or "operator[]" not in body:
                continue
            keys = set(KEY_RE.findall(body))
            if keys:
                cands.append((fname, ea, body, keys))
        vt = {}
        for t, info in tables.items():
            ref = {f["key"] for f in info["fields"]} | set(info["unwritten"])
            best = None
            for fname, ea, body, keys in cands:
                score = len(ref & keys) / max(1, len(ref | keys))
                if best is None or score > best[0]:
                    best = (score, fname, ea, body)
            if best and best[0] >= 0.5:
                size, fields, unwritten = extract(best[3])
                vt[t] = {"ea": best[2], "match": round(best[0], 2), "size": size, "fields": fields,
                         "unwritten": unwritten}
        result[ver] = vt
        print(f"{ver}: {len(vt)} tables matched")
    OUT.write_text(json.dumps(result, indent=1))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
