#!/usr/bin/env python3
"""Package readable source and verified assets without dependencies or local secrets.

Run after rebuilding the frontend. Every ZIP has one top-level directory and
explicit Unix permissions, so unpacking preserves executable deployment scripts.
"""
import argparse
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {"node_modules", ".next", "out", "__pycache__", ".pytest_cache", ".git", ".venv", "venv", "test-results"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.is_relative_to(ROOT):
        parser.error("Write the archive outside the source directory")
    subprocess.run([sys.executable, str(ROOT / "scripts/verify_frontend.py")], check=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(ROOT.rglob("*")):
            relative = path.relative_to(ROOT)
            if any(part in EXCLUDED for part in relative.parts):
                continue
            if path.is_symlink():
                raise SystemExit(f"Unexpected symlink: {relative}")
            if not path.is_file():
                continue
            if path.name == ".env" or path.suffix in {".pyc", ".env", ".enc", ".dump", ".legacy", ".zip"}:
                continue
            item = zipfile.ZipInfo("owncmd-community/" + relative.as_posix())
            item.create_system = 3
            mode = 0o755 if path.suffix == ".sh" or path.name == "asterctl" else 0o644
            item.external_attr = (0o100000 | mode) << 16
            item.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(item, path.read_bytes())
    with zipfile.ZipFile(output) as archive:
        bad = archive.testzip()
        if bad:
            raise SystemExit(f"Corrupt archive entry: {bad}")
        print(f"Packaged {len(archive.infolist())} files: {output} ({output.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
