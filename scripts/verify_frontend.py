import hashlib, json, pathlib

root = pathlib.Path(__file__).resolve().parents[1]
manifest = json.loads((root / "frontend-manifest.json").read_text())
for name, expected in manifest.items():
    path = root / "app/static" / name
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise SystemExit("Frontend integrity check failed: " + name)
assert "index.html" in manifest and any(n.startswith("_next/static/") for n in manifest)
print(f"Frontend integrity passed: {len(manifest)} assets")
