"""Baixa todas as fontes para cache/ (uma única vez; downloads retomáveis).

Uso:  python build/fetch.py [static|gutenberg|all]
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from common import CACHE, check_disk, download, fetch_bytes, log

STATIC = {
    "da_data.sql.xz": "https://raw.githubusercontent.com/ambs/Dicionario-Aberto/master/SQL/data-20151213.sql.xz",
    "da_structure.sql": "https://raw.githubusercontent.com/ambs/Dicionario-Aberto/master/SQL/structure.sql",
    "wikt_pt.jsonl.gz": "https://kaikki.org/dictionary/downloads/pt/pt-extract.jsonl.gz",
    "wikt_en_pt.jsonl.gz": "https://kaikki.org/dictionary/Portuguese/kaikki.org-dictionary-Portuguese.jsonl.gz",
    "mechura_pt.txt": "https://raw.githubusercontent.com/michmech/lemmatization-lists/master/lemmatization-pt.txt",
    "pg_catalog.csv.gz": "https://gutenberg.pglaf.org/cache/epub/feeds/pg_catalog.csv.gz",
    "ptwikisource.xml.bz2": "https://dumps.wikimedia.org/ptwikisource/latest/ptwikisource-latest-pages-articles.xml.bz2",
}

MIRROR = "https://gutenberg.pglaf.org"


def fetch_static() -> None:
    for name, url in STATIC.items():
        log(f"baixando {name} ...")
        try:
            download(url, CACHE / name)
        except RuntimeError as exc:
            # O arquivo kaikki en-pt está marcado como "deprecated": tolera a falta.
            if name == "wikt_en_pt.jsonl.gz":
                log(f"  AVISO: {exc}; seguindo sem as etiquetas do Wikcionário-en.")
            else:
                raise
    log("fontes fixas OK")


def gutenberg_catalog() -> list[dict]:
    raw = gzip.decompress((CACHE / "pg_catalog.csv.gz").read_bytes()).decode("utf-8")
    rows = []
    for row in csv.DictReader(io.StringIO(raw)):
        if row["Type"] == "Text" and row["Language"].strip() == "pt":
            rows.append(row)
    return rows


FAST_MIRROR = "http://mirrors.xmission.com/gutenberg"  # ~8x mais rápido; texto de domínio público


def _book_paths(book_id: int) -> list[str]:
    s = str(book_id)
    d = "/".join(s[:-1]) if len(s) > 1 else "0"
    return [
        f"{FAST_MIRROR}/{d}/{s}/{s}-0.txt",
        f"{FAST_MIRROR}/{d}/{s}/{s}-8.txt",
        f"{FAST_MIRROR}/{d}/{s}/{s}.txt",
        f"{MIRROR}/cache/epub/{s}/pg{s}.txt",
    ]


def _fetch_book(book_id: int) -> tuple[int, str]:
    dest = CACHE / "gutenberg" / f"{book_id}.txt.gz"
    if dest.exists():
        return book_id, "cache"
    for url in _book_paths(book_id):
        data = fetch_bytes(url)
        if data:
            if url.endswith("-8.txt"):
                text = data.decode("latin-1")
            else:
                try:
                    text = data.decode("utf-8-sig")
                except UnicodeDecodeError:
                    text = data.decode("latin-1")
            tmp = dest.with_suffix(".part")
            tmp.write_bytes(gzip.compress(text.encode("utf-8"), 6))
            tmp.replace(dest)
            time.sleep(0.2)  # educação com o espelho
            return book_id, url.rsplit("/", 1)[-1]
    return book_id, "FALHOU"


def fetch_gutenberg() -> None:
    rows = gutenberg_catalog()
    (CACHE / "gutenberg").mkdir(parents=True, exist_ok=True)
    (CACHE / "gutenberg" / "catalog_pt.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=0), encoding="utf-8"
    )
    log(f"Gutenberg: {len(rows)} livros em português")
    failed = []
    done = 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = [pool.submit(_fetch_book, int(r["Text#"])) for r in rows]
        for fut in as_completed(futs):
            book_id, how = fut.result()
            done += 1
            if how == "FALHOU":
                failed.append(book_id)
            if done % 50 == 0:
                check_disk()
                log(f"  {done}/{len(rows)}")
    log(f"Gutenberg OK; falhas: {failed}")


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("static", "all"):
        fetch_static()
    if what in ("gutenberg", "all"):
        fetch_gutenberg()
