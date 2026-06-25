import struct
from dataclasses import dataclass, field
from typing import List, Optional


# =============================================================================
# Avatar Part Payload Structure (m000.jpg / "avatarParts" BGAD container)
# =============================================================================
#
# Each numbered BGAD entry in m000.jpg represents one avatar part definition
# from the master::AvatarParts table. The entry name is the avatarPartsId as
# a decimal string.
#
# --- Entry Data Layout (208 bytes total for the base version) ---
#
# Offset  Size  Field
# 0x00    4     seed (u32 LE) -- MSVC LCG seed used to XOR-encrypt the payload;
#                                also doubles as a creation timestamp
#                                (std::chrono::system_clock::now() at serialization time)
# 0x04    4     payload_size (u32 LE) -- byte length of the encrypted payload
#                                        (0xC8 = 200 for base avatar parts)
# 0x08    N     encrypted payload -- XOR'd with MSVC LCG keystream (see below)
#
# --- Payload Encryption ---
#
# The payload is XOR-encrypted using the MSVC linear congruential generator:
#
#     key[i] = ((214013 * (i + seed) + 2531011) >> 16) & 0xFF
#
# where seed is the u32 at offset 0x00 of the entry data, and i is the byte
# index within the payload (0-based). Constants 214013 (0x343FD) and 2531011
# (0x269EC3) are the standard MSVC LCG multiplier and increment.
#
# This same encryption scheme is used across ALL m*.jpg master data files
# (medals, skills, stages, etc.), not just avatar parts. It is implemented in
# the game binary at sub_3933B4, called from sub_39311C (the buffer allocator
# that generates the seed from system_clock::now and pre-fills the buffer with
# the keystream).
#
# --- Decrypted Struct Layout (200 bytes, confirmed from decompiled sub_6CF7C8) ---
#
# Offset  Size  Type       Field             Description
# 0x00    4     int32      avatarPartsId     Unique part ID (matches BGAD entry name)
# 0x04    129   char[129]  name              Part name, UTF-8, null-terminated
#                                            (strncpy with size 0x81; byte 128 forced to 0)
# 0x85    3     padding    (alignment)       Padding to 4-byte boundary
# 0x88    4     int32      partsType         Part category (see PARTS_TYPE_* below)
# 0x8C    4     int32      gender            1 = Male, 2 = Female
# 0x90    4     int32      combinationType   Combination group index
# 0x94    4     int32      combinationFlag   Combination flag (usually 0)
# 0x98    4     int32      position          Equip slot / body position (0-9)
# 0x9C    4     int32      luxCategory       Lux bonus category (0-6)
# 0xA0    4     int32      luxAddRate        Lux bonus rate (e.g. 1000 = base)
# 0xA4    4     int32      setKind           Set/outfit group identifier
# 0xA8    4     int32      fixedFlag         1 = default/fixed part, 0 = unlockable
# 0xAC    4     int32      validSetCloth     Number of valid entries in setCloth[] (0-5)
# 0xB0    20    int32[5]   setCloth          Related part IDs for the set outfit;
#                                            only the first validSetCloth entries are valid
# 0xC4    4     int32      status            1 = active/available, 0 = disabled/hidden
#                                            Total: 0xC8 = 200 bytes
#
# --- partsType Values ---
#
# The UI text files (102520001-102520007.txt) and decompiled code define:
#
PARTS_TYPE_CLOTHES = 2      # Costumes/outfits (IDs 1-282)
PARTS_TYPE_HAIRSTYLE = 3    # Hair styles (IDs 40001-41xxx)
PARTS_TYPE_EXPRESSION = 4   # Facial expressions (IDs 20001-20036)
PARTS_TYPE_SKIN_COLOR = 5   # Skin colors (IDs 30001-30012)
PARTS_TYPE_HAIR_COLOR = 6   # Hair colors (IDs 50001-51xxx)
PARTS_TYPE_ACCESSORY = 7    # Accessories -- hats, masks, etc. (IDs 101xxx-209xxx)

