from __future__ import annotations

import html
from markdown_it import MarkdownIt
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name, get_lexer_for_filename
from pygments.lexers.special import TextLexer


def _highlight(code: str, lang: str, attrs: str) -> str:
    try:
        lexer = (
            get_lexer_by_name((lang or "").strip(), stripall=False)
            if lang
            else TextLexer()
        )
    except Exception:
        lexer = TextLexer()
    return highlight(code, lexer, HtmlFormatter(nowrap=True))


MD = MarkdownIt(
    "commonmark",
    {
        "html": False,
        "breaks": True,
        "linkify": False,
        "highlight": _highlight,
    },
)
# GFM-style conveniences that are present in markdown-it-py but disabled by commonmark.
for rule in ("table", "strikethrough"):
    try:
        MD.enable(rule)
    except Exception:
        pass


def markdown(text: str | None, task: str | None = None, files=()) -> str:
    """Render model/user Markdown to safe HTML.

    Raw HTML is disabled and markdown-it validates unsafe link schemes. Pygments output is
    generated from escaped source code, so the returned markup is safe to place in the UI.
    """
    from .artifacts import link

    tokens = MD.parse(str(text or ""))
    for token in tokens:
        children = token.children or []
        for i, child in enumerate(children):
            if child.type == "link_open":
                label = ""
                for x in children[i + 1 :]:
                    if x.type == "link_close":
                        break
                    if x.type in ("text", "code_inline"):
                        label += x.content
                href = link(task, child.attrGet("href") or "", label, files)
                if href:
                    child.attrSet("href", href)
                else:
                    child.attrs.pop("href", None)
    return MD.renderer.render(tokens, MD.options, {})


def plain(text: object, limit: int = 500) -> str:
    value = str(text or "")
    return value[:limit]


def code_preview(text: str | None, filename: str = "file.txt") -> tuple[str, str]:
    """Render sandbox text as safe, read-only syntax-highlighted HTML with line numbers."""
    value = str(text or "")
    try:
        lexer = get_lexer_for_filename(filename, value, stripall=False)
    except Exception:
        lexer = TextLexer()
    formatter = HtmlFormatter(linenos="table", noclasses=True, wrapcode=True)
    return highlight(value, lexer, formatter), getattr(lexer, "name", "Text")
