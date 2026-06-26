import struct
from dataclasses import dataclass
from io import BufferedReader
from typing import Dict, List, Optional, Union

from khux.models.bgi import BGIHeader, BGIEntry, BGINameEntry
from khux.utils.common import KHUxFile
from khux.utils.crypto import chacha8_crypt, BGI_NONCE_XOR, KEY_APK


def _derive_bgi_nonce(last8: bytes) -> bytes:
    if len(last8) != 8:
        raise ValueError(f"Expected 8 bytes for nonce derivation, got {len(last8)}")
    return bytes(b ^ m for b, m in zip(last8, BGI_NONCE_XOR))


def _xxh32(data: bytes, seed: int = 0) -> int:
    P1 = 0x9E3779B1
    P2 = 0x85EBCA77
    P3 = 0xC2B2AE3D
    P4 = 0x27D4EB2F
    P5 = 0x165667B1
    M = 0xFFFFFFFF

    def rotl(x, r):
        return ((x << r) | (x >> (32 - r))) & M

    n = len(data)
    p = 0
    seed &= M

    if n >= 16:
        v1 = (seed + P1 + P2) & M
        v2 = (seed + P2) & M
        v3 = seed
        v4 = (seed - P1) & M
        while p + 16 <= n:
            d1 = struct.unpack_from("<I", data, p)[0]
            d2 = struct.unpack_from("<I", data, p + 4)[0]
            d3 = struct.unpack_from("<I", data, p + 8)[0]
            d4 = struct.unpack_from("<I", data, p + 12)[0]
            v1 = (rotl((v1 + d1 * P2) & M, 13) * P1) & M
            v2 = (rotl((v2 + d2 * P2) & M, 13) * P1) & M
            v3 = (rotl((v3 + d3 * P2) & M, 13) * P1) & M
            v4 = (rotl((v4 + d4 * P2) & M, 13) * P1) & M
            p += 16
        h = (rotl(v1, 1) + rotl(v2, 7) + rotl(v3, 12) + rotl(v4, 18)) & M
    else:
        h = (seed + P5) & M

    h = (h + n) & M

    while p + 4 <= n:
        k = struct.unpack_from("<I", data, p)[0]
        h = (rotl((h + k * P3) & M, 17) * P4) & M
        p += 4

    while p < n:
        h = (rotl((h + data[p] * P5) & M, 11) * P1) & M
        p += 1

    h ^= h >> 15
    h = (h * P2) & M
    h ^= h >> 13
    h = (h * P3) & M
    h ^= h >> 16
    return h & M


@dataclass
class BGIArchive:
    header: BGIHeader
    entries: List[BGIEntry]
    names: List[BGINameEntry]
    name_map: Dict[str, int]
    data_blob: bytes

    def lookup(self, name: str) -> Optional[BGIEntry]:
        idx = self.name_map.get(name)
        if idx is None:
            return None
        if idx >= len(self.entries):
            return None
        return self.entries[idx]

    def list_files(self) -> List[str]:
        return [ne.name for ne in self.names]

    def read_file(self, name: str) -> Optional[bytes]:
        entry = self.lookup(name)
        if entry is None:
            return None
        lo = entry.offset
        hi = lo + entry.size
        if hi > len(self.data_blob):
            return None
        return self.data_blob[lo:hi]


class KHUxBGI(KHUxFile):
    VERSION_EXPECTED = 3

    def __init__(self, file_path: Union[str, BufferedReader], file_name: str = "",
                 key: Optional[bytes] = None) -> None:
        super().__init__(file_path, file_name)
        self.key = key or KEY_APK
        self.header = BGIHeader.from_file(self.file_handle)

    def parse(self) -> BGIArchive:
        if self.header.version != self.VERSION_EXPECTED:
            raise ValueError(
                f"Unsupported BGI version: {self.header.version} (expected {self.VERSION_EXPECTED})"
            )

        if self.header.encrypted:
            data = self._decrypt_payload()
        elif self.header.flags != 0:
            raise ValueError(f"Unsupported BGI flags: {self.header.flags}")
        else:
            data = self.file_handle.read()

        return self._parse_tables(data)

    def _decrypt_payload(self) -> bytes:
        pos = self.file_handle.tell()
        self.file_handle.seek(-8, 2)
        end_pos = self.file_handle.tell()
        data_size = end_pos - pos
        last8 = self.file_handle.read(8)
        self.file_handle.seek(pos)

        nonce = _derive_bgi_nonce(last8)
        encrypted = self.file_handle.read(data_size)
        return chacha8_crypt(encrypted, self.key, nonce)

    def _parse_tables(self, data: bytes) -> BGIArchive:
        if len(data) < 8:
            raise ValueError("BGI data too small for entry/name counts")

        entry_count = struct.unpack_from("<I", data, 0)[0]
        name_count = struct.unpack_from("<I", data, 4)[0]

        min_size = 8 + entry_count * 8 + name_count * 4 + name_count * 4
        if len(data) < min_size:
            raise ValueError(
                f"BGI data too small: need {min_size} bytes, have {len(data)}"
            )

        off = 8
        entries: List[BGIEntry] = []
        for _ in range(entry_count):
            a = struct.unpack_from("<I", data, off)[0]
            b = struct.unpack_from("<I", data, off + 4)[0]
            entries.append(BGIEntry(offset=a, size=b))
            off += 8

        name_to_entry: List[int] = []
        for _ in range(name_count):
            name_to_entry.append(struct.unpack_from("<I", data, off)[0])
            off += 4

        name_offsets: List[int] = []
        for _ in range(name_count):
            name_offsets.append(struct.unpack_from("<I", data, off)[0])
            off += 4

        string_blob_start = off

        names: List[BGINameEntry] = []
        name_map: Dict[str, int] = {}
        for i in range(name_count):
            str_off = string_blob_start + name_offsets[i]
            if str_off >= len(data):
                continue
            end = data.index(0, str_off) if 0 in data[str_off:] else len(data)
            name = data[str_off:end].decode("utf-8", errors="replace")
            idx = name_to_entry[i]
            names.append(BGINameEntry(name=name, entry_index=idx))
            name_map[name] = idx

        data_blob = bytes(data[string_blob_start:])

        return BGIArchive(
            header=self.header,
            entries=entries,
            names=names,
            name_map=name_map,
            data_blob=data_blob,
        )
