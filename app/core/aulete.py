"""Consulta online ao Dicionário Caldas Aulete (aulete.com.br), priorizando o Verbete Original."""
from __future__ import annotations

import html
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Callable

from .textnorm import fold

BASE_URL = "https://aulete.com.br/"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Abonario/1.0"
DEFAULT_TIMEOUT = 10.0
CACHE_MAX = 512

ALLOWED_TAGS = frozenset({
    "p", "br", "strong", "b", "em", "i", "u", "sup", "sub", "span", "h3", "ol", "ul", "li",
})
VOID_TAGS = frozenset({"br"})
DROP_SUBTREE = frozenset({"script", "style", "textarea", "iframe", "noscript", "object", "embed", "button"})
DROP_VOID = frozenset({"img", "input"})
ALLOWED_CLASSES = frozenset({
    "textodeforiginal", "silabas", "separacao-silaba", "classificacao1", "numdef",
    "rub", "regio", "uso", "textodef", "notaverb", "marginNoloc", "noloc",
    "underline", "abon", "ex", "cochete", "aulete-sep", "aulete-orig",
})

_NOT_FOUND_RE = re.compile(
    r'Não foi encontrado o verbete\s*"[^"]*".*?mais próximo do pesquisado\s*\?\s*'
    r'(?:<span[^>]*>\s*<strong>(?P<nearest>[^<]*)</strong>\s*</span>)?\s*(?:<br\s*/?>\s*)*',
    re.S | re.I,
)
_HOMOGRAPH_ORIG_RE = re.compile(
    r"<strong>\s*([^<]+?)\s*</strong>\s*<span\s+class=[\"']silabas[\"'][^>]*>\s*"
    r"<sup>\s*([^<]+?)\s*</sup>\s*</span>",
    re.S | re.I,
)
_EMPTY_HOMOGRAPH_RE = re.compile(
    r"<p>\s*<strong>\s*</strong>\s*<sup>\s*<span\s+class=[\"']silabas[\"'][^>]*>\s*\d+\s*</span>\s*</sup>\s*</p>",
    re.S | re.I,
)
_LIGHTBOX_IMG_RE = re.compile(r"<a\b[^>]*>\s*<img\b[^>]*>\s*</a>", re.S | re.I)
_EDICAO_DIV_RE = re.compile(r'<div\b[^>]*\bclass=["\']edicao-verbete["\'][^>]*>\s*</div>', re.S | re.I)
_FORM_RE = re.compile(r"<form\b[^>]*>(.*)</form>", re.S | re.I)
_NOCAB_RE = re.compile(r'<span\b[^>]*\bid=["\']nocab["\'][^>]*>(.*?)</span>', re.S | re.I)
_TAB_ATUAL_RE = re.compile(r'<li\b[^>]*\bid=["\']tabatualizado["\'][^>]*>(.*?)</li>', re.S | re.I)
_TAB_ATUAL_HIDDEN_RE = re.compile(r'<li\b[^>]*\bid=["\']tabatualizado["\'][^>]*display:\s*none', re.I)
_TAB_ORIG_HIDDEN_RE = re.compile(r'<li\b[^>]*\bid=["\']taboriginal["\'][^>]*display:\s*none', re.I)
_TAG_SPLIT_RE = re.compile(r"(<[^>]+>)")


@dataclass
class AuleteEntry:
    query: str
    headword: str = ""
    url: str = ""
    original_html: str = ""
    updated_html: str = ""
    updated_label: str = "Verbete Atualizado"
    nearest: str = ""
    error: str = ""

    @property
    def has_original(self) -> bool:
        return bool(self.original_html)

    @property
    def has_updated(self) -> bool:
        return bool(self.updated_html)

    @property
    def found(self) -> bool:
        return self.has_original or self.has_updated

    @property
    def preferred_kind(self) -> str:
        if self.has_original:
            return "original"
        if self.has_updated:
            return "updated"
        return ""

    @property
    def preferred_html(self) -> str:
        return self.original_html or self.updated_html


