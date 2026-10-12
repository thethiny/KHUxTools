"""Derive master-table layouts from the *disassembly* of the game's JSON parse functions.

Companion to master_layout.py (which reads IDA decompiles). Some versions' big parse functions were never
decompiled (1.1.3: enemy, stage, medal, skill, keyblade, ...), so this reads the ARM/Thumb code directly:
key strings are found through their PC-relative loads, each parse function is swept linearly with simple
constant tracking, and the event stream

    operator[](json, "key")  |  SafeBuffer(buf, size, 1)  |  Date::init  |  strncpy(dst, src, n)
    SafeBuffer::write(buf, ptr, src, size=r3, offset=[sp])

is turned into key -> (offset, size, kind) with the same attribution rules as the decompile extractor.
It is validated by running it on 1.0.1 and comparing with the decompile-derived layouts.

  python tools/master_layout_asm.py 1.0.1          # validate against tools/master_layouts.json
  python tools/master_layout_asm.py 1.1.3          # write tools/master_layouts_asm_1.1.3.json
"""
import json
import re
import struct
import sys
from pathlib import Path

from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs
from elftools.elf.elffile import ELFFile

ROOT = Path(__file__).resolve().parents[1]
BUILDS = {
    "1.0.1": (ROOT / "Input/1.0.1/libcocos2dcpp.so", ROOT / "Input/1.0.1/libcocos2dcpp_decompile/strings.txt"),
    "1.1.3": (ROOT / "Input/1.1.3/lib/armeabi/libcocos2dcpp.so",
              ROOT / "Input/1.1.3/lib/armeabi/libcocos2dcpp_decompile/strings.txt"),
}
LAYOUTS = ROOT / "tools/master_layouts.json"
KEY_ADDRS = set()   # string addresses of known JSON keys (filled per build)
IDENT = re.compile(r"^[a-z][A-Za-z0-9_]{1,40}$")   # any JSON-key-like string (fields new in later versions)
DEBUG = sys.argv[sys.argv.index("--debug") + 1] if "--debug" in sys.argv else None


class Image:
    def __init__(self, path):
        self.raw = Path(path).read_bytes()
        elf = ELFFile(open(path, "rb"))
        self.loads = [(s["p_vaddr"], s["p_offset"], s["p_filesz"]) for s in elf.iter_segments()
                      if s["p_type"] == "PT_LOAD"]
        sec = {s.name: s for s in elf.iter_sections()}
        t = sec[".text"]
        self.text = (t["sh_addr"], t["sh_addr"] + t["sh_size"])
        self.syms = {}
        for s in sec[".dynsym"].iter_symbols():
            if s.name and s["st_shndx"] != "SHN_UNDEF":
                self.syms[s.name] = s["st_value"]
        # PLT: stub address -> symbol name (calls in PIC code go through these)
        self.plt = {}
        syms = list(sec[".dynsym"].iter_symbols())
        got_sym = {r["r_offset"]: syms[r["r_info_sym"]].name for r in sec[".rel.plt"].iter_relocations()}
        md = Cs(CS_ARCH_ARM, 0)
        plt = sec[".plt"]
        lo, hi = plt["sh_addr"], plt["sh_addr"] + plt["sh_size"]
        for stub in range(lo + 20, hi, 12):
            ins = list(md.disasm(self.read(stub, 12), stub))
            if len(ins) != 3:
                continue
            imms = []
            for i in ins:
                parts = [int(p.split()[0].rstrip("]!,"), 0) for p in i.op_str.split("#")[1:]]
                imms.append(((parts[0] >> parts[1]) | (parts[0] << (32 - parts[1]))) & 0xFFFFFFFF
                            if len(parts) == 2 else parts[-1])
            got = (stub + 8 + sum(imms)) & 0xFFFFFFFF
            if got in got_sym:
                self.plt[stub] = got_sym[got]

        lo, hi = self.text
        starts = {v & ~1 for v in self.syms.values() if lo <= (v & ~1) < hi}
        for name in (".rel.dyn",):
            for r in sec[name].iter_relocations():
                if r["r_info_type"] == 23:   # R_ARM_RELATIVE
                    v = self.u32_raw(r["r_offset"])
                    if v is not None and lo <= (v & ~1) < hi and v & 1:
                        starts.add(v & ~1)
        self.fn_starts = starts

    def rodata_occurrences(self, key):
        """Every address where key\0 is stored (the linker tail-merges strings, e.g. "id" inside "...uid")."""
        if not hasattr(self, "_occ"):
            self._occ = {}
        if key not in self._occ:
            needle = key.encode() + b"\0"
            out, pos = [], 0
            while True:
                pos = self.raw.find(needle, pos)
                if pos < 0:
                    break
                for v, o, n in self.loads:
                    if o <= pos < o + n:
                        out.append(v + pos - o)
                pos += 1
            self._occ[key] = out
        return self._occ[key]

    def u32_raw(self, va):
        for v, o, n in self.loads:
            if v <= va < v + n:
                return struct.unpack_from("<I", self.raw, o + va - v)[0]
        return None

    def off(self, va):
        for v, o, n in self.loads:
            if v <= va < v + n:
                return o + va - v
        return None

    def read(self, va, n):
        o = self.off(va)
        return self.raw[o:o + n] if o is not None else b""

    def u32(self, va):
        b = self.read(va, 4)
        return struct.unpack("<I", b)[0] if len(b) == 4 else None


