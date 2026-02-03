from io import BufferedReader
import os
import struct

from PIL import Image

from src.compression import decompress
from src.utils.common import FileClass

class KHUxBTF:
    def __init__(self, file_handle: BufferedReader, file_name: str) -> None:
        self.file_handle = file_handle
        self.file_name = file_name

    def process(self, extract_dir: str, canvas: bool = False):
        f = self.file_handle

        skip_2_bytes = self.file_handle.read(2)
        unknown_1 = struct.unpack("<I", self.file_handle.read(4))[0]
        unknown_2 = struct.unpack("<I", self.file_handle.read(4))[0]
        image_format = struct.unpack("<I", self.file_handle.read(4))[0]  # not compression
        unknown_4 = struct.unpack("<I", self.file_handle.read(4))[0]

        canvas_width = struct.unpack("<H", self.file_handle.read(2))[0] # Probably instructions for game
        canvas_height = struct.unpack("<H", self.file_handle.read(2))[0]
        canvas_offset_x = struct.unpack("<H", self.file_handle.read(2))[0]
        canvas_offset_y = struct.unpack("<H", self.file_handle.read(2))[0]
        image_width = struct.unpack("<H", self.file_handle.read(2))[0]
        image_height = struct.unpack("<H", self.file_handle.read(2))[0]

        if image_format == 0x090000: # Could be related to image bit or something
            image_palette_size = struct.unpack("<H", self.file_handle.read(2))[0]
        else:
            image_palette_size = 0

        compressed_size = struct.unpack("<I", self.file_handle.read(4))[0]
        data = self.file_handle.read(compressed_size)
        decompressed_data = decompress(data)

        # file_out_dir = os.path.join(extract_dir, self.file_name)
        file_out_dir = os.path.join(extract_dir)
        os.makedirs(file_out_dir, exist_ok=True)

        img = self.btf_image_to_png(decompressed_data, image_width, image_height, image_format, palette_size=image_palette_size)
        img.save(os.path.join(file_out_dir, f"{self.file_name}.png"), format="PNG")

        # save image with canvas
        if canvas:
            img_with_canvas = Image.new("RGBA", (canvas_width, canvas_height))
            img_with_canvas.paste(img, (canvas_offset_x, canvas_offset_y))
            img_with_canvas.save(os.path.join(file_out_dir, f"{self.file_name}_canvas.png"), format="PNG")

    def btf_image_to_png(self, raw_bytes: bytes, width: int, height: int, image_format: int, **image_format_config):
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
        return img


class KHUxPNG(FileClass):
    def __init__(self, file_path: str) -> None:
        super().__init__(file_path)

        # if not file_path:
        #     raise ValueError("Invalid file path")

        # if not os.path.isfile(file_path):
        #     raise ValueError("File does not exist")

        # self.file_name = os.path.splitext(os.path.basename(file_path))[0]
        # self.file_path = file_path
        # self.file_handle = open(file_path, "rb")

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

    def close(self) -> None:
        if self.file_handle:
            self.file_handle.close()

    def extract(self, extract_dir: str):
        if self.file_type == "BTF":
            btf = KHUxBTF(self.file_handle, self.file_name)
            btf.process(extract_dir)
        else:
            raise NotImplementedError(f"Unsupported file type: {self.file_type}")