PARTS_TYPE_NAMES = {
    PARTS_TYPE_CLOTHES: "Clothes",
    PARTS_TYPE_HAIRSTYLE: "Hairstyle",
    PARTS_TYPE_EXPRESSION: "Expression",
    PARTS_TYPE_SKIN_COLOR: "Skin Color",
    PARTS_TYPE_HAIR_COLOR: "Hair Color",
    PARTS_TYPE_ACCESSORY: "Accessory",
}
#
# --- gender Values ---
#
GENDER_MALE = 1
GENDER_FEMALE = 2
#
# --- position Values ---
#
# The position field determines which equip slot the part occupies.
# From the MyCoordinate struct in the decompiled code:
#   0 = body/costume (main outfit slot)
#   1 = accessory slot varies by sub-type
#   2-9 = additional accessory/detail slots
# The extended MyCoordinate struct names specific accessory positions:
#   mask, hat, ear, face, necklace, leg, backpack, body, tail, special, mouth
#
# --- Related Structs (from decompiled code, for reference) ---
#
# hole::network::api::UserAvatarParts (per-user ownership, 24 bytes):
#   0x00  int64  userAvatarPartsId   Unique user ownership record ID
#   0x08  int32  partsType           Same category as master data
#   0x0C  int32  avatarPartsId       References master::AvatarParts.avatarPartsId
#   0x10  int64  getDatetime         Acquisition timestamp
#
# MyCoordinate (equipped outfit configuration, 48 bytes):
#   0x00  int32  myCoordinateNo      Outfit slot number
#   0x04  int32  gender
#   0x08  int32  hairPartsId
#   0x0C  int32  hairColorPartsId
#   0x10  int32  facePartsId
#   0x14  int32  bodyPartsId
#   0x18  int32  skinPartsId
#   0x1C  int32[5]  accessoriesPartsIds  (up to 5 accessory slots)
#
# Extended MyCoordinate (detailed accessory slots, 48 bytes):
#   [0] myCoordinateNo, [1] accessoryMask, [2] accessoryHat,
#   [3] earPartsId, [4] facePartsId, [5] accessoryNecklace,
#   [6] legPartsId, [7] accessoryBackpack, [8] bodyPartsId,
#   [9] tailPartsId, [10] accessorySpecial, [11] accessoryMouth
#
# --- Notes ---
#
# - Avatar part sprite images are loaded from "img/avatarParts/%sai%03d.png"
#   and "img/avatarParts/%sai%d.png" (from libcocos2dcpp_0005.c).
# - The setCloth array links related parts that form a complete outfit.
#   Only the first validSetCloth entries contain valid part IDs.
# - Parts with fixedFlag=1 are default parts available to all players.
# - Parts with status=0 are disabled/hidden from the game.
# - Expression and skin/hair color parts often have blank names (" ").
# =============================================================================


# MSVC LCG constants used for master data payload encryption
_MSVC_LCG_MULTIPLIER = 214013    # 0x343FD
_MSVC_LCG_INCREMENT = 2531011    # 0x269EC3

# Struct size for the base avatar parts definition
_AVATAR_STRUCT_SIZE = 200  # 0xC8


def _msvc_lcg_keystream(seed: int, length: int) -> bytes:
    """Generate the MSVC LCG XOR keystream used to decrypt master data payloads.

    Each byte of the keystream is:
        key[i] = ((214013 * (i + seed) + 2531011) >> 16) & 0xFF

    This matches the game's sub_3933B4 encryption routine.
    """
    key = bytearray(length)
    for i in range(length):
        val = (_MSVC_LCG_MULTIPLIER * (i + seed) + _MSVC_LCG_INCREMENT) & 0xFFFFFFFF
        key[i] = (val >> 16) & 0xFF
    return bytes(key)


def decrypt_master_data_payload(data: bytes) -> tuple:
    """Decrypt a master data entry's payload.

    Args:
        data: The raw entry data (seed + size + encrypted payload).

    Returns:
        Tuple of (seed, payload_size, decrypted_bytes).
    """
    if len(data) < 8:
        raise ValueError(f"Entry data too short ({len(data)} bytes, need at least 8)")
    seed = struct.unpack_from("<I", data, 0)[0]
    payload_size = struct.unpack_from("<I", data, 4)[0]
    encrypted = data[8:]
    key = _msvc_lcg_keystream(seed, len(encrypted))
    decrypted = bytes(a ^ b for a, b in zip(encrypted, key))
    return seed, payload_size, decrypted


@dataclass
class AvatarPartEntry:
    id: int
    timestamp: int
    payload_size: int
    payload: bytes


