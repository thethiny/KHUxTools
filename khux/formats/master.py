"""
Generic master data parser for KHUx m*.jpg files.

Each m*.jpg is a BGAD container with numbered entries. Each entry uses
MSVC LCG encryption (seed + payload_size + encrypted_payload). The
decrypted payload is a fixed-size struct whose layout differs per table.

Usage:
    from khux.formats.master import MasterDataParser
    parser = MasterDataParser()
    records = parser.parse_file("D:/Modding/KHUx/m/m002.jpg", "avatarParts")
    # Or auto-detect table name:
    records = parser.parse_file("D:/Modding/KHUx/m/m002.jpg")
"""

import struct
import os
from typing import List, Dict, Any, Optional

from .avatar import decrypt_master_data_payload


# v1.0.1 table index → table name (from dword_1004100 registration order)
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
    return s, offset + size


def _read_int_array(data: bytes, offset: int, count: int) -> (list, int):
    arr = list(struct.unpack_from(f"<{count}i", data, offset))
    return arr, offset + count * 4


def _read_date(data: bytes, offset: int) -> (Any, int):
    # u16 year, u8 month/day/hour/minute/second, u8 flags -> "YYYY-MM-DD HH:MM:SS" (the game's Date::init format)
    year, month, day, hour, minute, second, _flags = struct.unpack_from("<HBBBBBB", data, offset)
    return f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}", offset + 8


def _read_time(data: bytes, offset: int) -> (Any, int):
    val = struct.unpack_from("<I", data, offset)[0]
    h = (val >> 16) & 0xFF
    m = (val >> 8) & 0xFF
    s = val & 0xFF
    return f"{h:02d}:{m:02d}:{s:02d}", offset + 4


# ── Schema definitions ────────────────────────────────────────────────────────
#
# Each schema is a list of (field_name, field_type, *args):
#   ("name", "int")              → 4-byte signed int
#   ("name", "uint")             → 4-byte unsigned int
#   ("name", "str", 129)         → null-terminated string, 129-byte buffer
#   ("name", "str[]", 3, 129)    → array of 3 strings, each 129-byte buffer
#   ("name", "int[]", 5)         → fixed-size int array of 5 elements
#   ("name", "date")             → 8-byte Date struct
#   ("name", "time")             → 4-byte Time struct
#
# Schemas for v1.1.3 m file binary layouts. The m files are from v1.1.3 but
# the server targets v1.0.1 — extra v1.1.3 fields are included so the parser
# reads at correct offsets, and the v1.0.1 client ignores fields it doesn't know.
#
# Tables marked [v1.0.1=v1.1.3] have identical layouts across versions.
# Tables marked [v1.1.3 layout] have fields added/changed from v1.0.1.

