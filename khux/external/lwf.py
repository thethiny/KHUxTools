from dataclasses import dataclass
from io import BufferedReader
from typing import Union

from khux.models.lwf import LWFHeader
from khux.utils.common import KHUxFile


@dataclass
class LWFData:
    header: LWFHeader
    raw_data: bytes


class KHUxLWF(KHUxFile):
    def __init__(self, file_path: Union[str, BufferedReader], file_name: str = "") -> None:
        super().__init__(file_path, file_name)
        self.header = LWFHeader.from_file(self.file_handle)

    def parse(self) -> LWFData:
        remaining = self.file_handle.read()
        full_data = (
            self.header._struct.pack(
                self.header.magic, self.header.version,
                self.header.data_size, self.header.total_size
            ) + remaining
        )
        return LWFData(header=self.header, raw_data=full_data)

    @classmethod
    def from_bytes(cls, data: bytes) -> LWFData:
        header = LWFHeader.from_bytes(data[:LWFHeader._struct.size])
        return LWFData(header=header, raw_data=data)
