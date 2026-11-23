"""Dicionário: Dicionário Aberto + Wikcionário-pt -> abonario.db (entries, headwords, entries_fts)."""
from __future__ import annotations

import gzip
import html
import json
import re
import sqlite3
import xml.etree.ElementTree as ET

from common import CACHE, DB_PATH, check_disk, log
from mysqldump import iter_rows
from app.core.textnorm import fold

OUT = DB_PATH
SRC_DA, SRC_WIKT = 1, 2
FORM_GLOSS = re.compile(r"^(?:(?:primeira|segunda|terceira) pessoa\b.*\bd[oe] verbo|(?:feminino |masculino )?(?:singular|plural) d[eoa]s?\s+\S+\s*$|feminino d[eoa]\s+\S+\s*$)", re.I)

POS_PT = {
    "verb": "verbo", "noun": "substantivo", "adj": "adjetivo", "adv": "advérbio", "prep": "preposição",
    "conj": "conjunção", "pron": "pronome", "intj": "interjeição", "contraction": "contração",
    "num": "numeral", "article": "artigo", "phrase": "locução", "abbrev": "abreviatura",
    "prefix": "prefixo", "suffix": "sufixo", "name": "nome próprio", "proverb": "provérbio",
    "symbol": "símbolo", "particle": "partícula", "interfix": "interfixo", "character": "caractere",
}
TAG_PT = {
    "Brazil": "Brasil", "Brazilian": "Brasil", "Portugal": "Portugal", "Lusitanian": "Portugal",
    "Portuguese": "Portugal", "figuratively": "figurado", "colloquial": "coloquial", "informal": "informal",
    "popular": "popular", "pejorative": "pejorativo", "vulgar": "vulgar", "archaic": "arcaico",
    "obsolete": "obsoleto", "familiar": "familiar", "transitive": "transitivo", "intransitive": "intransitivo",
    "reflexive": "reflexivo", "pronominal": "pronominal", "rare": "raro", "poetic": "poético",
    "uncommon": "pouco usado", "ironic": "irônico", "dialectal": "dialetal", "derogatory": "depreciativo",
    "slang": "gíria", "Internet": "internet", "historical": "histórico", "Angola": "Angola",
    "Galicia": "Galiza", "Northeast-Brazil": "Nordeste do Brasil", "Southern-Brazil": "Sul do Brasil",
    "North-Brazil": "Norte do Brasil", "Anglicism": "anglicismo", "collective": "coletivo",
}


def esc(s: str) -> str:
    return html.escape(s, quote=False)


def italics(s: str) -> str:
    """_texto_ -> <i>texto</i> (convenção do Dicionário Aberto)."""
    return re.sub(r"_([^_]+)_", r"<i>\1</i>", s)


# ---------------------------------------------------------------------------
# Dicionário Aberto
# ---------------------------------------------------------------------------
def _inner(el: ET.Element) -> str:
    """Texto do elemento com <cit>/<ref> convertidos em HTML."""
    parts = [esc(el.text or "")]
    for ch in el:
        tag = ch.tag
        if tag == "cit":
            q = "".join(ch.itertext()).strip()
            parts.append(f'<span class="cit">{italics(esc(q))}</span>')
        elif tag == "ref":
            terms = [t for t in ch.iter("term")]
            if terms:
                txt = esc("".join(ch.itertext()))
                for t in terms:
                    w = (t.text or "").strip()
                    if w:
                        txt = txt.replace(esc(w), f'<a href="w:{html.escape(w)}">{esc(w)}</a>', 1)
                parts.append(txt)
            else:
                parts.append(esc("".join(ch.itertext())))
        else:
            parts.append(esc("".join(ch.itertext())))
        parts.append(esc(ch.tail or ""))
    return italics("".join(parts))


