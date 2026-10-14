"""Regenerate the server's master-data JSONs from the 1.1.3 m files, using code-derived layouts.

Layouts come from tools/master_layout_asm.py (key -> offset/size/kind, read from each version's own
master::X::parse): the 1.1.3 layout decodes the m-file records by key, the 1.0.1 layout decides which keys,
types and array lengths the v1.0.1 client's parsers accept. Nothing is guessed from the data.

  python tools/regen_master.py                  # report only (what would change)
  python tools/regen_master.py --write          # write server/data/<table>.json (old files kept in server/data_prev/)

Tables that no longer exist in 1.1.3 (albumChallenge, avatarCombination, chapter, drawMedalList, drawSkillList,
drawSkillType) and tables whose 1.1.3 record differs completely (evStage) are left untouched and reported.
"""
import json
import shutil
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from khux.containers.bgad import KHUxBGADContainer  # noqa: E402
from khux.formats.master import decrypt_master_data_payload  # noqa: E402

M_DIR = Path("D:/Modding/KHUx/m")
DATA = ROOT / "server/data"
PREV = ROOT / "server/data_prev"
L101 = json.loads((ROOT / "tools/master_layouts_asm_1.0.1.json").read_text())
L113 = json.loads((ROOT / "tools/master_layouts_asm_1.1.3.json").read_text())
# keys the 1.0.1 parsers type-check as arrays (tools/master_array_keys.py): a 4-byte array is int[1], not int
ARRAY_KEYS = json.loads((ROOT / "tools/master_array_keys_1.0.1.json").read_text())
# keys parsed with Time::init ("HH:MM:SS"); the m files store them as 4 bytes h, m, s, flags
TIME_KEYS = json.loads((ROOT / "tools/master_time_keys_1.0.1.json").read_text())
for _t, _keys in TIME_KEYS.items():
    for _f in L101.get(_t, {}).get("fields", []):
        if _f["key"] in _keys and _f["kind"] == "int":
            _f["kind"] = "time"
for _t, _keys in ARRAY_KEYS.items():
    for _f in L101.get(_t, {}).get("fields", []):
        if _f["key"] in _keys and _f["kind"] == "int":
            _f["kind"] = "int[1]"

# 1.1.3 m files follow the 1.0.1 registration order minus the tables 1.1.3 dropped; m013 is a table that is new
# in 1.1.3 (m013) and m044-m048 are appended ones (none of them exist in 1.0.1).
ORDER_101 = [
    "albumChallenge", "avatarCombination", "avatarParts", "badstatus", "battleMisc", "buff", "burst", "chapter",
    "colosseum", "colosseumStage", "drawMedalList", "drawMedalType", "drawSkillList", "drawSkillType",
    "enemyAttack", "enemy", "evCampaign", "evGroupPattern", "evResource", "evStage", "guiltProb", "initItem",
    "keyblade", "loginBonus", "material", "medal", "medalMisc", "misc", "mypageBackground", "player",
    "raidEnemyAttack", "raidEnemy", "raidReward", "raidSetting", "ranking", "rankingReward", "reward",
    "serialcodeReward", "shop", "skillExp", "skill", "sphereArray", "sphere", "sphereMasu", "stage", "stamp",
    "title", "tutorialMisc", "world",
]
# 1.1.3 has no evGroupPattern: its ev* tables are evCampaign, evMedalList (m011), evResource, evScoreReward (m013),
# evStage (m014) - 1.1.3 strings.txt. So m011 is evMedalList, not evGroupPattern (it used to be written to
# evGroupPattern.json; the server serves evGroupPattern empty - the client never reads it).
DROPPED_113 = {"albumChallenge", "avatarCombination", "chapter", "drawMedalList", "drawSkillList", "drawSkillType",
               "evGroupPattern"}
NEW_113_AT = {11: "evMedalList (new in 1.1.3)", 13: "evScoreReward (new in 1.1.3, 252-byte records)"}


def m_file_map():
    names = [t for t in ORDER_101 if t not in DROPPED_113]
    out, k = {}, 0
    for idx in range(44):
        if idx in NEW_113_AT:
            continue
        out[names[k]] = M_DIR / f"m{idx:03d}.jpg"
        k += 1
    return out