SCHEMAS: Dict[str, list] = {
    # ── Existing tables (v1.1.3 layouts, hand-verified) ──────────────────────

    "avatarParts": [  # v1.1.3: 200 bytes (v1.0.1: 192, +luxCategory/luxAddRate)
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
    "initItem": [  # v1.0.1=v1.1.3: 28 bytes
        ("id", "int"),
        ("category", "int"),
        ("equipType", "int"),
        ("equipNo", "int"),
        ("param", "int"),
        ("itemId", "int"),
        ("skillId", "int"),
    ],
    "misc": [  # v1.0.1=v1.1.3: 8 bytes
        ("miscId", "int"),
        ("value", "int"),
    ],
    "battleMisc": [  # v1.0.1=v1.1.3: 8 bytes
        ("battleMiscId", "int"),
        ("value", "int"),
    ],
    "world": [  # v1.0.1=v1.1.3: 948 bytes
        ("worldId", "int"),
        ("worldName", "str", 129),
        ("raidBackground", "str", 129),
        ("instanceLwf", "str", 129),
        ("instance", "str", 129),
        ("xPos", "int"),
        ("yPos", "int"),
        ("rate", "int"),
        ("validParts", "int"),
        ("partsId", "str[]", 3, 129),   # strings: master::World::parse rejects non-string elements
        ("xPostion", "int[]", 3),
        ("yPostion", "int[]", 3),
    ],
    "chapter": [  # v1.0.1 only (not in 1.1.3 m files)
        ("chapterId", "int"),
        ("worldId", "int"),
        ("name", "str", 129),
    ],
    "stage": [  # v1.1.3: 2080 bytes (v1.0.1: 1020). Use m044 for v1.0.1 layout.
        ("stageId", "int"),
        ("id", "int"),
        ("name", "str", 129),
        ("mapName", "str", 129),
        ("useAp", "int"),
        ("chapterId", "int"),
        ("worldId", "int"),
        ("thumbId", "int"),
        ("stageKind", "int"),
        ("showIcon", "int"),
        ("validBeforeDrama", "int"),
        ("beforeDramaId", "int[]", 5),
        ("beforeDramaType", "int[]", 5),
        ("validAfterDrama", "int"),
        ("afterDramaId", "int[]", 5),
        ("afterDramaType", "int[]", 5),
        ("validClearGetTitle", "int"),
        ("clearGetTitle", "int"),
        ("validClearGetSphere", "int"),
        ("clearGetSphere", "int"),
        ("resetClearGet", "int"),
        ("validClearGetItem", "int"),
        ("clearGetItemType", "int[]", 3),
        ("clearGetItemId", "int[]", 3),
        ("clearGetAssignSkillType", "int[]", 3),
        ("clearGetAssignSkillId", "int[]", 3),
        ("clearGetAssignSkillLv", "int[]", 3),
        ("clearGetItemNum", "int[]", 3),
        ("resetSubMission", "int"),
        ("validSubmission", "int"),
        ("submissionRequire", "int[]", 3),
        ("submissionName", "str[]", 3, 129),
        ("submissionDataType", "int[]", 3),
        ("submissionIdType", "int[]", 3),
        ("submissionId", "int[]", 3),
        ("submissionNum", "int[]", 3),
        ("submissionRewardType", "int[]", 3),
        ("submissionItemId", "int[]", 3),
        ("submissionSkillType", "int[]", 3),
        ("submissionSkillId", "int[]", 3),
        ("submissionSkillLv", "int[]", 3),
        ("submissionItemNum", "int[]", 3),
        ("raidBoss", "int"),
        ("bgmField", "int"),
        ("bgmBattle", "int"),
        ("bgmBoss", "int"),
    ],
    "enemy": [  # v1.1.3: 1100 bytes (v1.0.1: 992, larger arrays)
        ("enemyId", "int"),
        ("name", "str", 65),
        ("flavor", "str", 513),
        ("displayId", "int"),
        ("show", "int"),
        ("showSwf", "int"),
        ("showFrame", "int"),
        ("hideFrame", "int"),
        ("moveSpeed", "int"),
        ("hitRadius", "int"),
        ("tapRadius", "int"),
        ("width", "int"),
        ("height", "int"),
        ("spBattle", "int"),
        ("kind", "int"),
        ("attribute", "int"),
        ("validGrowth", "int"),
        ("baseLv", "int[]", 6),
        ("hp", "int[]", 5),
        ("attack", "int[]", 5),
        ("defense", "int[]", 5),
        ("exp", "int[]", 5),
        ("money", "int[]", 5),
        ("raidPoint", "int[]", 5),
        ("lux", "int[]", 5),
        ("attackCp", "int"),
        ("suppressCp", "int"),
        ("attackHp", "int"),
        ("suppressHp", "int"),
        ("suppressGuilt", "int"),
        ("battlePattern", "int"),
        ("displayHeight", "int"),
        ("runaway", "int"),
        ("neverAttack", "int"),
        ("validSkill", "int"),
        ("skillId", "int[]", 5),
        ("skillRequire", "int[]", 5),
        ("skillRequireArg", "int[]", 5),
        ("skillOdds", "int[]", 5),
        ("protectPoison", "int"),
        ("protectDeepPoison", "int"),
        ("protectSleep", "int"),
        ("protectParalysis", "int"),
        ("registPoison", "int"),
        ("registDeepPoison", "int"),
        ("registSleep", "int"),
        ("registParalysis", "int"),
        ("bufAttack", "int"),
        ("bufDefense", "int"),
        ("bufAttackPower", "int"),
        ("bufDefensePower", "int"),
        ("bufAttackSpeed", "int"),
        ("bufDefenseSpeed", "int"),
        ("bufAttackMagic", "int"),
        ("bufDefenseMagic", "int"),
        ("bufTurn", "int"),
        ("bufCount", "int"),
        ("statusAilments", "int[]", 5),
        ("statusAilmentsTurn", "int"),
        ("statusAilmentsCount", "int"),
    ],
    "enemyAttack": [  # v1.1.3: 236 bytes (v1.0.1: 228)
        ("enemyAttackId", "int"),
        ("name", "str", 65),
        ("attackMotion", "int"),
        ("hitEffect", "int"),
        ("effectDirectionFix", "int"),
        ("display", "int"),
        ("choiseAttribute", "int"),
        ("hitCount", "int"),
        ("power", "int"),
        ("critical", "int"),
        ("criticalPower", "int"),
        ("target", "int"),
        ("effect", "int"),
        ("addTarget", "int"),
        ("addTurn", "int"),
        ("addCount", "int"),
        ("bufAttack", "int"),
        ("bufDefense", "int"),
        ("bufAttackPower", "int"),
        ("bufDefensePower", "int"),
        ("bufAttackSpeed", "int"),
        ("bufDefenseSpeed", "int"),
        ("bufAttackMagic", "int"),
        ("bufDefenseMagic", "int"),
        ("resetAttack", "int"),
        ("resetDefense", "int"),
        ("resetAttackPower", "int"),
        ("resetDefensePower", "int"),
        ("resetAttackSpeed", "int"),
        ("resetDefenseSpeed", "int"),
        ("resetAttackMagic", "int"),
        ("resetDefenseMagic", "int"),
        ("heal", "int"),
        ("healShake", "int"),
        ("poison", "int"),
        ("deepPoison", "int"),
        ("sleep", "int"),
        ("paralysis", "int"),
        ("curePoison", "int"),
        ("cureSleep", "int"),
        ("cureParalysis", "int"),
    ],
    "reward": [  # v1.0.1=v1.1.3: 136 bytes
        ("rewardId", "int"),
        ("validReward", "int"),
        ("display", "int[]", 4),
        ("type", "int[]", 4),
        ("id", "int[]", 4),
        ("assignSkillType", "int[]", 4),
        ("assignSkillId", "int[]", 4),
        ("assignSkillLv", "int[]", 4),
        ("num", "int[]", 4),
        ("odds", "int[]", 4),
    ],
    "skill": [  # v1.1.3: 316 bytes (v1.0.1: 312, +1 extra int)
        ("skillId", "int"),
        ("imageId", "int"),
        ("thumbId", "int"),
        ("name", "str", 65),
        ("description", "str", 129),
        ("rank", "int"),
        ("maxLv", "int"),
        ("expType", "int"),
        ("sortId", "int"),
        ("categoryEvolve", "int"),
        ("invokeType", "int"),
        ("invokeProb", "int"),
        ("invokeProbPerLv", "int"),
        ("invokeShowTiming", "int"),
        ("attackUp", "int"),
        ("burstCancel", "int"),
        ("damageCut", "int"),
        ("dokonjo", "int"),
        ("counter", "int"),
        ("addAction", "int"),
        ("addPoison", "int"),
        ("addDeepPoison", "int"),
        ("addSleep", "int"),
        ("addParalysis", "int"),
        ("conditionTurn", "int"),
        ("conditionCount", "int"),
        ("prizeHpUp", "int"),
        ("prizeBurstUp", "int"),
        ("luxUp", "int"),
        ("moneyUp", "int"),
        ("raidUp", "int"),
    ],
    "keyblade": [  # v1.1.3: 380 bytes (v1.0.1: 356, larger arrays)
        ("keybladeId", "int"),
        ("name", "str", 65),
        ("description", "str", 129),
        ("lv", "int"),
        ("displayId", "int"),
        ("category", "int"),
        ("passive", "int"),
        ("passivePower", "int"),
        ("drawCount", "int"),
        ("maxBurstGauge", "int"),
        ("validConsist", "int"),
        ("attribute", "int[]", 5),
        ("darklight", "int[]", 5),
        ("accord", "int[]", 5),
        ("dlaccord", "int[]", 5),
        ("partnerRate", "int"),
        ("evolveId", "int"),
        ("validNeedMaterial", "int"),
        ("needMaterialId", "int[]", 5),
        ("needMaterialNum", "int[]", 5),
    ],
    "medal": [  # v1.1.3: 1300 bytes (v1.0.1: 1276, +_pad0/_pad1, larger arrays)
        ("medalId", "int"),
        ("imageId", "int"),
        ("thumbId", "int"),
        ("sortId", "int"),
        ("_pad0", "int"),
        ("_pad1", "int"),
        ("name", "str", 65),
        ("flavor", "str", 513),
        ("advantage", "str", 513),
        ("type", "int"),
        ("attribute", "int"),
        ("darklight", "int"),
        ("validSource", "int"),
        ("source", "int[]", 5),
        ("rare", "int"),
        ("skillSlot", "int"),
        ("guiltValue", "int"),
        ("maxLv", "int"),
        ("expType", "int"),
        ("cost", "int"),
        ("minCost", "int"),
        ("growthType", "int"),
        ("attack", "int"),
        ("maxAttack", "int"),
        ("addMaxAttack", "int"),
        ("defense", "int"),
        ("maxDefense", "int"),
        ("addMaxDefense", "int"),
        ("validBurst", "int"),
        ("burstId", "int"),
        ("burstEnhanceCategory", "int[]", 5),
        ("groupId", "int"),
        ("sellSpherePoint", "int"),
        ("materialExp", "int"),
        ("sell", "int"),
        ("sellPerLv", "int"),
        ("enhanceAttack", "int"),
        ("enhanceDefense", "int"),
        ("enhanceCost", "int"),
        ("validEvolve", "int"),
        ("evolveId", "int"),
        ("evolveMoney", "int"),
        ("validEvolveNeed", "int"),
        ("evolveNeedId", "int[]", 4),
    ],

    # ── New tables [v1.0.1=v1.1.3] ──────────────────────────────────────────

    "badstatus": [  # 92 bytes
        ("badstatusId", "int"), ("name", "str", 65),
        ("iconId", "int"), ("effect", "int"),
        ("target", "int"), ("power", "int[]", 2),
    ],
    "buff": [  # 88 bytes
        ("buffId", "int"), ("grade", "int"), ("name", "str", 65),
        ("iconId", "int"), ("effect", "int"), ("addPower", "int"),
    ],
    "colosseum": [  # 220 bytes
        ("colosseumId", "int"), ("colosseumStageId", "int"),
        ("round", "int"), ("ap", "int"),
        ("arrivalStageCount", "int"), ("rankId", "str", 65),
        ("excellentUnlockCount", "int"), ("validStageReward", "int"),
        ("stageRewardType", "int"), ("stageRewardId", "int"),
        ("stageRewardAssignType", "int"), ("stageRewardSkillId", "int"),
        ("stageRewardSkillLv", "int"), ("stageRewardNum", "int"),
        ("validReward", "int"),
        ("rewardType", "int[]", 4), ("rewardId", "int[]", 4),
        ("rewardAssignType", "int[]", 4), ("rewardSkillId", "int[]", 4),
        ("rewardSkillLv", "int[]", 4), ("rewardNum", "int[]", 4),
    ],
    "colosseumStage": [  # 92 bytes
        ("colosseumStageId", "int"),
        ("openDate", "date"), ("closeDate", "date"), ("rankingCloseDate", "date"),
        ("headColosseumId", "int"), ("termColosseumId", "int"),
        ("rankingId", "int"), ("validStage", "int"),
        ("stageId", "int[]", 10),
        ("loopStageCount", "int"), ("lvPerLoop", "int"),
    ],
    "evCampaign": [  # 352 bytes
        ("campaignId", "int"), ("type", "int"), ("power", "int"),
        ("displayText", "str", 257),
        ("stageType", "int"), ("validStageId", "int"),
        ("stageId", "int[]", 5),
        ("startTime", "date"), ("endTime", "date"),
        ("weekMonday", "int"), ("weekTuesday", "int"), ("weekWednesday", "int"),
        ("weekThursday", "int"), ("weekFriday", "int"),
        ("weekSaturday", "int"), ("weekSunday", "int"),
        ("groupPattern", "int"), ("validMinute", "int"),
    ],
    "evGroupPattern": [  # 24 bytes
        ("patternId", "int"), ("groupDivide", "int"),
        ("startTime", "time"), ("endTime", "time"),
        ("shiftTime", "time"), ("rotate", "int"),
    ],
    "evResource": [  # 20 bytes
        ("resourceId", "int"), ("priority", "int"),
        ("validResource", "int"), ("endTime", "date"),
    ],
    "guiltProb": [  # 20 bytes
        ("id", "int"), ("value", "int"), ("factor", "int"),
        ("weight", "int"), ("isCampaign", "int"),
    ],
    "loginBonus": [  # 2360 bytes
        ("loginBonusId", "int"), ("bonusType", "int"),
        ("title", "str", 257), ("description", "str", 1025), ("comment", "str", 1025),
        ("day", "int"),
        ("startDate", "date"), ("endDate", "date"),
        ("rewardType", "int"), ("rewardId", "int"),
        ("rewardAssignSkillType", "int"), ("rewardAssignSkillId", "int"),
        ("rewardAssignSkillLv", "int"), ("rewardNum", "int"),
    ],
    "material": [  # 212 bytes
        ("materialId", "int"), ("category", "int"), ("sortId", "int"),
        ("name", "str", 65), ("description", "str", 129), ("sell", "int"),
    ],
    "medalMisc": [  # 16 bytes
        ("medalMiscId", "int"), ("value", "int[]", 3),
    ],
    "mypageBackground": [  # 160 bytes
        ("id", "int"), ("backgroundId", "int"), ("sortId", "int"),
        ("validChild", "int"),
        ("startTime", "date"), ("endTime", "date"),
        ("viewType", "int"), ("validParts", "int"),
        ("partsId", "int[]", 6), ("dataType", "int[]", 6),
        ("xPostion", "int[]", 6), ("yPostion", "int[]", 6),
        ("zSort", "int[]", 6),
    ],
    "player": [  # 28 bytes
        ("lv", "int"), ("needExp", "int"), ("luxMedal", "int"),
        ("ap", "int"), ("cost", "int"), ("hp", "int"), ("rewardId", "int"),
    ],
    "raidEnemyAttack": [  # 216 bytes
        ("raidEnemyAttackId", "int"), ("name", "str", 65),
        ("display", "int"), ("choiseAttribute", "int"),
        ("hitCount", "int"), ("power", "int"),
        ("critical", "int"), ("criticalPower", "int"),
        ("target", "int"), ("effect", "int"),
        ("addTarget", "int"), ("addTurn", "int"), ("addCount", "int"),
        ("bufAttack", "int"), ("bufDefense", "int"),
        ("bufAttackPower", "int"), ("bufDefensePower", "int"),
        ("bufAttackSpeed", "int"), ("bufDefenseSpeed", "int"),
        ("bufAttackMagic", "int"), ("bufDefenseMagic", "int"),
        ("resetAttack", "int"), ("resetDefense", "int"),
        ("resetAttackPower", "int"), ("resetDefensePower", "int"),
        ("resetAttackSpeed", "int"), ("resetDefenseSpeed", "int"),
        ("resetAttackMagic", "int"), ("resetDefenseMagic", "int"),
        ("heal", "int"), ("healShake", "int"),
        ("poison", "int"), ("deepPoison", "int"),
        ("sleep", "int"), ("paralysis", "int"),
        ("curePoison", "int"), ("cureSleep", "int"), ("cureParalysis", "int"),
    ],
    "raidReward": [  # 128 bytes
        ("raidRewardId", "int"), ("oddsUpPerLv", "int"),
        ("pointUpPerLv", "int"), ("validReward", "int"),
        ("type", "int[]", 4), ("id", "int[]", 4),
        ("assignSkillType", "int[]", 4), ("assignSkillId", "int[]", 4),
        ("assignSkillLv", "int[]", 4), ("num", "int[]", 4), ("odds", "int[]", 4),
    ],
    "raidSetting": [  # 68 bytes
        ("raidSettingId", "int"), ("bossId", "int"),
        ("bossUpTime", "int"), ("useAp", "int"),
        ("rareBossId", "int"), ("rareBossUpTime", "int"),
        ("rareUseAp", "int"), ("rareUpType", "int"),
        ("rareUpTypeArg", "int"), ("rareUpTriggerBossId", "int"),
        ("validUnlockRare", "int"),
        ("unlockRareBossId", "int[]", 3), ("unlockRareNum", "int[]", 3),
    ],
    "ranking": [  # 76 bytes
        ("rankingId", "int"), ("category", "int"),
        ("startDatetime", "date"), ("endDatetime", "date"),
        ("startRank", "int"), ("endRank", "int"),
        ("unionStartRank", "int[]", 5), ("unionEndRank", "int[]", 5),
        ("validReward", "int"),
    ],
    "rankingReward": [  # 256 bytes
        ("rankingRewardId", "int"), ("startRank", "int"),
        ("endRank", "int"), ("validReward", "int"),
        ("type", "int[]", 10), ("id", "int[]", 10),
        ("skillType", "int[]", 10), ("skillId", "int[]", 10),
        ("skillLv", "int[]", 10), ("num", "int[]", 10),
    ],
    "serialcodeReward": [  # 432 bytes
        ("serialcodeRewardId", "int"), ("name", "str", 257),
        ("startDate", "date"), ("endDate", "date"),
        ("itemId", "int"), ("validReward", "int"),
        ("type", "int[]", 6), ("id", "int[]", 6),
        ("skillType", "int[]", 6), ("skillId", "int[]", 6),
        ("skillLv", "int[]", 6), ("num", "int[]", 6),
    ],
    "shop": [  # 708 bytes
        ("shopId", "int"), ("productId", "str", 129),
        ("sortId", "int"), ("type", "int"), ("os", "int"),
        ("price", "int"), ("number", "int"), ("bonus", "int"),
        ("explanation", "str", 129),
        ("stageSkipTicket", "int"), ("appleStatus", "int"),
        ("benefitId", "int"), ("benefitBonusValue", "int"),
        ("benefitResetWeek", "str", 129),
        ("benefitResetTime", "time"),
        ("benefitExplanation", "str", 129),
        ("useBenefitExplanation", "str", 129),
        ("thumbId", "int"), ("status", "int"),
    ],
    "skillExp": [  # 16 bytes
        ("expId", "int"), ("value", "int[]", 3),
    ],
    "sphere": [  # 184 bytes
        ("sphereBoardId", "int"), ("boardName", "str", 129),
        ("kindId", "int"), ("boardId", "int"),
        ("arryId", "int"), ("masuId", "int"),
        ("type", "int"), ("openId", "int"),
        ("openParam", "int"), ("price", "int"),
        ("startDatetime", "date"), ("endDatetime", "date"),
    ],
    "sphereArray": [  # 184 bytes
        ("arryId", "int"),
        ("spCol4", "int[]", 9), ("spCol3", "int[]", 9),
        ("spCol2", "int[]", 9), ("spCol1", "int[]", 9),
        ("spCol0", "int[]", 9),
    ],
    "sphereMasu": [  # 652 bytes
        ("masuId", "int"), ("sphereBoardId", "int"),
        ("spherePoint", "int[]", 23), ("rewardSelect", "int[]", 23),
        ("medalCategory", "int[]", 23), ("rewardId", "int[]", 23),
        ("rewardExpand", "int[]", 23), ("rewardExpandId", "int[]", 23),
        ("rewardValue", "int[]", 23),
    ],
    "stamp": [  # 32 bytes
        ("stampId", "int"), ("category", "int"), ("imageId", "int"),
        ("require", "int"), ("sortId", "int"),
        ("imageWidth", "int"), ("imageHeight", "int"), ("validStamp", "int"),
    ],
    "title": [  # 344 bytes
        ("titleId", "int"), ("category", "int"),
        ("title", "str", 65), ("description", "str", 257),
        ("require", "int"), ("value", "int"), ("label", "int"),
    ],
    "tutorialMisc": [  # 32 bytes
        ("tutorialId", "int"), ("startClearQuest", "int"),
        ("startMiscId", "int"), ("num1", "int"), ("num2", "int"),
        ("setClearQuest", "int"), ("setMiscId", "int"), ("valid", "int"),
    ],
}

# Fields to drop from JSON output (v1.1.3 internal, not needed by server)
_FIELD_DROPS = {
    "medal": {"_pad0", "_pad1"},
}


def _align4(offset: int) -> int:
    r = offset % 4
    return offset + (4 - r) if r else offset


def _parse_entry(data: bytes, schema: list) -> Optional[Dict[str, Any]]:
    """Parse a decrypted entry using a schema definition."""
    result = {}
    offset = 0
    prev_was_str = False

    for idx, field_def in enumerate(schema):
        name = field_def[0]
        ftype = field_def[1]

        if prev_was_str and ftype not in ("str", "str[]", "time"):
            offset = _align4(offset)
        prev_was_str = False

        if offset >= len(data):
            break

        if ftype == "int":
            val, offset = _read_int(data, offset)
        elif ftype == "uint":
            val, offset = _read_uint(data, offset)
        elif ftype == "str":
            size = field_def[2]
            val, offset = _read_string(data, offset, size)
            prev_was_str = True
        elif ftype == "str[]":
            count = field_def[2]
            size = field_def[3]
            val = []
            for _ in range(count):
                s, offset = _read_string(data, offset, size)
                val.append(s)
            prev_was_str = True
        elif ftype == "int[]":
            count = field_def[2]
            val, offset = _read_int_array(data, offset, count)
        elif ftype == "date":
            val, offset = _read_date(data, offset)
        elif ftype == "time":
            val, offset = _read_time(data, offset)
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


class MasterDataParser:
    """Generic parser for KHUx master data m*.jpg files."""

    def __init__(self, extra_schemas: Optional[Dict[str, list]] = None):
        self.schemas = dict(SCHEMAS)
        if extra_schemas:
            self.schemas.update(extra_schemas)

    def table_name_from_filename(self, filename: str) -> Optional[str]:
        import re
        base = os.path.basename(filename)
        match = re.match(r'm(\d+)\.jpg', base)
        if match:
            idx = int(match.group(1))
            if idx < len(TABLE_NAMES):
                return TABLE_NAMES[idx]
        return None

    def detect_table(self, path: str) -> Optional[str]:
        """Auto-detect table name from the BGAD container's embedded name entry."""
        from ..containers.bgad import KHUxBGADContainer
        container = KHUxBGADContainer(path)
        result = None
        _special = ("/", "md5", "size", "hash", "revision")
        for entry in container.iter_entries_lazy():
            if entry.name not in _special and not entry.name.isdigit():
                result = entry.name
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
                drops = _FIELD_DROPS.get(table_name, set())
                if drops:
                    result = {k: v for k, v in result.items() if k not in drops}
                return result
        return _raw_dump(decrypted)

    def parse_file(self, path: str, table_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """Parse all entries from an m*.jpg BGAD container."""
        from ..containers.bgad import KHUxBGADContainer

        if table_name is None:
            table_name = self.detect_table(path)

        container = KHUxBGADContainer(path)
        records = []
        has_schema = table_name and table_name in self.schemas
        drops = _FIELD_DROPS.get(table_name, set()) if has_schema else set()

        for entry in container.iter_entries_lazy():
            if not entry.name.isdigit():
                continue
            if len(entry.data) < 8:
                continue
            try:
                _, _, decrypted = decrypt_master_data_payload(entry.data)
                if has_schema:
                    rec = _parse_entry(decrypted, self.schemas[table_name])
                    if rec is not None:
                        if drops:
                            rec = {k: v for k, v in rec.items() if k not in drops}
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