def decode_aulete_bytes(data: bytes) -> str:
    """Decodifica HTML do aulete.com.br tolerando bytes Windows-1252/Latin-1 misturados a UTF-8."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    out: list[str] = []
    i = 0
    n = len(data)
    while i < n:
        try:
            out.append(data[i:].decode("utf-8"))
            break
        except UnicodeDecodeError as exc:
            if exc.start:
                out.append(data[i : i + exc.start].decode("utf-8"))
            pos = i + exc.start
            b = data[pos : pos + 1]
            try:
                out.append(b.decode("cp1252"))
            except UnicodeDecodeError:
                out.append(b.decode("latin-1"))
            i = pos + 1
    return "".join(out)


def _extract_div(html_text: str, div_id: str) -> str:
    m = re.search(rf'<div\b[^>]*\bid=["\']{re.escape(div_id)}["\'][^>]*>', html_text, re.I)
    if not m:
        return ""
    start = m.start()
    depth = 0
    for tm in re.finditer(r"<(/?)div\b[^>]*>", html_text[start:], re.I):
        depth += -1 if tm.group(1) else 1
        if depth == 0:
            return html_text[start : start + tm.end()]
    return html_text[start:]


def _unwrap_outer_div(div_html: str) -> str:
    if not div_html:
        return ""
    m = re.match(r"^\s*<div\b[^>]*>(.*)</div>\s*$", div_html, re.S | re.I)
    return m.group(1) if m else div_html


def _strip_not_found_banner(fragment: str) -> tuple[str, bool, str]:
    if "Não foi encontrado o verbete" not in fragment:
        return fragment, False, ""
    nearest = ""
    m = _NOT_FOUND_RE.search(fragment)
    if m:
        nearest = html.unescape(m.group("nearest") or "").strip()
        cleaned = fragment[: m.start()] + fragment[m.end() :]
        return cleaned, True, nearest
    return fragment, True, nearest


class _Sanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        if t in DROP_SUBTREE:
            self._skip_depth += 1
            return
        if self._skip_depth or t in DROP_VOID or t not in ALLOWED_TAGS:
            return
        if t in VOID_TAGS:
            self.out.append("<br/>")
            return
        cls_attr = ""
        for k, v in attrs:
            if k.lower() == "class" and v:
                kept = [c for c in v.split() if c in ALLOWED_CLASSES]
                if kept:
                    cls_attr = f' class="{html.escape(" ".join(kept), quote=True)}"'
                break
        self.out.append(f"<{t}{cls_attr}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        if self._skip_depth or t in DROP_SUBTREE or t in DROP_VOID:
            return
        if t in VOID_TAGS:
            self.out.append("<br/>")

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in DROP_SUBTREE:
            if self._skip_depth > 0:
                self._skip_depth -= 1
            return
        if self._skip_depth or t in VOID_TAGS or t in DROP_VOID or t not in ALLOWED_TAGS:
            return
        self.out.append(f"</{t}>")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth and data:
            self.out.append(html.escape(data, quote=False))


def _sanitize_html(fragment: str) -> str:
    parser = _Sanitizer()
    parser.feed(fragment)
    parser.close()
    return "".join(parser.out).strip()


def _plain_text(fragment: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment)).strip()


def _highlight_orig_separators(fragment: str) -> str:
    parts = _TAG_SPLIT_RE.split(fragment)
    for i in range(0, len(parts), 2):
        if "||" in parts[i]:
            parts[i] = parts[i].replace("||", '<span class="aulete-sep">||</span>')
    return "".join(parts)


def _clean_original(orig_div: str, tab_hidden: bool) -> str:
    if tab_hidden or not orig_div:
        return ""
    inner, _, _ = _strip_not_found_banner(_unwrap_outer_div(orig_div))
    inner = _HOMOGRAPH_ORIG_RE.sub(r"<h3>\1 <sup>\2</sup></h3>", inner)
    inner = _highlight_orig_separators(inner)
    cleaned = _sanitize_html(inner)
    cleaned = re.sub(r"^(?:\s*<br/>\s*)+|(?:\s*<br/>\s*)+$", "", cleaned)
    cleaned = re.sub(r"(?:\s*<br/>\s*)+(?=<h3>)", "", cleaned)
    if not _plain_text(cleaned):
        return ""
    if "<h3>" in cleaned or "<p" in cleaned:
        return f'<div class="aulete-orig">{cleaned}</div>'
    return f'<p class="aulete-orig">{cleaned}</p>'


def _clean_updated(atual_div: str, tab_hidden: bool) -> str:
    if tab_hidden or not atual_div or "{definicao}" in atual_div:
        return ""
    m = _FORM_RE.search(atual_div)
    inner = m.group(1) if m else _unwrap_outer_div(atual_div)
    inner, _, _ = _strip_not_found_banner(inner)
    inner = _EDICAO_DIV_RE.sub("", inner)
    inner = _LIGHTBOX_IMG_RE.sub("", inner)
    inner = _EMPTY_HOMOGRAPH_RE.sub("", inner)
    cleaned = _sanitize_html(inner)
    cleaned = re.sub(r"^(?:\s*<br/>\s*)+|(?:\s*<br/>\s*)+$", "", cleaned)
    if not _plain_text(cleaned):
        return ""
    return cleaned


def _extract_headword(html_text: str) -> str:
    m = _NOCAB_RE.search(html_text)
    if not m:
        return ""
    return html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()


def _entry_url(term: str) -> str:
    return BASE_URL + urllib.parse.quote(term.strip(), safe="")


def parse_aulete_page(query: str, raw: bytes, url: str = "") -> AuleteEntry:
    """Interpreta uma página de verbete de aulete.com.br."""
    q = query.strip()
    html_text = decode_aulete_bytes(raw)
    nocab = _extract_headword(html_text)
    abas = _extract_div(html_text, "abas_verbete")
    orig_div = _extract_div(html_text, "definicao_verbete_homologado_original")
    atual_div = _extract_div(html_text, "definicao_verbete_homologado")

    tab_orig_hidden = bool(_TAB_ORIG_HIDDEN_RE.search(abas))
    tab_atual_hidden = bool(_TAB_ATUAL_HIDDEN_RE.search(abas))
    updated_label = "Verbete Atualizado"
    tm = _TAB_ATUAL_RE.search(abas)
    if tm:
        lbl = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", tm.group(1)))).strip()
        if lbl:
            updated_label = lbl

    _, nf_orig, nearest_orig = _strip_not_found_banner(orig_div)
    _, nf_atual, nearest_atual = _strip_not_found_banner(atual_div)
    nearest = nocab or nearest_orig or nearest_atual

    if nf_orig or nf_atual:
        if not nocab or fold(nocab) != fold(q):
            return AuleteEntry(query=q, headword="", url=url or _entry_url(q), nearest=nearest)

    original_html = _clean_original(orig_div, tab_orig_hidden)
    updated_html = _clean_updated(atual_div, tab_atual_hidden)
    if not original_html and not updated_html:
        return AuleteEntry(query=q, headword="", url=url or _entry_url(q), nearest=nearest)

    headword = nocab or q
    return AuleteEntry(
        query=q,
        headword=headword,
        url=_entry_url(headword),
        original_html=original_html,
        updated_html=updated_html,
        updated_label=updated_label,
        nearest=nearest if nearest and nearest != headword else "",
    )


def _default_fetch(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


class AuleteClient:
    """Cliente HTTP síncrono com cache LRU thread-safe para aulete.com.br."""

    def __init__(
        self,
        fetcher: Callable[[str], bytes] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        cache_max: int = CACHE_MAX,
    ) -> None:
        self._fetcher = fetcher or (lambda url: _default_fetch(url, timeout))
        self._cache_max = max(1, cache_max)
        self._lock = threading.Lock()
        self._cache: OrderedDict[str, AuleteEntry] = OrderedDict()

    def get_cached(self, term: str) -> AuleteEntry | None:
        key = term.strip().lower()
        if not key:
            return None
        with self._lock:
            entry = self._cache.get(key)
            if entry is not None:
                self._cache.move_to_end(key)
            return entry

    def _put_cache(self, key: str, entry: AuleteEntry) -> None:
        with self._lock:
            self._cache[key] = entry
            self._cache.move_to_end(key)
            while len(self._cache) > self._cache_max:
                self._cache.popitem(last=False)

    def lookup(self, term: str) -> AuleteEntry:
        q = term.strip()
        if not q:
            return AuleteEntry(query="")
        cached = self.get_cached(q)
        if cached is not None:
            return cached
        url = _entry_url(q)
        try:
            raw = self._fetcher(url)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return AuleteEntry(query=q, url=url, error=str(exc))
        entry = parse_aulete_page(q, raw, url=url)
        self._put_cache(q.lower(), entry)
        return entry

    def get_cached_candidates(self, terms: list[str]) -> AuleteEntry | None:
        clean = [t.strip() for t in dict.fromkeys(terms) if t and t.strip()]
        if not clean:
            return None
        entries: list[AuleteEntry] = []
        for t in clean:
            e = self.get_cached(t)
            if e is None:
                return None
            if e.found:
                return e
            entries.append(e)
        return entries[0] if entries else None

    def lookup_candidates(self, terms: list[str]) -> AuleteEntry:
        clean = [t.strip() for t in dict.fromkeys(terms) if t and t.strip()]
        if not clean:
            return AuleteEntry(query="")
        first_miss: AuleteEntry | None = None
        for t in clean:
            entry = self.lookup(t)
            if entry.found or entry.error:
                return entry
            if first_miss is None or (entry.nearest and not first_miss.nearest):
                first_miss = entry
        return first_miss or AuleteEntry(query=clean[0], url=_entry_url(clean[0]))
