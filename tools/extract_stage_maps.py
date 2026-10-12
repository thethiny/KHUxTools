"""Extract per-stage treasure chests and enemy symbols from the downloaded resources into
server/data/stage_maps.json (used by /stage/start to roll chest contents and enemy drops).

python tools/extract_stage_maps.py [misc.mp4]

Sources are the story map files stage/mappoi_stg%05d_%02d.bin (one per area; "MAP" magic).
Layout from StageManager::setNextMapInfo / createMapEnemyInfo / createMapTreasureInfo (1.0.1):
  header +32/+36/+40/+44/+48: transfer/enemy/treasure/material/npc section offsets (each + 52)
  treasure section: count, then 20-byte records {x, y, rewardId, ?, uniqueTreasureId}
      (MapTreasure::Info +12 = rewardId, +16 = uniqueTreasureId -> StageUtil::getTreasurePrizes)
  enemy section: teamCount, symbolCount, teamCount x 68-byte teams, symbolCount x 32-byte symbols
      {x, y, enemyId, ?, ?, level, rewardId, uniqueEnemyId} (-> StageUtil::getEnemyDropPrizes)
uniqueTreasureId / uniqueEnemyId are unique across the areas of a stage.
"""
import json
import os
import re
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from khux.containers.bgad import KHUxBGADContainer

ROOT = os.path.join(os.path.dirname(__file__), "..")
DEFAULT_MP4 = os.path.join(ROOT, "recomp/fs/data/data/com.square_enix.android_googleplay.khuxww/files/r/misc.mp4")
OUT = os.path.join(ROOT, "server/data/stage_maps.json")
AREA_RE = re.compile(r"^stage/mappoi_stg(\d{5})_(\d{2})\.bin$")


def _u32(b, o):
    return struct.unpack_from("<i", b, o)[0]


def parse_area(b: bytes) -> dict:
    enemy_off, treasure_off = _u32(b, 36) + 52, _u32(b, 40) + 52
    treasures = []
    for i in range(_u32(b, treasure_off)):
        x, y, reward_id, _, uid = struct.unpack_from("<5i", b, treasure_off + 4 + 20 * i)
        treasures.append({"uniqueTreasureId": uid, "rewardId": reward_id})
    teams, symbols = _u32(b, enemy_off), _u32(b, enemy_off + 4)
    base = enemy_off + 8 + 68 * teams
    enemies = []
    if base + 32 * symbols > len(b):        # a couple of unused maps (10340_03, 40101_00) don't fit the layout
        print(f"  skipping enemies: {teams} teams / {symbols} symbols overrun {len(b)} bytes")
        symbols = 0
    for i in range(symbols):
        s = struct.unpack_from("<8i", b, base + 32 * i)
        enemies.append({"uniqueEnemyId": s[7], "enemyId": s[2], "rewardId": s[6]})
    return {"treasures": treasures, "enemies": enemies}


def main():
    mp4 = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MP4
    stages = {}
    for e in KHUxBGADContainer(mp4).iter_entries_lazy():
        m = AREA_RE.match(e.name or "")
        if not m or len(e.data) < 52 or e.data[:4] != b"MAP\0":
            continue
        area = parse_area(e.data)
        st = stages.setdefault(int(m.group(1)), {"treasures": [], "enemies": []})
        st["treasures"] += area["treasures"]
        st["enemies"] += area["enemies"]
    out = {str(k): stages[k] for k in sorted(stages)}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"{len(out)} stages, {sum(len(s['treasures']) for s in out.values())} treasures, "
          f"{sum(len(s['enemies']) for s in out.values())} enemy symbols -> {OUT}")


if __name__ == "__main__":
    main()
