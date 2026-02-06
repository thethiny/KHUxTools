from io import BufferedReader
import os
import struct
from typing import Optional

from PIL import Image

from src.compression import decompress
from src.utils.common import KHUxFile

class KHUxBTF:
    @classmethod
    def process(cls, file_handle: BufferedReader, canvas: bool = False):
        f = file_handle

        skip_2_bytes = f.read(2)
        unknown_1 = struct.unpack("<I", f.read(4))[0]
        unknown_2 = struct.unpack("<I", f.read(4))[0]
        image_format = struct.unpack("<I", f.read(4))[0]
        unknown_4 = struct.unpack("<I", f.read(4))[0]

        canvas_width = struct.unpack("<H", f.read(2))[0]
        canvas_height = struct.unpack("<H", f.read(2))[0]
        canvas_offset_x = struct.unpack("<H", f.read(2))[0]
        canvas_offset_y = struct.unpack("<H", f.read(2))[0]
        image_width = struct.unpack("<H", f.read(2))[0]
        image_height = struct.unpack("<H", f.read(2))[0]

        if image_format == 0x090000: # 9 is Indexed Image
            image_palette_size = struct.unpack("<H", f.read(2))[0]
        elif image_format == 0x080000: # 8 is RGBA
            image_palette_size = 0
        else:
            raise NotImplementedError(f"Unsupported BTF image format: {hex(image_format)}")

        compressed_size = struct.unpack("<I", f.read(4))[0]
        data = f.read(compressed_size)
        decompressed_data = decompress(data)

        canvas_info = (canvas_width, canvas_height, canvas_offset_x, canvas_offset_y) if canvas else None
        img = cls.btf_image_to_png(decompressed_data, image_width, image_height, image_format, canvas_info, palette_size=image_palette_size)

        return img

    @classmethod
    def btf_image_to_png(cls, raw_bytes: bytes, width: int, height: int, image_format: int, canvas: Optional[tuple] = None, **image_format_config):
        if image_format == 0x080000:
            img = Image.frombytes(mode="RGBA", size=(width, height), data=raw_bytes)
        elif image_format == 0x090000:
            palette_size = image_format_config.get("palette_size", 0)
            if not palette_size:
                raise ValueError("Invalid palette size!")

            palette = raw_bytes[:palette_size * 4] # RGBA
            pixel_indices = raw_bytes[palette_size * 4 : palette_size * 4 + width * height]

            img_p = Image.frombytes(mode="P", size=(width, height), data=pixel_indices)
            img_p.putpalette(palette, rawmode="RGBA")
            img = img_p.convert("RGBA")
        
        if canvas:
            canvas_width, canvas_height, canvas_offset_x, canvas_offset_y = canvas
            img_with_canvas = Image.new("RGBA", (canvas_width, canvas_height))
            img_with_canvas.paste(img, (canvas_offset_x, canvas_offset_y))
            return img_with_canvas
        return img


class KHUxPNG(KHUxFile):
    def __init__(self, file_path: str, file_name: str = "") -> None:
        super().__init__(file_path, file_name)
        self.file_type = self.detect_file_type()

    def detect_file_type(self):
        magic = self.file_handle.read(4)
        if magic == b"\x89BTF":
            file_type = "BTF"
        elif magic == b"LWF\0":
            file_type = "LWF"
        else:
            raise ValueError("Unknown file type")

        return file_type

    def extract(self, extract_dir: str):
        if self.file_type == "BTF":
            canvas = False
            img = KHUxBTF.process(self.file_handle, canvas)

            file_out_dir = os.path.join(extract_dir, "png")
            os.makedirs(file_out_dir, exist_ok=True)

            file_out_name = f"{self.file_name}_canvas.png" if canvas else f"{self.file_name}.png"
            img.save(os.path.join(file_out_dir, file_out_name), format="PNG")

        else:
            raise NotImplementedError(f"Unsupported file type: {self.file_type}")
