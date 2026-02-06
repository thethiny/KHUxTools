import os
import struct
from dataclasses import dataclass
from io import BufferedReader
from typing import Union


from src.compression import decompress
from src.utils.common import KHUxFile
from src.utils import khux_decrypt

@dataclass
class BGADHeader:
    magic: bytes # 4
    encryption_mode: int # 2
    unk: int # 2
    header_size: int # 2
    name_length: int # 2
    data_type: int # 2
    compression_flag: int # 2
    data_size: int # 4
    decompressed_size: int # 4

    _fmt = "<4sHHHHHHII"
    _struct = struct.Struct(_fmt)
    _magic = b"BGAD"

    @classmethod
    def from_bytes(cls, data: bytes) -> "BGADHeader":
        unpacked = cls._struct.unpack(data)
        obj = cls(*unpacked)
        assert hasattr(obj, "magic") and obj.magic == cls._magic, f"Invalid BGAD magic: {obj.magic} | expected: {cls._magic}"
        return obj

    @classmethod
    def from_file(cls, file: BufferedReader) -> "BGADHeader":
        data = file.read(cls._struct.size)
        return cls.from_bytes(data)
    

class KHUxBGAD(KHUxFile):
    def __init__(self, file_path: Union[str, BufferedReader], file_name: str = "") -> None:
        super().__init__(file_path, file_name)
        
        self.header = BGADHeader.from_file(self.file_handle)
        self.name = ""

    def extract(self, extract_dir: str) -> None:
        name_bytes = self.file_handle.read(self.header.name_length)
        name = khux_decrypt(name_bytes, self.header.data_size, self.header.encryption_mode)
        self.name = name.decode("utf-8").rstrip("\x00")

        print(f"Detected BGAD {self.name}")

        data = self.file_handle.read(self.header.data_size)
        data = khux_decrypt(data, self.header.name_length, self.header.encryption_mode)
        if self.header.compression_flag != 0:
            data = decompress(data)
            
        file_dir, file_base = os.path.split(self.name)
        if file_dir == "/":
            file_base = "@root"
            file_dir = ""
        elif not file_base:
            file_base = f"@{os.path.basename(file_dir)}"  # Use directory name as base
        file_dir = file_dir.rstrip("/")  # prevent file from overriding joint directories
        
        file_out_dir = os.path.join(extract_dir, "bgad", self.file_name, file_dir)
        os.makedirs(file_out_dir, exist_ok=True)

        with open(os.path.join(file_out_dir, file_base), "wb") as out_file:
            out_file.write(data)
            
class KHUxBGADContainer(KHUxFile):
    def __init__(self, file_path: Union[str, BufferedReader], file_name: str = "") -> None:
        super().__init__(file_path, file_name)
        
    def extract(self, extract_dir: str) -> list:
        os.makedirs(extract_dir, exist_ok=True)
        
        bgads = []
        while True:
            try:
                loc = self.file_handle.tell()
                bgad = KHUxBGAD(self.file_handle, self.file_name)
                bgad.extract(extract_dir)
                bgads.append({
                    "offset": loc,
                    "name": bgad.name
                })
            except (IOError, struct.error):
                break

        return bgads