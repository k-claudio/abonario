"""Corpus de abonações: Wikisource + Gutenberg -> authors, works, sentences, sent_fts,
variants e term_freq."""
from __future__ import annotations

import gzip
import os
import hashlib
import json
import random
import re
import sqlite3
import time

from common import CACHE, DB_PATH, check_disk, log
from build_lexicon import load_normalizer
from textproc import gutenberg_units, text_units
from app.core.textnorm import WORD_RE, skel2
import wikisource as ws

LIMIT = int(os.environ.get("ABONARIO_LIMIT", "0"))  # teste rápido
RK_SPACE = 1 << 24  # identificadores aleatórios dos trechos (ordem do índice = ordem aleatória)

BR_PATTERNS = [
    "Machado de Assis", "Alencar, José", "José de Alencar", "Taunay", "Barreto, Lima", "Lima Barreto",
    "Pompéia", "Pompeia", "Azevedo, Aluísio", "Aluísio Azevedo", "Azevedo, Álvares", "Álvares de Azevedo",
    "Azevedo, Artur", "Azevedo, Arthur", "Artur Azevedo", "Bilac", "Castro Alves", "Gonçalves Dias",
    "Almeida, Manuel Antônio", "Macedo, Joaquim Manuel", "Joaquim Manuel de Macedo", "Euclides da Cunha",
    "Cunha, Euclides", "Lobato", "Graça Aranha", "Veríssimo, José", "Coelho Neto", "Cruz e Sousa",
    "Guimarães, Bernardo", "Bernardo Guimarães", "Romero, Sílvio", "Nabuco", "Barbosa, Rui", "Ruy Barbosa",
    "Rui Barbosa", "Fagundes Varela", "Varela, Fagundes", "Casimiro de Abreu", "Abreu, Casimiro",
    "Martins Pena", "Penna, Martins", "Pena, Martins", "Gonçalves de Magalhães", "Porto-Alegre",
    "França Júnior", "Afonso Arinos", "Raimundo Correia", "Alberto de Oliveira", "Lopes Neto",
    "Augusto dos Anjos", "Humberto de Campos", "Gregório de Matos", "Basílio da Gama", "Santa Rita Durão",
    "Tomás Antônio Gonzaga", "Alvarenga Peixoto", "Cláudio Manuel da Costa", "Silva Alvarenga",
    "Franklin Távora", "Júlio Ribeiro", "Adolfo Caminha", "Afrânio Peixoto", "João do Rio",
    "Patrocínio", "Varnhagen", "Capistrano de Abreu", "Alphonsus de Guimaraens", "Vicente de Carvalho",
    "Júlia Lopes de Almeida", "Junqueira Freire", "Sousândrade", "Medeiros e Albuquerque", "Rocha Pombo",
    "Afonso Celso", "Visconde de Taunay", "Manuel Antônio de Almeida", "Raul Pompeia", "Olavo Bilac",
]
NAME_OVERRIDES = {
    "Alencar, José Martiniano de": "José de Alencar",
    "Almeida Garrett, João Batista da Silva Leitão de Almeida Garrett, Visconde de": "Almeida Garrett",
    "Taunay, Alfredo d'Escragnolle Taunay, Visconde de": "Visconde de Taunay",
    "Bocage, Manuel Maria Barbosa du": "Bocage",
    "Junqueiro, Abílio Manuel Guerra": "Guerra Junqueiro",
    "Queirós, Eça de": "Eça de Queirós",
    "Pompéia, Raul": "Raul Pompeia",
}


GENERIC_AUTHORS = {"Anonymous": "Anônimo", "Unknown": "Autor desconhecido", "Various": "Vários"}
# obras de referência não são abonações literárias
NON_LITERARY_TITLE = re.compile(r"dic+ion[aá]rio|vocabul[aá]rio|gloss[aá]rio|gram+[aá]tica|ortogra(?:ph|f)ia|"
                                r"prontu[aá]rio|tabuada|catálogo|catalogo", re.I)


def parse_pg_author(s: str) -> tuple[str, int | None, int | None, str]:
    s = s.strip()
    role = ""
    m = re.search(r"\[([^\]]+)\]\s*$", s)
    if m:
        role = m.group(1)
        s = s[: m.start()].strip()
    birth = death = None
    m = re.search(r",\s*(?:BCE?\s*)?(\d{1,4})\??\s*(?:BCE?)?\s*-\s*(\d{1,4})?\??\s*(?:BCE?)?\s*$", s)
    if m:
        birth = int(m.group(1))
        death = int(m.group(2)) if m.group(2) else None
        s = s[: m.start()].strip()
    key = re.sub(r"\s*\([^)]*\)", "", s).strip()
    if key in NAME_OVERRIDES:
        return NAME_OVERRIDES[key], birth, death, role
    if key in GENERIC_AUTHORS:
        return GENERIC_AUTHORS[key], birth, death, role
    parts = [p.strip() for p in key.split(",") if p.strip()]
    if len(parts) >= 2:
        name = parts[1] if parts[0] in parts[1] else f"{parts[1]} {parts[0]}"
    else:
        name = parts[0] if parts else s
    return name, birth, death, role


