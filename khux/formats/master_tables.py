"""
Per-table master data classes with version-aware schemas.

Each table is a subclass of MasterTable with schemas for v1.0.1 and v1.1.3.
Use `to(version)` to convert a parsed record between versions.

Usage:
    from khux.formats.master_tables import AvatarParts
    record = AvatarParts.parse(decrypted_bytes, version="1.1.3")
    record_101 = AvatarParts.to(record, target="1.0.1")
"""

import struct
from typing import Dict, List, Any, Optional


# ── Field readers ────────────────────────────────────────────────────────────

def _read_int(data, off):
    return struct.unpack_from("<i", data, off)[0], off + 4

def _read_str(data, off, size):
    raw = data[off:off + size]
    null = raw.find(b'\x00')
    if null >= 0:
        raw = raw[:null]
    try:
        return raw.decode('utf-8'), off + size
    except UnicodeDecodeError:
        return raw.decode('shift-jis', errors='replace'), off + size

def _read_int_array(data, off, count):
    arr = list(struct.unpack_from(f"<{count}i", data, off))
    return arr, off + count * 4

def _read_str_array(data, off, count, size):
    arr = []
    for _ in range(count):
        s, off = _read_str(data, off, size)
        arr.append(s)
    return arr, off

def format_date(raw8):
    """8-byte game Date -> the string the game's JSON parsers expect (Date::init: "YYYY-MM-DD HH:MM:SS").

    Layout (from Date::init): u16 year, u8 month, day, hour, minute, second, u8 flags (bit1 = valid).
    """
    year, month, day, hour, minute, second, _flags = struct.unpack("<HBBBBBB", raw8)
    return f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}"


def _read_date(data, off):
    return format_date(data[off:off + 8]), off + 8

def _read_time(data, off):
    val = struct.unpack_from("<I", data, off)[0]
    return f"{(val >> 16) & 0xFF:02d}:{(val >> 8) & 0xFF:02d}:{val & 0xFF:02d}", off + 4

def _align4(off):
    r = off % 4
    return off + (4 - r) if r else off


# ── Base class ───────────────────────────────────────────────────────────────

class MasterTable:
    """Base class for all master data tables."""

    name: str = ""
    versions: Dict[str, list] = {}

    @classmethod
    def parse(cls, data: bytes, version: str = "1.1.3") -> Optional[Dict[str, Any]]:
        """Parse decrypted binary data into a dict using the schema for `version`."""
        schema = cls.versions.get(version)
        if not schema:
            return None
        result = {}
        offset = 0
        prev_was_str = False
        for field_def in schema:
            fname = field_def[0]
            ftype = field_def[1]
            if prev_was_str and ftype not in ("str", "str[]", "time"):
                offset = _align4(offset)
            prev_was_str = False
            if offset >= len(data):
                break
            if ftype == "int":
                val, offset = _read_int(data, offset)
            elif ftype == "str":
                val, offset = _read_str(data, offset, field_def[2])
                prev_was_str = True
            elif ftype == "str[]":
                val, offset = _read_str_array(data, offset, field_def[2], field_def[3])
                prev_was_str = True
            elif ftype == "int[]":
                val, offset = _read_int_array(data, offset, field_def[2])
            elif ftype == "date":
                val, offset = _read_date(data, offset)
            elif ftype == "time":
                val, offset = _read_time(data, offset)
            else:
                break
            result[fname] = val
        return result

    @classmethod
    def serialize(cls, record: Dict[str, Any], version: str = "1.0.1") -> bytes:
        """Serialize a dict record into binary data for `version`. Stub."""
        raise NotImplementedError(f"{cls.name}.serialize")

    @classmethod
    def to(cls, record: Dict[str, Any], target: str = "1.0.1") -> Dict[str, Any]:
        """Convert a parsed record to the target version's field set.
        Drops fields not in the target schema, adds defaults for missing fields."""
        target_schema = cls.versions.get(target)
        if not target_schema:
            return record
        target_fields = {fd[0] for fd in target_schema}
        return {k: v for k, v in record.items() if k in target_fields}

    @classmethod
    def fields(cls, version: str = "1.0.1") -> List[str]:
        """Return field names for the given version."""
        schema = cls.versions.get(version)
        return [fd[0] for fd in schema] if schema else []


# ── Table definitions ────────────────────────────────────────────────────────

class AlbumChallenge(MasterTable):
    """v1.0.1 only (not in 1.1.3 m files).
    Fields: challengeId, sortId, valid, submissionName, type, attribute,
            targetNumber, rewardType, rewardId, assignSkillType, assignSkillId,
            assignSkillLv, num"""
    name = "albumChallenge"
    versions = {
        "1.0.1": [
            ("challengeId", "int"), ("sortId", "int"), ("valid", "int"),
            ("submissionName", "str", 257),
            ("type", "int"), ("attribute", "int"), ("targetNumber", "int"),
            ("rewardType", "int"), ("rewardId", "int"),
            ("assignSkillType", "int"), ("assignSkillId", "int"),
            ("assignSkillLv", "int"), ("num", "int"),
        ],
    }


class AvatarCombination(MasterTable):
    """v1.0.1 only (not in 1.1.3 m files).
    Fields: avatarCombinationId, combinationType, avatarPartsId, status"""
    name = "avatarCombination"
    versions = {
        "1.0.1": [
            ("avatarCombinationId", "int"), ("combinationType", "int"),
            ("avatarPartsId", "int"), ("status", "int"),
        ],
    }


class AvatarParts(MasterTable):
    """v1.0.1: 192 bytes — no luxCategory/luxAddRate
    v1.1.3: 200 bytes — added luxCategory, luxAddRate after position"""
    name = "avatarParts"
    versions = {
        "1.0.1": [
            ("avatarPartsId", "int"), ("name", "str", 129),
            ("partsType", "int"), ("gender", "int"),
            ("combinationType", "int"), ("combinationFlag", "int"),
            ("position", "int"), ("setKind", "int"),
            ("fixedFlag", "int"), ("validSetCloth", "int"),
            ("setCloth", "int[]", 5), ("status", "int"),
        ],
        "1.1.3": [
            ("avatarPartsId", "int"), ("name", "str", 129),
            ("partsType", "int"), ("gender", "int"),
            ("combinationType", "int"), ("combinationFlag", "int"),
            ("position", "int"),
            ("luxCategory", "int"), ("luxAddRate", "int"),
            ("setKind", "int"), ("fixedFlag", "int"),
            ("validSetCloth", "int"), ("setCloth", "int[]", 5),
            ("status", "int"),
        ],
    }


class Badstatus(MasterTable):
    """v1.0.1=v1.1.3: 92 bytes.
    Fields: badstatusId, name, iconId, effect, target, power[2]"""
    name = "badstatus"
    _schema = [
        ("badstatusId", "int"), ("name", "str", 65),
        ("iconId", "int"), ("effect", "int"),
        ("target", "int"), ("power", "int[]", 2),
    ]
    versions = {"1.0.1": _schema, "1.1.3": _schema}


class BattleMisc(MasterTable):
    """v1.0.1=v1.1.3: 8 bytes.
    Fields: battleMiscId, value"""
    name = "battleMisc"
    _schema = [("battleMiscId", "int"), ("value", "int")]
    versions = {"1.0.1": _schema, "1.1.3": _schema}


class Buff(MasterTable):
    """v1.0.1=v1.1.3: 88 bytes.
    Fields: buffId, grade, name, iconId, effect, addPower"""
    name = "buff"
    _schema = [
        ("buffId", "int"), ("grade", "int"), ("name", "str", 65),
        ("iconId", "int"), ("effect", "int"), ("addPower", "int"),
    ]
    versions = {"1.0.1": _schema, "1.1.3": _schema}


