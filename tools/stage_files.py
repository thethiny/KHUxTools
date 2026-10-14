"""List the stage ids whose map (stage/mappoi_stg<id>.bin) is in a resource archive -> server/data/stage_files.json.

The server only offers events whose quests all have maps on the client (events.py): the 2016 event maps came in
event packs (evResource) that are not in the base archive, and opening such an event crashes the client.

    python tools/stage_files.py <misc.mp4>
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from khux.containers.bgad import KHUxBGADContainer  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "..", "server", "data", "stage_files.json")


def main():
    pat = re.compile(r"stage/mappoi_stg(\d+)\.bin$")
    c = KHUxBGADContainer(sys.argv[1])
    ids = sorted({int(m.group(1)) for e in c.iter_entries() if e.name and (m := pat.match(e.name))})
    c.close()
    json.dump({"_comment": open(OUT, encoding="utf-8").read() and json.load(open(OUT, encoding="utf-8"))["_comment"]
               if os.path.exists(OUT) else "", "stageIds": ids}, open(OUT, "w"), indent=0)
    print(len(ids), "stages with maps")


if __name__ == "__main__":
    main()
