"""Leitura do dump do Wikisource em português: obras, autores e texto limpo."""
from __future__ import annotations

import bz2
import re
import sqlite3
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from common import CACHE, log

DUMP = CACHE / "ptwikisource.xml.bz2"
TMP_DB = CACHE / "ws_tmp.db"
KEEP_NS = {"0", "102", "104", "106"}

EXCLUDE_CATS = [
    "bíblia", "joão ferreira de almeida", "hino", "cantor cristão", "nobiliarchico", "trovadorismo",
    "galaico", "cantigas de amor", "cantigas de amigo", "cantigas de escárnio", "cantigas de santa maria",
    "cancioneiro geral", "cancioneiro de paris", "cancioneiro de elvas",
    "dicionário", "diccionario", "legislação", "lei ", "leis ", "lei orgânica", "constituição", "código",
    "decreto", "portaria", "resolução", "resoluções", "atos institucionais", "presidência do brasil",
    "tratado berakhot", "tao te ching", "holodomor", "ucrânia", "direito autoral", "psicoterapias",
    "pensar é preciso", "wikisource", "desambiguação", "marchas de carnaval", "ibge", "diário oficial",
]
STRUCT_TPL = {  # a própria página é lista/desambiguação (as obras ficam em subpáginas)
    "desambig", "desambiguação", "disambig", "minidesambig", "lista de versões", "versões",
    "cabeçalho para portais",
}
EXCLUDE_TPL = {
    "em tradução", "tradução colaborativa", "hino", "cc-by-sa-4.0",
    "cc-by-4.0", "cc-by-sa-3.0", "gfdl", "pd-self", "pd-brasil-gov", "pd-usgov", "aviso-lei",
    "dou-referenda1", "dou-sumário",
}
NATIONALITY = {"BRAn": "BR", "PRTn": "PT", "BRA-PRTn": "BR", "AGOn": "AO", "MOZn": "MZ", "CPVn": "CV"}

# -- predefinições -------------------------------------------------------------
TPL_TEXT = {  # predefinição -> texto literal
    "ss": "ss", "s": "s", "--": "—", "-": "-", "nop": "", "dhr": "\n", "gap": " ", "br": "\n",
    "espaços": " ", "nbsp": " ", "!": "|", "'": "'", "ae": "æ", "oe": "œ", "*": "*", "e": "e",
}
KEEP_LAST = {
    "c", "center", "centro", "centralizado", "sc", "sc2", "small caps", "smallcaps", "smaller", "small",
    "larger", "x-larger", "xx-larger", "xxx-larger", "xxxx-larger", "x-smaller", "grande", "right",
    "left", "direita", "esquerda", "alinhado à direita", "alinhar à direita", "alinhar à esquerda",
    "justificado", "serifa", "cursivo", "gótico", "uc", "lang", "sic", "reconstruído", "quote",
    "citação longa", "fine", "fine block", "underline", "romano", "verso", "parágrafo", "bd",
    "vermelho", "verde", "tooltip", "lsp", "ts", "block center", "block right", "bloco direito",
    "margem esquerda", "alinhamento deslocado", "ano", "k", "kt", "uso", "pt", "pl", "abv", "til",
}
KEEP_FIRST = {"capitular", "gcapitular", "dropinitial", "dropcap", "lh", "t2", "t3", "t4", "w", "a"}
HYPH_START = {"hws", "hífen", "começo de palavra hifenizada"}
HYPH_END = {"hwe", "hífen-fim", "término de palavra hifenizada"}
CORR = {"corr"}

_COMMENT = re.compile(r"<!--.*?-->", re.S)
_DROP_TAGS = re.compile(
    r"<(noinclude|ref|math|score|gallery|includeonly|timeline|syntaxhighlight|imagemap)\b[^>]*?(?:/>|>.*?</\1\s*>)",
    re.S | re.I)
