"""Acesso somente leitura ao banco abonario.db (nenhum acesso à rede)."""
from __future__ import annotations

import bisect
import os
import sqlite3
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from .textnorm import fold, make_terms_lookup

DB_NAME = "abonario.db"


def find_db() -> Path | None:
    """Procura o banco ao lado do executável, na pasta data/ do projeto ou em %LOCALAPPDATA%."""
    here = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve()
    candidates = []
    if getattr(sys, "frozen", False):
        candidates += [here.parent / DB_NAME, here.parent / "data" / DB_NAME]
    else:
        root = here.parents[2]
        candidates += [root / "data" / DB_NAME]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "Programs" / "Abonario" / DB_NAME)
    env = os.environ.get("ABONARIO_DB")
    if env:
        candidates.insert(0, Path(env))
    return next((c for c in candidates if c.exists()), None)


@dataclass
class Work:
    id: int
    title: str
    author: str
    birth: int | None
    death: int | None
    country: str
    year: int | None
    translator: str | None
    source: str
    ref: str

    def citation(self) -> str:
        who = self.author or "Autor desconhecido"
        if self.birth or self.death:
            who += f" ({self.birth or '?'}–{self.death or '?'})"
        s = f"{who}, {self.title}"
        if self.translator:
            s += f", trad. {self.translator}"
        if self.year:
            s += f" ({self.year})"
        return s