def load_strings(path):
    out = {}
    for line in open(path, encoding="utf-8", errors="replace"):
        m = re.match(r"(0x[0-9A-Fa-f]+)\s+\d+\s+\d+\s+(.*)$", line.rstrip("\n"))
        if m:
            out.setdefault(int(m.group(1), 16), m.group(2))
    return out


def callee_name(img, target):
    target &= ~1
    if target in img.plt:
        return img.plt[target]
    if not hasattr(img, "by_addr"):
        img.by_addr = {v & ~1: name for name, v in img.syms.items()}
        # stripped builds: IDA's names.txt (names imported via BinDiff); thunks carry a "j_" prefix
        names = getattr(img, "names_txt", None)
        if names and Path(names).exists():
            for line in open(names, encoding="utf-8", errors="replace"):
                m = re.match(r"0x([0-9A-Fa-f]+)\s+(\S+)", line)
                if m:
                    img.by_addr.setdefault(int(m.group(1), 16) & ~1, re.sub(r"^j_", "", m.group(2)))
    return img.by_addr.get(target)


def find_string_refs(img, wanted):
    """Linear Thumb sweep with tiny constant tracking (PIC bases: 'ldr r0,=off; add r0,pc' then
    'ldr r1,=off2; adds r1,r1,r0'): (address, string address) whenever a register becomes a wanted string."""
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    lo, hi = img.text
    code = img.read(lo, hi - lo)
    refs = []
    regs = {}
    push = None
    pos = 0
    while pos < len(code) - 2:
        got = False
        for addr, size, mnem, op in md.disasm_lite(code[pos:], lo + pos):
            got = True
            pos = addr + size - lo
            ops = [o.strip() for o in op.split(",")]
            d = ops[0] if ops else None
            val = None
            if mnem == "ldr" and "[pc, #" in op:
                imm = int(op.split("#")[1].rstrip("]"), 0)
                val = img.u32(((addr + 4) & ~3) + imm)
            elif mnem in ("add", "adds") and len(ops) == 2 and ops[1] == "pc":
                val = (regs[d] + addr + 4) & 0xFFFFFFFF if d in regs else None
            elif mnem in ("add", "adds") and len(ops) == 3 and ops[1] in regs and ops[2] in regs:
                val = (regs[ops[1]] + regs[ops[2]]) & 0xFFFFFFFF
            elif mnem in ("add", "adds") and len(ops) == 2 and ops[0] in regs and ops[1] in regs:
                val = (regs[ops[0]] + regs[ops[1]]) & 0xFFFFFFFF
            elif mnem in ("mov", "movs") and len(ops) == 2 and ops[1] in regs:
                val = regs[ops[1]]
            elif mnem == "push" and op.count(",") == 0:
                push = regs.get(op.strip("{} "))
                continue
            elif mnem == "pop" and op.count(",") == 0 and "pc" not in op:
                d = op.strip("{} ")
                val = push
            elif mnem in ("bl", "blx", "b", "bx") or mnem.startswith("b") and len(mnem) <= 3:
                if mnem in ("bl", "blx"):
                    for r in ("r0", "r1", "r2", "r3", "ip"):
                        regs.pop(r, None)
                continue
            elif mnem.startswith(("str", "cmp", "cmn", "tst")):
                continue
            if d is None:
                continue
            if val is None:
                regs.pop(d, None)
            else:
                regs[d] = val
                if val in wanted:
                    refs.append((addr, val))
        if not got:
            pos += 2
            regs.clear()
    return refs


