"""
Convert KHUx master data m*.jpg files to JSON.

Usage:
    python tools/m_to_json.py D:/Modding/KHUx/m/m002.jpg              # auto-detect table
    python tools/m_to_json.py D:/Modding/KHUx/m/m002.jpg avatarParts  # explicit table
    python tools/m_to_json.py D:/Modding/KHUx/m/m002.jpg -o out.json  # write to file
    python tools/m_to_json.py --list                                   # list known schemas
    python tools/m_to_json.py D:/Modding/KHUx/m/ --all                # convert all m*.jpg
"""
import os
import sys
import json
import glob

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from khux.formats.master import MasterDataParser, TABLE_NAMES


def main():
    import argparse
    p = argparse.ArgumentParser(description="Convert KHUx m*.jpg master data to JSON")
    p.add_argument("path", nargs="?", help="Path to m*.jpg file or directory")
    p.add_argument("table", nargs="?", help="Table name override (auto-detected from filename)")
    p.add_argument("-o", "--output", help="Output file path (default: stdout)")
    p.add_argument("--all", action="store_true", help="Convert all m*.jpg in directory")
    p.add_argument("--list", action="store_true", help="List known table schemas")
    p.add_argument("--compact", action="store_true", help="Compact JSON output")
    args = p.parse_args()

    parser = MasterDataParser()

    if args.list:
        print("Known schemas:")
        for name in parser.list_schemas():
            print(f"  {name}")
        print(f"\nAll {len(TABLE_NAMES)} table names (by index):")
        for i, name in enumerate(TABLE_NAMES):
            schema = "schema" if name in parser.schemas else "raw"
            print(f"  m{i:03d}.jpg = {name} [{schema}]")
        return

    if not args.path:
        p.print_help()
        return

    indent = None if args.compact else 2

    if args.all:
        directory = args.path
        outdir = args.output or directory
        files = sorted(glob.glob(os.path.join(directory, "m*.jpg")))
        if not files:
            print(f"No m*.jpg files found in {directory}", file=sys.stderr)
            return
        for fpath in files:
            detected = parser.detect_table(fpath)
            fallback = parser.table_name_from_filename(fpath)
            table_name = detected or fallback
            label = table_name or os.path.basename(fpath)
            has_schema = table_name and table_name in parser.schemas
            try:
                records = parser.parse_file(fpath, detected)
                out_path = os.path.join(outdir, f"{label}.json")
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(records, f, ensure_ascii=False, indent=indent)
                tag = "parsed" if has_schema else "raw"
                print(f"  {os.path.basename(fpath)} -> {label}.json ({len(records)} entries) [{tag}]")
            except Exception as e:
                print(f"  {os.path.basename(fpath)} -> ERROR: {e}", file=sys.stderr)
    else:
        table_name = args.table
        records = parser.parse_file(args.path, table_name)
        if not table_name:
            table_name = parser.detect_table(args.path) or parser.table_name_from_filename(args.path)
        has_schema = table_name and table_name in parser.schemas
        result = json.dumps(records, ensure_ascii=False, indent=indent)

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(result)
            tag = "parsed" if has_schema else "raw"
            print(f"Wrote {len(records)} {table_name or 'unknown'} entries to {args.output} [{tag}]")
        else:
            print(result)


if __name__ == "__main__":
    main()