def is_br(raw: str, name: str) -> bool:
    return any(p in raw or p in name for p in BR_PATTERNS)


class CorpusWriter:
    def __init__(self, db: sqlite3.Connection, normalizer) -> None:
        self.db = db
        self.N = normalizer
        self.author_ids: dict[str, int] = {}
        self.author_country: dict[str, str] = {}
        self.work_ids: dict[tuple[str, str], int] = {}
        self.seen: set[int] = set()
        self.used_rk: set[int] = set()
        self.skel_memo: dict[str, str] = {}
        self.next_sid = 1
        self.sent_rows: list[tuple] = []
        self.fts_rows: list[tuple] = []
        self.work_counts: dict[int, int] = {}
        self.dups = 0
        self.rng = random.Random(20261123)

    def author(self, name: str, birth=None, death=None, country: str = "") -> int | None:
        name = (name or "").strip()
        if not name:
            return None
        aid = self.author_ids.get(name)
        if aid is None:
            cur = self.db.execute("INSERT INTO authors(name, birth, death, country) VALUES (?,?,?,?)",
                                  (name, birth, death, country))
            aid = self.author_ids[name] = cur.lastrowid
            self.author_country[name] = country
        else:
            if country and not self.author_country.get(name):
                self.db.execute("UPDATE authors SET country=? WHERE id=?", (country, aid))
                self.author_country[name] = country
            if birth or death:
                self.db.execute("UPDATE authors SET birth=coalesce(birth,?), death=coalesce(death,?) WHERE id=?",
                                (birth, death, aid))
        return aid

    def work(self, source: str, key: str, title: str, author_id, translator: str, year, country: str,
             ref: str) -> int:
        wid = self.work_ids.get((source, key))
        if wid is None:
            cur = self.db.execute(
                "INSERT INTO works(author_id, title, translator, year, country, source, ref) VALUES (?,?,?,?,?,?,?)",
                (author_id, title, translator or None, year, country, source, ref))
            wid = self.work_ids[(source, key)] = cur.lastrowid
        return wid

    def _dedup_key(self, unit: str) -> int:
        sk = []
        memo = self.skel_memo
        for w in WORD_RE.findall(unit):
            lw = w.lower()
            s = memo.get(lw)
            if s is None:
                s = memo[lw] = skel2(lw)
            sk.append(s)
        return int.from_bytes(hashlib.blake2b(" ".join(sk).encode(), digest_size=8).digest(), "little")

    def add_units(self, work_id: int, units: list[str]) -> None:
        for u in units:
            u = u.replace("ſ", "s")  # s longo das edições antigas
            k = self._dedup_key(u)
            if k in self.seen:
                self.dups += 1
                continue
            self.seen.add(k)
            rk = self.rng.randrange(1, RK_SPACE)
            while rk in self.used_rk:
                rk = self.rng.randrange(1, RK_SPACE)
            self.used_rk.add(rk)
            terms = dict.fromkeys(self.N.terms_for_text(u))
            self.sent_rows.append((self.next_sid, work_id, rk, u))
            self.fts_rows.append((rk, " ".join(terms)))
            self.next_sid += 1
            self.work_counts[work_id] = self.work_counts.get(work_id, 0) + 1
        if len(self.sent_rows) >= 20000:
            self.flush()

    def flush(self) -> None:
        if self.sent_rows:
            self.db.executemany("INSERT INTO sentences(id, work_id, rk, text) VALUES (?,?,?,?)", self.sent_rows)
            self.db.executemany("INSERT INTO sent_fts(rowid, terms) VALUES (?,?)", self.fts_rows)
            self.sent_rows.clear()
            self.fts_rows.clear()