def function_start(img, addr):
    """Entry of the function containing addr: the nearest exported function or code pointer at or below it
    (parse functions are referenced from std::function objects, so they are relocation targets)."""
    if not hasattr(img, "starts_sorted"):
        import bisect
        img._bisect = bisect
        img.starts_sorted = sorted(img.fn_starts)
    k = img._bisect.bisect_right(img.starts_sorted, addr & ~1) - 1
    return img.starts_sorted[k] if k >= 0 else None


def walk_function(img, start, limit=0x20000):
    """Instructions of the Thumb function at `start`, found by following branches (so literal pools are never
    decoded). Returns [(addr, size, mnem, op)] sorted by address. Thumb-1 far branches (bl into the same
    function) are followed; calls elsewhere are not."""
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    seen = {}
    work = [start]
    hi_bound = start + limit
    while work:
        pc = work.pop()
        while start <= pc < hi_bound and pc not in seen:
            b = img.read(pc, 4)
            ins = next(md.disasm_lite(b, pc, 1), None)
            if ins is None:
                break
            addr, size, mnem, op = ins
            seen[pc] = ins
            nxt = pc + size
            if mnem in ("b", "b.w") or (mnem.startswith("b") and len(mnem) == 3 and op.startswith("#")
                                          and mnem not in ("bic", "blx")):
                tgt = int(op[1:], 0)
                if mnem in ("b", "b.w"):
                    pc = tgt
                    continue
                work.append(tgt)
                pc = nxt
                continue
            if mnem in ("bl", "blx") and op.startswith("#"):
                tgt = int(op[1:], 0)
                if mnem == "bl" and start < tgt < hi_bound and tgt not in getattr(img, "fn_starts", ()):
                    # far branch inside this function (or a fragment): follow, no fall-through
                    pc = tgt
                    continue
                pc = nxt
                continue
            if mnem == "bx" or (mnem == "pop" and "pc" in op) or (mnem == "mov" and op.startswith("pc")):
                break
            pc = nxt
    return [seen[a] for a in sorted(seen)]