class Burst(MasterTable):
    """v1.0.1: 732 bytes. v1.1.3: 744 bytes (+12).
    Fields: burstId, motionId, effectId, distance, effectDirectionFix,
            name, description, maxEnhanceCount, attribute, target, hitCount,
            gauge, critical, criticalPower, displayPower,
            displayPowerPerEnforce[5], displayMaxPower,
            displayMaxPowerPerEnforce[5], basePower, basePowerPerEnforce[5],
            damageType, specialPowerType, sp1, sp2, sp1PerEnforce[5],
            sp2PerEnforce[5], addTurn, addCount, bufAttack..cureParalysis (56 buf/debuf/reset fields),
            copyBufBase, copyBufAttribute, heal, healShake,
            curePoison, cureSleep, cureDeepPoison, cureParalysis"""
    name = "burst"
    _schema_101 = [
        ("burstId", "int"), ("motionId", "int"), ("effectId", "int"),
        ("distance", "int"), ("effectDirectionFix", "int"),
        ("name", "str", 65), ("description", "str", 257),
        ("maxEnhanceCount", "int"), ("attribute", "int"),
        ("target", "int"), ("hitCount", "int"), ("gauge", "int"),
        ("critical", "int"), ("criticalPower", "int"), ("displayPower", "int"),
        ("displayPowerPerEnforce", "int[]", 5), ("displayMaxPower", "int"),
        ("displayMaxPowerPerEnforce", "int[]", 5), ("basePower", "int"),
        ("basePowerPerEnforce", "int[]", 5),
        ("damageType", "int"), ("specialPowerType", "int"),
        ("sp1", "int"), ("sp2", "int"),
        ("sp1PerEnforce", "int[]", 5), ("sp2PerEnforce", "int[]", 5),
        ("addTurn", "int"), ("addCount", "int"),
        ("bufAttack", "int"), ("debufAttack", "int"), ("debufAttackAll", "int"),
        ("bufDefense", "int"), ("debufDefense", "int"), ("debufDefenseAll", "int"),
        ("bufAttackPower", "int"), ("debufAttackPower", "int"), ("debufAttackPowerAll", "int"),
        ("bufDefensePower", "int"), ("debufDefensePower", "int"), ("debufDefensePowerAll", "int"),
        ("bufAttackSpeed", "int"), ("debufAttackSpeed", "int"), ("debufAttackSpeedAll", "int"),
        ("bufDefenseSpeed", "int"), ("debufDefenseSpeed", "int"), ("debufDefenseSpeedAll", "int"),
        ("bufAttackMagic", "int"), ("debufAttackMagic", "int"), ("debufAttackMagicAll", "int"),
        ("bufDefenseMagic", "int"), ("debufDefenseMagic", "int"), ("debufDefenseMagicAll", "int"),
        ("resetBufAtttack", "int"), ("resetDebufAttack", "int"), ("resetDebufAttackAll", "int"),
        ("resetBufDefense", "int"), ("resetDebufDefense", "int"), ("resetDebufDefenseAll", "int"),
        ("resetBufAtttackPower", "int"), ("resetDebufAttackPower", "int"), ("resetDebufAttackPowerAll", "int"),
        ("resetBufDefensePower", "int"), ("resetDebufDefensePower", "int"), ("resetDebufDefensePowerAll", "int"),
        ("resetBufAtttackSpeed", "int"), ("resetDebufAttackSpeed", "int"), ("resetDebufAttackSpeedAll", "int"),
        ("resetBufDefenseSpeed", "int"), ("resetDebufDefenseSpeed", "int"), ("resetDebufDefenseSpeedAll", "int"),
        ("resetBufAtttackMagic", "int"), ("resetDebufAttackMagic", "int"), ("resetDebufAttackMagicAll", "int"),
        ("resetBufDefenseMagic", "int"), ("resetDebufDefenseMagic", "int"), ("resetDebufDefenseMagicAll", "int"),
        ("copyBufBase", "int"), ("copyBufAttribute", "int"),
        ("heal", "int"), ("healShake", "int"),
        ("curePoison", "int"), ("cureSleep", "int"),
        ("cureDeepPoison", "int"), ("cureParalysis", "int"),
    ]
    _schema_113 = [
        ("burstId", "int"), ("motionId", "int"), ("effectId", "int"),
        ("distance", "int"), ("effectDirectionFix", "int"),
        ("name", "str", 65), ("description", "str", 257),
        ("maxEnhanceCount", "int"), ("attribute", "int"),
        ("attributeChange", "int"), ("imitation", "int"),
        ("target", "int"), ("hitCount", "int"), ("gauge", "int"),
        ("critical", "int"), ("criticalPower", "int"), ("displayPower", "int"),
        ("displayPowerPerEnforce", "int[]", 5), ("displayMaxPower", "int"),
        ("displayMaxPowerPerEnforce", "int[]", 5), ("basePower", "int"),
        ("basePowerPerEnforce", "int[]", 5),
        ("damageType", "int"), ("specialPowerType", "int"),
        ("sp1", "int"), ("sp2", "int"),
        ("sp1PerEnforce", "int[]", 5), ("sp2PerEnforce", "int[]", 5),
        ("addTurn", "int"), ("addCount", "int"),
        ("bufAttack", "int"), ("debufAttack", "int"), ("debufAttackAll", "int"),
        ("bufDefense", "int"), ("debufDefense", "int"), ("debufDefenseAll", "int"),
        ("bufAttackPower", "int"), ("debufAttackPower", "int"), ("debufAttackPowerAll", "int"),
        ("bufDefensePower", "int"), ("debufDefensePower", "int"), ("debufDefensePowerAll", "int"),
        ("bufAttackSpeed", "int"), ("debufAttackSpeed", "int"), ("debufAttackSpeedAll", "int"),
        ("bufDefenseSpeed", "int"), ("debufDefenseSpeed", "int"), ("debufDefenseSpeedAll", "int"),
        ("bufAttackMagic", "int"), ("debufAttackMagic", "int"), ("debufAttackMagicAll", "int"),
        ("bufDefenseMagic", "int"), ("debufDefenseMagic", "int"), ("debufDefenseMagicAll", "int"),
        ("resetBufAtttack", "int"), ("resetDebufAttack", "int"), ("resetDebufAttackAll", "int"),
        ("resetBufDefense", "int"), ("resetDebufDefense", "int"), ("resetDebufDefenseAll", "int"),
        ("resetBufAtttackPower", "int"), ("resetDebufAttackPower", "int"), ("resetDebufAttackPowerAll", "int"),
        ("resetBufDefensePower", "int"), ("resetDebufDefensePower", "int"), ("resetDebufDefensePowerAll", "int"),
        ("resetBufAtttackSpeed", "int"), ("resetDebufAttackSpeed", "int"), ("resetDebufAttackSpeedAll", "int"),
        ("resetBufDefenseSpeed", "int"), ("resetDebufDefenseSpeed", "int"), ("resetDebufDefenseSpeedAll", "int"),
        ("resetBufAtttackMagic", "int"), ("resetDebufAttackMagic", "int"), ("resetDebufAttackMagicAll", "int"),
        ("resetBufDefenseMagic", "int"), ("resetDebufDefenseMagic", "int"), ("resetDebufDefenseMagicAll", "int"),
        ("copyBufBase", "int"), ("copyBufAttribute", "int"),
        ("heal", "int"), ("healShake", "int"),
        ("curePoison", "int"), ("cureSleep", "int"),
        ("cureDeepPoison", "int"), ("cureParalysis", "int"),
        ("recovery", "int"),
    ]
    versions = {
        "1.0.1": _schema_101,
        "1.1.3": _schema_113,
    }


class Chapter(MasterTable):
    """v1.0.1 only. Fields: chapterId, name"""
    name = "chapter"
    versions = {
        "1.0.1": [("chapterId", "int"), ("name", "str", 257)],
    }


class Colosseum(MasterTable):
    """v1.0.1=v1.1.3: 220 bytes.
    Fields: colosseumId, colosseumStageId, round, ap, arrivalStageCount,
            rankId, excellentUnlockCount, validStageReward, stageReward*,
            validReward, reward*[4]"""
    name = "colosseum"
    _schema = [
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
    ]
    versions = {"1.0.1": _schema, "1.1.3": _schema}


