"""Checks the exact exported frontend through its production FastAPI host."""

import base64, hashlib, json, re, subprocess, sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Assets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.assets = []
        self.inline = []
        self.active = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script":
            self.active = "src" not in attrs
            if attrs.get("src"):
                self.assets.append(attrs["src"])
        if tag == "link" and attrs.get("rel") == "stylesheet":
            self.assets.append(attrs["href"])

    def handle_data(self, data):
        if self.active:
            self.inline.append(data)

    def handle_endtag(self, tag):
        if tag == "script":
            self.active = False


def test_every_exported_asset_matches_manifest():
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/verify_frontend.py")], check=True
    )


def test_production_html_scripts_styles_and_csp(client):
    response = client.get("/")
    assert response.status_code == 200
    parser = Assets()
    parser.feed(response.text)
    assert len(parser.assets) >= 3
    for asset in parser.assets:
        assert asset.startswith("/static/_next/")
        r = client.get(asset)
        assert r.status_code == 200, asset
        assert "html" not in r.headers["content-type"]
    csp = response.headers["content-security-policy"]
    script = csp.split("script-src", 1)[1].split(";", 1)[0]
    assert "'unsafe-inline'" not in script and "'unsafe-eval'" not in script
    for script in parser.inline:
        token = (
            "'sha256-"
            + base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
            + "'"
        )
        assert token in csp
    assert "frame-ancestors 'none'" in csp
    assert client.get("/static/../../config.env").status_code == 404


def test_legacy_frontend_not_shipped():
    assert not (ROOT / "app/static/app.js").exists()
    assert not (ROOT / "app/static/style.css").exists()
    package = json.loads((ROOT / "frontend/package.json").read_text())
    assert package["dependencies"]["next"] == "16.4.0"
    assert package["dependencies"]["react"] == "19.3.0"
    assert (ROOT / "frontend/package-lock.json").is_file()