@dataclass
class Sentence:
    id: int
    rk: int
    work: Work
    text: str


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._local = threading.local()
        c = self.conn
        self.works: dict[int, Work] = {}
        for row in c.execute(
            "SELECT w.id, w.title, coalesce(a.name,''), a.birth, a.death, coalesce(w.country,''), w.year, "
            "w.translator, w.source, w.ref FROM works w LEFT JOIN authors a ON a.id = w.author_id"
        ):
            self.works[row[0]] = Work(*row)
        self.terms_for = make_terms_lookup(self.variant)
        self._heads: list[tuple[str, str]] | None = None
        self._head_folds: list[str] | None = None
        self.stats = {
            "verbetes": c.execute("SELECT count(*) FROM headwords").fetchone()[0],
            "formas": c.execute("SELECT count(*) FROM forms").fetchone()[0],
            "trechos": c.execute("SELECT max(id) FROM sentences").fetchone()[0] or 0,
            "obras": len(self.works),
        }

    # uma conexão por thread (consultas longas rodam fora da interface)
    @property
    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            uri = self.path.resolve().as_uri() + "?mode=ro&immutable=1"
            c = sqlite3.connect(uri, uri=True, check_same_thread=False)
            c.execute("PRAGMA cache_size=-64000")
            c.execute("PRAGMA mmap_size=268435456")
            self._local.conn = c
        return c

    # -- lista de verbetes -----------------------------------------------------
    def headwords(self) -> list[tuple[str, str]]:
        """[(chave, lema)] em ordem alfabética sem acentos."""
        if self._heads is None:
            rows = self.conn.execute("SELECT key, lemma, fold FROM headwords").fetchall()
            rows.sort(key=lambda r: (r[2], r[0]))
            self._heads = [(k, l) for k, l, _ in rows]
            self._head_folds = [f for _, _, f in rows]
        return self._heads

    def headword_position(self, prefix: str) -> int:
        self.headwords()
        return bisect.bisect_left(self._head_folds, fold(prefix))

    def is_headword(self, key: str) -> bool:
        return self.conn.execute("SELECT 1 FROM headwords WHERE key=?", (key.lower(),)).fetchone() is not None

    def headword_lemma(self, key: str) -> str | None:
        r = self.conn.execute("SELECT lemma FROM headwords WHERE key=?", (key.lower(),)).fetchone()
        return r[0] if r else None

    def headwords_by_fold(self, f: str) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT key FROM headwords WHERE fold=?", (f,))]

    def headwords_glob(self, pattern: str, limit: int = 300) -> list[str]:
        return [r[0] for r in self.conn.execute(
            "SELECT key FROM headwords WHERE key GLOB ? ORDER BY fold LIMIT ?", (pattern, limit))]

    def headwords_prefix(self, prefix: str, limit: int = 20) -> list[str]:
        f = fold(prefix)
        return [r[0] for r in self.conn.execute(
            "SELECT key FROM headwords WHERE fold >= ? AND fold < ? ORDER BY fold LIMIT ?",
            (f, f + "\uffff", limit))]

    def entries(self, key: str) -> list[tuple]:
        return self.conn.execute(
            "SELECT lemma, source, homograph, pos, html FROM entries WHERE key=? ORDER BY source, homograph, id",
            (key.lower(),)).fetchall()

    def search_definitions(self, query: str, limit: int = 300) -> list[str]:
        q = " ".join(f'"{w}"' for w in query.replace('"', " ").split())
        try:
            rows = self.conn.execute(
                "SELECT DISTINCT e.key FROM entries_fts f JOIN entries e ON e.id = f.rowid "
                "WHERE entries_fts MATCH ? LIMIT ?", (q, limit)).fetchall()
        except sqlite3.OperationalError:
            return []
        return [r[0] for r in rows]

    # -- morfologia ------------------------------------------------------------------
    def lemmas_of(self, form: str) -> list[tuple[str, str | None]]:
        return self.conn.execute("SELECT lemma, tags FROM forms WHERE form=?", (form.lower(),)).fetchall()

    def forms_of(self, lemma: str) -> list[tuple[str, str | None]]:
        return self.conn.execute("SELECT form, tags FROM forms WHERE lemma=?", (lemma,)).fetchall()

    def folded_forms(self, f: str) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT form FROM formfold WHERE fold=?", (f,))]

    def known_form(self, w: str) -> bool:
        c = self.conn
        return bool(c.execute("SELECT 1 FROM forms WHERE form=? LIMIT 1", (w,)).fetchone()
                    or c.execute("SELECT 1 FROM headwords WHERE key=?", (w,)).fetchone())

    def in_mechura(self, w: str) -> bool:
        """A palavra consta da lista moderna de lematização (forma ou lema)?"""
        c = self.conn
        return bool(c.execute("SELECT 1 FROM forms WHERE form=? AND src & 1 LIMIT 1", (w,)).fetchone()
                    or c.execute("SELECT 1 FROM forms WHERE lemma=? AND src & 1 LIMIT 1", (w,)).fetchone())

    def alt_modern(self, old: str) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT modern FROM alt WHERE old=?", (old.lower(),))]

    def variant(self, tok: str) -> str | None:
        r = self.conn.execute("SELECT terms FROM variants WHERE tok=?", (tok,)).fetchone()
        return r[0] if r else None

    def lemma_count(self, forms: list[str]) -> dict[str, int]:
        """Nº de lemas distintos por forma (para marcar formas ambíguas)."""
        out: dict[str, int] = {}
        for i in range(0, len(forms), 500):
            chunk = forms[i:i + 500]
            q = ",".join("?" * len(chunk))
            for f, n in self.conn.execute(
                    f"SELECT form, count(DISTINCT lower(lemma)) FROM forms WHERE form IN ({q}) GROUP BY form", chunk):
                out[f] = n
        return out

    # -- corpus ------------------------------------------------------------------------
    def freq(self, terms: list[str]) -> dict[str, int]:
        out: dict[str, int] = {}
        for i in range(0, len(terms), 500):
            chunk = terms[i:i + 500]
            q = ",".join("?" * len(chunk))
            out.update(self.conn.execute(f"SELECT term, n FROM term_freq WHERE term IN ({q})", chunk).fetchall())
        return out

    @staticmethod
    def match_expr(terms: list[str], op: str = "OR") -> str:
        """Expressão FTS5: cada termo entre aspas (termos são palavras isoladas)."""
        return f" {op} ".join('"' + t.replace('"', "") + '"' for t in terms if t)

    def count_sentences(self, terms: list[str], op: str = "OR") -> int:
        if not terms:
            return 0
        try:
            return self.conn.execute("SELECT count(*) FROM sent_fts WHERE sent_fts MATCH ?",
                                     (self.match_expr(terms, op),)).fetchone()[0]
        except sqlite3.OperationalError:
            return 0

    def count_filtered(self, terms: list[str], accept, op: str = "AND", cap: int = 300000) -> int:
        """Conta trechos que casam com os termos e passam em `accept` (ex.: expressão exata)."""
        if not terms:
            return 0
        n = seen = 0
        try:
            cur = self.conn.execute(
                "SELECT s.text FROM sent_fts f JOIN sentences s ON s.rk = f.rowid WHERE sent_fts MATCH ?",
                (self.match_expr(terms, op),))
            for (text,) in cur:
                seen += 1
                if accept(text):
                    n += 1
                if seen >= cap:
                    break
        except sqlite3.OperationalError:
            return 0
        return n

    def sentences(self, terms: list[str], after_rk: int = 0, limit: int = 30, country: str = "",
                  author: str = "", accept=None, op: str = "OR") -> tuple[list[Sentence], int]:
        """Trechos com qualquer um dos termos, em ordem aleatória estável (rk).
        `accept(texto)` pode descartar trechos (ex.: só nome próprio). Devolve (trechos, último rk)."""
        out: list[Sentence] = []
        if not terms:
            return out, after_rk
        expr = self.match_expr(terms, op)
        last = after_rk
        batch = max(limit * 3, 90) if (country or author or accept) else limit
        while len(out) < limit:
            try:
                rks = [r[0] for r in self.conn.execute(
                    "SELECT rowid FROM sent_fts WHERE sent_fts MATCH ? AND rowid > ? ORDER BY rowid LIMIT ?",
                    (expr, last, batch))]
            except sqlite3.OperationalError:
                break
            if not rks:
                break
            q = ",".join("?" * len(rks))
            rows = {r[2]: r for r in self.conn.execute(
                f"SELECT id, work_id, rk, text FROM sentences WHERE rk IN ({q})", rks)}
            for rk in rks:
                last = rk
                r = rows.get(rk)
                if not r:
                    continue
                w = self.works.get(r[1])
                if w is None:
                    continue
                if country and w.country != country:
                    continue
                if author and author.lower() not in w.author.lower():
                    continue
                if accept is not None and not accept(r[3]):
                    continue
                out.append(Sentence(r[0], r[2], w, r[3]))
                if len(out) >= limit:
                    break
        return out, last

    def context(self, sentence_id: int, k: int = 3) -> list[tuple[int, str]]:
        c = self.conn
        r = c.execute("SELECT work_id FROM sentences WHERE id=?", (sentence_id,)).fetchone()
        if not r:
            return []
        return c.execute("SELECT id, text FROM sentences WHERE id BETWEEN ? AND ? AND work_id=? ORDER BY id",
                         (sentence_id - k, sentence_id + k, r[0])).fetchall()