_REF_SINGLE = re.compile(r"<ref\b[^>]*/>", re.I)
_LINK = re.compile(r"\[\[([^\[\]]*)\]\]")
_EXTLINK = re.compile(r"\[(?:https?:)?//[^\s\]]+\s*([^\]]*)\]")
_TPL = re.compile(r"\{\{([^{}]*)\}\}")
_TAG = re.compile(r"</?([a-zA-Z]+)\b[^>]*?/?>")
_BOLDITAL = re.compile(r"'{2,}")
_HEADING = re.compile(r"^\s*=+.*?=+\s*$", re.M)
_SECTION_TAG = re.compile(r"<section\b[^>]*/>", re.I)
_DROP_NS = re.compile(r"^\s*:?\s*(categoria|category|imagem|image|ficheiro|file|arquivo|media|"
                      r"[a-z]{2,3}(?:-[a-z]+)?)\s*:", re.I)
_PREFIX_NS = re.compile(r"^\s*:?\s*(autor|author|w|wikipedia|wikipédia|wikt|portal|página|galeria|s)\s*:\s*", re.I)
POEM_MARK = "\u0001"


def _link_sub(m: re.Match) -> str:
    inner = m.group(1)
    target, _, label = inner.partition("|")
    pm = _PREFIX_NS.match(target)
    if not pm and _DROP_NS.match(target):
        return ""
    if label:
        return label.split("|")[-1]
    t = _PREFIX_NS.sub("", target)
    return t.split("#")[0]


def _tpl_sub(m: re.Match) -> str:
    body = m.group(1)
    parts = body.split("|")
    name = parts[0].strip().lower().replace("_", " ")
    args = [p for p in parts[1:]]
    positional = [a for a in args if not re.match(r"^\s*[\w\s-]+\s*=", a)]
    if name in TPL_TEXT:
        return TPL_TEXT[name]
    if name in HYPH_START:
        return (positional[1] if len(positional) > 1 else (positional[0] if positional else "")).strip()
    if name in HYPH_END:
        return ""
    if name in CORR:
        return (positional[-1] if positional else "").strip()
    if name in KEEP_FIRST:
        return positional[0] if positional else ""
    if name in KEEP_LAST:
        return positional[-1] if positional else ""
    if not args and len(name) == 1:
        return name  # letras soltas usadas como predefinição
    return ""


def wikitext_to_text(wt: str) -> str:
    t = _COMMENT.sub("", wt)
    t = _DROP_TAGS.sub("", t)
    t = _REF_SINGLE.sub("", t)
    t = _SECTION_TAG.sub("", t)
    t = re.sub(r"##\s*[^#\n]+?\s*##", "", t)
    t = re.sub(r"__[A-ZÇÃ]+__", "", t)

    # <poem>: marca as linhas como verso
    def poem(m):
        lines = m.group(1).split("\n")
        return "\n\n" + "\n".join(POEM_MARK + l if l.strip() else "" for l in lines) + "\n\n"

    t = re.sub(r"<poem[^>]*>(.*?)</poem>", poem, t, flags=re.S | re.I)
    for _ in range(6):
        t2 = _LINK.sub(_link_sub, t)
        if t2 == t:
            break
        t = t2
    t = _EXTLINK.sub(lambda m: m.group(1), t)
    for _ in range(8):
        t2 = _TPL.sub(_tpl_sub, t)
        if t2 == t:
            break
        t = t2
    t = re.sub(r"\{\{|\}\}", "", t)
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    t = _TAG.sub("", t)
    t = _BOLDITAL.sub("", t)
    t = _HEADING.sub("", t)
    out_lines = []
    in_table = 0
    for line in t.split("\n"):
        s = line.strip()
        if s.startswith("{|"):
            in_table += 1
            continue
        if s.startswith("|}"):
            in_table = max(0, in_table - 1)
            continue
        if in_table or s.startswith(("|", "!")):
            continue
        if s.lstrip(POEM_MARK).startswith(("*", "#")):
            continue
        line = re.sub(r"^(\u0001?)\s*:+", r"\1", line)
        out_lines.append(line)
    t = "\n".join(out_lines)
    t = t.replace("&nbsp;", " ").replace("&mdash;", "—").replace("&ndash;", "–").replace("&amp;", "&")
    t = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), t)
    return t


