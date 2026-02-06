import os
import sys

from src.bgad import KHUxBGADContainer

argv = sys.argv
argc = len(argv)

ext_dir = "extracted_files"

if argc < 2:
    print(f"Usage: {argv[0]} khux_file.mp4")
    sys.exit(1)

if __name__ == "__main__":
    os.makedirs(ext_dir, exist_ok=True)

    khux_file = argv[1]
    bgad = KHUxBGADContainer(khux_file)
    bgad.extract(ext_dir)
