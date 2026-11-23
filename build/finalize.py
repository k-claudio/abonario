"""Etapa final: remove tabelas só de construção, ANALYZE, VACUUM e relatório com tempos de consulta."""
from __future__ import annotations

import sqlite3
import time

from common import CACHE, DB_PATH, check_disk, log
from app.core.db import Database
from app.core.lookup import Lookup

BUILD_LEX = CACHE / "build_lexicon.db"


def report() -> None:
    db = Database(DB_PATH)
    lk = Lookup(db)
    c = db.conn
    log(f"tamanho do banco: {DB_PATH.stat().st_size / 2**20:.0f} MB")
    for k, v in db.stats.items():
        log(f"  {k}: {v:,}".replace(",", "."))
    for country, n, s in c.execute(
            "SELECT coalesce(country,''), count(*), sum(nsent) FROM works GROUP BY 1 ORDER BY 3 DESC"):
        log(f"  obras {country or '(sem país)'}: {n} obras, {s or 0} trechos")
    for q in ("fizéramos", "coubesse", "meninas", "vimos", "fazê-lo", "pharmacia", "coracao", "elle"):
        t = time.perf_counter()
        res = lk.resolve(q)
        lemma = res.main[0].lemma if res.main else None
        forms = [f for f, _ in lk.lemma_forms(lemma)] if lemma else []
        freq = db.freq(forms)
        attested = [f for f in forms if freq.get(f)]
        sents, _ = db.sentences(attested, 0, 25)
        exact, _ = db.sentences([res.form], 0, 25)
        dt = (time.perf_counter() - t) * 1000
        t2 = time.perf_counter()
        total = db.count_sentences(attested)
        dt2 = (time.perf_counter() - t2) * 1000
        log(f"  {q!r}: lema={[r.lemma for r in res.main]} via={res.via!r} formas={len(attested)} "
            f"trechos(forma)={len(exact)} trechos(lema)={total} | {dt:.0f} ms (+{dt2:.0f} ms contagem)")


def finalize() -> None:
    check_disk()
    db = sqlite3.connect(DB_PATH)
    has = db.execute("SELECT 1 FROM sqlite_master WHERE name='lexicon_known'").fetchone()
    if has:  # guarda o léxico de construção (testes/reconstrução) fora do banco do app
        BUILD_LEX.unlink(missing_ok=True)
        db.execute("ATTACH ? AS b", (str(BUILD_LEX),))
        db.execute("CREATE TABLE b.lexicon_known AS SELECT * FROM lexicon_known")
        db.execute("CREATE TABLE b.alt AS SELECT * FROM alt")
        db.commit()
        db.execute("DETACH b")
        db.execute("DROP TABLE lexicon_known")
        db.commit()
    log("ANALYZE...")
    db.execute("ANALYZE")
    db.commit()
    log("VACUUM...")
    db.execute("VACUUM")
    db.close()
    report()


if __name__ == "__main__":
    finalize()
