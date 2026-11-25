"""Pré-carrega o cache offline do Caldas Aulete (aulete_cache.db) a partir do abonario.db."""
from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import http.client
import math
import os
import re
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import zlib
from pathlib import Path
from typing import Callable

from common import CACHE, ROOT, checkpoint_aulete_cache, log
from app.core.aulete import AuleteClient, AuleteEntry, USER_AGENT, _entry_url, parse_aulete_page
from app.core.db import find_db

WORD_RE = re.compile(r"^[a-zà-öø-ÿ]+(?:-[a-zà-öø-ÿ]+)*$")


def _fmt_duration(seconds: float) -> str:
    """Formata duração em segundos como MM:SS ou HH:MM:SS."""
    if not math.isfinite(seconds) or seconds < 0:
        return "--:--"
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _format_progress(
    done: int,
    target: int,
    elapsed: float,
    stats: dict[str, int],
    cache_total: int,
    current: str = "",
    bar_width: int = 20,
) -> str:
    """Formata linha de acompanhamento com barra ASCII, taxa e ETA."""
    pct = (done / target * 100.0) if target else 100.0
    filled = int(round(bar_width * done / target)) if target else bar_width
    filled = max(0, min(bar_width, filled))
    bar = "#" * filled + "-" * (bar_width - filled)
    rate = (done / elapsed) if (elapsed > 0 and done > 0) else 0.0
    eta = ((target - done) / rate) if (rate > 0 and target >= done) else -1.0
    rate_txt = f"{rate:.1f}/s" if rate > 0 else "--/s"
    cur = current[:21] + "..." if len(current) > 24 else current
    line = (
        f"[{bar}] {pct:5.1f}% ({done}/{target}) | "
        f"ok={stats['found']} miss={stats['not_found']} err={stats['errors']} | "
        f"cache={cache_total} | {rate_txt} | "
        f"decorrido {_fmt_duration(elapsed)} ETA {_fmt_duration(eta)}"
    )
    if cur:
        line += f" | {cur}"
    return line


class _ProgressReporter:
    """Exibe progresso em linha única no terminal (TTY) ou em logs periódicos."""

    def __init__(self, target: int, every: int = 25, stream=None) -> None:
        self.target = max(0, target)
        self.every = every
        self.stream = sys.stdout if stream is None else stream
        self.is_tty = bool(getattr(self.stream, "isatty", lambda: False)())
        self.start = time.monotonic()
        self._last_len = 0

    def update(
        self,
        done: int,
        stats: dict[str, int],
        cache_total: int,
        current: str = "",
    ) -> None:
        elapsed = time.monotonic() - self.start
        line = _format_progress(done, self.target, elapsed, stats, cache_total, current=current)
        if self.is_tty:
            pad = max(0, self._last_len - len(line))
            self.stream.write("\r" + line + (" " * pad))
            self.stream.flush()
            self._last_len = len(line)
        elif done == 1 or done == self.target or (self.every > 0 and done % self.every == 0):
            log(line)

    def break_line(self) -> None:
        if self.is_tty and self._last_len > 0:
            self.stream.write("\n")
            self.stream.flush()
            self._last_len = 0


