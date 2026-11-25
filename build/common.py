"""Utilidades compartilhadas pelos scripts de construção (rede só aqui, nunca no app)."""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "cache"
DATA = ROOT / "data"
DB_PATH = DATA / "abonario.db"
AULETE_CACHE_PATH = DATA / "aulete_cache.db"

sys.path.insert(0, str(ROOT))  # permite "from app.core import ..."

USER_AGENT = "Abonario-build/1.0 (offline dictionary builder)"
MIN_FREE_BYTES = 600 * 1024 * 1024


def log(*args) -> None:
    print(time.strftime("%H:%M:%S"), *args, flush=True)


def check_disk(path: Path = ROOT, min_free: int = MIN_FREE_BYTES) -> None:
    free = shutil.disk_usage(path).free
    if free < min_free:
        raise SystemExit(
            f"Espaço livre insuficiente: {free / 2**20:.0f} MB (mínimo {min_free / 2**20:.0f} MB)."
        )


def download(url: str, dest: Path, retries: int = 5, timeout: int = 60) -> Path:
    """Baixa url para dest com o curl do Windows (usa o repositório de certificados do
    sistema), retomando downloads parciais. Não baixa de novo se já existir."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    part = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(1, retries + 1):
        check_disk()
        cmd = ["curl", "-sSL", "--fail", "-A", USER_AGENT, "--connect-timeout", str(timeout),
               "-C", "-", "-o", str(part), url]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            os.replace(part, dest)
            return dest
        log(f"  falha ({attempt}/{retries}) em {url}: curl {res.returncode} {res.stderr.strip()[:200]}")
        time.sleep(min(30, 2 ** attempt))
    raise RuntimeError(f"Não foi possível baixar {url}")


def fetch_bytes(url: str, retries: int = 4, timeout: int = 60) -> bytes | None:
    """Retorna o conteúdo de url, ou None se 404."""
    for attempt in range(1, retries + 1):
        cmd = ["curl", "-sSL", "-A", USER_AGENT, "--connect-timeout", str(timeout),
               "--max-time", "600", "-w", "\\n%{http_code}", url]
        res = subprocess.run(cmd, capture_output=True)
        if res.returncode == 0:
            body, _, code = res.stdout.rpartition(b"\n")
            code = code.strip().decode() or "0"
            if code == "200":
                return body
            if code == "404":
                return None
            log(f"  HTTP {code} em {url} ({attempt}/{retries})")
        else:
            log(f"  falha em {url} ({attempt}/{retries}): curl {res.returncode}")
        time.sleep(min(20, 2 ** attempt))
    return None


def checkpoint_aulete_cache(path: Path, vacuum: bool = False) -> int:
    """Consolida o WAL de aulete_cache.db em arquivo único e devolve o nº de verbetes."""
    con = sqlite3.connect(path, timeout=5.0)
    try:
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        if vacuum:
            con.execute("ANALYZE")
            con.execute("VACUUM")
        con.execute("PRAGMA journal_mode=DELETE")
        con.commit()
        try:
            row = con.execute(
                "SELECT count(DISTINCT lower(headword)) FROM aulete_entries WHERE headword != ''"
            ).fetchone()
            return int(row[0]) if row else 0
        except sqlite3.Error:
            return 0
    finally:
        con.close()