class ColosseumStage(MasterTable):
    """v1.0.1=v1.1.3: 92 bytes.
    Fields: colosseumStageId, openDate, closeDate, rankingCloseDate,
            headColosseumId, termColosseumId, rankingId, validStage,
            stageId[10], loopStageCount, lvPerLoop"""
    name = "colosseumStage"
    _schema = [
        ("colosseumStageId", "int"),
        ("openDate", "date"), ("closeDate", "date"), ("rankingCloseDate", "date"),
        ("headColosseumId", "int"), ("termColosseumId", "int"),
        ("rankingId", "int"), ("validStage", "int"),
        ("stageId", "int[]", 10),
        ("loopStageCount", "int"), ("lvPerLoop", "int"),
    ]
    versions = {"1.0.1": _schema, "1.1.3": _schema}


class DrawMedalList(MasterTable):
    """v1.0.1 only. Fields: drawMedalListId, tableId, medalId, weight,
    skillType, skillId, burstUpperNumber, isDeleted"""
    name = "drawMedalList"
    _schema = [
        ("drawMedalListId", "int"), ("tableId", "int"),
        ("medalId", "int"), ("weight", "int"),
        ("skillType", "int"), ("skillId", "int"),
        ("burstUpperNumber", "int"), ("isDeleted", "int"),
    ]
    versions = {"1.0.1": _schema}


class DrawMedalType(MasterTable):
    """v1.0.1: 1136 bytes. v1.1.3: 1660 bytes (+524).
    Fields: drawMedalTypeId, drawType, sortId, name, description, payType,
            price, tableId, validLot, lot*[3], tableIds[3], validAdd, add*,
            bannerUrl, mypageBanner, dayCount, warrantNumberOfTime,
            warrantMedalListIds[1], warrantMedalRepeat,
            warrantResetMedalListIds[10], startDate, endDate, isDeleted"""
    name = "drawMedalType"
    _schema_101 = [
        ("drawMedalTypeId", "int"), ("drawType", "int"), ("sortId", "int"),
        ("name", "str", 129), ("description", "str", 257),
        ("payType", "int"), ("price", "int"),
        ("tableId", "int"), ("validLot", "int"),
        ("lotCount", "int[]", 3), ("lotPsr", "int[]", 3),
        ("lotSr", "int[]", 3), ("lotPr", "int[]", 3),
        ("lotR", "int[]", 3), ("lotPn", "int[]", 3),
        ("lotN", "int[]", 3), ("tableIds", "int[]", 3),
        ("validAdd", "int"), ("addType", "int"), ("addId", "int"),
        ("addSkillType", "int"), ("addSkillId", "int"),
        ("addSkillLv", "int"), ("addNum", "int"),
        ("bannerUrl", "str", 513),
        ("mypageBanner", "int"), ("dayCount", "int"),
        ("warrantNumberOfTime", "int"),
        ("warrantMedalListIds", "int[]", 1),
        ("warrantMedalRepeat", "int"),
        ("warrantResetMedalListIds", "int[]", 10),
        ("startDate", "date"), ("endDate", "date"),
        ("isDeleted", "int"),
    ]
    _schema_113 = [
        ("drawMedalTypeId", "int"), ("drawType", "int"), ("sortId", "int"),
        ("name", "str", 129), ("description", "str", 257),
        ("payType", "int"), ("price", "int"),
        ("tableId", "int"), ("validLot", "int"),
        ("lotCount", "int[]", 3), ("lotPsr", "int[]", 3),
        ("lotSr", "int[]", 3), ("lotPr", "int[]", 3),
        ("lotR", "int[]", 3), ("lotPn", "int[]", 3),
        ("lotN", "int[]", 3), ("tableIds", "int[]", 3),
        ("validAdd", "int"), ("addType", "int"), ("addId", "int"),
        ("addSkillType", "int"), ("addSkillId", "int"),
        ("addSkillLv", "int"), ("addNum", "int"),
        ("bannerUrl", "str", 513),
        ("mypageBanner", "int"),
        ("detailUrl", "str", 513),
        ("dayCount", "int"), ("warrantNumberOfTime", "int"),
        ("warrantDisplayOfTime", "int"),
        ("warrantMedalListIds", "int[]", 1),
        ("warrantMedalRepeat", "int"),
        ("warrantResetMedalListIds", "int[]", 10),
        ("displayTimeLeft", "int"),
        ("startDate", "date"), ("endDate", "date"),
        ("isDeleted", "int"),
    ]
    versions = {
        "1.0.1": _schema_101,
        "1.1.3": _schema_113,
    }


class DrawSkillList(MasterTable):
    """v1.0.1 only. Fields: drawSkillListId, tableId, skillId, weight, isDeleted"""
    name = "drawSkillList"
    _schema = [
        ("drawSkillListId", "int"), ("tableId", "int"),
        ("skillId", "int"), ("weight", "int"), ("isDeleted", "int"),
    ]
    versions = {"1.0.1": _schema}


class DrawSkillType(MasterTable):
    """v1.0.1 only. Fields: drawSkillTypeId, tableId, lotRare3/2/1, lotNon, lotReserve, isDeleted"""
    name = "drawSkillType"
    _schema = [
        ("drawSkillTypeId", "int"), ("tableId", "int"),
        ("lotRare3", "int"), ("lotRare2", "int"), ("lotRare1", "int"),
        ("lotNon", "int"), ("lotReserve", "int"), ("isDeleted", "int"),
    ]
    versions = {"1.0.1": _schema}


class Enemy(MasterTable):
    """v1.0.1: 992 bytes (baseLv[5], skill*[4], statusAilments[2]).
    v1.1.3: 1100 bytes (baseLv[6], 26 extra ints before validSkill, skill*[4], statusAilments[2]).
    Fields: enemyId, name, flavor, displayId, show, showSwf, showFrame,
            hideFrame, moveSpeed, hitRadius, tapRadius, width, height,
            spBattle, kind, attribute, validGrowth, baseLv[], hp[5],
            attack[5], defense[5], exp[5], money[5], raidPoint[5], lux[5],
            attackCp, suppressCp, attackHp, suppressHp, suppressGuilt,
            battlePattern, displayHeight, runaway, neverAttack, validSkill,
            skillId[], skillRequire[], skillRequireArg[], skillOdds[],
            protect*, regist*, buf*, bufTurn, bufCount, statusAilments[],
            statusAilmentsTurn, statusAilmentsCount"""
    name = "enemy"
    versions = {
        "1.0.1": [
            ("enemyId", "int"), ("name", "str", 65), ("flavor", "str", 513),
            ("displayId", "int"), ("show", "int"), ("showSwf", "int"),
            ("showFrame", "int"), ("hideFrame", "int"), ("moveSpeed", "int"),
            ("hitRadius", "int"), ("tapRadius", "int"),
            ("width", "int"), ("height", "int"),
            ("spBattle", "int"), ("kind", "int"), ("attribute", "int"),
            ("validGrowth", "int"), ("baseLv", "int[]", 5),
            ("hp", "int[]", 5), ("attack", "int[]", 5), ("defense", "int[]", 5),
            ("exp", "int[]", 5), ("money", "int[]", 5),
            ("raidPoint", "int[]", 5), ("lux", "int[]", 5),
            ("attackCp", "int"), ("suppressCp", "int"),
            ("attackHp", "int"), ("suppressHp", "int"), ("suppressGuilt", "int"),
            ("battlePattern", "int"), ("displayHeight", "int"),
            ("runaway", "int"), ("neverAttack", "int"), ("validSkill", "int"),
            ("skillId", "int[]", 4), ("skillRequire", "int[]", 4),
            ("skillRequireArg", "int[]", 4), ("skillOdds", "int[]", 4),
            ("protectPoison", "int"), ("protectDeepPoison", "int"),
            ("protectSleep", "int"), ("protectParalysis", "int"),
            ("registPoison", "int"), ("registDeepPoison", "int"),
            ("registSleep", "int"), ("registParalysis", "int"),
            ("bufAttack", "int"), ("bufDefense", "int"),
            ("bufAttackPower", "int"), ("bufDefensePower", "int"),
            ("bufAttackSpeed", "int"), ("bufDefenseSpeed", "int"),
            ("bufAttackMagic", "int"), ("bufDefenseMagic", "int"),
            ("bufTurn", "int"), ("bufCount", "int"),
            ("statusAilments", "int[]", 2),
            ("statusAilmentsTurn", "int"), ("statusAilmentsCount", "int"),
        ],
        "1.1.3": [
            ("enemyId", "int"), ("name", "str", 65), ("flavor", "str", 513),
            ("displayId", "int"), ("show", "int"), ("showSwf", "int"),
            ("showFrame", "int"), ("hideFrame", "int"), ("moveSpeed", "int"),
            ("hitRadius", "int"), ("tapRadius", "int"),
            ("width", "int"), ("height", "int"),
            ("spBattle", "int"), ("kind", "int"), ("attribute", "int"),
            ("validGrowth", "int"), ("baseLv", "int[]", 6),
            ("hp", "int[]", 5), ("attack", "int[]", 5), ("defense", "int[]", 5),
            ("exp", "int[]", 5), ("money", "int[]", 5),
            ("raidPoint", "int[]", 5), ("lux", "int[]", 5),
            ("attackCp", "int"), ("suppressCp", "int"),
            ("attackHp", "int"), ("suppressHp", "int"), ("suppressGuilt", "int"),
            ("battlePattern", "int"), ("displayHeight", "int"),
            ("runaway", "int"), ("neverAttack", "int"),
            # 26 ints absent from v1.0.1 (4.3.1 names urgency data here). Without this block every field
            # from validSkill on read shifted: validSkill came out as 10 for all 665 enemies, and the
            # game's cooldown loop (EnemyActor::select_enemy_attack) then overran into the Enemy* and
            # crashed the tutorial battle. Anchored on 4.3.1 Shadow: validSkill 2, skillId [100, 101].
            ("extra113", "int[]", 26),
            ("validSkill", "int"),
            ("skillId", "int[]", 4), ("skillRequire", "int[]", 4),
            ("skillRequireArg", "int[]", 4), ("skillOdds", "int[]", 4),
            ("protectPoison", "int"), ("protectDeepPoison", "int"),
            ("protectSleep", "int"), ("protectParalysis", "int"),
            ("registPoison", "int"), ("registDeepPoison", "int"),
            ("registSleep", "int"), ("registParalysis", "int"),
            ("bufAttack", "int"), ("bufDefense", "int"),
            ("bufAttackPower", "int"), ("bufDefensePower", "int"),
            ("bufAttackSpeed", "int"), ("bufDefenseSpeed", "int"),
            ("bufAttackMagic", "int"), ("bufDefenseMagic", "int"),
            ("bufTurn", "int"), ("bufCount", "int"),
            ("statusAilments", "int[]", 2),
            ("statusAilmentsTurn", "int"), ("statusAilmentsCount", "int"),
        ],
    }