class _KeepAliveFetcher:
    """Cliente HTTP persistente por thread com Keep-Alive e suporte a gzip/deflate."""

    _RETRYABLE_CONN_ERRORS = (
        http.client.RemoteDisconnected,
        http.client.BadStatusLine,
        http.client.CannotSendRequest,
        ConnectionResetError,
        BrokenPipeError,
    )

    def __init__(self, timeout: float = 10.0) -> None:
        self.timeout = timeout
        self._local = threading.local()
        self._lock = threading.Lock()
        self._conns: list[http.client.HTTPConnection] = []

    def _get_conn(self, scheme: str, netloc: str) -> http.client.HTTPConnection:
        conns = getattr(self._local, "conns", None)
        if conns is None:
            conns = {}
            self._local.conns = conns
        key = (scheme, netloc)
        conn = conns.get(key)
        if conn is None:
            if scheme == "https":
                conn = http.client.HTTPSConnection(netloc, timeout=self.timeout)
            elif scheme == "http":
                conn = http.client.HTTPConnection(netloc, timeout=self.timeout)
            else:
                raise urllib.error.URLError(f"Esquema não suportado: {scheme}")
            conns[key] = conn
            with self._lock:
                self._conns.append(conn)
        return conn

    def _drop_conn(self, scheme: str, netloc: str) -> None:
        conns = getattr(self._local, "conns", None)
        if not conns:
            return
        conn = conns.pop((scheme, netloc), None)
        if conn is not None:
            try:
                conn.close()
            except (OSError, http.client.HTTPException):
                pass

    def __call__(self, url: str) -> bytes:
        cur_url = url
        for _ in range(4):
            parts = urllib.parse.urlsplit(cur_url)
            scheme = parts.scheme.lower()
            netloc = parts.netloc
            path = urllib.parse.urlunsplit(("", "", parts.path or "/", parts.query, ""))
            headers = {
                "User-Agent": USER_AGENT,
                "Accept-Encoding": "gzip, deflate",
                "Connection": "keep-alive",
            }
            resp = None
            body = b""
            for attempt in range(2):
                conn = self._get_conn(scheme, netloc)
                try:
                    conn.request("GET", path, headers=headers)
                    resp = conn.getresponse()
                    body = resp.read()
                    break
                except self._RETRYABLE_CONN_ERRORS:
                    self._drop_conn(scheme, netloc)
                    if attempt == 1:
                        raise
            assert resp is not None
            conn_hdr = (resp.getheader("Connection") or "").lower()
            if "close" in conn_hdr:
                self._drop_conn(scheme, netloc)
            if resp.status in (301, 302, 303, 307, 308):
                loc = resp.getheader("Location")
                if not loc:
                    raise urllib.error.HTTPError(cur_url, resp.status, resp.reason, resp.headers, None)
                cur_url = urllib.parse.urljoin(cur_url, loc)
                continue
            if resp.status >= 400:
                raise urllib.error.HTTPError(cur_url, resp.status, resp.reason, resp.headers, None)
            enc = (resp.getheader("Content-Encoding") or "").lower()
            if "gzip" in enc:
                return gzip.decompress(body)
            if "deflate" in enc:
                try:
                    return zlib.decompress(body)
                except zlib.error:
                    return zlib.decompress(body, -zlib.MAX_WBITS)
            return body
        raise urllib.error.URLError(f"Muitos redirecionamentos em {url}")

    def close(self) -> None:
        with self._lock:
            conns = list(self._conns)
            self._conns.clear()
        for conn in conns:
            try:
                conn.close()
            except (OSError, http.client.HTTPException):
                pass


class _RateController:
    """Coordena espaçamento opcional e backoff adaptativo compartilhado entre workers."""

    def __init__(self, delay: float = 0.0) -> None:
        self.delay = max(0.0, delay)
        self._lock = threading.Lock()
        self._paused_until = 0.0
        self._next_slot = 0.0
        self._consecutive_errors = 0

    def wait_turn(self, stop_event: threading.Event) -> bool:
        while not stop_event.is_set():
            with self._lock:
                now = time.monotonic()
                target = max(now, self._paused_until)
                if self.delay > 0:
                    target = max(target, self._next_slot)
                    self._next_slot = target + self.delay
                wait_for = target - now
            if wait_for <= 0:
                return True
            if stop_event.wait(wait_for):
                return False
        return False

    def on_success(self) -> None:
        with self._lock:
            self._consecutive_errors = 0

    def on_error(self, status: int | None = None, retry_after: float | None = None) -> float:
        with self._lock:
            self._consecutive_errors += 1
            pause = 0.0
            if retry_after is not None and retry_after > 0:
                pause = min(60.0, retry_after)
            elif status in (429, 502, 503, 504) or self._consecutive_errors >= 3:
                pause = min(30.0, float(2.0 ** min(self._consecutive_errors, 5)))
            if pause > 0:
                until = time.monotonic() + pause
                if until > self._paused_until:
                    self._paused_until = until
                if self.delay > 0 and until > self._next_slot:
                    self._next_slot = until
            return pause


def _parse_retry_after(headers) -> float | None:
    if not headers:
        return None
    raw = headers.get("Retry-After")
    if not raw:
        return None
    try:
        val = float(raw.strip())
        return val if val >= 0 else None
    except ValueError:
        return None