# -- passagem 1: dump -> SQLite temporário ------------------------------------
def stage_dump() -> None:
    if TMP_DB.exists():
        log("Wikisource: banco temporário já existe")
        return
    part = TMP_DB.with_suffix(".part")
    if part.exists():
        part.unlink()
    db = sqlite3.connect(part)
    db.execute("PRAGMA journal_mode=OFF")
    db.execute("CREATE TABLE pages(ns INTEGER, title TEXT PRIMARY KEY, text TEXT)")
    n = 0
    batch = []
    with bz2.open(DUMP, "rb") as fh:
        for _, el in ET.iterparse(fh, events=("end",)):
            if not el.tag.endswith("}page"):
                continue
            ns = title = text = None
            redirect = False
            for sub in el:
                tag = sub.tag.rsplit("}", 1)[-1]
                if tag == "ns":
                    ns = sub.text
                elif tag == "title":
                    title = sub.text
                elif tag == "redirect":
                    redirect = True
                elif tag == "revision":
                    for r in sub:
                        if r.tag.endswith("}text"):
                            text = r.text or ""
            if ns in KEEP_NS and title and text and not redirect:
                batch.append((int(ns), title, text))
                n += 1
                if len(batch) >= 2000:
                    db.executemany("INSERT OR REPLACE INTO pages VALUES (?,?,?)", batch)
                    batch.clear()
            el.clear()
    db.executemany("INSERT OR REPLACE INTO pages VALUES (?,?,?)", batch)
    db.execute("CREATE INDEX pages_ns ON pages(ns, title)")
    db.commit()
    db.close()
    part.rename(TMP_DB)
    log(f"Wikisource: {n} páginas guardadas")


# -- metadados -------------------------------------------------------------------
def _param(text: str, name: str) -> str:
    # nomes de parâmetro sem espaços ([\w-]+) mantêm a busca linear (sem retrocesso exponencial)
    m = re.search(r"\|[ \t]*" + re.escape(name) + r"[ \t]*=[ \t]*(.*?)(?=\n[ \t]*\||\|[ \t]*[\w-]+[ \t]*=|\n?\}\}|$)",
                  text, re.S | re.I)
    v = m.group(1).strip() if m else ""
    return "" if v.startswith("|") else v


def _plain(v: str) -> str:
    v = _LINK.sub(_link_sub, v)
    v = _TPL.sub("", v)
    v = re.sub(r"<[^>]+>", "", v)
    return re.sub(r"\s+", " ", v).strip(" ,;.")


def _link_target(v: str) -> str:
    m = re.search(r"\[\[\s*(?:Autor|Author)\s*:\s*([^\]|]+)", v, re.I)
    return m.group(1).strip() if m else _plain(v)


def _year(v: str) -> int | None:
    m = re.search(r"\b(1[2-9]\d\d)\b", v or "")
    return int(m.group(1)) if m else None


@dataclass
class Author:
    name: str
    birth: int | None = None
    death: int | None = None
    country: str = ""


def load_authors(db: sqlite3.Connection) -> dict[str, Author]:
    out: dict[str, Author] = {}
    for title, text in db.execute("SELECT title, text FROM pages WHERE ns=102"):
        key = title.split(":", 1)[1].strip()
        nat = _param(text, "nacionalidade")
        country = ""
        m = re.search(r"\{\{\s*([A-Z\-]+n)\b", nat)
        if m:
            country = NATIONALITY.get(m.group(1), "XX")
        elif re.search(r"brasil", nat, re.I):
            country = "BR"
        elif re.search(r"portug", nat, re.I):
            country = "PT"
        name = _plain(_param(text, "nome")) or key
        out[key] = Author(name, _year(_param(text, "data_nascimento")), _year(_param(text, "data_morte")), country)
    return out


@dataclass
class IndexInfo:
    title: str = ""
    author: str = ""
    translator: str = ""
    year: int | None = None