class EnemyAttack(MasterTable):
    """v1.0.1: 228 bytes. v1.1.3: 236 bytes (+8, +2 fields at end).
    Fields: enemyAttackId, name, attackMotion..cureParalysis (41 fields)"""
    name = "enemyAttack"
    _schema_101 = [
        ("enemyAttackId", "int"), ("name", "str", 65),
        ("attackMotion", "int"), ("hitEffect", "int"),
        ("effectDirectionFix", "int"), ("display", "int"),
        ("choiseAttribute", "int"), ("hitCount", "int"),
        ("power", "int"), ("critical", "int"), ("criticalPower", "int"),
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
    ]
    _schema_113 = [
        ("enemyAttackId", "int"), ("name", "str", 65),
        ("attackMotion", "int"), ("hitEffect", "int"),
        ("effectDirectionFix", "int"), ("display", "int"),
        ("attackTarget", "int"),
        ("choiseAttribute", "int"), ("hitCount", "int"),
        ("power", "int"), ("critical", "int"), ("criticalPower", "int"),
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
        ("spEffect", "int"),
    ]
    versions = {
        "1.0.1": _schema_101,
        "1.1.3": _schema_113,
    }


class EvCampaign(MasterTable):
    """v1.0.1=v1.1.3: 352 bytes.
    Fields: campaignId, type, power, displayText, stageType, validStageId,
            stageId[5], startTime, endTime, week*, groupPattern, validMinute"""
    name = "evCampaign"
    _schema = [
        ("campaignId", "int"), ("type", "int"), ("power", "int"),
        ("displayText", "str", 257),
        ("stageType", "int"), ("validStageId", "int"),
        ("stageId", "int[]", 5),
        ("startTime", "date"), ("endTime", "date"),
        ("weekMonday", "int"), ("weekTuesday", "int"), ("weekWednesday", "int"),
        ("weekThursday", "int"), ("weekFriday", "int"),
        ("weekSaturday", "int"), ("weekSunday", "int"),
        ("groupPattern", "int"), ("validMinute", "int"),
    ]
    versions = {"1.0.1": _schema, "1.1.3": _schema}


class EvGroupPattern(MasterTable):
    """v1.0.1 only: 24 bytes.
    Fields: patternId, groupDivide, startTime, endTime, shiftTime, rotate"""
    name = "evGroupPattern"
    _schema = [
        ("patternId", "int"), ("groupDivide", "int"),
        ("startTime", "time"), ("endTime", "time"),
        ("shiftTime", "time"), ("rotate", "int"),
    ]
    versions = {"1.0.1": _schema}


class EvResource(MasterTable):
    """v1.0.1=v1.1.3: 20 bytes.
    Fields: resourceId, priority, validResource, endTime"""
    name = "evResource"
    _schema = [
        ("resourceId", "int"), ("priority", "int"),
        ("validResource", "int"), ("endTime", "date"),
    ]
    versions = {"1.0.1": _schema, "1.1.3": _schema}


class EvStage(MasterTable):
    """v1.0.1: 660 bytes. v1.1.3: 1204 bytes (+544).
    Fields: eventStageId, validStageId, stageId[5], validStageWidthId,
            stageStartId, stageEndId, eventCategory, eventType, bannerUrl,
            mypageBanner, startTime, endTime, boardEndTime, week*,
            benefit*, groupPattern, validMinute"""
    name = "evStage"
    _schema_101 = [
        ("eventStageId", "int"), ("validStageId", "int"),
        ("stageId", "int[]", 5),
        ("validStageWidthId", "int"), ("stageStartId", "int"), ("stageEndId", "int"),
        ("eventCategory", "int"), ("eventType", "int"),
        ("bannerUrl", "str", 513), ("mypageBanner", "int"),
        ("startTime", "date"), ("endTime", "date"), ("boardEndTime", "date"),
        ("weekMonday", "int"), ("weekTuesday", "int"), ("weekWednesday", "int"),
        ("weekThursday", "int"), ("weekFriday", "int"),
        ("weekSaturday", "int"), ("weekSunday", "int"),
        ("benefitId", "int"),
        ("benefitMonday", "int"), ("benefitTuesday", "int"),
        ("benefitWednesday", "int"), ("benefitThursday", "int"),
        ("benefitFriday", "int"), ("benefitSaturday", "int"),
        ("benefitSunday", "int"),
        ("groupPattern", "int"), ("validMinute", "int"),
    ]
    _schema_113 = _schema_101 + [
        ("_reserved", "int[]", 109),
        ("resetFlag", "int"),
        ("startTimeNew", "date"), ("endTimeNew", "date"),
        ("boardEndTimeNew", "date"), ("endDispTime", "date"),
        ("scoreMedalListId", "int"),
        ("weekMonday2", "int"), ("weekTuesday2", "int"), ("weekWednesday2", "int"),
        ("weekThursday2", "int"), ("weekFriday2", "int"),
        ("weekSaturday2", "int"), ("weekSunday2", "int"),
        ("benefitId2", "int"),
        ("benefitMonday2", "int"), ("benefitTuesday2", "int"),
        ("benefitWednesday2", "int"), ("benefitThursday2", "int"),
        ("benefitFriday2", "int"), ("benefitSaturday2", "int"),
        ("benefitSunday2", "int"),
        ("_reserved2", "int"), ("_reserved3", "int"),
    ]
    versions = {
        "1.0.1": _schema_101,
        "1.1.3": _schema_113,
    }