def sweep(img, start, strings):
    """Event stream of one parse function (linear sweep, mnemonic-level constant tracking)."""
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    regs, stack = {}, {}
    spoff = {}          # reg -> its value as an offset from sp (mov rX, sp / add rX, sp, #k)
    push = None
    events = []
    body = walk_function(img, start)
    inside = {a for a, _, _, _ in body}
    for addr, size, mnem, op in body:
        ops = [o.strip() for o in op.split(",")] if op else []
        d = ops[0] if ops else None
        val = None
        if mnem in ("bl", "blx") and op.startswith("#"):
            target = int(op[1:], 0)
            if mnem == "bl" and (target & ~1) in inside:
                continue   # Thumb-1 far branch within this function (error path), not a call
            name = callee_name(img, target) or ""
            r1, r2, r3 = regs.get("r1"), regs.get("r2"), regs.get("r3")
            if r1 in KEY_ADDRS or (r1 in strings and IDENT.match(strings[r1] or "")):
                events.append(("key", strings.get(r1)))
            elif name.startswith("_ZN10SafeBufferC") and r1 is not None:
                events.append(("ctor", r1))
            elif name.startswith("_ZN10SafeBuffer5write"):
                events.append(("write", r3, stack.get(0)))
            elif "Date4init" in name:
                events.append(("date",))
            elif name in ("strncpy", "strlcpy"):
                events.append(("strcpy", r2))
            for r in ("r0", "r1", "r2", "r3", "ip"):
                regs.pop(r, None)
            continue
        if mnem.startswith("b") and mnem not in ("bic", "bics"):
            continue
        if mnem == "ldr" and "[pc, #" in op:
            imm = int(op.split("#")[1].rstrip("]"), 0)
            val = img.u32(((addr + 4) & ~3) + imm)
        elif mnem == "ldr" and "[sp" in op:
            m = re.search(r"\[sp(?:, #(\w+))?\]", op)
            k = int(m.group(1), 0) if m and m.group(1) else 0
            val = stack.get(k)
        elif mnem == "mov" and len(ops) == 2 and ops[1] == "sp":
            spoff[d] = 0
            regs.pop(d, None)
            continue
        elif mnem in ("add", "adds") and len(ops) == 3 and ops[1] == "sp" and ops[2].startswith("#"):
            spoff[d] = int(ops[2][1:], 0)
            regs.pop(d, None)
            continue
        elif mnem == "str" and (mm := re.match(r"(\w+), \[(r\d+)(?:, #(\w+))?\]$", op)) and mm.group(2) in spoff:
            # store through a register holding sp+k (how the write() offset argument gets to [sp])
            base = spoff[mm.group(2)] + (int(mm.group(3), 0) if mm.group(3) else 0)
            if ops[0] in regs:
                stack[base] = regs[ops[0]]
            else:
                stack.pop(base, None)
            continue
        elif mnem.startswith("str") and "[sp" in op:
            m = re.search(r"\[sp(?:, #(\w+))?\]", op)
            k = int(m.group(1), 0) if m and m.group(1) else 0
            if mnem == "str" and ops[0] in regs:
                stack[k] = regs[ops[0]]
            else:
                stack.pop(k, None)
            continue
        elif mnem in ("mov", "movs") and len(ops) == 2:
            if ops[1].startswith("#"):
                val = int(ops[1][1:], 0)
            else:
                val = regs.get(ops[1])
        elif mnem in ("add", "adds", "sub", "subs", "lsl", "lsls"):
            if len(ops) == 2 and ops[1] == "pc":
                val = (regs[d] + addr + 4) & 0xFFFFFFFF if d in regs else None
            else:
                srcs = ops[1:] if len(ops) == 3 else ops
                vs = []
                for o in srcs:
                    if o.startswith("#"):
                        vs.append(int(o[1:], 0))
                    elif o in regs:
                        vs.append(regs[o])
                    else:
                        vs = None
                        break
                if vs and len(vs) == 2:
                    a, b = vs
                    if mnem.startswith("add"):
                        val = (a + b) & 0xFFFFFFFF
                    elif mnem.startswith("sub"):
                        val = (a - b) & 0xFFFFFFFF
                    else:
                        val = (a << b) & 0xFFFFFFFF
        elif mnem == "push" and "," not in op:
            push = regs.get(op.strip("{} "))
            continue
        elif mnem == "pop" and "," not in op and "pc" not in op:
            d = op.strip("{} ")
            val = push
        elif mnem.startswith(("str", "cmp", "cmn", "tst", "push", "pop")):
            continue
        if d is None or not re.match(r"r\d+$|ip$|lr$", d):
            continue
        spoff.pop(d, None)
        if val is None:
            regs.pop(d, None)
        else:
            regs[d] = val
    return events


def attribute(events):
    """Same rules as the decompile extractor, but without scalar dataflow: scalar writes not preceded by a
    key access take the oldest checked-but-unwritten key (checks and writes happen in the same order)."""
    size = None
    fields, queue, written = [], [], set()
    last = None
    date = False
    strlen = None
    started = False
    for ev in events:
        if ev[0] == "key":
            k = ev[1]
            if k is None:
                continue
            if k not in written and k not in queue:
                queue.append(k)
            last = k
        elif ev[0] == "ctor":
            if size is None:
                size = ev[1]
                started = True
                last = None
        elif ev[0] == "date":
            date = True
        elif ev[0] == "strcpy":
            strlen = ev[1]
        elif ev[0] == "write" and started:
            wsize, woff = ev[1], ev[2]
            if last is not None and (wsize != 4 or date or strlen):
                key = last
            elif last is not None and last in queue and queue and queue[0] == last:
                key = last
            elif last is not None and wsize == 4 and last not in written and queue and queue[0] != last \
                    and last == queue[-1] and len(queue) == 1:
                key = last
            else:
                key = queue[0] if queue else last
            if date and wsize == 8:
                kind = "date"
            elif strlen:
                kind = f"str[{wsize}]" if strlen >= (wsize or 0) else f"str[{wsize // strlen}x{strlen}]"
            elif wsize == 4:
                kind = "int"
            else:
                kind = f"int[{wsize // 4}]" if wsize else "?"
            fields.append({"key": key, "offset": woff, "size": wsize, "kind": kind})
            if key in queue:
                queue.remove(key)
            written.add(key)
            last = None
            date = False
            strlen = None
    return size, fields


