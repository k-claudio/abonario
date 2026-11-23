"""Limpeza de textos e segmentação em trechos (frases ou grupos de versos)."""
from __future__ import annotations

import re

import common  # noqa: F401  (põe a raiz do projeto no sys.path)
from app.core.textnorm import WORD_RE

ABBREV = {
    "sr", "sra", "srs", "sras", "snr", "snra", "snrs", "d", "dr", "dra", "drs", "s", "sto", "sta",
    "v", "vv", "exa", "exma", "exmo", "ex", "il", "ilm", "ilmo", "illm", "illmo", "illma", "ilma",
    "rev", "revd", "revmo", "pe", "fr", "prof", "profa", "gen", "cap", "cel", "ten", "sarg", "mme",
    "mlle", "mr", "mrs", "n", "pag", "pág", "págs", "cf", "vol", "vols", "tom", "fig", "art", "arts",
    "ed", "edd", "obr", "op", "cit", "liv", "cart", "l", "lib", "trad", "pp", "p", "sec", "séc",
    "jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez", "st", "ss",
    "mons", "bel", "dom", "fl", "fls", "ms", "mss", "num", "núm", "nº", "no", "sr.ª", "v.ª", "v.ª",
    "exc", "exm", "e", "ill", "rr", "s.ª", "mm", "nn",
}
_BOUNDARY = re.compile(r"[.!?…]+[\"»”’')\]]*(?=\s+[\"«“—–(¡¿'‘A-ZÀ-ÖØ-Þ0-9])")
_FINAL = re.compile(r"[.!?…][\"»”’')\]]*\s*$")
_WS = re.compile(r"[ \t ]+")

MAX_LEN = 480
MIN_WORDS = 4
MIN_CHARS = 20


def _prev_word(text: str, end: int) -> str:
    j = end
    while j > 0 and (text[j - 1].isalpha() or text[j - 1] in "ªº"):
        j -= 1
    return text[j:end]


def split_sentences(par: str) -> list[str]:
    out: list[str] = []
    start = 0
    for m in _BOUNDARY.finditer(par):
        dot = m.start()
        if par[dot] == ".":
            w = _prev_word(par, dot)
            if w.lower() in ABBREV or (len(w) == 1 and w.isupper()):
                continue
            if re.fullmatch(r"[IVXLC]+", w) and len(w) <= 4 and dot - len(w) - 1 >= 0 and par[dot - len(w) - 1] == " ":
                # "D. João V. Era" é raro; "capítulo IV. O..." também. Mantém o corte.
                pass
        piece = par[start:m.end()].strip()
        if piece:
            out.append(piece)
        start = m.end()
    tail = par[start:].strip()
    if tail:
        out.append(tail)
    return out


def _split_long(s: str) -> list[str]:
    if len(s) <= MAX_LEN:
        return [s]
    for sep in ("; ", ": ", " — ", ", "):
        best = -1
        for m in re.finditer(re.escape(sep), s):
            pos = m.start() + len(sep.rstrip())
            if 120 <= pos <= MAX_LEN:
                best = pos
        if best > 0:
            return [s[:best].strip()] + _split_long(s[best:].strip())
    cut = s.rfind(" ", 0, MAX_LEN)
    if cut < 100:
        cut = MAX_LEN
    return [s[:cut].strip()] + _split_long(s[cut:].strip())


def is_verse(lines: list[str]) -> bool:
    if len(lines) < 2:
        return False
    body = [l.strip() for l in lines[:-1]]
    long_lines = sum(1 for l in body if len(l) >= 55)
    if long_lines >= len(body) / 2:
        return False
    caps = sum(1 for l in lines[1:] if l.strip()[:1].isupper() or l.strip()[:1] in "«\"“—-(¡¿'")
    return caps >= 0.6 * (len(lines) - 1)


def join_prose(lines: list[str]) -> str:
    out = ""
    for line in lines:
        line = line.strip()
        if not out:
            out = line
        elif out.endswith("-") and line[:1].islower():
            out += line            # disse-\nlhe -> disse-lhe
        else:
            out += " " + line
    return _WS.sub(" ", out).strip()


def verse_units(lines: list[str], max_lines: int = 6) -> list[str]:
    units, cur = [], []
    for line in lines:
        line = _WS.sub(" ", line).strip()
        if not line:
            continue
        cur.append(line)
        if _FINAL.search(line) or len(cur) >= max_lines:
            units.append("\n".join(cur))
            cur = []
    if cur:
        units.append("\n".join(cur))
    return units