def render_da(xml: str) -> tuple[str, str, str, str]:
    """-> (lema exibido, classes, html, texto simples)."""
    root = ET.fromstring(xml)
    orth = (root.findtext("form/orth") or root.get("id") or "").strip()
    pron = (root.findtext("form/pron") or "").strip()
    out, plain, poses = [], [], []
    if pron:
        out.append(f'<p class="pron">[{esc(pron)}]</p>')
    for sense in root.findall("sense"):
        gram = (sense.findtext("gramGrp") or "").strip()
        usgs = [u.text.strip() for u in sense.findall("usg") if u.text and u.text.strip()]
        if gram:
            poses.append(gram)
        head = []
        if gram:
            head.append(f'<span class="gram">{esc(gram)}</span>')
        for u in usgs:
            head.append(f'<span class="usg">{esc(u)}</span>')
        if head:
            out.append('<p class="sensehead">' + " ".join(head) + "</p>")
        d = sense.find("def")
        if d is not None:
            body = _inner(d)
            lines = [l.strip() for l in body.split("\n") if l.strip()]
            if len(lines) == 1:
                out.append(f'<p class="def">{lines[0]}</p>')
            elif lines:
                out.append("<ol>" + "".join(f"<li>{l}</li>" for l in lines) + "</ol>")
            plain.append(re.sub(r"<[^>]+>", "", " ".join(lines)))
    et = root.find("etym")
    if et is not None:
        txt = _inner(et).strip()
        if txt:
            out.append(f'<p class="etym">{txt}</p>')
    return orth, "; ".join(dict.fromkeys(poses)), "\n".join(out), html.unescape(" ".join(plain))


def load_da() -> list[tuple]:
    words, revs = {}, {}
    for t, row in iter_rows(CACHE / "da_data.sql.xz", {"word", "revision"}):
        if t == "word":
            if row[4] == 0:
                words[row[0]] = row
        elif row[5] == 0:
            wid = row[1]
            if wid not in revs or row[0] > revs[wid][0]:
                revs[wid] = row
    out = []
    bad = 0
    for wid, w in words.items():
        r = revs.get(wid)
        if not r:
            continue
        try:
            orth, poses, body, plain = render_da(r[4])
        except ET.ParseError:
            bad += 1
            txt = re.sub(r"<[^>]+>", " ", r[4])
            orth, poses, body, plain = w[1], "", f'<p class="def">{italics(esc(txt.strip()))}</p>', txt
        key = w[1].strip().lower()
        out.append((key, w[1].strip(), int(w[2] or 0), poses, body, plain))
    log(f"Dicionário Aberto: {len(out)} verbetes ({bad} com XML irregular)")
    return out


# ---------------------------------------------------------------------------
# Wikcionário
# ---------------------------------------------------------------------------
def _example_html(ex: dict) -> str:
    text = ex.get("text", "")
    offs = sorted(ex.get("bold_text_offsets") or [])
    if offs:
        parts, last = [], 0
        for a, b in offs:
            if a < last:
                continue
            parts.append(esc(text[last:a]))
            parts.append(f"<b>{esc(text[a:b])}</b>")
            last = b
        parts.append(esc(text[last:]))
        t = "".join(parts)
    else:
        t = esc(text)
    ref = (ex.get("ref") or "").strip(" -;")
    r = f' <span class="ref">— {esc(ref)}</span>' if ref else ""
    return f'<div class="ex">{t}{r}</div>'


