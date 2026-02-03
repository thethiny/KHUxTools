import os
import sys

from src.png import KHUxPNG


argv = sys.argv
argc = len(argv)

ext_dir = "extracted_files"

if argc < 2:
    print(f"Usage: {argv[0]} khux_file.PNG")
    sys.exit(1)

if __name__ == "__main__":
    os.makedirs(ext_dir, exist_ok=True)

    khux_file = argv[1]
    png = KHUxPNG(khux_file)
    png.extract(ext_dir)