_LIST_ITEM = re.compile(r"^\s*(?:\d+|[IVXLC]+|[a-z])\s*(?:[.)\-—–]|\s—)\s")


def good_unit(u: str) -> bool:
    if len(u) < MIN_CHARS or _LIST_ITEM.match(u):
        return False
    ws = WORD_RE.findall(u)
    if len(ws) < MIN_WORDS:
        return False
    lower = sum(1 for w in ws if w[:1].islower())
    if lower < len(ws) * 0.5:  # títulos, nomes, maiúsculas
        return False
    letters = sum(c.isalpha() for c in u)
    return letters >= len(u) * 0.6


POEM_MARK = "\u0001"


def units_from_paragraph(lines: list[str]) -> list[str]:
    force = any(l.startswith(POEM_MARK) for l in lines)
    lines = [l.replace(POEM_MARK, "").rstrip() for l in lines]
    lines = [l for l in lines if l.strip()]
    if not lines:
        return []
    if force or is_verse(lines):
        units = verse_units(lines)
    else:
        units = []
        for s in split_sentences(join_prose(lines)):
            units.extend(_split_long(s))
    return [u for u in units if good_unit(u)]


# ---------------------------------------------------------------------------
# Gutenberg
# ---------------------------------------------------------------------------
_PG_START = re.compile(r"^\s*\*\*\*\s*START OF (?:THE|THIS) PROJECT GUTENBERG.*$", re.M | re.I)
_PG_END = re.compile(r"^\s*\*\*\*\s*END OF (?:THE|THIS) PROJECT GUTENBERG.*$|^\s*End of (?:the )?Project Gutenberg", re.M | re.I)
_CREDITS = re.compile(r"^(?:produced by|e-?text prepared by|this (?:e-?book|file) was produced|"
                      r"transcriber'?s? note|nota do transcritor|nota de edi[cç][aã]o|"
                      r"\[?nota(?:s)? (?:do|de) transcri)", re.I)


def clean_gutenberg(raw: str) -> str:
    s = _PG_START.search(raw)
    e = _PG_END.search(raw, s.end() if s else 0)
    body = raw[s.end() if s else 0: e.start() if e else len(raw)]
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    body = re.sub(r"\[(?:Ilustra[cç][aã]o|Illustra[cç][aã]o|Illustration|Gravura|Imagem)[^\]]*\]", "", body, flags=re.I)
    body = re.sub(r"\[(?:\d+|[A-Z]|\*)\]", "", body)              # chamadas de nota
    body = re.sub(r"\{[^}\n]{0,20}\}", "", body)
    body = re.sub(r"(?<=\w)_(?=\w)", " ", body)
    body = body.replace("_", "")
    body = re.sub(r"\+([^+\n]{1,200})\+", r"\1", body)          # +negrito+
    body = re.sub(r"\^\{?([oa]s?)\}?", lambda m: "º" if m.group(1) == "o" else ("ª" if m.group(1) == "a" else m.group(1)), body)
    body = re.sub(r"\s*--\s*", " — ", body)
    body = re.sub(r"^\s*(?:\*\s*){3,}\s*$", "", body, flags=re.M)  # separadores
    return body


def paragraphs(body: str) -> list[list[str]]:
    pars, cur = [], []
    for line in body.split("\n"):
        if line.strip():
            cur.append(line)
        elif cur:
            pars.append(cur)
            cur = []
    if cur:
        pars.append(cur)
    # créditos de digitalização no começo
    while pars and _CREDITS.match(pars[0][0].strip()):
        pars.pop(0)
    return [p for p in pars if not _CREDITS.match(p[0].strip())]


def gutenberg_units(raw: str) -> list[str]:
    units: list[str] = []
    for par in paragraphs(clean_gutenberg(raw)):
        units.extend(units_from_paragraph(par))
    return units


def text_units(text: str) -> list[str]:
    """Texto já limpo (ex.: Wikisource): parágrafos separados por linha em branco."""
    units: list[str] = []
    cur: list[str] = []
    for line in text.split("\n"):
        if line.replace(POEM_MARK, "").strip():
            cur.append(line)
        elif cur:
            units.extend(units_from_paragraph(cur))
            cur = []
    if cur:
        units.extend(units_from_paragraph(cur))
    return units
