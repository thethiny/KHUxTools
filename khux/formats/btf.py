import io
import struct
from io import BufferedReader
from typing import Optional

from PIL import Image

from khux.utils.compression import decompress
from khux.models.btf import BTFHeader


class KHUxBTF:
    @classmethod
    def from_file(cls, file_handle: BufferedReader) -> "KHUxBTF":
        obj = cls()
        obj.header = BTFHeader.from_file(file_handle)
        obj._file_handle = file_handle
        obj._data = None
        return obj

    @classmethod
    def from_bytes(cls, data: bytes) -> "KHUxBTF":
        obj = cls()
        obj.header = BTFHeader.from_bytes(data[:BTFHeader._struct.size])
        obj._data = data[BTFHeader._struct.size:]
        obj._file_handle = None
        return obj

    def decode(self, use_canvas: bool = False) -> Image.Image:
        h = self.header

        if h.image_format == BTFHeader.FORMAT_INDEXED:
            palette_size = self._read_u16()
        else:
            palette_size = 0

        compressed_size = self._read_u32()
        compressed_data = self._read_bytes(compressed_size)
        raw = decompress(compressed_data)

        img = self._decode_pixels(raw, h.image_width, h.image_height,
                                  h.image_format, palette_size)

        if use_canvas and (h.canvas_width != h.image_width or
                           h.canvas_height != h.image_height or
                           h.canvas_offset_x != 0 or h.canvas_offset_y != 0):
            canvas = Image.new("RGBA", (h.canvas_width, h.canvas_height))
            canvas.paste(img, (h.canvas_offset_x, h.canvas_offset_y))
            return canvas

        return img

    def _read_u16(self) -> int:
        if self._file_handle:
            return struct.unpack("<H", self._file_handle.read(2))[0]
        val = struct.unpack_from("<H", self._data, 0)[0]
        self._data = self._data[2:]
        return val

    def _read_u32(self) -> int:
        if self._file_handle:
            return struct.unpack("<I", self._file_handle.read(4))[0]
        val = struct.unpack_from("<I", self._data, 0)[0]
        self._data = self._data[4:]
        return val

    def _read_bytes(self, size: int) -> bytes:
        if self._file_handle:
            return self._file_handle.read(size)
        data = self._data[:size]
        self._data = self._data[size:]
        return data

    @staticmethod
    def _decode_pixels(raw: bytes, width: int, height: int,
                       image_format: int, palette_size: int = 0) -> Image.Image:
        if image_format == BTFHeader.FORMAT_RGBA:
            return Image.frombytes("RGBA", (width, height), raw)

        elif image_format == BTFHeader.FORMAT_INDEXED:
            if not palette_size:
                raise ValueError("Indexed image requires palette_size > 0")
            palette_bytes = raw[:palette_size * 4]
            pixel_data = raw[palette_size * 4:palette_size * 4 + width * height]

            img = Image.frombytes("P", (width, height), pixel_data)
            img.putpalette(palette_bytes, rawmode="RGBA")
            return img.convert("RGBA")

        else:
            raise ValueError(f"Unsupported BTF image format: {image_format:#x}")