def load_indexes(db: sqlite3.Connection) -> dict[str, IndexInfo]:
    out = {}
    for title, text in db.execute("SELECT title, text FROM pages WHERE ns=104"):
        key = title.split(":", 1)[1].strip()
        out[key] = IndexInfo(_plain(_param(text, "Título")), _link_target(_param(text, "Autor")),
                             _link_target(_param(text, "Tradutor")), _year(_param(text, "Ano")))
    return out


# -- montagem de páginas transcluídas -------------------------------------------
_PAGES_TAG = re.compile(r"<pages\b([^>]*?)/?>", re.I)


def _attrs(s: str) -> dict[str, str]:
    return {k.lower(): (v1 or v2 or v3) for k, v1, v2, v3 in
            re.findall(r"(\w+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s/>]+))", s)}


def _section(text: str, name: str, begin: bool) -> str:
    """Recorta o texto a partir (begin) ou até (not begin) da seção `name`."""
    if begin:
        m = re.search(r"<section\s+begin\s*=\s*[\"']?" + re.escape(name) + r"[\"']?\s*/>", text, re.I) \
            or re.search(r"##\s*" + re.escape(name) + r"\s*##", text)
        return text[m.end():] if m else text
    m = re.search(r"<section\s+end\s*=\s*[\"']?" + re.escape(name) + r"[\"']?\s*/>", text, re.I)
    if m:
        return text[:m.start()]
    m = re.search(r"##\s*" + re.escape(name) + r"\s*##", text)
    if m:
        nxt = re.search(r"##\s*[^#\n]+?\s*##", text[m.end():])
        return text[:m.end() + nxt.start()] if nxt else text
    return text


def _ranges(spec: str) -> list[int]:
    out = []
    for part in re.split(r"[,\s]+", spec or ""):
        if "-" in part:
            a, _, b = part.partition("-")
            if a.isdigit() and b.isdigit():
                out.extend(range(int(a), int(b) + 1))
        elif part.isdigit():
            out.append(int(part))
    return out


def expand_pages(wt: str, db: sqlite3.Connection) -> tuple[str, list[str]]:
    used_indexes = []

    def sub(m: re.Match) -> str:
        a = _attrs(m.group(1))
        index = a.get("index", "")
        if not index or not re.search(r"\.(djvu|pdf)$", index, re.I):
            return ""
        used_indexes.append(index)
        nums = []
        if a.get("from", "").isdigit():
            start = int(a["from"])
            end = int(a["to"]) if a.get("to", "").isdigit() else start
            nums = list(range(start, end + 1))
        nums += [n for n in _ranges(a.get("include", "")) if n not in nums]
        excl = set(_ranges(a.get("exclude", "")))
        nums = [n for n in nums if n not in excl][:1500]
        texts = []
        for i, n in enumerate(nums):
            row = db.execute("SELECT text FROM pages WHERE title=?", (f"Página:{index}/{n}",)).fetchone()
            if not row:
                continue
            pt = row[0]
            if i == 0 and a.get("fromsection"):
                pt = _section(pt, a["fromsection"], True)
            if i == len(nums) - 1 and a.get("tosection"):
                pt = _section(pt, a["tosection"], False)
            texts.append(pt)
        return "\n".join(texts)

    return _PAGES_TAG.sub(sub, wt), used_indexes


# -- obras -----------------------------------------------------------------------
@dataclass
class WsWork:
    key: str
    title: str
    author: str = ""
    translator: str = ""
    year: int | None = None
    country: str = ""
    texts: list[str] = field(default_factory=list)


def _categories(wt: str) -> list[str]:
    return [c.strip() for c in re.findall(r"\[\[\s*Categoria\s*:\s*([^\]|]+)", wt, re.I)]


def _templates(wt: str) -> set[str]:
    return {m.strip().lower() for m in re.findall(r"\{\{\s*([^|}\n<]+?)\s*(?=[|}])", wt)}