def render_wikt(d: dict) -> tuple[str, str, str] | None:
    senses = [s for s in d.get("senses", []) if not s.get("form_of") and s.get("glosses")
              and not FORM_GLOSS.search(s["glosses"][-1])]
    if not senses:
        return None
    pos = POS_PT.get(d.get("pos", ""), d.get("pos_title") or d.get("pos", ""))
    out, plain = [], []
    ipas = []
    for s in d.get("sounds", []) or []:
        if s.get("ipa"):
            tag = ", ".join(TAG_PT.get(t, t) for t in s.get("tags", []) or [] if t in TAG_PT)
            ipa = s["ipa"] + (f" ({tag})" if tag else "")
            if ipa not in ipas:
                ipas.append(ipa)
    out.append(f'<p class="sensehead"><span class="gram">{esc(pos)}</span>'
               + (f' <span class="pron">{esc("  ".join(ipas[:3]))}</span>' if ipas else "") + "</p>")
    items = []
    for s in senses:
        g = esc(s["glosses"][-1])
        labels = [TAG_PT[t] for t in s.get("tags", []) or [] if t in TAG_PT]
        labels += [t for t in s.get("raw_tags", []) or []]
        lab = f'<span class="usg">({esc(", ".join(dict.fromkeys(labels)))})</span> ' if labels else ""
        exs = "".join(_example_html(e) for e in (s.get("examples") or [])[:3])
        items.append(f"<li>{lab}{g}{exs}</li>")
        plain.append(s["glosses"][-1])
    out.append("<ol>" + "".join(items) + "</ol>")
    for key, label in (("synonyms", "Sinônimos"), ("antonyms", "Antônimos")):
        ws = [x.get("word") for x in d.get(key, []) or [] if x.get("word")]
        if ws:
            links = ", ".join(f'<a href="w:{html.escape(w)}">{esc(w)}</a>' for w in dict.fromkeys(ws[:15]))
            out.append(f'<p class="rel"><b>{label}:</b> {links}</p>')
    ety = " ".join(d.get("etymology_texts") or [])
    if ety:
        out.append(f'<p class="etym">{esc(ety[:600])}</p>')
    return pos, "\n".join(out), " ".join(plain)


def load_wikt() -> list[tuple]:
    out = []
    with gzip.open(CACHE / "wikt_pt.jsonl.gz", "rt", encoding="utf-8") as fh:
        for line in fh:
            d = json.loads(line)
            if d.get("lang_code") != "pt":
                continue
            w = (d.get("word") or "").strip()
            if not w:
                continue
            r = render_wikt(d)
            if r:
                pos, body, plain = r
                out.append((w.lower(), w, 0, pos, body, plain))
    log(f"Wikcionário: {len(out)} verbetes")
    return out


def build() -> None:
    check_disk()
    db = sqlite3.connect(OUT)
    db.executescript(
        """
        PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
        DROP TABLE IF EXISTS entries; DROP TABLE IF EXISTS headwords; DROP TABLE IF EXISTS entries_fts;
        CREATE TABLE entries(id INTEGER PRIMARY KEY, key TEXT NOT NULL, lemma TEXT NOT NULL, source INTEGER NOT NULL,
                             homograph INTEGER, pos TEXT, html TEXT NOT NULL);
        CREATE TABLE headwords(key TEXT PRIMARY KEY, lemma TEXT NOT NULL, fold TEXT NOT NULL,
                               srcmask INTEGER NOT NULL) WITHOUT ROWID;
        CREATE VIRTUAL TABLE entries_fts USING fts5(body, content='', detail=none,
                                                   tokenize='unicode61 remove_diacritics 2');
        """
    )
    heads: dict[str, list] = {}
    for src, rows in ((SRC_DA, load_da()), (SRC_WIKT, load_wikt())):
        rows.sort(key=lambda r: (r[0], r[2]))
        for key, lemma, hom, pos, body, plain in rows:
            cur = db.execute("INSERT INTO entries(key, lemma, source, homograph, pos, html) VALUES (?,?,?,?,?,?)",
                             (key, lemma, src, hom, pos, body))
            db.execute("INSERT INTO entries_fts(rowid, body) VALUES (?,?)", (cur.lastrowid, plain))
            h = heads.get(key)
            if h is None:
                heads[key] = [lemma, src]
            else:
                h[1] |= src
                if src == SRC_WIKT and lemma[:1].isupper() and not h[0][:1].isupper():
                    pass
    db.executemany("INSERT INTO headwords VALUES (?,?,?,?)",
                   ((k, l, fold(k), m) for k, (l, m) in heads.items()))
    db.execute("CREATE INDEX entries_key ON entries(key)")
    db.execute("CREATE INDEX headwords_fold ON headwords(fold)")
    db.commit()
    for t in ("entries", "headwords"):
        log(f"  {t}: {db.execute(f'SELECT count(*) FROM {t}').fetchone()[0]}")
    db.close()


if __name__ == "__main__":
    build()