class GuiltProb(MasterTable):
    """v1.0.1=v1.1.3: 20 bytes. Fields: id, value, factor, weight, isCampaign"""
    name = "guiltProb"
    _schema = [
        ("id", "int"), ("value", "int"), ("factor", "int"),
        ("weight", "int"), ("isCampaign", "int"),
    ]
    versions = {"1.0.1": _schema, "1.1.3": _schema}


class InitItem(MasterTable):
    """v1.0.1=v1.1.3: 28 bytes.
    Fields: id, category, equipType, equipNo, param, itemId, skillId"""
    name = "initItem"
    _schema = [
        ("id", "int"), ("category", "int"), ("equipType", "int"),
        ("equipNo", "int"), ("param", "int"),
        ("itemId", "int"), ("skillId", "int"),
    ]
    versions = {"1.0.1": _schema, "1.1.3": _schema}


class Keyblade(MasterTable):
    """v1.0.1: 356 bytes (needMaterial*[4]). v1.1.3: 380 bytes (needMaterial*[5], +24).
    Fields: keybladeId, name, description, lv, displayId, category,
            passive, passivePower, drawCount, maxBurstGauge, validConsist,
            attribute[5], darklight[5], accord[5], dlaccord[5],
            partnerRate, evolveId, validNeedMaterial,
            needMaterialId[], needMaterialNum[]"""
    name = "keyblade"
    versions = {
        "1.0.1": [
            ("keybladeId", "int"), ("name", "str", 65), ("description", "str", 129),
            ("lv", "int"), ("displayId", "int"), ("category", "int"),
            ("passive", "int"), ("passivePower", "int"),
            ("drawCount", "int"), ("maxBurstGauge", "int"), ("validConsist", "int"),
            ("attribute", "int[]", 5), ("darklight", "int[]", 5),
            ("accord", "int[]", 5), ("dlaccord", "int[]", 5),
            ("partnerRate", "int"), ("evolveId", "int"),
            ("validNeedMaterial", "int"),
            ("needMaterialId", "int[]", 4), ("needMaterialNum", "int[]", 4),
        ],
        "1.1.3": [
            ("keybladeId", "int"), ("name", "str", 65), ("description", "str", 129),
            ("lv", "int"), ("displayId", "int"), ("category", "int"),
            ("passive", "int"), ("passivePower", "int"),
            ("drawCount", "int"), ("maxBurstGauge", "int"), ("validConsist", "int"),
            ("attribute", "int[]", 5), ("darklight", "int[]", 5),
            ("accord", "int[]", 5), ("dlaccord", "int[]", 5),
            ("partnerRate", "int"), ("evolveId", "int"),
            ("validNeedMaterial", "int"),
            ("needMaterialId", "int[]", 5), ("needMaterialNum", "int[]", 5),
        ],
    }


class LoginBonus(MasterTable):
    """v1.0.1=v1.1.3: 2360 bytes.
    Fields: loginBonusId, bonusType, title, description, comment, day,
            startDate, endDate, rewardType, rewardId, rewardAssignSkill*, rewardNum"""
    name = "loginBonus"
    _schema = [
        ("loginBonusId", "int"), ("bonusType", "int"),
        ("title", "str", 257), ("description", "str", 1025), ("comment", "str", 1025),
        ("day", "int"),
        ("startDate", "date"), ("endDate", "date"),
        ("rewardType", "int"), ("rewardId", "int"),
        ("rewardAssignSkillType", "int"), ("rewardAssignSkillId", "int"),
        ("rewardAssignSkillLv", "int"), ("rewardNum", "int"),
    ]
    versions = {"1.0.1": _schema, "1.1.3": _schema}


class Material(MasterTable):
    """v1.0.1=v1.1.3: 212 bytes.
    Fields: materialId, category, sortId, name, description, sell"""
    name = "material"
    _schema = [
        ("materialId", "int"), ("category", "int"), ("sortId", "int"),
        ("name", "str", 65), ("description", "str", 129), ("sell", "int"),
    ]
    versions = {"1.0.1": _schema, "1.1.3": _schema}


class Medal(MasterTable):
    """v1.0.1: 1276 bytes (source[3], burstEnhanceCategory[2]).
    v1.1.3: 1300 bytes (+_pad0/_pad1 before name, source[5], burstEnhanceCategory[5]).
    Fields: medalId, imageId, thumbId, sortId, name, flavor, advantage,
            type, attribute, darklight, validSource, source[], rare,
            skillSlot, guiltValue, maxLv, expType, cost, minCost, growthType,
            attack, maxAttack, addMaxAttack, defense, maxDefense, addMaxDefense,
            validBurst, burstId, burstEnhanceCategory[], groupId,
            sellSpherePoint, materialExp, sell, sellPerLv,
            enhanceAttack, enhanceDefense, enhanceCost,
            validEvolve, evolveId, evolveMoney, validEvolveNeed, evolveNeedId[]"""
    name = "medal"
    versions = {
        "1.0.1": [
            ("medalId", "int"), ("imageId", "int"), ("thumbId", "int"), ("sortId", "int"),
            ("name", "str", 65), ("flavor", "str", 513), ("advantage", "str", 513),
            ("type", "int"), ("attribute", "int"), ("darklight", "int"),
            ("validSource", "int"), ("source", "int[]", 3),
            ("rare", "int"), ("skillSlot", "int"), ("guiltValue", "int"),
            ("maxLv", "int"), ("expType", "int"),
            ("cost", "int"), ("minCost", "int"), ("growthType", "int"),
            ("attack", "int"), ("maxAttack", "int"), ("addMaxAttack", "int"),
            ("defense", "int"), ("maxDefense", "int"), ("addMaxDefense", "int"),
            ("validBurst", "int"), ("burstId", "int"),
            ("burstEnhanceCategory", "int[]", 2),
            ("groupId", "int"), ("sellSpherePoint", "int"),
            ("materialExp", "int"), ("sell", "int"), ("sellPerLv", "int"),
            ("enhanceAttack", "int"), ("enhanceDefense", "int"), ("enhanceCost", "int"),
            ("validEvolve", "int"), ("evolveId", "int"), ("evolveMoney", "int"),
            ("validEvolveNeed", "int"), ("evolveNeedId", "int[]", 5),
        ],
        "1.1.3": [
            ("medalId", "int"), ("imageId", "int"), ("thumbId", "int"), ("sortId", "int"),
            ("_pad0", "int"), ("_pad1", "int"),
            ("name", "str", 65), ("flavor", "str", 513), ("advantage", "str", 513),
            ("type", "int"), ("attribute", "int"), ("darklight", "int"),
            ("validSource", "int"), ("source", "int[]", 5),
            ("rare", "int"), ("skillSlot", "int"), ("guiltValue", "int"),
            ("maxLv", "int"), ("expType", "int"),
            ("cost", "int"), ("minCost", "int"), ("growthType", "int"),
            ("attack", "int"), ("maxAttack", "int"), ("addMaxAttack", "int"),
            ("defense", "int"), ("maxDefense", "int"), ("addMaxDefense", "int"),
            ("validBurst", "int"), ("burstId", "int"),
            ("burstEnhanceCategory", "int[]", 5),
            ("groupId", "int"), ("sellSpherePoint", "int"),
            ("materialExp", "int"), ("sell", "int"), ("sellPerLv", "int"),
            ("enhanceAttack", "int"), ("enhanceDefense", "int"), ("enhanceCost", "int"),
            ("validEvolve", "int"), ("evolveId", "int"), ("evolveMoney", "int"),
            ("validEvolveNeed", "int"), ("evolveNeedId", "int[]", 4),
        ],
    }


class MedalMisc(MasterTable):
    """v1.0.1=v1.1.3: 16 bytes. Fields: medalMiscId, value[3]"""
    name = "medalMisc"
    _schema = [("medalMiscId", "int"), ("value", "int[]", 3)]
    versions = {"1.0.1": _schema, "1.1.3": _schema}


class Misc(MasterTable):
    """v1.0.1=v1.1.3: 8 bytes. Fields: miscId, value"""
    name = "misc"
    _schema = [("miscId", "int"), ("value", "int")]
    versions = {"1.0.1": _schema, "1.1.3": _schema}


