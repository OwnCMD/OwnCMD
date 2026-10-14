"""Legacy source-preservation checks insensitive to formatting and quote style.

These supplement behavioral API/runtime tests, rather than replacing them.
"""

import re


def normalize(value):
    return (
        re.sub(r"\s+", "", str(value))
        .replace('"', "'")
        .replace(",)", ")")
        .replace(",]", "]")
    )


class Source(str):
    def __contains__(self, part):
        return normalize(part) in normalize(self)

    def count(self, part, *args):
        return normalize(self).count(normalize(part), *args)

    def split(self, sep=None, maxsplit=-1):
        if sep is None:
            return super().split(sep, maxsplit)
        return [Source(x) for x in normalize(self).split(normalize(sep), maxsplit)]


def read_source(path):
    return Source(path.read_text())
