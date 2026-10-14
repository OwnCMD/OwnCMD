"""Shared bounded parser. Imports are data and never execute code."""

import base64, io, json, stat, unicodedata, zipfile, re
from pathlib import PurePosixPath
import yaml

MAX_FILES = 80
MAX_FILE = 512 * 1024
MAX_TOTAL = 8 * 1024 * 1024
FIELDS = {
    "name",
    "description",
    "tags",
    "when_to_use",
    "when_not_to_use",
    "capabilities",
    "version",
}
CAPABILITIES = {"search_web", "browse", "run_code", "files"}


class StrictLoader(yaml.SafeLoader):
    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            raise ValueError("YAML aliases are not allowed")
        self.depth = getattr(self, "depth", 0) + 1
        if self.depth > 5:
            raise ValueError("YAML nesting exceeds limit")
        try:
            return super().compose_node(parent, index)
        finally:
            self.depth -= 1

    def construct_mapping(self, node, deep=False):
        out = {}
        for k, v in node.value:
            key = self.construct_object(k, deep=deep)
            if not isinstance(key, str) or key in out:
                raise ValueError("Duplicate or invalid YAML key")
            out[key] = self.construct_object(v, deep=deep)
        return out


def text(v, name, n, empty=False):
    if (
        not isinstance(v, str)
        or len(v) > n
        or "\x00" in v
        or (not empty and not v.strip())
    ):
        raise ValueError(f"Invalid {name} (maximum {n} characters)")
    return v.strip()


def path(v):
    if (
        not isinstance(v, str)
        or len(v) > 180
        or v != unicodedata.normalize("NFC", v)
        or any(ord(x) < 32 for x in v)
        or "\\" in v
        or ":" in v
    ):
        raise ValueError("Unsafe resource path")
    p = PurePosixPath(v)
    if (
        p.is_absolute()
        or str(p) != v
        or any(x in (".", "..", "") for x in v.split("/"))
        or len(p.parts) < 2
        or p.parts[0] not in ("scripts", "references", "templates", "assets")
    ):
        raise ValueError(
            "Use a safe path inside scripts/, references/, templates/, or assets/"
        )
    return v


def matching_text(d):
    return json.dumps(
        {
            k: d[k]
            for k in (
                "name",
                "description",
                "tags",
                "when_to_use",
                "when_not_to_use",
                "capabilities",
            )
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def markdown(d):
    return (
        "---\n"
        + yaml.safe_dump({k: d[k] for k in FIELDS}, sort_keys=True, allow_unicode=True)
        + "---\n"
        + d["instructions"]
        + "\n"
    )


def validate(d):
    if not isinstance(d, dict) or set(d) - FIELDS - {"instructions", "resources"}:
        raise ValueError("Invalid Skill fields")
    out = {
        "name": text(d.get("name"), "name", 100),
        "description": text(d.get("description"), "description", 600),
        "instructions": text(d.get("instructions"), "instructions", 12000),
    }
    for k, n, size in [
        ("tags", 12, 60),
        ("when_to_use", 12, 240),
        ("when_not_to_use", 12, 240),
        ("capabilities", 4, 30),
    ]:
        arr = d.get(k, [])
        if not isinstance(arr, list) or len(arr) > n:
            raise ValueError("Invalid " + k)
        out[k] = list(dict.fromkeys(text(x, k, size) for x in arr))
    if set(out["capabilities"]) - CAPABILITIES:
        raise ValueError("Unsupported capability")
    v = d.get("version", 1)
    if type(v) != int or not 1 <= v <= 1000000:
        raise ValueError("Version must be a positive integer")
    out["version"] = v
    out["resources"] = []
    seen = set()
    total = 0
    resources = d.get("resources", [])
    if not isinstance(resources, list) or len(resources) > MAX_FILES:
        raise ValueError("Resource count exceeded")
    for r in resources:
        if not isinstance(r, dict) or set(r) - {"path", "text", "data"}:
            raise ValueError("Invalid resource")
        name = path(r.get("path"))
        if name.casefold() in seen:
            raise ValueError("Duplicate resource path")
        seen.add(name.casefold())
        try:
            raw = (
                base64.b64decode(r["data"], validate=True)
                if "data" in r
                else r["text"].encode()
            )
        except Exception:
            raise ValueError("Invalid resource content")
        total += len(raw)
        if len(raw) > MAX_FILE or total > MAX_TOTAL - 65536:
            raise ValueError("Resource size exceeded")
        out["resources"].append({"path": name, "data": base64.b64encode(raw).decode()})
    if len(markdown(out).encode()) > 24000 or len(matching_text(out).encode()) > 10000:
        raise ValueError("Skill metadata or instructions exceed byte limit")
    return out


def parse_markdown(raw):
    if len(raw) > 24000:
        raise ValueError("SKILL.md exceeds 24 KB")
    try:
        doc = raw.decode("utf-8")
    except UnicodeError:
        raise ValueError("SKILL.md must be UTF-8")
    m = re.fullmatch(r"---\r?\n(.*?)\r?\n---\r?\n(.*)", doc, re.S)
    if not m or len(m[1]) > 10000:
        raise ValueError("SKILL.md requires bounded YAML frontmatter")
    try:
        d = yaml.load(m[1], Loader=StrictLoader)
    except yaml.YAMLError:
        raise ValueError("Invalid YAML")
    if not isinstance(d, dict) or set(d) - FIELDS:
        raise ValueError("Invalid frontmatter fields")
    return {**d, "instructions": m[2]}


def import_zip(raw):
    if len(raw) > MAX_TOTAL:
        raise ValueError("ZIP exceeds 8 MB")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            infos = z.infolist()
            seen = set()
            files = {}
            total = 0
            if not infos or len(infos) > MAX_FILES + 1:
                raise ValueError("ZIP file count exceeded")
            for i in infos:
                if i.filename != "SKILL.md":
                    path(i.filename)
                if (
                    i.filename.casefold() in seen
                    or stat.S_IFMT(i.external_attr >> 16) not in (0, stat.S_IFREG)
                    or i.flag_bits & 1
                ):
                    raise ValueError("Duplicate, encrypted or non-regular entry")
                seen.add(i.filename.casefold())
                total += i.file_size
                if (
                    total > MAX_TOTAL
                    or i.file_size > MAX_FILE
                    or i.file_size > max(1, i.compress_size) * 100
                ):
                    raise ValueError("ZIP expansion limit exceeded")
                with z.open(i) as f:
                    content = f.read(MAX_FILE + 1)
                if len(content) != i.file_size:
                    raise ValueError("Invalid ZIP entry")
                files[i.filename] = content
            if "SKILL.md" not in files:
                raise ValueError("Root SKILL.md is required")
            d = parse_markdown(files.pop("SKILL.md"))
            d["resources"] = [
                {"path": k, "data": base64.b64encode(v).decode()}
                for k, v in files.items()
            ]
            return validate(d)
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError) as e:
        raise ValueError("Invalid ZIP") from e


def export_zip(d):
    d = validate(d)
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_STORED) as z:
        z.writestr("SKILL.md", markdown(d))
        for r in d["resources"]:
            z.writestr(r["path"], base64.b64decode(r["data"]))
    return b.getvalue()
