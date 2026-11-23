"""Leitor mínimo de dumps MySQL (INSERT ... VALUES (...),(...);)."""
from __future__ import annotations

import lzma
import re
from typing import Iterator

_INSERT = re.compile(r"INSERT\s+(?:IGNORE\s+)?INTO\s+`(\w+)`\s+VALUES\s*", re.I)
_ESC = {"0": "\0", "n": "\n", "r": "\r", "t": "\t", "Z": "\x1a", "b": "\b"}


def _parse_values(s: str, i: int) -> Iterator[tuple]:
    n = len(s)
    while i < n:
        while i < n and s[i] in " ,\n\r\t":
            i += 1
        if i >= n or s[i] == ";":
            return
        assert s[i] == "(", s[i : i + 50]
        i += 1
        row = []
        while True:
            c = s[i]
            if c == "'":
                i += 1
                buf = []
                while True:
                    j = s.find("'", i)
                    k = s.find("\\", i)
                    if k != -1 and k < j:
                        buf.append(s[i:k])
                        e = s[k + 1]
                        buf.append(_ESC.get(e, e))
                        i = k + 2
                        continue
                    if j + 1 < n and s[j + 1] == "'":  # '' dentro da string
                        buf.append(s[i:j] + "'")
                        i = j + 2
                        continue
                    buf.append(s[i:j])
                    i = j + 1
                    break
                row.append("".join(buf))
            else:
                j = i
                while s[j] not in ",)":
                    j += 1
                tok = s[i:j].strip()
                row.append(None if tok == "NULL" else (int(tok) if re.fullmatch(r"-?\d+", tok) else tok))
                i = j
            if s[i] == ",":
                i += 1
                continue
            if s[i] == ")":
                i += 1
                break
        yield tuple(row)


def iter_rows(path, tables: set[str]) -> Iterator[tuple[str, tuple]]:
    opener = lzma.open if str(path).endswith(".xz") else open
    with opener(path, "rt", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = _INSERT.match(line)
            if not m or m.group(1) not in tables:
                continue
            for row in _parse_values(line, m.end()):
                yield m.group(1), row
