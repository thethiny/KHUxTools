import os
import struct
from dataclasses import dataclass
from io import BufferedReader
from typing import List, Optional, Union

from khux.utils.compression import decompress
from khux.utils.crypto import khux_decrypt, chacha8_crypt, BGAD_NONCE_XOR, KEY_APK, KEY_DOWNLOAD, KEY_SAVE
from khux.utils.common import KHUxFile
from khux.models.bgad import BGADHeader
from khux.detect import MAGIC_TABLE


_ALL_KEYS = [KEY_APK, KEY_DOWNLOAD, KEY_SAVE]


def _guess_key_from_filename(filename: str) -> Optional[bytes]:
    base = os.path.basename(filename).lower()
    if base.startswith("misc."):
        return KEY_APK
    if base.startswith("extra.") or base.startswith("aliud."):
        return KEY_DOWNLOAD
    if base.endswith(".gif"):
        return None
    if base.endswith(".jpg"):
        return None
    if base.endswith(".mp4") or base.endswith(".png"):
        return KEY_DOWNLOAD
    return None


def _validate_entry_data(data: bytes) -> bool:
    if len(data) < 4:
        return len(data) > 0
    magic = data[:4]
    if magic in MAGIC_TABLE:
        return True
    if magic[:3] == b"\xEF\xBB\xBF" or magic[:1] == b"<":
        return True
    if magic[:1] in (b"[", b"{"):
        return True
    return False


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
        nonce = bytes(a ^ b for a, b in zip(raw_nonce, BGAD_NONCE_XOR))
        decrypted = chacha8_crypt(name_bytes, self.encryption_key, nonce)
        try:
            return decrypted.decode("utf-8").rstrip("\x00")
        except UnicodeDecodeError:
            return decrypted.hex()

    def _decrypt_data_mode3(self, encrypted_data: bytes, raw_nonce: bytes) -> bytes:
        if self.encryption_key is None:
            return encrypted_data
        nonce = bytes(a ^ b for a, b in zip(raw_nonce, BGAD_NONCE_XOR))
        return chacha8_crypt(encrypted_data, self.encryption_key, nonce)

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
        self._resolved_key = encryption_key

    def _needs_mode3_key(self) -> bool:
        pos = self.file_handle.tell()
        try:
            hdr_bytes = self.file_handle.read(BGADHeader._struct.size)
            if len(hdr_bytes) < BGADHeader._struct.size:
                return False
            hdr = BGADHeader.from_bytes(hdr_bytes)
            return hdr.encryption_mode == 3
        except (ValueError, struct.error):
            return False
        finally:
            self.file_handle.seek(pos)

    def _try_key(self, key: bytes) -> bool:
        pos = self.file_handle.tell()
        try:
            bgad = KHUxBGAD(self.file_handle, self.file_name, encryption_key=key)
            entry = bgad.read_entry()
            if _validate_entry_data(entry.data):
                return True
            # Small entries (index values) won't match any magic.
            # If we got here without exceptions, decompression (if any) succeeded
            # and the entry parsed cleanly — the key is likely correct.
            if len(entry.data) <= 4:
                return True
            return False
        except (IOError, struct.error, ValueError):
            return False
        finally:
            self.file_handle.seek(pos)

    def _resolve_key(self) -> Optional[bytes]:
        if self.encryption_key is not None:
            return self.encryption_key

        if not self._needs_mode3_key():
            return None

        guessed = _guess_key_from_filename(self.file_name)
        if guessed and self._try_key(guessed):
            return guessed

        for key in _ALL_KEYS:
            if key == guessed:
                continue
            if self._try_key(key):
                return key

        return None

    def iter_entries(self) -> List[BGADEntry]:
        if self._resolved_key is None and self.encryption_key is None:
            self._resolved_key = self._resolve_key()

        key = self._resolved_key or self.encryption_key
        entries = []
        while True:
            try:
                bgad = KHUxBGAD(self.file_handle, self.file_name,
                                encryption_key=key)
                entry = bgad.read_entry()
                entries.append(entry)
            except (IOError, struct.error, ValueError):
                break
        return entries

    def extract(self, extract_dir: str) -> List[BGADEntry]:
        if self._resolved_key is None and self.encryption_key is None:
            self._resolved_key = self._resolve_key()

        key = self._resolved_key or self.encryption_key
        os.makedirs(extract_dir, exist_ok=True)
        entries = []
        while True:
            try:
                bgad = KHUxBGAD(self.file_handle, self.file_name,
                                encryption_key=key)
                entry = bgad.extract(extract_dir)
                entries.append(entry)
            except (IOError, struct.error, ValueError):
                break
        return entries
