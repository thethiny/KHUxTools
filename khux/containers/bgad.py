import os
import struct
from dataclasses import dataclass
from io import BufferedReader
from typing import List, Optional, Union

from khux.utils.compression import decompress
from khux.utils.crypto import khux_decrypt
from khux.utils.common import KHUxFile
from khux.models.bgad import BGADHeader


@dataclass
class BGADEntry:
    offset: int
    name: str
    data: bytes
    header: BGADHeader


class KHUxBGAD(KHUxFile):
    def __init__(self, file_path: Union[str, BufferedReader], file_name: str = "",
                 encryption_key: Optional[bytes] = None) -> None:
        super().__init__(file_path, file_name)
        self.encryption_key = encryption_key
        self.header = BGADHeader.from_file(self.file_handle)
        self.name = ""

    def read_entry(self) -> BGADEntry:
        offset = self.file_handle.tell() - self.header._struct.size

        name_bytes = self.file_handle.read(self.header.name_length)

        if self.header.encryption_mode == 3:
            data_plus_nonce = self.file_handle.read(self.header.data_size)
            raw_nonce = data_plus_nonce[-8:] if self.header.has_nonce else b"\x00" * 8
            encrypted_data = data_plus_nonce[:-8] if self.header.has_nonce else data_plus_nonce
            name = self._decrypt_name_mode3(name_bytes, raw_nonce)
            data = self._decrypt_data_mode3(encrypted_data, raw_nonce)
        else:
            name = self._decrypt_name(name_bytes)
            raw_data = self.file_handle.read(self.header.data_size)
            data = khux_decrypt(raw_data, self.header.name_length,
                                self.header.encryption_mode)

        if self.header.compression_mode != 0:
            data = decompress(data)

        self.name = name
        return BGADEntry(offset=offset, name=name, data=data, header=self.header)

    def _decrypt_name(self, name_bytes: bytes) -> str:
        if self.header.encryption_mode == 0:
            decrypted = name_bytes
        else:
            decrypted = khux_decrypt(name_bytes, self.header.data_size,
                                     self.header.encryption_mode)
        try:
            return decrypted.decode("utf-8").rstrip("\x00")
        except UnicodeDecodeError:
            return decrypted.hex()

    def _decrypt_name_mode3(self, name_bytes: bytes, raw_nonce: bytes) -> str:
        if self.encryption_key is None:
            return f"<encrypted:{name_bytes.hex()}>"
        from khux.utils.crypto import _chacha20_crypt, BGAD_NONCE_XOR
        nonce = bytes(a ^ b for a, b in zip(raw_nonce, BGAD_NONCE_XOR))
        decrypted = _chacha20_crypt(name_bytes, self.encryption_key, nonce)
        try:
            return decrypted.decode("utf-8").rstrip("\x00")
        except UnicodeDecodeError:
            return f"<encrypted:{name_bytes.hex()}>"

    def _decrypt_data_mode3(self, encrypted_data: bytes, raw_nonce: bytes) -> bytes:
        if self.encryption_key is None:
            return encrypted_data
        from khux.utils.crypto import _chacha20_crypt, BGAD_NONCE_XOR
        nonce = bytes(a ^ b for a, b in zip(raw_nonce, BGAD_NONCE_XOR))
        return _chacha20_crypt(encrypted_data, self.encryption_key, nonce)

    def extract(self, extract_dir: str) -> BGADEntry:
        entry = self.read_entry()

        file_dir, file_base = os.path.split(entry.name)
        if file_dir == "/":
            file_base = "@root"
            file_dir = ""
        elif not file_base:
            file_base = f"@{os.path.basename(file_dir)}"
        file_dir = file_dir.rstrip("/")

        file_out_dir = os.path.join(extract_dir, "bgad", self.file_name, file_dir)
        os.makedirs(file_out_dir, exist_ok=True)

        with open(os.path.join(file_out_dir, file_base), "wb") as out_file:
            out_file.write(entry.data)

        return entry


class KHUxBGADContainer(KHUxFile):
    def __init__(self, file_path: Union[str, BufferedReader], file_name: str = "",
                 encryption_key: Optional[bytes] = None) -> None:
        super().__init__(file_path, file_name)
        self.encryption_key = encryption_key

    def iter_entries(self) -> List[BGADEntry]:
        entries = []
        while True:
            try:
                bgad = KHUxBGAD(self.file_handle, self.file_name,
                                encryption_key=self.encryption_key)
                entry = bgad.read_entry()
                entries.append(entry)
            except (IOError, struct.error, ValueError):
                break
        return entries

    def extract(self, extract_dir: str) -> List[BGADEntry]:
        os.makedirs(extract_dir, exist_ok=True)
        entries = []
        while True:
            try:
                bgad = KHUxBGAD(self.file_handle, self.file_name,
                                encryption_key=self.encryption_key)
                entry = bgad.extract(extract_dir)
                entries.append(entry)
            except (IOError, struct.error, ValueError):
                break
        return entries
