"""Bounded subprocess parser. No application imports, credentials or network calls."""

import sys, os, json, subprocess, zipfile, re, time, resource
from pathlib import Path
from xml.etree import ElementTree as ET

MAX_TEXT = 32 * 1024 * 1024


def run(args, timeout=60):
    r = subprocess.run(
        args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if r.returncode:
        raise ValueError(
            "Document could not be parsed. It may be damaged or password protected."
        )
    return r.stdout


def main():
    resource.setrlimit(resource.RLIMIT_AS, (1536 * 1024 * 1024, 1536 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (240, 240))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_TEXT * 2, MAX_TEXT * 2))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    source, ext, target = sys.argv[1:]
    target = Path(target)
    target.mkdir(exist_ok=True)
    out = (target / "pages.jsonl").open("w")
    total = 0
    pages = 0
    ocr_count = 0
    warnings = []
    images = []

    def emit(text, visual=False):
        nonlocal total, pages
        text = text.replace("\x00", "")
        total += len(text.encode())
        pages += 1
        if total > MAX_TEXT or pages > 2000:
            raise ValueError(
                "Document exceeds 32 MB of extracted text or 2,000 pages. Split it into smaller files."
            )
        out.write(json.dumps({"page": pages, "text": text, "visual": visual}) + "\n")

    if ext == ".pdf":
        info = run(["pdfinfo", source]).decode(errors="replace")
        match = re.search(r"^Pages:\s+(\d+)", info, re.M)
        if not match or int(match[1]) > 2000:
            raise ValueError("PDF must contain 1–2,000 pages")
        textfile = target / "text.txt"
        run(["pdftotext", "-layout", "-enc", "UTF-8", source, str(textfile)], 120)
        if textfile.stat().st_size > MAX_TEXT:
            raise ValueError("PDF text exceeds the processing limit. Split the PDF.")
        texts = textfile.read_text(errors="replace").split("\f")
        started = time.monotonic()
        for i in range(int(match[1])):
            text = texts[i] if i < len(texts) else ""
            if len(text.strip()) < 40:
                if ocr_count < 40 and time.monotonic() - started < 180:
                    try:
                        run(
                            [
                                "pdftoppm",
                                "-f",
                                str(i + 1),
                                "-l",
                                str(i + 1),
                                "-scale-to",
                                "1800",
                                "-singlefile",
                                "-png",
                                source,
                                str(target / "scan"),
                            ],
                            15,
                        )
                        text = run(
                            [
                                "tesseract",
                                str(target / "scan.png"),
                                "stdout",
                                "-l",
                                "eng",
                            ],
                            10,
                        ).decode(errors="replace")
                        ocr_count += 1
                    except (ValueError, subprocess.TimeoutExpired):
                        warnings.append("Some scanned pages need visual inspection.")
                else:
                    warnings.append(
                        "Some scanned pages need visual inspection; OCR processing budget reached."
                    )
            emit(text, True)
    elif ext in (".docx", ".xlsx", ".pptx"):
        with zipfile.ZipFile(source) as z:
            entries = z.infolist()
            if (
                len(entries) > 10000
                or sum(i.file_size for i in entries) > 100 * 1024 * 1024
                or any(i.file_size > 32 * 1024 * 1024 for i in entries)
            ):
                raise ValueError("Expanded document exceeds safe processing limits")

            def tree(name):
                data = z.read(name)
                if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
                    raise ValueError("Unsupported XML declarations")
                return ET.fromstring(data)

            if ext == ".docx":
                root = tree("word/document.xml")
                parts = []
                for p in root.iter():
                    if p.tag.endswith("}p"):
                        parts.append(
                            "".join(
                                n.text or "" for n in p.iter() if n.tag.endswith("}t")
                            )
                        )
                text = "\n".join(parts)
                for n in range(0, max(1, len(text)), 12000):
                    emit(text[n : n + 12000])
                if any(i.filename.startswith("word/media/") for i in entries):
                    warnings.append(
                        "Embedded images are available as separate sections. Export to PDF when exact Word page layout matters."
                    )
            elif ext == ".pptx":
                names = sorted(
                    (
                        i.filename
                        for i in entries
                        if re.fullmatch(r"ppt/slides/slide\d+\.xml", i.filename)
                    ),
                    key=lambda n: int(re.search(r"(\d+)\.xml", n)[1]),
                )
                for name in names:
                    emit(
                        "\n".join(
                            n.text or ""
                            for n in tree(name).iter()
                            if n.tag.endswith("}t")
                        )
                    )
                warnings.append(
                    "Slide text and embedded images are available. Export to PDF when exact slide layout matters."
                )
            else:
                shared = (
                    [
                        "".join(n.text or "" for n in si.iter() if n.tag.endswith("}t"))
                        for si in tree("xl/sharedStrings.xml")
                    ]
                    if "xl/sharedStrings.xml" in z.namelist()
                    else []
                )
                sheets = sorted(
                    i.filename
                    for i in entries
                    if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", i.filename)
                )
                for sheet in sheets:
                    batch = []
                    size = 0
                    for row in tree(sheet).iter():
                        if not row.tag.endswith("}row"):
                            continue
                        values = []
                        for cell in row:
                            v = next(
                                (n.text or "" for n in cell if n.tag.endswith("}v")), ""
                            )
                            if cell.get("t") == "s":
                                v = (
                                    shared[int(v)]
                                    if v.isdigit() and int(v) < len(shared)
                                    else ""
                                )
                            if cell.get("t") == "inlineStr":
                                v = "".join(
                                    n.text or ""
                                    for n in cell.iter()
                                    if n.tag.endswith("}t")
                                )
                            values.append(cell.get("r", "") + "=" + v)
                        line = "\t".join(values)
                        batch.append(line)
                        size += len(line)
                        if size > 10000:
                            emit(sheet + "\n" + "\n".join(batch))
                            batch = []
                            size = 0
                    if batch:
                        emit(sheet + "\n" + "\n".join(batch))
                warnings.append(
                    "Spreadsheet values use saved formula results; formulas are not executed."
                )
    else:
        with open(source, "r", encoding="utf-8-sig", errors="strict") as f:
            while True:
                text = f.read(12000)
                if not text:
                    break
                if "\x00" in text:
                    raise ValueError(
                        "This file is binary. Upload PDF, Office, or UTF-8 text instead."
                    )
                emit(text)
    if ext in (".docx", ".pptx", ".xlsx"):
        with zipfile.ZipFile(source) as z:
            for entry in z.infolist():
                if not re.fullmatch(r"(word|ppt|xl)/media/[^/]+", entry.filename):
                    continue
                if entry.file_size > 6 * 1024 * 1024:
                    warnings.append(
                        "An embedded image exceeds 6 MB; use the original document in Work or export to PDF."
                    )
                    continue
                data = z.read(entry)
                mime = (
                    "image/png"
                    if data.startswith(b"\x89PNG\r\n\x1a\n")
                    else (
                        "image/jpeg"
                        if data.startswith(b"\xff\xd8")
                        else (
                            "image/gif"
                            if data.startswith((b"GIF87a", b"GIF89a"))
                            else (
                                "image/webp"
                                if data[:4] == b"RIFF" and data[8:12] == b"WEBP"
                                else None
                            )
                        )
                    )
                )
                if not mime:
                    warnings.append(
                        "An embedded vector/unsupported image needs PDF export for visual inspection."
                    )
                    continue
                emit(
                    "Embedded image "
                    + Path(entry.filename).name
                    + ". Use action=image with this section number to inspect it.",
                    True,
                )
                name = "image-" + str(pages) + ".bin"
                (target / name).write_bytes(data)
                images.append({"page": pages, "file": name, "mime": mime})
    out.close()
    (target / "manifest.json").write_text(
        json.dumps(
            {
                "pages": pages,
                "text_bytes": total,
                "warnings": list(dict.fromkeys(warnings)),
                "ocr_pages": ocr_count,
                "images": images,
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(str(e)[:500], file=sys.stderr)
        sys.exit(1)