class MypageBackground(MasterTable):
    """v1.0.1=v1.1.3: 160 bytes.
    Fields: id, backgroundId, sortId, validChild, startTime, endTime,
            viewType, validParts, partsId[6], dataType[6], xPostion[6],
            yPostion[6], zSort[6]"""
    name = "mypageBackground"
    _schema = [
        ("id", "int"), ("backgroundId", "int"), ("sortId", "int"),
        ("validChild", "int"),
        ("startTime", "date"), ("endTime", "date"),
        ("viewType", "int"), ("validParts", "int"),
        ("partsId", "int[]", 6), ("dataType", "int[]", 6),
        ("xPostion", "int[]", 6), ("yPostion", "int[]", 6),
        ("zSort", "int[]", 6),
    ]
    versions = {"1.0.1": _schema, "1.1.3": _schema}


class Player(MasterTable):
    """v1.0.1=v1.1.3: 28 bytes.
    Fields: lv, needExp, luxMedal, ap, cost, hp, rewardId"""
    name = "player"
    _schema = [
        ("lv", "int"), ("needExp", "int"), ("luxMedal", "int"),
        ("ap", "int"), ("cost", "int"), ("hp", "int"), ("rewardId", "int"),
    ]
    versions = {"1.0.1": _schema, "1.1.3": _schema}


class RaidEnemy(MasterTable):
    """v1.0.1: 708 bytes. v1.1.3: 876 bytes (+168).
    Fields: raidEnemyId, name, attribute, rare, weakness, validParts, parts[5],
            validGrowth, baseLv[5]..guiltSuppress[5] (many int[5] arrays),
            rewardId[5], mvpRewardId[5], destroyAllRewardId[5],
            drawHeight, validSkill, skillId[4]..skillOdds[4],
            protect*, regist*, buf*, statusAilments[2],
            statusAilmentsTurn, statusAilmentsCount, bgmRaid"""
    name = "raidEnemy"
    _schema_101 = [
        ("raidEnemyId", "int"), ("name", "str", 129),
        ("attribute", "int"), ("rare", "int"), ("weakness", "int"),
        ("validParts", "int"), ("parts", "int[]", 5),
        ("validGrowth", "int"),
        ("baseLv", "int[]", 5), ("hp", "int[]", 5),
        ("attack", "int[]", 5), ("defense", "int[]", 5),
        ("expAttack", "int[]", 5), ("expSuppress", "int[]", 5),
        ("moneyAttack", "int[]", 5), ("moneySuppress", "int[]", 5),
        ("luxAttack", "int[]", 5), ("luxSuppress", "int[]", 5),
        ("burstAttack", "int[]", 5), ("burstSuppress", "int[]", 5),
        ("hpAttack", "int[]", 5), ("hpSuppress", "int[]", 5),
        ("guiltSuppress", "int[]", 5),
        ("rewardId", "int[]", 5), ("mvpRewardId", "int[]", 5),
        ("destroyAllRewardId", "int[]", 5),
        ("drawHeight", "int"), ("validSkill", "int"),
        ("skillId", "int[]", 4), ("skillRequire", "int[]", 4),
        ("skillRequireArg", "int[]", 4), ("skillOdds", "int[]", 4),
        ("protectPoison", "int"), ("protectDeepPoison", "int"),
        ("protectSleep", "int"), ("protectParalysis", "int"),
        ("protectConfusion", "int"),
        ("registPoison", "int"), ("registDeepPoison", "int"),
        ("registSleep", "int"), ("registParalysis", "int"),
        ("registConfusion", "int"),
        ("bufAttack", "int"), ("bufDefense", "int"),
        ("bufAttackPower", "int"), ("bufDefensePower", "int"),
        ("bufAttackSpeed", "int"), ("bufDefenseSpeed", "int"),
        ("bufAttackMagic", "int"), ("bufDefenseMagic", "int"),
        ("bufTurn", "int"), ("bufCount", "int"),
        ("statusAilments", "int[]", 2),
        ("statusAilmentsTurn", "int"), ("statusAilmentsCount", "int"),
        ("bgmRaid", "int"),
    ]
    _schema_113 = [
        ("raidEnemyId", "int"), ("name", "str", 129),
        ("attribute", "int"), ("rare", "int"), ("weakness", "int"),
        ("validParts", "int"),
        ("raidDisplayId", "int"),
        ("parts", "int[]", 5),
        ("validGrowth", "int"),
        ("baseLv", "int[]", 5), ("hp", "int[]", 5),
        ("attack", "int[]", 5), ("defense", "int[]", 5),
        ("expAttack", "int[]", 5), ("expSuppress", "int[]", 5),
        ("moneyAttack", "int[]", 5), ("moneySuppress", "int[]", 5),
        ("luxAttack", "int[]", 5), ("luxSuppress", "int[]", 5),
        ("burstAttack", "int[]", 5), ("burstSuppress", "int[]", 5),
        ("hpAttack", "int[]", 5), ("hpSuppress", "int[]", 5),
        ("guiltSuppress", "int[]", 5),
        ("rewardId", "int[]", 5), ("mvpRewardId", "int[]", 5),
        ("destroyAllRewardId", "int[]", 5),
        ("validLocked", "int"),
        ("lockedLv", "int[]", 10), ("lockedRewardId", "int[]", 10),
        ("lockedMvpRewardId", "int[]", 10), ("lockedDestroyAllRewardId", "int[]", 10),
        ("drawHeight", "int"), ("validSkill", "int"),
        ("skillId", "int[]", 4), ("skillRequire", "int[]", 4),
        ("skillRequireArg", "int[]", 4), ("skillOdds", "int[]", 4),
        ("registPoison", "int"), ("registDeepPoison", "int"),
        ("registSleep", "int"), ("registParalysis", "int"),
        ("registConfusion", "int"),
        ("protectPoison", "int"), ("protectDeepPoison", "int"),
        ("protectSleep", "int"), ("protectParalysis", "int"),
        ("protectConfusion", "int"),
        ("bufAttack", "int"), ("bufDefense", "int"),
        ("bufAttackPower", "int"), ("bufDefensePower", "int"),
        ("bufAttackSpeed", "int"), ("bufDefenseSpeed", "int"),
        ("bufAttackMagic", "int"), ("bufDefenseMagic", "int"),
        ("bufTurn", "int"), ("bufCount", "int"),
        ("statusAilments", "int[]", 2),
        ("statusAilmentsTurn", "int"), ("statusAilmentsCount", "int"),
        ("bgmRaid", "int"),
    ]
    versions = {
        "1.0.1": _schema_101,
        "1.1.3": _schema_113,
    }


class RaidEnemyAttack(MasterTable):
    """v1.0.1=v1.1.3: 216 bytes.
    Fields: raidEnemyAttackId, name, display..cureParalysis (38 fields)"""
    name = "raidEnemyAttack"
    _schema = [
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
    ]
    versions = {"1.0.1": _schema, "1.1.3": _schema}


class RaidReward(MasterTable):
    """v1.0.1=v1.1.3: 128 bytes.
    Fields: raidRewardId, oddsUpPerLv, pointUpPerLv, validReward,
            type[4], id[4], assignSkill*[4], num[4], odds[4]"""
    name = "raidReward"
    _schema = [
        ("raidRewardId", "int"), ("oddsUpPerLv", "int"),
        ("pointUpPerLv", "int"), ("validReward", "int"),
        ("type", "int[]", 4), ("id", "int[]", 4),
        ("assignSkillType", "int[]", 4), ("assignSkillId", "int[]", 4),
        ("assignSkillLv", "int[]", 4), ("num", "int[]", 4), ("odds", "int[]", 4),
    ]
    versions = {"1.0.1": _schema, "1.1.3": _schema}