class _BatchCacheWriter:
    """Grava verbetes em lotes no SQLite na thread principal para evitar locks e commits por item."""

    def __init__(self, cache_path: Path, batch_size: int = 50) -> None:
        self.path = Path(cache_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.batch_size = max(1, batch_size)
        self._conn = sqlite3.connect(self.path, timeout=10.0)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS aulete_entries (
                key TEXT PRIMARY KEY,
                headword TEXT NOT NULL,
                url TEXT NOT NULL,
                original_html TEXT NOT NULL,
                updated_html TEXT NOT NULL,
                updated_label TEXT NOT NULL,
                nearest TEXT NOT NULL,
                fetched_at INTEGER NOT NULL
            ) WITHOUT ROWID
            """
        )
        self._conn.commit()
        self._buf: list[tuple[str, str, str, str, str, str, str, int]] = []

    def add(self, key: str, entry: AuleteEntry) -> None:
        row = (
            key,
            entry.headword,
            entry.url,
            entry.original_html,
            entry.updated_html,
            entry.updated_label,
            entry.nearest,
            entry.fetched_at,
        )
        self._buf.append(row)
        hw_key = entry.headword.strip().lower()
        if hw_key and hw_key != key:
            self._buf.append((hw_key, *row[1:]))
        if len(self._buf) >= self.batch_size:
            self.flush()

    def flush(self) -> None:
        if not self._buf:
            return
        self._conn.executemany(
            "INSERT OR REPLACE INTO aulete_entries "
            "(key, headword, url, original_html, updated_html, updated_label, nearest, fetched_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            self._buf,
        )
        self._conn.commit()
        self._buf.clear()

    def count(self) -> int:
        self.flush()
        row = self._conn.execute(
            "SELECT count(DISTINCT lower(headword)) FROM aulete_entries WHERE headword != ''"
        ).fetchone()
        return int(row[0]) if row else 0

    def close(self) -> None:
        try:
            self.flush()
        finally:
            self._conn.close()


def resolve_db_path(explicit: Path | None = None) -> Path:
    """Resolve o caminho do abonario.db (argumento --db, find_db() ou dist/Abonario/)."""
    if explicit is not None:
        p = explicit.resolve()
        if not p.exists():
            raise SystemExit(f"Banco não encontrado em: {p}")
        return p
    found = find_db()
    if found is not None and found.exists():
        return found.resolve()
    dist_db = (ROOT / "dist" / "Abonario" / "abonario.db").resolve()
    if dist_db.exists():
        return dist_db
    raise SystemExit(
        "abonario.db não encontrado em ABONARIO_DB, data/abonario.db, "
        "%LOCALAPPDATA%\\Programs\\Abonario\\abonario.db nem dist\\Abonario\\abonario.db. "
        "Informe --db ou defina ABONARIO_DB."
    )


def resolve_cache_path(db_path: Path, explicit: Path | None = None) -> Path:
    """Resolve o caminho de aulete_cache.db (--cache, ABONARIO_AULETE_CACHE ou ao lado de db_path)."""
    if explicit is not None:
        return explicit.resolve()
    env = os.environ.get("ABONARIO_AULETE_CACHE", "").strip()
    if env:
        return Path(env).resolve()
    return db_path.resolve().parent / "aulete_cache.db"


def iter_headwords(
    db_path: Path, source: str = "wikt", order: str = "freq"
) -> list[tuple[str, str]]:
    """Seleciona (key, lemma) de palavras modernas válidas do abonario.db."""
    filters = ["a.old IS NULL"]
    if source == "both":
        filters.append("h.srcmask = 3")
    elif source == "wikt":
        filters.append("(h.srcmask & 2) != 0")
    elif source != "all":
        raise ValueError(f"Fonte inválida: {source}")

    if order == "freq":
        order_sql = "COALESCE(tf.n, 0) DESC, (h.srcmask = 3) DESC, h.fold, h.key"
    elif order == "alpha":
        order_sql = "h.fold, h.key"
    else:
        raise ValueError(f"Ordenação inválida: {order}")

    sql = (
        "SELECT h.key, h.lemma "
        "FROM headwords h "
        "LEFT JOIN alt a ON a.old = h.key "
        "LEFT JOIN term_freq tf ON tf.term = h.key "
        f"WHERE {' AND '.join(filters)} "
        f"ORDER BY {order_sql}"
    )

    uri = f"{db_path.resolve().as_uri()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        out: list[tuple[str, str]] = []
        seen: set[str] = set()
        for key, lemma in con.execute(sql):
            if not key or key in seen or not WORD_RE.fullmatch(key):
                continue
            seen.add(key)
            out.append((key, lemma))
        return out
    finally:
        con.close()


def load_cached_keys(cache_path: Path) -> set[str]:
    """Lê as chaves já presentes em aulete_entries no cache SQLite."""
    if not cache_path.exists():
        return set()
    con = sqlite3.connect(cache_path)
    try:
        rows = con.execute("SELECT key FROM aulete_entries").fetchall()
        return {r[0] for r in rows if r and r[0]}
    except sqlite3.Error:
        return set()
    finally:
        con.close()


def load_misses(path: Path) -> set[str]:
    """Lê termos já consultados que retornaram não encontrados no Aulete."""
    if not path.exists():
        return set()
    out: set[str] = set()
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            term = line.strip().lower()
            if term:
                out.add(term)
    return out


def _populate_with_client(
    client: AuleteClient,
    pending: list[tuple[str, str]],
    target: int,
    limit: int,
    delay: float,
    cached_keys: set[str],
    misses: set[str],
    misses_path: Path,
    progress: _ProgressReporter,
    stats: dict[str, int],
) -> tuple[bool, int]:
    """Caminho de compatibilidade quando um AuleteClient pronto é injetado."""
    base_cached = client.cached_count()
    misses_path.parent.mkdir(parents=True, exist_ok=True)
    interrupted = False
    try:
        with misses_path.open("a", encoding="utf-8") as misses_fh:
            total_pending = len(pending)
            for idx, (key, lemma) in enumerate(pending):
                if limit > 0 and stats["fetched"] >= limit:
                    break
                if key in cached_keys:
                    continue

                entry = client.lookup(lemma)
                stats["fetched"] += 1

                if entry.error:
                    stats["errors"] += 1
                    progress.break_line()
                    log(f"  erro ao consultar {lemma!r}: {entry.error}")
                elif entry.found:
                    stats["found"] += 1
                    cached_keys.add(key)
                    hw_key = entry.headword.strip().lower()
                    if hw_key:
                        cached_keys.add(hw_key)
                else:
                    stats["not_found"] += 1
                    misses.add(key)
                    misses_fh.write(f"{key}\n")
                    misses_fh.flush()

                done = stats["fetched"] if limit > 0 else min(idx + 1, target)
                progress.update(done, stats, base_cached + stats["found"], current=lemma)

                if delay > 0 and (limit <= 0 or stats["fetched"] < limit) and idx < total_pending - 1:
                    time.sleep(delay)
    except KeyboardInterrupt:
        interrupted = True
        progress.break_line()
        log("Interrompido pelo usuário; progresso já salvo em disco.")
    finally:
        progress.break_line()
    return interrupted, client.cached_count()


def populate(
    db_path: Path,
    cache_path: Path,
    misses_path: Path,
    source: str = "wikt",
    order: str = "freq",
    limit: int = 0,
    delay: float = 0.0,
    timeout: float = 10.0,
    workers: int = 6,
    batch_size: int = 50,
    retries: int = 2,
    retry_misses: bool = False,
    dry_run: bool = False,
    progress_every: int = 25,
    vacuum: bool = False,
    client: AuleteClient | None = None,
    fetcher: Callable[[str], bytes] | None = None,
) -> dict[str, int]:
    """Popula o cache do Aulete de forma concorrente e retomável e retorna contadores."""
    workers = max(1, workers)
    batch_size = max(1, batch_size)
    retries = max(0, retries)

    cached_keys = load_cached_keys(cache_path)
    misses = set() if retry_misses else load_misses(misses_path)
    candidates = iter_headwords(db_path, source=source, order=order)
    pending = [(k, l) for k, l in candidates if k not in cached_keys and k not in misses]
    target = min(len(pending), limit) if limit > 0 else len(pending)

    stats: dict[str, int] = {
        "candidates": len(candidates),
        "already_cached": len(cached_keys),
        "skipped_misses": len(misses),
        "pending": len(pending),
        "fetched": 0,
        "found": 0,
        "not_found": 0,
        "errors": 0,
    }

    log(f"Banco: {db_path}")
    log(f"Cache: {cache_path}")
    log(
        f"Candidatos ({source}, {order}): {stats['candidates']} | "
        f"já no cache: {stats['already_cached']} | "
        f"misses ignorados: {stats['skipped_misses']} | "
        f"pendentes: {stats['pending']} | alvo: {target} | "
        f"workers={workers} delay={delay:.2f}s"
    )

    if dry_run:
        preview = [lemma for _, lemma in pending[:10]]
        log(f"Primeiros 10 pendentes: {', '.join(preview) if preview else '(nenhum)'}")
        return stats

    if target == 0:
        log("Nada a consultar: todos os candidatos já estão no cache ou em misses.")
        return stats

    progress = _ProgressReporter(target=target, every=progress_every)
    if client is not None:
        interrupted, total_cached = _populate_with_client(
            client=client,
            pending=pending,
            target=target,
            limit=limit,
            delay=delay,
            cached_keys=cached_keys,
            misses=misses,
            misses_path=misses_path,
            progress=progress,
            stats=stats,
        )
    else:
        own_fetcher = fetcher is None
        http_fetcher = fetcher or _KeepAliveFetcher(timeout=timeout)
        rate = _RateController(delay=delay)
        stop_event = threading.Event()
        writer = _BatchCacheWriter(cache_path, batch_size=batch_size)
        base_cached = writer.count()
        misses_path.parent.mkdir(parents=True, exist_ok=True)
        interrupted = False

        def _fetch_one(key: str, lemma: str) -> tuple[str, str, AuleteEntry, float]:
            url = _entry_url(lemma)
            last_err = ""
            backoff_wait = 0.0
            for attempt in range(retries + 1):
                if not rate.wait_turn(stop_event):
                    return key, lemma, AuleteEntry(query=lemma, url=url, error="interrompido"), 0.0
                try:
                    raw = http_fetcher(url)
                    entry = parse_aulete_page(lemma, raw, url=url)
                    entry.fetched_at = int(time.time())
                    entry.from_cache = False
                    rate.on_success()
                    return key, lemma, entry, 0.0
                except urllib.error.HTTPError as exc:
                    last_err = f"HTTP {exc.code}"
                    backoff_wait = rate.on_error(
                        status=exc.code, retry_after=_parse_retry_after(exc.headers)
                    )
                    transient = exc.code in (429, 500, 502, 503, 504)
                    if not transient or attempt >= retries or stop_event.is_set():
                        return key, lemma, AuleteEntry(query=lemma, url=url, error=last_err), backoff_wait
                except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
                    last_err = str(exc)
                    backoff_wait = rate.on_error()
                    if attempt >= retries or stop_event.is_set():
                        return key, lemma, AuleteEntry(query=lemma, url=url, error=last_err), backoff_wait
            return key, lemma, AuleteEntry(query=lemma, url=url, error=last_err), backoff_wait

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
        try:
            with misses_path.open("a", encoding="utf-8") as misses_fh:
                misses_buf: list[str] = []
                pending_iter = iter(pending)
                in_flight: set[concurrent.futures.Future] = set()
                submitted = 0
                max_in_flight = workers * 4

                def _submit_more() -> None:
                    nonlocal submitted
                    while len(in_flight) < max_in_flight and submitted < target:
                        try:
                            key, lemma = next(pending_iter)
                        except StopIteration:
                            break
                        if key in cached_keys:
                            continue
                        in_flight.add(executor.submit(_fetch_one, key, lemma))
                        submitted += 1

                try:
                    _submit_more()
                    while in_flight:
                        done_futs, in_flight = concurrent.futures.wait(
                            in_flight, return_when=concurrent.futures.FIRST_COMPLETED
                        )
                        for fut in done_futs:
                            key, lemma, entry, backoff_wait = fut.result()
                            stats["fetched"] += 1
                            if entry.error:
                                stats["errors"] += 1
                                progress.break_line()
                                pause_note = (
                                    f" (pausa adaptativa {backoff_wait:.1f}s)"
                                    if backoff_wait > 0
                                    else ""
                                )
                                log(f"  erro ao consultar {lemma!r}: {entry.error}{pause_note}")
                            elif entry.found:
                                stats["found"] += 1
                                cached_keys.add(key)
                                hw_key = entry.headword.strip().lower()
                                if hw_key:
                                    cached_keys.add(hw_key)
                                writer.add(key, entry)
                            else:
                                stats["not_found"] += 1
                                misses.add(key)
                                misses_buf.append(f"{key}\n")
                                if len(misses_buf) >= batch_size:
                                    misses_fh.writelines(misses_buf)
                                    misses_fh.flush()
                                    misses_buf.clear()

                            progress.update(
                                stats["fetched"], stats, base_cached + stats["found"], current=lemma
                            )
                        _submit_more()
                except KeyboardInterrupt:
                    interrupted = True
                    stop_event.set()
                    progress.break_line()
                    log("Interrompido pelo usuário; gravando lote pendente em disco...")
                finally:
                    if misses_buf:
                        misses_fh.writelines(misses_buf)
                        misses_fh.flush()
                        misses_buf.clear()
        finally:
            executor.shutdown(wait=not interrupted, cancel_futures=interrupted)
            progress.break_line()
            total_cached = writer.count()
            writer.close()
            if own_fetcher:
                http_fetcher.close()
            if cache_path.exists():
                total_cached = checkpoint_aulete_cache(cache_path, vacuum=vacuum)

    elapsed_txt = _fmt_duration(time.monotonic() - progress.start)
    prefix = "Resumo parcial" if interrupted else "Concluído"
    log(
        f"{prefix} em {elapsed_txt}: {stats['fetched']} consultadas | "
        f"encontradas={stats['found']} não_encontradas={stats['not_found']} "
        f"erros={stats['errors']} | total no cache={total_cached}"
    )
    return stats


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Pré-carrega o cache offline do Caldas Aulete a partir do abonario.db."
    )
    p.add_argument("--db", type=Path, default=None, help="Caminho para abonario.db")
    p.add_argument("--cache", type=Path, default=None, help="Caminho para aulete_cache.db")
    p.add_argument(
        "--source",
        choices=("wikt", "both", "all"),
        default="wikt",
        help="Subconjunto de verbetes: wikt (padrão), both (DA+Wikcionário) ou all",
    )
    p.add_argument(
        "--order",
        choices=("freq", "alpha"),
        default="freq",
        help="Ordem das consultas: freq (mais frequentes no corpus) ou alpha",
    )
    p.add_argument("--limit", type=int, default=0, help="Máximo de consultas nesta execução (0 = sem limite)")
    p.add_argument("--workers", type=int, default=6, help="Requisições paralelas ao aulete.com.br (padrão: 6)")
    p.add_argument("--delay", type=float, default=0.0, help="Pausa mínima em segundos entre requisições (padrão: 0)")
    p.add_argument("--batch-size", type=int, default=50, help="Tamanho do lote de gravação no SQLite (padrão: 50)")
    p.add_argument("--retries", type=int, default=2, help="Novas tentativas em erros transitórios/429/5xx (padrão: 2)")
    p.add_argument("--timeout", type=float, default=10.0, help="Timeout HTTP em segundos")
    p.add_argument(
        "--misses",
        type=Path,
        default=CACHE / "aulete_misses.txt",
        help="Arquivo para registrar termos não encontrados e pular ao retomar",
    )
    p.add_argument(
        "--retry-misses",
        action="store_true",
        help="Ignora o arquivo de misses e tenta consultar novamente os termos não encontrados",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostra totais e os 10 primeiros termos pendentes sem acessar a rede",
    )
    p.add_argument(
        "--progress-every",
        type=int,
        default=25,
        help="Intervalo de logs de progresso quando a saída não é terminal interativo (padrão: 25)",
    )
    p.add_argument(
        "--vacuum",
        action="store_true",
        help="Executa ANALYZE/VACUUM ao finalizar para compactar aulete_cache.db",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    db_path = resolve_db_path(args.db)
    cache_path = resolve_cache_path(db_path, args.cache)
    populate(
        db_path=db_path,
        cache_path=cache_path,
        misses_path=args.misses.resolve(),
        source=args.source,
        order=args.order,
        limit=args.limit,
        delay=args.delay,
        timeout=args.timeout,
        workers=args.workers,
        batch_size=args.batch_size,
        retries=args.retries,
        retry_misses=args.retry_misses,
        dry_run=args.dry_run,
        progress_every=args.progress_every,
        vacuum=args.vacuum,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