@dataclass
class AvatarPartDecrypted:
    """Fully decoded avatar part definition from master data."""
    avatar_parts_id: int
    name: str
    parts_type: int
    gender: int
    combination_type: int
    combination_flag: int
    position: int
    lux_category: int
    lux_add_rate: int
    set_kind: int
    fixed_flag: int
    valid_set_cloth: int
    set_cloth: List[int] = field(default_factory=list)
    status: int = 0

    @property
    def parts_type_name(self) -> str:
        return PARTS_TYPE_NAMES.get(self.parts_type, f"Unknown({self.parts_type})")

    @property
    def is_male(self) -> bool:
        return self.gender == GENDER_MALE

    @property
    def is_female(self) -> bool:
        return self.gender == GENDER_FEMALE

    @property
    def is_active(self) -> bool:
        return self.status == 1

    @property
    def is_fixed(self) -> bool:
        return self.fixed_flag == 1

    @classmethod
    def from_decrypted(cls, decrypted: bytes) -> "AvatarPartDecrypted":
        """Parse a decrypted 200-byte avatar part struct."""
        if len(decrypted) < _AVATAR_STRUCT_SIZE:
            raise ValueError(
                f"Decrypted data too short ({len(decrypted)} bytes, "
                f"need {_AVATAR_STRUCT_SIZE})"
            )

        avatar_parts_id = struct.unpack_from("<i", decrypted, 0x00)[0]

        name_raw = decrypted[0x04:0x04 + 129]
        null_idx = name_raw.find(b'\x00')
        if null_idx >= 0:
            name_raw = name_raw[:null_idx]
        try:
            name = name_raw.decode('utf-8')
        except UnicodeDecodeError:
            name = name_raw.decode('shift-jis', errors='replace')

        parts_type = struct.unpack_from("<i", decrypted, 0x88)[0]
        gender = struct.unpack_from("<i", decrypted, 0x8C)[0]
        combination_type = struct.unpack_from("<i", decrypted, 0x90)[0]
        combination_flag = struct.unpack_from("<i", decrypted, 0x94)[0]
        position = struct.unpack_from("<i", decrypted, 0x98)[0]
        lux_category = struct.unpack_from("<i", decrypted, 0x9C)[0]
        lux_add_rate = struct.unpack_from("<i", decrypted, 0xA0)[0]
        set_kind = struct.unpack_from("<i", decrypted, 0xA4)[0]
        fixed_flag = struct.unpack_from("<i", decrypted, 0xA8)[0]
        valid_set_cloth = struct.unpack_from("<i", decrypted, 0xAC)[0]
        set_cloth_raw = list(struct.unpack_from("<5i", decrypted, 0xB0))
        set_cloth = set_cloth_raw[:max(0, min(valid_set_cloth, 5))]
        status = struct.unpack_from("<i", decrypted, 0xC4)[0]

        return cls(
            avatar_parts_id=avatar_parts_id,
            name=name,
            parts_type=parts_type,
            gender=gender,
            combination_type=combination_type,
            combination_flag=combination_flag,
            position=position,
            lux_category=lux_category,
            lux_add_rate=lux_add_rate,
            set_kind=set_kind,
            fixed_flag=fixed_flag,
            valid_set_cloth=valid_set_cloth,
            set_cloth=set_cloth,
            status=status,
        )


@dataclass
class AvatarData:
    total_count: int
    hash: str
    parts: List[AvatarPartEntry]


class KHUxAvatar:
    @staticmethod
    def from_bgad_entries(entries: list) -> AvatarData:
        total_count = 0
        hash_str = ""
        parts: List[AvatarPartEntry] = []

        for entry in entries:
            if entry.name == "avatarParts" and len(entry.data) >= 4:
                total_count = struct.unpack_from("<I", entry.data, 0)[0]
            elif entry.name == "hash":
                hash_str = entry.data.decode("ascii", errors="replace")
            elif entry.name.isdigit():
                part_id = int(entry.name)
                if len(entry.data) >= 8:
                    ts = struct.unpack_from("<I", entry.data, 0)[0]
                    payload_size = struct.unpack_from("<I", entry.data, 4)[0]
                    payload = entry.data[8:]
                else:
                    ts = 0
                    payload_size = 0
                    payload = entry.data
                parts.append(AvatarPartEntry(
                    id=part_id, timestamp=ts,
                    payload_size=payload_size, payload=payload
                ))

        return AvatarData(total_count=total_count, hash=hash_str, parts=parts)

    @staticmethod
    def decrypt_part(entry_data: bytes) -> AvatarPartDecrypted:
        """Decrypt and parse a single avatar part entry's data.

        Args:
            entry_data: The full raw data of a numbered BGAD entry
                        (8-byte header + encrypted payload).

        Returns:
            Fully decoded AvatarPartDecrypted instance.
        """
        _, _, decrypted = decrypt_master_data_payload(entry_data)
        return AvatarPartDecrypted.from_decrypted(decrypted)

    @staticmethod
    def decrypt_all(entries: list) -> List[AvatarPartDecrypted]:
        """Decrypt and parse all numbered avatar part entries.

        Args:
            entries: List of BGADEntry objects from KHUxBGADContainer.iter_entries().

        Returns:
            List of decoded AvatarPartDecrypted instances.
        """
        results = []
        for entry in entries:
            if entry.name.isdigit() and len(entry.data) >= 8:
                try:
                    part = KHUxAvatar.decrypt_part(entry.data)
                    results.append(part)
                except (struct.error, ValueError):
                    pass
        return results
