"""
Generic master data parser for KHUx m*.jpg files.

Each m*.jpg is a BGAD container with numbered entries. Each entry uses
MSVC LCG encryption (seed + payload_size + encrypted_payload). The
decrypted payload is a fixed-size struct whose layout differs per table.

Usage:
    from khux.formats.master import MasterDataParser
    parser = MasterDataParser()
    records = parser.parse_file("D:/Modding/KHUx/m/m002.jpg", "avatarParts")
    # Or auto-detect table name from filename index:
    records = parser.parse_file("D:/Modding/KHUx/m/m002.jpg")
"""

import struct
import os
from typing import List, Dict, Any, Optional

from .avatar import decrypt_master_data_payload


# m*.jpg index → table name (matches server's MASTER_TABLE_NAMES)
TABLE_NAMES = [
    "albumChallenge", "avatarCombination", "avatarParts", "badstatus",
    "battleMisc", "buff", "burst", "chapter", "colosseum", "colosseumStage",
    "drawMedalList", "drawMedalType", "drawSkillList", "drawSkillType",
    "enemyAttack", "enemy", "evCampaign", "evGroupPattern", "evResource",
    "evStage", "guiltProb", "initItem", "keyblade", "loginBonus",
    "material", "medal", "medalMisc", "misc", "mypageBackground", "player",
    "raidEnemyAttack", "raidEnemy", "raidReward", "raidSetting", "ranking",
    "rankingReward", "reward", "serialcodeReward", "shop", "skillExp",
    "skill", "sphereArray", "sphere", "sphereMasu", "stage", "stamp",
    "title", "tutorialMisc", "world",
]


# ── Field type handlers ───────────────────────────────────────────────────────

def _read_int(data: bytes, offset: int) -> (Any, int):
    return struct.unpack_from("<i", data, offset)[0], offset + 4


def _read_uint(data: bytes, offset: int) -> (Any, int):
    return struct.unpack_from("<I", data, offset)[0], offset + 4


def _read_string(data: bytes, offset: int, size: int) -> (Any, int):
    raw = data[offset:offset + size]
    null = raw.find(b'\x00')
    if null >= 0:
        raw = raw[:null]
    try:
        s = raw.decode('utf-8')
    except UnicodeDecodeError:
        s = raw.decode('shift-jis', errors='replace')
    padded = size
    remainder = padded % 4
    if remainder:
        padded += 4 - remainder
    return s, offset + padded


def _read_int_array(data: bytes, offset: int, count: int) -> (list, int):
    arr = []
    for _ in range(count):
        val = struct.unpack_from("<i", data, offset)[0]
        arr.append(val)
        offset += 4
    return arr, offset


# ── Schema definitions ────────────────────────────────────────────────────────
#
# Each schema is a list of (field_name, field_type, *args):
#   ("name", "int")              → 4-byte signed int
#   ("name", "uint")             → 4-byte unsigned int
#   ("name", "str", 129)         → null-terminated string, 129-byte buffer (padded to 4-byte align)
#   ("name", "int[]", 5)         → fixed-size int array of 5 elements
#   ("name", "int[v]", "count")  → variable-size int array, length from field "count"

SCHEMAS: Dict[str, list] = {
    "avatarParts": [
        ("avatarPartsId", "int"),
        ("name", "str", 129),
        ("partsType", "int"),
        ("gender", "int"),
        ("combinationType", "int"),
        ("combinationFlag", "int"),
        ("position", "int"),
        ("luxCategory", "int"),
        ("luxAddRate", "int"),
        ("setKind", "int"),
        ("fixedFlag", "int"),
        ("validSetCloth", "int"),
        ("setCloth", "int[]", 5),
        ("status", "int"),
    ],
    "initItem": [
        ("id", "int"),
        ("category", "int"),
        ("equipType", "int"),
        ("equipNo", "int"),
        ("param", "int"),
        ("itemId", "int"),
        ("skillId", "int"),
    ],
    "misc": [
        ("miscId", "int"),
        ("value", "int"),
    ],
    "battleMisc": [
        ("battleMiscId", "int"),
        ("value", "int"),
    ],
    "world": [
        ("worldId", "int"),
        ("worldName", "str", 129),
        ("raidBackground", "str", 129),
        ("instanceLwf", "str", 129),
        ("instance", "str", 129),
        ("xPos", "int"),
        ("yPos", "int"),
        ("rate", "int"),
        ("validParts", "int"),
        ("partsId", "int[]", 10),
        ("xPostion", "int[]", 10),
        ("yPostion", "int[]", 10),
    ],
    "chapter": [
        ("chapterId", "int"),
        ("worldId", "int"),
        ("name", "str", 129),
    ],
}

