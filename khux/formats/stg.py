from dataclasses import dataclass
from io import BufferedReader
import struct
from typing import List, Union

from khux.models.stg import STGHeader
from khux.utils.common import KHUxFile


@dataclass
class STGEntry:
    name: str
    data: bytes


@dataclass
class STGData:
    header: STGHeader
    raw_data: bytes
    entries: List[STGEntry]


class KHUxSTG(KHUxFile):
    def __init__(self, file_path: Union[str, BufferedReader], file_name: str = "") -> None:
        super().__init__(file_path, file_name)
        self.header = STGHeader.from_file(self.file_handle)

    def parse(self) -> STGData:
        remaining = self.file_handle.read()
        full_data = (
            self.header._struct.pack(
                self.header.magic, self.header.version,
                self.header.count, self.header.data_offset
            ) + remaining
        )
        entries = self._parse_entries(full_data)
        return STGData(header=self.header, raw_data=full_data, entries=entries)

    def _parse_entries(self, data: bytes) -> List[STGEntry]:
        entries = []
        off = STGHeader._struct.size
        for i in range(self.header.count):
            if off + 4 > len(data):
                break
            name_len = struct.unpack_from("<I", data, off)[0]
            off += 4
            if off + name_len > len(data):
                break
            name = data[off:off + name_len].decode("utf-8", errors="replace").rstrip("\x00")
            off += name_len
            if off + 4 > len(data):
                entries.append(STGEntry(name=name, data=b""))
                break
            entry_size = struct.unpack_from("<I", data, off)[0]
            off += 4
            entry_data = data[off:off + entry_size]
            off += entry_size
            entries.append(STGEntry(name=name, data=entry_data))
        return entries

    @classmethod
    def from_bytes(cls, data: bytes) -> STGData:
        header = STGHeader.from_bytes(data[:STGHeader._struct.size])
        obj = cls.__new__(cls)
        obj.header = header
        obj.file_handle = None
        entries = obj._parse_entries(data)
        return STGData(header=header, raw_data=data, entries=entries)