def records(path):
    c = KHUxBGADContainer(str(path))
    out = []
    for ent in c.iter_entries_lazy():
        if not ent.name.isdigit() or len(ent.data) < 8:
            continue
        _, _, dec = decrypt_master_data_payload(ent.data)
        out.append((int(ent.name), dec))
    c.close()
    return [d for _, d in sorted(out)]


def cstr(b):
    b = b.split(b"\0", 1)[0]
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return None          # uninitialised garbage in an unused slot


def date(b):
    y, mo, d, h, mi, s, _f = struct.unpack("<HBBBBBB", b)
    if y == 0:
        return "2015-01-01 00:00:00"
    return f"{y:04d}-{mo:02d}-{d:02d} {h:02d}:{mi:02d}:{s:02d}"


def decode(rec, field):
    """Value of one 1.1.3 field as a python object (ints, strings, lists)."""
    off, size, kind = field["offset"], field["size"], field["kind"]
    raw = rec[off:off + size]
    if kind == "int":
        return struct.unpack("<i", raw)[0]
    if kind == "date":
        return date(raw)
    if kind.startswith("int["):
        return list(struct.unpack(f"<{size // 4}i", raw))
    if kind.startswith("str[") and "x" in kind:
        n, ln = (int(x) for x in kind[4:-1].split("x"))
        return [cstr(raw[k * ln:(k + 1) * ln]) for k in range(n)]
    if kind.startswith("str["):
        return cstr(raw)
    return list(raw)


def convert(table, rec):
    """One 1.1.3 record -> the 1.0.1 JSON object for `table`; returns (obj, missing_keys)."""
    src = {f["key"]: f for f in L113[table]["fields"]}
    obj, missing = {}, []
    for f in sorted(L101[table]["fields"], key=lambda f: f["offset"]):
        key, kind, size = f["key"], f["kind"], f["size"]
        if key not in src:
            missing.append(key)
            v = None
        else:
            v = decode(rec, src[key])
        if kind == "int":
            v = v if isinstance(v, int) else 0
        elif kind == "date":
            v = v if isinstance(v, str) else "2015-01-01 00:00:00"
        elif kind == "time":
            b = (v if isinstance(v, int) else 0).to_bytes(4, "little", signed=True)
            v = f"{b[0]:02d}:{b[1]:02d}:{b[2]:02d}"
        elif kind.startswith("int["):
            n = size // 4
            v = (list(v) if isinstance(v, list) else [])[:n]
            v += [0] * (n - len(v))
        elif kind.startswith("str[") and "x" in kind:
            n = int(kind[4:-1].split("x")[0])
            v = [s or "" for s in (v if isinstance(v, list) else [])][:n]
            v += [""] * (n - len(v))
        elif kind.startswith("str["):
            v = v if isinstance(v, str) else ""
        obj[key] = v
    return obj, missing


def main():
    write = "--write" in sys.argv
    mapping = m_file_map()
    report = []
    for table in ORDER_101:
        if table in DROPPED_113:
            report.append(f"{table:18} not in 1.1.3 - kept as is")
            continue
        path = mapping[table]
        recs = records(path)
        rsize = len(recs[0]) if recs else 0
        if table not in L113 and L101[table]["size"] == rsize:
            L113[table] = L101[table]     # 1.1.3 parse function not found, record unchanged: same layout
        if table not in L113 or L113[table]["size"] != rsize:
            report.append(f"{table:18} {path.name}: record {rsize} B != 1.1.3 layout "
                          f"{L113.get(table, {}).get('size')} - kept as is")
            continue
        out, missing = [], set()
        for rec in recs:
            obj, miss = convert(table, rec)
            out.append(obj)
            missing.update(miss)
        old_p = DATA / f"{table}.json"
        old = json.loads(old_p.read_text(encoding="utf-8")) if old_p.exists() else None
        changed = old != out
        report.append(f"{table:18} {path.name}: {len(out)} rows  {'CHANGED' if changed else 'same'}"
                      + (f"  (no 1.1.3 value for: {sorted(missing)})" if missing else "")
                      + (f"  old rows {len(old)}" if old is not None and len(old) != len(out) else ""))
        if write and changed:
            PREV.mkdir(exist_ok=True)
            if old_p.exists() and not (PREV / old_p.name).exists():
                shutil.copy2(old_p, PREV / old_p.name)
            old_p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n".join(report))


if __name__ == "__main__":
    main()