# Remap JSON field names to match the server's expected names
# (the binary struct uses camelCase matching the server parser)
_FIELD_RENAMES = {
    "avatarParts": {
        "luxCategory": None,  # not in server JSON, drop
        "luxAddRate": None,
    },
}


def _parse_entry(data: bytes, schema: list) -> Optional[Dict[str, Any]]:
    """Parse a decrypted entry using a schema definition."""
    result = {}
    offset = 0
    for field_def in schema:
        name = field_def[0]
        ftype = field_def[1]

        if offset >= len(data):
            break

        if ftype == "int":
            val, offset = _read_int(data, offset)
        elif ftype == "uint":
            val, offset = _read_uint(data, offset)
        elif ftype == "str":
            size = field_def[2]
            val, offset = _read_string(data, offset, size)
        elif ftype == "int[]":
            count = field_def[2]
            val, offset = _read_int_array(data, offset, count)
        elif ftype == "int[v]":
            count_field = field_def[2]
            count = result.get(count_field, 0)
            val, offset = _read_int_array(data, offset, max(0, count))
        else:
            break

        result[name] = val

    if "validSetCloth" in result and "setCloth" in result:
        n = max(0, min(result["validSetCloth"], len(result["setCloth"])))
        result["setCloth"] = result["setCloth"][:n]

    return result


def _raw_dump(data: bytes) -> Dict[str, Any]:
    """Fallback: dump decrypted bytes as hex + detected ints."""
    result = {"_raw_hex": data.hex(), "_size": len(data)}
    if len(data) >= 4:
        result["_first_int"] = struct.unpack_from("<i", data, 0)[0]
    return result


# Map decrypted struct size → table name (for auto-detection of local files)
_STRUCT_SIZE_TO_TABLE = {
    200: "avatarParts",
    28: "initItem",
    8: "misc",  # also battleMisc — disambiguate by entry count
    948: "world",
}


class MasterDataParser:
    """Generic parser for KHUx master data m*.jpg files."""

    def __init__(self, extra_schemas: Optional[Dict[str, list]] = None):
        self.schemas = dict(SCHEMAS)
        if extra_schemas:
            self.schemas.update(extra_schemas)

    def table_name_from_filename(self, filename: str) -> Optional[str]:
        """Resolve table name from m*.jpg filename using the server index mapping."""
        import re
        base = os.path.basename(filename)
        match = re.match(r'm(\d+)\.jpg', base)
        if match:
            idx = int(match.group(1))
            if idx < len(TABLE_NAMES):
                return TABLE_NAMES[idx]
        return None

    def detect_table(self, path: str) -> Optional[str]:
        """Auto-detect table name by probing entry struct size.

        Local m*.jpg files may not follow the server index order.
        This checks the first entry's decrypted size against known schemas.
        """
        from ..containers.bgad import KHUxBGADContainer
        container = KHUxBGADContainer(path)
        result = None
        for entry in container.iter_entries():
            if entry.name.isdigit() and len(entry.data) >= 8:
                _, _, dec = decrypt_master_data_payload(entry.data)
                size = len(dec)
                result = _STRUCT_SIZE_TO_TABLE.get(size)
                break
        container.close()
        return result

    def parse_entry_bytes(self, data: bytes, table_name: str) -> Dict[str, Any]:
        """Decrypt and parse a single raw entry."""
        _, _, decrypted = decrypt_master_data_payload(data)
        schema = self.schemas.get(table_name)
        if schema:
            result = _parse_entry(decrypted, schema)
            if result is not None:
                return result
        return _raw_dump(decrypted)

    def parse_file(self, path: str, table_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """Parse all entries from an m*.jpg BGAD container.

        Args:
            path: Path to the m*.jpg file.
            table_name: Override table name. Auto-detected from filename if None.

        Returns:
            List of parsed records as dicts.
        """
        from ..containers.bgad import KHUxBGADContainer

        if table_name is None:
            table_name = self.detect_table(path)

        container = KHUxBGADContainer(path)
        records = []
        has_schema = table_name and table_name in self.schemas

        for entry in container.iter_entries():
            if not entry.name.isdigit():
                continue
            if len(entry.data) < 8:
                continue
            try:
                _, _, decrypted = decrypt_master_data_payload(entry.data)
                if has_schema:
                    rec = _parse_entry(decrypted, self.schemas[table_name])
                    if rec is not None:
                        records.append(rec)
                        continue
                records.append(_raw_dump(decrypted))
            except (struct.error, ValueError):
                pass

        container.close()
        return records

    def parse_file_to_json(self, path: str, table_name: Optional[str] = None) -> str:
        """Parse and return as JSON string."""
        import json
        records = self.parse_file(path, table_name)
        return json.dumps(records, ensure_ascii=False, indent=2)

    def list_schemas(self) -> List[str]:
        """Return names of tables with known schemas."""
        return sorted(self.schemas.keys())