class RaidSetting(MasterTable):
    """v1.0.1=v1.1.3: 68 bytes.
    Fields: raidSettingId, bossId, bossUpTime, useAp, rareBoss*,
            rareUpType*, validUnlockRare, unlockRareBossId[3], unlockRareNum[3]"""
    name = "raidSetting"
    _schema = [
        ("raidSettingId", "int"), ("bossId", "int"),
        ("bossUpTime", "int"), ("useAp", "int"),
        ("rareBossId", "int"), ("rareBossUpTime", "int"),
        ("rareUseAp", "int"), ("rareUpType", "int"),
        ("rareUpTypeArg", "int"), ("rareUpTriggerBossId", "int"),
        ("validUnlockRare", "int"),
        ("unlockRareBossId", "int[]", 3), ("unlockRareNum", "int[]", 3),
    ]
    versions = {"1.0.1": _schema, "1.1.3": _schema}


class Ranking(MasterTable):
    """v1.0.1=v1.1.3: 76 bytes.
    Fields: rankingId, category, startDatetime, endDatetime,
            startRank, endRank, unionStartRank[5], unionEndRank[5], validReward"""
    name = "ranking"
    _schema = [
        ("rankingId", "int"), ("category", "int"),
        ("startDatetime", "date"), ("endDatetime", "date"),
        ("startRank", "int"), ("endRank", "int"),
        ("unionStartRank", "int[]", 5), ("unionEndRank", "int[]", 5),
        ("validReward", "int"),
    ]
    versions = {"1.0.1": _schema, "1.1.3": _schema}


class RankingReward(MasterTable):
    """v1.0.1=v1.1.3: 256 bytes.
    Fields: rankingRewardId, startRank, endRank, validReward,
            type[10], id[10], skillType[10], skillId[10], skillLv[10], num[10]"""
    name = "rankingReward"
    _schema = [
        ("rankingRewardId", "int"), ("startRank", "int"),
        ("endRank", "int"), ("validReward", "int"),
        ("type", "int[]", 10), ("id", "int[]", 10),
        ("skillType", "int[]", 10), ("skillId", "int[]", 10),
        ("skillLv", "int[]", 10), ("num", "int[]", 10),
    ]
    versions = {"1.0.1": _schema, "1.1.3": _schema}


class Reward(MasterTable):
    """v1.0.1=v1.1.3: 136 bytes.
    Fields: rewardId, validReward, display[4], type[4], id[4],
            assignSkill*[4], num[4], odds[4]"""
    name = "reward"
    _schema = [
        ("rewardId", "int"), ("validReward", "int"),
        ("display", "int[]", 4), ("type", "int[]", 4), ("id", "int[]", 4),
        ("assignSkillType", "int[]", 4), ("assignSkillId", "int[]", 4),
        ("assignSkillLv", "int[]", 4), ("num", "int[]", 4), ("odds", "int[]", 4),
    ]
    versions = {"1.0.1": _schema, "1.1.3": _schema}


class SerialcodeReward(MasterTable):
    """v1.0.1=v1.1.3: 432 bytes.
    Fields: serialcodeRewardId, name, startDate, endDate, itemId,
            validReward, type[6], id[6], skill*[6], num[6]"""
    name = "serialcodeReward"
    _schema = [
        ("serialcodeRewardId", "int"), ("name", "str", 257),
        ("startDate", "date"), ("endDate", "date"),
        ("itemId", "int"), ("validReward", "int"),
        ("type", "int[]", 6), ("id", "int[]", 6),
        ("skillType", "int[]", 6), ("skillId", "int[]", 6),
        ("skillLv", "int[]", 6), ("num", "int[]", 6),
    ]
    versions = {"1.0.1": _schema, "1.1.3": _schema}


class Shop(MasterTable):
    """v1.0.1=v1.1.3: 708 bytes.
    Fields: shopId, productId, sortId, type, os, price, number, bonus,
            explanation, stageSkipTicket, appleStatus, benefit*,
            benefitResetWeek, benefitResetTime, benefitExplanation,
            useBenefitExplanation, thumbId, status"""
    name = "shop"
    _schema = [
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
    ]
    versions = {"1.0.1": _schema, "1.1.3": _schema}


class Skill(MasterTable):
    """v1.0.1: 312 bytes. v1.1.3: 316 bytes (+4, +1 field).
    Fields: skillId, imageId, thumbId, name, description, rank, maxLv,
            expType, sortId, categoryEvolve, invoke*, attackUp, burstCancel,
            damageCut, dokonjo, counter, addAction, addPoison..addParalysis,
            conditionTurn, conditionCount, prizeHpUp, prizeBurstUp,
            luxUp, moneyUp, raidUp"""
    name = "skill"
    _schema_101 = [
        ("skillId", "int"), ("imageId", "int"), ("thumbId", "int"),
        ("name", "str", 65), ("description", "str", 129),
        ("rank", "int"), ("maxLv", "int"), ("expType", "int"),
        ("sortId", "int"), ("categoryEvolve", "int"),
        ("invokeType", "int"), ("invokeProb", "int"),
        ("invokeProbPerLv", "int"), ("invokeShowTiming", "int"),
        ("attackUp", "int"), ("burstCancel", "int"),
        ("damageCut", "int"), ("dokonjo", "int"), ("counter", "int"),
        ("addAction", "int"), ("addPoison", "int"), ("addDeepPoison", "int"),
        ("addSleep", "int"), ("addParalysis", "int"),
        ("conditionTurn", "int"), ("conditionCount", "int"),
        ("prizeHpUp", "int"), ("prizeBurstUp", "int"),
        ("luxUp", "int"), ("moneyUp", "int"), ("raidUp", "int"),
    ]
    _schema_113 = [
        ("skillId", "int"), ("imageId", "int"), ("thumbId", "int"),
        ("name", "str", 65), ("description", "str", 129),
        ("rank", "int"), ("maxLv", "int"), ("expType", "int"),
        ("sortId", "int"), ("categoryEvolve", "int"),
        ("invokeType", "int"), ("invokeProb", "int"),
        ("invokeProbPerLv", "int"), ("invokeShowTiming", "int"),
        ("attackUp", "int"), ("burstCancel", "int"),
        ("burstLock", "int"),
        ("damageCut", "int"), ("dokonjo", "int"), ("counter", "int"),
        ("addAction", "int"), ("addPoison", "int"), ("addDeepPoison", "int"),
        ("addSleep", "int"), ("addParalysis", "int"),
        ("conditionTurn", "int"), ("conditionCount", "int"),
        ("prizeHpUp", "int"), ("prizeBurstUp", "int"),
        ("luxUp", "int"), ("moneyUp", "int"), ("raidUp", "int"),
    ]
    versions = {
        "1.0.1": _schema_101,
        "1.1.3": _schema_113,
    }


class SkillExp(MasterTable):
    """v1.0.1=v1.1.3: 16 bytes. Fields: expId, value[3]"""
    name = "skillExp"
    _schema = [("expId", "int"), ("value", "int[]", 3)]
    versions = {"1.0.1": _schema, "1.1.3": _schema}


class Sphere(MasterTable):
    """v1.0.1=v1.1.3: 184 bytes.
    Fields: sphereBoardId, boardName, kindId, boardId, arryId, masuId,
            type, openId, openParam, price, startDatetime, endDatetime"""
    name = "sphere"
    _schema = [
        ("sphereBoardId", "int"), ("boardName", "str", 129),
        ("kindId", "int"), ("boardId", "int"),
        ("arryId", "int"), ("masuId", "int"),
        ("type", "int"), ("openId", "int"),
        ("openParam", "int"), ("price", "int"),
        ("startDatetime", "date"), ("endDatetime", "date"),
    ]
    versions = {"1.0.1": _schema, "1.1.3": _schema}


class SphereArray(MasterTable):
    """v1.0.1=v1.1.3: 184 bytes.
    Fields: arryId, spCol4[9], spCol3[9], spCol2[9], spCol1[9], spCol0[9]"""
    name = "sphereArray"
    _schema = [
        ("arryId", "int"),
        ("spCol4", "int[]", 9), ("spCol3", "int[]", 9),
        ("spCol2", "int[]", 9), ("spCol1", "int[]", 9),
        ("spCol0", "int[]", 9),
    ]
    versions = {"1.0.1": _schema, "1.1.3": _schema}