def create_tables(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA cache_size=-200000;
        DROP TABLE IF EXISTS authors; DROP TABLE IF EXISTS works; DROP TABLE IF EXISTS sentences;
        DROP TABLE IF EXISTS sent_fts; DROP TABLE IF EXISTS variants; DROP TABLE IF EXISTS term_freq;
        CREATE TABLE authors(id INTEGER PRIMARY KEY, name TEXT NOT NULL, birth INTEGER, death INTEGER, country TEXT);
        CREATE TABLE works(id INTEGER PRIMARY KEY, author_id INTEGER, title TEXT, translator TEXT, year INTEGER,
                           country TEXT, source TEXT, ref TEXT, nsent INTEGER);
        CREATE TABLE sentences(id INTEGER PRIMARY KEY, work_id INTEGER NOT NULL, rk INTEGER NOT NULL, text TEXT NOT NULL);
        CREATE VIRTUAL TABLE sent_fts USING fts5(terms, content='', detail=none,
            tokenize="unicode61 remove_diacritics 0 tokenchars '-'''");
        CREATE TABLE variants(tok TEXT PRIMARY KEY, terms TEXT NOT NULL) WITHOUT ROWID;
        CREATE TABLE term_freq(term TEXT PRIMARY KEY, n INTEGER NOT NULL) WITHOUT ROWID;
        """
    )


def do_wikisource(cw: CorpusWriter) -> None:
    ws.stage_dump()
    tdb = sqlite3.connect(ws.TMP_DB)
    authors = ws.load_authors(tdb)
    indexes = ws.load_indexes(tdb)
    n = 0
    for w, text in ws.iter_pages(tdb, authors, indexes):
        a = authors.get(w.author)
        aid = cw.author(a.name if a else w.author, a.birth if a else None, a.death if a else None,
                        a.country if a and a.country not in ("XX",) else "")
        tr = authors.get(w.translator)
        translator = tr.name if tr else w.translator
        wid = cw.work("wikisource", w.key, w.title, aid, translator, w.year, w.country, w.key)
        cw.add_units(wid, text_units(text))
        n += 1
        if LIMIT and n >= LIMIT:
            break
        if n % 2000 == 0:
            log(f"  Wikisource: {n} páginas, {cw.next_sid - 1} trechos")
            check_disk()
    cw.flush()
    log(f"Wikisource OK: {n} páginas, {cw.next_sid - 1} trechos, {cw.dups} duplicados")


def do_gutenberg(cw: CorpusWriter) -> None:
    rows = json.loads((CACHE / "gutenberg" / "catalog_pt.json").read_text(encoding="utf-8"))
    n = 0
    for row in rows:
        path = CACHE / "gutenberg" / f"{row['Text#']}.txt.gz"
        if not path.exists() or NON_LITERARY_TITLE.search(row["Title"]):
            continue
        authors = [parse_pg_author(a) for a in row["Authors"].split(";") if a.strip()]
        raws = [a for a in row["Authors"].split(";") if a.strip()]
        main = next((a for a in authors if a[3] in ("", "Author")), authors[0] if authors else ("", None, None, ""))
        trans = next((a for a in authors if "Translator" in a[3]), None)
        main_raw = raws[authors.index(main)] if authors else ""
        def country_of(name, raw):
            known = cw.author_country.get(name)
            if known:
                return known
            if is_br(raw, name) or re.search(r"Brazilian|Brazil -- Fiction", row["Subjects"]):
                return "BR"
            return "PT"
        if trans:
            t_raw = raws[authors.index(trans)]
            country = country_of(trans[0], t_raw)
            cw.author(trans[0], trans[1], trans[2], country)
            aid = cw.author(main[0], main[1], main[2], cw.author_country.get(main[0], ""))
            translator = trans[0]
        else:
            country = country_of(main[0], main_raw)
            aid = cw.author(main[0], main[1], main[2], country)
            translator = None
        title = re.sub(r"\s*\n\s*", ": ", row["Title"].strip())
        title = re.sub(r"\s+", " ", title)
        wid = cw.work("gutenberg", row["Text#"], title, aid, translator, None, country, row["Text#"])
        raw = gzip.decompress(path.read_bytes()).decode("utf-8")
        cw.add_units(wid, gutenberg_units(raw))
        n += 1
        if LIMIT and n >= max(3, LIMIT // 20):
            break
        if n % 50 == 0:
            log(f"  Gutenberg: {n} livros, {cw.next_sid - 1} trechos")
            check_disk()
    cw.flush()
    log(f"Gutenberg OK: {n} livros, {cw.next_sid - 1} trechos, {cw.dups} duplicados")


def build() -> None:
    check_disk()
    t0 = time.time()
    db = sqlite3.connect(DB_PATH)
    N = load_normalizer(db)
    log("normalizador carregado")
    create_tables(db)
    cw = CorpusWriter(db, N)
    do_wikisource(cw)
    db.commit()
    do_gutenberg(cw)
    db.executemany("UPDATE works SET nsent=? WHERE id=?", ((n, w) for w, n in cw.work_counts.items()))
    db.commit()
    log("gravando variantes...")
    db.executemany("INSERT OR IGNORE INTO variants VALUES (?,?)",
                   ((t, " ".join(r)) for t, r in N.memo.items() if r != [t] and t))
    log("índices auxiliares...")
    db.execute("CREATE UNIQUE INDEX sentences_rk ON sentences(rk)")
    db.execute("CREATE INDEX sentences_work ON sentences(work_id)")
    db.commit()
    log("otimizando índice de texto (pode demorar)...")
    db.execute("INSERT INTO sent_fts(sent_fts) VALUES('optimize')")
    db.commit()
    db.execute("CREATE VIRTUAL TABLE temp.vocab USING fts5vocab(main, sent_fts, row)")
    db.execute("INSERT INTO term_freq SELECT term, doc FROM temp.vocab")
    db.commit()
    for t in ("authors", "works", "sentences", "variants", "term_freq"):
        log(f"  {t}: {db.execute(f'SELECT count(*) FROM {t}').fetchone()[0]}")
    db.close()
    log(f"corpus pronto em {(time.time() - t0) / 60:.1f} min")


if __name__ == "__main__":
    build()