def extract_build(ver, tables_keys):
    so, strtxt = BUILDS[ver]
    img = Image(so)
    img.names_txt = Path(strtxt).with_name("names.txt")
    strings = load_strings(strtxt)
    # string address of each key, per table
    wanted = {}
    rodata = img.rodata_occurrences
    for t, keys in tables_keys.items():
        for k in keys:
            for a in rodata(k):
                wanted.setdefault(a, set()).add(t)
                strings.setdefault(a, k)
    KEY_ADDRS.clear()
    KEY_ADDRS.update(wanted)
    print(f"[{ver}] sweeping .text for {len(wanted)} key strings...", flush=True)
    cache = ROOT / f"tools/.asm_refs_{ver}.json"
    if cache.exists() and "--nocache" not in sys.argv:
        refs = [tuple(x) for x in json.loads(cache.read_text())]
    else:
        refs = find_string_refs(img, set(wanted))
        cache.write_text(json.dumps(refs))
    # group references into functions; pick for each table the function with most of its keys
    by_func = {}
    for addr, sval in refs:
        fs = function_start(img, addr)
        if fs is not None:
            by_func.setdefault(fs, set()).add(strings[sval])
    # one-to-one table <-> function assignment, best (recall, precision) first
    pairs = []
    for t, keys in tables_keys.items():
        ks = set(keys)
        for fs, fkeys in by_func.items():
            hit = len(fkeys & ks)
            if hit < 2:
                continue
            recall, precision = hit / max(1, len(ks)), hit / max(1, len(fkeys))
            if recall >= 0.25 or (recall >= 0.15 and hit >= 8):
                pairs.append((recall + precision, recall, t, fs))
    pairs.sort(reverse=True)
    chosen, used = {}, set()
    for score, recall, t, fs in pairs:
        if t in chosen or fs in used:
            continue
        chosen[t] = (fs, recall)
        used.add(fs)
    out = {}
    for t, keys in tables_keys.items():
        if t not in chosen:
            continue
        fs, score = chosen[t]
        events = sweep(img, fs, strings)
        if DEBUG == t:
            for ev in events:
                print("   ", ev)
        size, fields = attribute(events)
        out[t] = {"func": hex(fs), "match": round(score, 2), "size": size, "fields": fields}
    return out


def main():
    ver = sys.argv[1] if len(sys.argv) > 1 else "1.0.1"
    ref = json.loads(LAYOUTS.read_text())["1.0.1"]
    tables_keys = {t: [f["key"] for f in info["fields"] if f["key"]] + info.get("unwritten", [])
                   for t, info in ref.items()}
    res = extract_build(ver, tables_keys)
    if ver == "1.0.1":
        good = 0
        for t, info in sorted(ref.items()):
            got = res.get(t)
            if not got:
                print(f"  {t:20} NOT FOUND")
                continue
            exp = [(f["offset"], f["size"], f["key"]) for f in info["fields"] if f["offset"] is not None]
            act = [(f["offset"], f["size"], f["key"]) for f in got["fields"]]
            ok = exp == act and info["size"] == got["size"]
            good += ok
            if not ok:
                diff = [(e, a) for e, a in zip(exp, act) if e != a][:3]
                print(f"  {t:20} MISMATCH size {info['size']}/{got['size']} n {len(exp)}/{len(act)} first diffs {diff}")
        print(f"[1.0.1] {good}/{len(ref)} tables identical to the decompile-derived layout")
    out = ROOT / f"tools/master_layouts_asm_{ver}.json"
    out.write_text(json.dumps(res, indent=1))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
