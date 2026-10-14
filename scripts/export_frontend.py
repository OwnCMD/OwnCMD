"""Copy a production Next.js static export and record every shipped asset hash."""

import hashlib, json, pathlib, shutil

root = pathlib.Path(__file__).resolve().parents[1]
source = root / "frontend/out"
target = root / "app/static"
if not (source / "index.html").is_file():
    raise SystemExit("Build the Next.js frontend first")
if target.exists():
    shutil.rmtree(target)
shutil.copytree(source, target)
manifest = {
    str(p.relative_to(target)): hashlib.sha256(p.read_bytes()).hexdigest()
    for p in sorted(target.rglob("*"))
    if p.is_file()
}
(root / "frontend-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(f"Exported {len(manifest)} verified frontend assets")