class SphereMasu(MasterTable):
    """v1.0.1=v1.1.3: 652 bytes.
    Fields: masuId, sphereBoardId, spherePoint[23], rewardSelect[23],
            medalCategory[23], rewardId[23], rewardExpand[23],
            rewardExpandId[23], rewardValue[23]"""
    name = "sphereMasu"
    _schema = [
        ("masuId", "int"), ("sphereBoardId", "int"),
        ("spherePoint", "int[]", 23), ("rewardSelect", "int[]", 23),
        ("medalCategory", "int[]", 23), ("rewardId", "int[]", 23),
        ("rewardExpand", "int[]", 23), ("rewardExpandId", "int[]", 23),
        ("rewardValue", "int[]", 23),
    ]
    versions = {"1.0.1": _schema, "1.1.3": _schema}


class Stage(MasterTable):
    """v1.0.1: 1020 bytes. v1.1.3: 2080 bytes (+1060).
    Fields: stageId, id, name, mapName, useAp, chapterId, worldId, thumbId,
            stageKind, showIcon, validBeforeDrama, beforeDrama*[5],
            validAfterDrama, afterDrama*[5], clearGet*, submission*,
            raidBoss, bgmField, bgmBattle, bgmBoss"""
    name = "stage"
    _schema_101 = [
        ("stageId", "int"), ("id", "int"),
        ("name", "str", 129), ("mapName", "str", 129),
        ("useAp", "int"), ("chapterId", "int"), ("worldId", "int"),
        ("thumbId", "int"), ("stageKind", "int"), ("showIcon", "int"),
        ("validBeforeDrama", "int"),
        ("beforeDramaId", "int[]", 5), ("beforeDramaType", "int[]", 5),
        ("validAfterDrama", "int"),
        ("afterDramaId", "int[]", 5), ("afterDramaType", "int[]", 5),
        ("validClearGetTitle", "int"), ("clearGetTitle", "int"),
        ("validClearGetSphere", "int"), ("clearGetSphere", "int"),
        ("resetClearGet", "int"), ("validClearGetItem", "int"),
        ("clearGetItemType", "int[]", 3), ("clearGetItemId", "int[]", 3),
        ("clearGetAssignSkillType", "int[]", 3), ("clearGetAssignSkillId", "int[]", 3),
        ("clearGetAssignSkillLv", "int[]", 3), ("clearGetItemNum", "int[]", 3),
        ("resetSubMission", "int"), ("validSubmission", "int"),
        ("submissionRequire", "int[]", 3),
        ("submissionName", "str[]", 3, 129),
        ("submissionDataType", "int[]", 3), ("submissionIdType", "int[]", 3),
        ("submissionId", "int[]", 3), ("submissionNum", "int[]", 3),
        ("submissionRewardType", "int[]", 3), ("submissionItemId", "int[]", 3),
        ("submissionSkillType", "int[]", 3), ("submissionSkillId", "int[]", 3),
        ("submissionSkillLv", "int[]", 3), ("submissionItemNum", "int[]", 3),
        ("raidBoss", "int"), ("bgmField", "int"),
        ("bgmBattle", "int"), ("bgmBoss", "int"),
    ]
    _schema_113 = [
        ("stageId", "int"), ("id", "int"),
        ("stageBinId", "int"),
        ("name", "str", 129), ("mapName", "str", 129),
        ("useAp", "int"), ("chapterId", "int"), ("worldId", "int"),
        ("thumbId", "int"), ("stageKind", "int"), ("showIcon", "int"),
        ("validBeforeDrama", "int"),
        ("beforeDramaId", "int[]", 5), ("beforeDramaType", "int[]", 5),
        ("validAfterDrama", "int"),
        ("afterDramaId", "int[]", 5), ("afterDramaType", "int[]", 5),
        ("branchType", "int"), ("disableContinue", "int"),
        ("addLevel", "int"), ("holdKeyblade", "int"),
        ("hardmodeRequire", "int"), ("hardmodeName", "str", 1025),
        ("hardmodeComparison", "int"), ("hardmodeNum", "int"),
        ("validClearGetTitle", "int"), ("clearGetTitle", "int"),
        ("validClearGetSphere", "int"), ("clearGetSphere", "int"),
        ("resetClearGet", "int"), ("validClearGetItem", "int"),
        ("clearGetItemType", "int[]", 3), ("clearGetItemId", "int[]", 3),
        ("clearGetAssignSkillType", "int[]", 3), ("clearGetAssignSkillId", "int[]", 3),
        ("clearGetAssignSkillLv", "int[]", 3), ("clearGetItemNum", "int[]", 3),
        ("resetSubMission", "int"), ("validSubmission", "int"),
        ("submissionRequire", "int[]", 3),
        ("submissionName", "str[]", 3, 129),
        ("submissionDataType", "int[]", 3), ("submissionIdType", "int[]", 3),
        ("submissionId", "int[]", 3), ("submissionNum", "int[]", 3),
        ("submissionRewardType", "int[]", 3), ("submissionItemId", "int[]", 3),
        ("submissionSkillType", "int[]", 3), ("submissionSkillId", "int[]", 3),
        ("submissionSkillLv", "int[]", 3), ("submissionItemNum", "int[]", 3),
        ("raidBoss", "int"), ("bgmField", "int"),
        ("bgmBattle", "int"), ("bgmBoss", "int"),
    ]
    versions = {
        "1.0.1": _schema_101,
        "1.1.3": _schema_113,
    }


class Stamp(MasterTable):
    """v1.0.1=v1.1.3: 32 bytes.
    Fields: stampId, category, imageId, require, sortId,
            imageWidth, imageHeight, validStamp"""
    name = "stamp"
    _schema = [
        ("stampId", "int"), ("category", "int"), ("imageId", "int"),
        ("require", "int"), ("sortId", "int"),
        ("imageWidth", "int"), ("imageHeight", "int"), ("validStamp", "int"),
    ]
    versions = {"1.0.1": _schema, "1.1.3": _schema}


class Title(MasterTable):
    """v1.0.1=v1.1.3: 344 bytes.
    Fields: titleId, category, title, description, require, value, label"""
    name = "title"
    _schema = [
        ("titleId", "int"), ("category", "int"),
        ("title", "str", 65), ("description", "str", 257),
        ("require", "int"), ("value", "int"), ("label", "int"),
    ]
    versions = {"1.0.1": _schema, "1.1.3": _schema}


class TutorialMisc(MasterTable):
    """v1.0.1=v1.1.3: 32 bytes.
    Fields: tutorialId, startClearQuest, startMiscId, num1, num2,
            setClearQuest, setMiscId, valid"""
    name = "tutorialMisc"
    _schema = [
        ("tutorialId", "int"), ("startClearQuest", "int"),
        ("startMiscId", "int"), ("num1", "int"), ("num2", "int"),
        ("setClearQuest", "int"), ("setMiscId", "int"), ("valid", "int"),
    ]
    versions = {"1.0.1": _schema, "1.1.3": _schema}


class World(MasterTable):
    """v1.0.1 and v1.1.3: 948 bytes.
    partsId is str[129]x3 (master::World::parse strncpy's each element into a 129-byte slot and the
    game rejects the table if an element is not a JSON string); xPostion/yPostion are int[3]:
    4 + 4*129 + 4*4 + 3*129 (+1 align) + 3*4 + 3*4 = 948.
    Fields: worldId, worldName, raidBackground, instanceLwf, instance,
            xPos, yPos, rate, validParts, partsId, xPostion, yPostion"""
    name = "world"
    _schema = [
        ("worldId", "int"),
        ("worldName", "str", 129), ("raidBackground", "str", 129),
        ("instanceLwf", "str", 129), ("instance", "str", 129),
        ("xPos", "int"), ("yPos", "int"),
        ("rate", "int"), ("validParts", "int"),
        ("partsId", "str[]", 3, 129),
        ("xPostion", "int[]", 3), ("yPostion", "int[]", 3),
    ]
    versions = {"1.0.1": _schema, "1.1.3": _schema}


# ── Registry ─────────────────────────────────────────────────────────────────

ALL_TABLES: Dict[str, type] = {cls.name: cls for cls in MasterTable.__subclasses__()}