def _country_from_cats(cats: list[str]) -> str:
    j = " ".join(cats).lower()
    if re.search(r"brasileir|brasil|brazil", j):
        return "BR"
    if re.search(r"portugu", j):
        return "PT"
    return ""


def _excluded(title: str, wt: str, structural: bool = True) -> bool:
    if wt.lstrip().upper().startswith(("#REDIREC", "#REDIRECT")) or title.startswith("Tradução:"):
        return True
    tpls = _templates(wt)
    if tpls & EXCLUDE_TPL or (structural and tpls & STRUCT_TPL):
        return True
    lc = " | ".join(_categories(wt)).lower()
    return any(x in lc for x in EXCLUDE_CATS)


def _meta(title: str, wt: str, indexes: dict[str, IndexInfo], authors: dict[str, Author]):
    cats = _categories(wt)
    nav = re.search(r"\{\{\s*[Nn]avegar(.*?)\n?\}\}", wt, re.S)
    navt = nav.group(1) if nav else ""
    used = [a.get("index", "") for a in (_attrs(m.group(1)) for m in _PAGES_TAG.finditer(wt))]
    idx = indexes.get(used[0]) if used else None
    author_key = _link_target(_param(navt, "author_override") or _param(navt, "autor")) if navt else ""
    if not author_key and idx:
        author_key = idx.author
    if not author_key:  # categoria com o nome de um autor conhecido
        author_key = next((c for c in cats if c in authors), "")
    translator = _link_target(_param(navt, "tradutor")) if navt else ""
    if not translator and idx:
        translator = idx.translator
    root = title.split("/")[0]
    work_title = _plain(_param(navt, "obra")) if navt else ""
    if not work_title or "/" in title:
        work_title = idx.title if idx and idx.title else root
    year = None
    for c in cats:
        m = re.fullmatch(r"(?:Obras publicadas em )?(1[5-9]\d\d)", c)
        if m:
            year = int(m.group(1))
            break
    year = year or _year(_param(navt, "ano")) or (idx.year if idx else None)
    return cats, author_key, translator, root, work_title, year


def iter_pages(db: sqlite3.Connection, authors: dict[str, Author], indexes: dict[str, IndexInfo]
               ) -> Iterator[tuple[WsWork, str]]:
    """Gera (metadados da obra, texto limpo) para cada página principal aproveitável."""
    # 1) raízes excluídas e votos de país por autor (categorias de todas as suas obras)
    excluded_roots: set[str] = set()
    votes: dict[str, dict[str, int]] = {}
    for title, wt in db.execute("SELECT title, text FROM pages WHERE ns=0"):
        if "/" not in title and _excluded(title, wt, structural=False):
            excluded_roots.add(title)
            continue
        cats, author_key, *_ = _meta(title, wt, indexes, authors)
        c = _country_from_cats(cats)
        if author_key and c:
            v = votes.setdefault(author_key, {})
            v[c] = v.get(c, 0) + 1
    for key, v in votes.items():
        a = authors.setdefault(key, Author(key))
        if not a.country:
            a.country = max(v, key=v.get)
    log(f"Wikisource: {len(excluded_roots)} obras-raiz excluídas")

    # 2) páginas
    for title, wt in db.execute("SELECT title, text FROM pages WHERE ns=0 ORDER BY title"):
        root = title.split("/")[0]
        if root in excluded_roots or _excluded(title, wt):
            continue
        cats, author_key, translator, root, work_title, year = _meta(title, wt, indexes, authors)
        body, used = expand_pages(wt, db)
        if not used and len(wt) < 150:
            continue
        a = authors.get(author_key)
        t = authors.get(translator)
        country = (t.country if t and t.country else "") or (a.country if a else "") or _country_from_cats(cats)
        if country in ("", "XX") and not (year and year <= 1950):
            continue  # estrangeiro/sem metadados e sem data antiga: provável texto moderno
        work = WsWork(key=root, title=work_title, author=author_key, translator=translator,
                      year=year, country=country)
        yield work, wikitext_to_text(body)
