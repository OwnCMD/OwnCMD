"""Canonical owner-authenticated links for sandbox deliverables."""

import re
from pathlib import PurePosixPath
from urllib.parse import quote, unquote, urlsplit, parse_qs


def path(value):
    if not isinstance(value, str) or not value or len(value) > 1000:
        raise ValueError("Invalid file path")
    if value.startswith("sandbox:"):
        value = value[8:]
    if value.startswith("/work/"):
        value = value[6:]
    if (
        value.startswith("/")
        or "\\" in value
        or any(ord(c) < 32 for c in value)
        or any(x in ("", "..", ".") for x in value.split("/"))
    ):
        raise ValueError("Use a file path inside /work")
    return value


def url(task, value):
    return (
        "/api/tasks/"
        + quote(task, safe="")
        + "/download?path="
        + quote(path(value), safe="")
    )


def record(task, s, value, info):
    value = path(value)
    size = info.get("size")
    if type(size) != int or not 0 <= size <= 20 * 1024 * 1024:
        raise ValueError("File exceeds the 20 MB download limit")
    item = {
        "path": value,
        "name": PurePosixPath(value).name,
        "size": size,
        "url": url(task, value),
        "turn": sum(m.get("role") == "user" for m in s.get("messages", [])),
    }
    previous = next(
        (
            x
            for x in s.get("artifacts", [])
            if x["path"] == value and x.get("turn") == item["turn"]
        ),
        {},
    )
    item["labels"] = list(
        dict.fromkeys(
            previous.get("labels", [])
            + ([previous["label"]] if previous.get("label") else [])
        )
    )
    s["artifacts"] = [x for x in s.get("artifacts", []) if x["path"] != value][-39:] + [
        item
    ]
    return item


def current(s):
    turn = sum(m.get("role") == "user" for m in s.get("messages", []))
    return [x for x in s.get("artifacts", []) if x.get("turn") == turn]


def relative_file(href):
    return bool(
        re.search(
            r"\.(?:pdf|csv|tsv|xlsx?|docx?|pptx?|zip|tar|gz|png|jpe?g|gif|webp|svg|txt|md|json|html?|py|js|jsx|ts|tsx|css|sql|mp4|mp3|wav|stl|ipynb)(?:$)",
            urlsplit(href).path,
            re.I,
        )
    )


def link(task, href, label="", files=()):
    """Rewrite only local task files; never grant cross-task access or allow scripts."""
    if not task:
        return href
    known = {x["path"]: x for x in files if isinstance(x, dict) and "path" in x}
    try:
        if href.startswith(("sandbox:/work/", "/work/")):
            return url(task, unquote(href))
        # Common foreign sandbox prefix is translated only for a verified exact path.
        if href.startswith("sandbox:/mnt/data/"):
            candidate = path(unquote(href[len("sandbox:/mnt/data/") :]))
            return url(task, candidate) if candidate in known else ""
        if href in ("", "#"):
            matches = [
                x
                for x in known.values()
                if x["name"].casefold() in label.casefold()
                or x.get("label") == label
                or label in x.get("labels", [])
            ]
            return url(task, matches[0]["path"]) if len(matches) == 1 else ""
        p = urlsplit(href)
        if (
            not p.scheme
            and not p.netloc
            and not href.startswith(("/", "#"))
            and relative_file(href)
        ):
            return url(task, unquote(href))
        if href.startswith("/api/tasks/") and "/download?" in href:
            candidate = parse_qs(p.query).get("path", [""])[0]
            return url(
                task, candidate
            )  # Bind generated links to the current owned task.
    except (ValueError, KeyError):
        return ""
    return href


async def prepare(row, s, message, broker):
    """Verify model-authored local links before completion, including older conventions."""
    from .render import MD

    unresolved = []
    inventory = None
    attempts = 0
    for token in MD.parse(str(message.get("content") or "")):
        children = token.children or []
        for i, t in enumerate(children):
            if t.type != "link_open":
                continue
            href = t.attrGet("href") or ""
            label = ""
            for child in children[i + 1 :]:
                if child.type == "link_close":
                    break
                if child.type in ("text", "code_inline"):
                    label += child.content
            p = urlsplit(href)
            candidate = None
            if href.startswith(("sandbox:/work/", "/work/")):
                candidate = unquote(href)
            elif href.startswith("sandbox:/mnt/data/"):
                candidate = unquote(href[len("sandbox:/mnt/data/") :])
            elif href.startswith("/api/tasks/") and "/download?" in href:
                candidate = parse_qs(p.query).get("path", [""])[0]
            elif (
                href
                and not p.scheme
                and not p.netloc
                and not href.startswith(("/", "#"))
                and relative_file(href)
            ):
                candidate = unquote(href)
            elif href in ("", "#") and re.search(
                r"download|\.(pdf|csv|xlsx|docx|pptx|zip|png|jpg|txt|md)\b", label, re.I
            ):
                if inventory is None:
                    try:
                        inventory = (
                            await broker(row["id"], "file", {"op": "list"})
                        ).get("files", [])
                    except Exception:
                        inventory = []
                matches = [
                    x
                    for x in inventory
                    if PurePosixPath(x).name.casefold() in label.casefold()
                ]
                if not matches:
                    extensions = re.findall(
                        r"\b(pdf|csv|xlsx|docx|pptx|zip|png|jpg|txt|md)\b", label, re.I
                    )
                    matches = [
                        x
                        for x in inventory
                        if PurePosixPath(x).suffix.lower().lstrip(".")
                        in [v.lower() for v in extensions]
                    ]
                if len(matches) == 1:
                    candidate = matches[0]
                else:
                    unresolved.append(label)
                    continue
            if candidate is None:
                continue
            attempts += 1
            if attempts > 10:
                unresolved.append(label)
                continue
            try:
                candidate = path(candidate)
                info = await broker(
                    row["id"], "file", {"op": "info", "path": candidate}
                )
                item = record(row["id"], s, candidate, info)
                item["labels"] = list(dict.fromkeys(item.get("labels", []) + [label]))
                # The renderer uses this verified record/label to replace placeholders safely.
            except Exception:
                unresolved.append(label or str(candidate))
    if unresolved:
        return (
            "A download could not be verified. Locate/create the intended file inside /work, call publish_file, and use its exact returned URL. Unresolved labels: "
            + ", ".join(unresolved)[:600]
        )
    return ""
