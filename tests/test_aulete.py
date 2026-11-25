"""Testes unitários para o cliente, parser, sanitizador e renderização do Caldas Aulete."""
from __future__ import annotations

import urllib.error

import pytest

from app.core.aulete import (
    AuleteClient,
    AuleteEntry,
    decode_aulete_bytes,
    default_cache_path,
    parse_aulete_page,
)
from app.core.lookup import LookupResult, Reading
from app.ui import render


def _make_html(
    nocab: str = "",
    orig_body: str = "",
    atual_body: str = "",
    tab_atual_label: str = "Verbete Atualizado",
    hide_orig: bool = False,
    hide_atual: bool = False,
) -> bytes:
    style_o = ' style="display:none"' if hide_orig else ""
    style_a = ' style="display:none"' if hide_atual else ""
    doc = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Teste</title></head>
<body>
  <div id="verbete_submenu" class="digital"><h2><span id="nocab"> {nocab} </span></h2></div>
  <div id="abas_verbete">
    <ul>
      <li class="selecionado" id="tabatualizado"{style_a}><a href="javascript:void(0);">{tab_atual_label}</a></li>
      <li id="taboriginal"{style_o}><a href="javascript:void(0);">Verbete Original</a></li>
    </ul>
  </div>
  <div id="definicao_verbete_homologado_original" class="definicao_verbete_homologado_interna" style="display:none;">
    {orig_body}
  </div>
  <div id="definicao_verbete_homologado" class="definicao_verbete_homologado_interna" style="display:block;">
    <textarea name="textarea" class="oculta" id="copy">texto oculto</textarea>
    <div><h5><a href="#" onclick="setActiveStyleSheet('small');">A</a></h5></div>
    <form style="font-size:1.5em; line-height:1.6em;">
      {atual_body}
    </form>
  </div>
</body>
</html>"""
    return doc.encode("utf-8")


def test_decode_aulete_bytes_mixed_utf8_and_cp1252_and_latin1():
    raw = (
        b"<strong>cora\xe7\xe3o</strong> e \xc3\xa1gua e "
        b"bytes \x93aspas\x94 e indefinido \x8d fim"
    )
    decoded = decode_aulete_bytes(raw)
    assert "\ufffd" not in decoded
    assert "<strong>coração</strong>" in decoded
    assert "água" in decoded
    assert "“aspas”" in decoded
    assert "\x8d" in decoded


def test_parse_both_original_and_updated_prioritizes_original():
    raw = _make_html(
        nocab="manga",
        orig_body=(
            '<strong>manga</strong> <span class="silabas"><sup>1</sup></span> '
            '<span class="textodeforiginal">s. f. || parte do vestido.</span><br /><br />'
            '<strong>manga</strong> <span class="silabas"><sup>2</sup></span> '
            '<span class="textodeforiginal">s. f. || fruto da mangueira.</span>'
        ),
        atual_body=(
            '<p><strong>manga</strong><sup><span class="silabas">1</span></sup> '
            '<span class="silabas separacao-silaba">(<em>man</em>.ga)</span>'
            '<div class="edicao-verbete"></div></p>'
            '<p class="classificacao1">sf.</p>'
            '<p><span class="numdef">1.</span> <span class="rub">Bot.</span> '
            '<span class="textodef">Fruto da mangueira.</span> '
            '<a href="http://ex/img.jpg" rel="lightbox"><img src="/img.gif"></a></p>'
        ),
    )
    entry = parse_aulete_page("manga", raw)
    assert entry.found
    assert entry.headword == "manga"
    assert entry.has_original and entry.has_updated
    assert entry.preferred_kind == "original"
    assert "<h3>manga <sup>1</sup></h3>" in entry.original_html
    assert "<h3>manga <sup>2</sup></h3>" in entry.original_html
    assert '<span class="aulete-sep">||</span>' in entry.original_html
    assert "<img" not in entry.updated_html
    assert "edicao-verbete" not in entry.updated_html
    assert "texto oculto" not in entry.updated_html
    assert "setActiveStyleSheet" not in entry.updated_html
    assert "Fruto da mangueira." in entry.updated_html


def test_parse_only_original_when_updated_is_placeholder():
    raw = _make_html(
        nocab="sede",
        orig_body=(
            '<strong>sede</strong> <span class="silabas"><sup>1</sup></span> '
            '<span class="textodeforiginal">s. f. || assento, cadeira.</span>'
        ),
        atual_body="{definicao}",
        hide_atual=True,
    )
    entry = parse_aulete_page("sede", raw)
    assert entry.found
    assert entry.has_original
    assert not entry.has_updated
    assert entry.preferred_kind == "original"
    assert "assento, cadeira." in entry.original_html


def test_parse_only_verbete_novo_falls_back_to_updated():
    raw = _make_html(
        nocab="internet",
        orig_body="",
        atual_body=(
            '<p><span class="silabas separacao-silaba">(in.ter.net)</span></p>'
            '<p class="classificacao1">sf.</p>'
            '<p><span class="numdef">1.</span> <span class="textodef">Rede mundial de computadores.</span></p>'
        ),
        tab_atual_label="Verbete Novo",
        hide_orig=True,
    )
    entry = parse_aulete_page("internet", raw)
    assert entry.found
    assert not entry.has_original
    assert entry.has_updated
    assert entry.updated_label == "Verbete Novo"
    assert entry.preferred_kind == "updated"
    assert "Rede mundial de computadores." in entry.preferred_html


def test_parse_accent_folded_match_removes_not_found_banner():
    banner = (
        'Não foi encontrado o verbete "<span class="textodef"><strong>coracao</strong></span>". '
        'Na ordem alfabética o verbete mais próximo do pesquisado ? '
        '<span class="textodef"><strong>coração</strong></span><br /><br />'
    )
    raw = _make_html(
        nocab="coração",
        orig_body=banner + '<span class="textodeforiginal">s. m. || órgão muscular.</span>',
        atual_body=banner + '<p><span class="textodef">Órgão muscular.</span></p>',
    )
    entry = parse_aulete_page("coracao", raw)
    assert entry.found
    assert entry.headword == "coração"
    assert "Não foi encontrado" not in entry.original_html
    assert "Não foi encontrado" not in entry.updated_html
    assert "órgão muscular." in entry.original_html


def test_parse_unrelated_nearest_neighbor_is_not_found():
    banner = (
        'Não foi encontrado o verbete "<span class="textodef"><strong>faz</strong></span>". '
        'Na ordem alfabética o verbete mais próximo do pesquisado ? '
        '<span class="textodef"><strong>fazânio</strong></span><br /><br />'
    )
    raw = _make_html(
        nocab="fazânio",
        orig_body=banner + '<span class="textodeforiginal">s. m. || faisão.</span>',
        atual_body=banner + '<p><span class="textodef">Faisão.</span></p>',
    )
    entry = parse_aulete_page("faz", raw)
    assert not entry.found
    assert entry.nearest == "fazânio"


def test_parse_empty_not_found():
    banner = (
        'Não foi encontrado o verbete "<span class="textodef"><strong>xyznaoe</strong></span>". '
        'Na ordem alfabética o verbete mais próximo do pesquisado ? '
        '<span class="textodef"><strong></strong></span><br /><br />'
    )
    raw = _make_html(
        nocab="",
        orig_body=banner,
        atual_body=banner + '<p><strong></strong><sup><span class="silabas">1</span></sup> </p>',
        hide_orig=True,
    )
    entry = parse_aulete_page("xyznaoe", raw)
    assert not entry.found
    assert entry.nearest == ""


def test_sanitizer_strips_unsafe_tags_and_attributes():
    raw = _make_html(
        nocab="teste",
        orig_body=(
            '<script>alert(1)</script>'
            '<style>.x{color:red}</style>'
            '<textarea>ignorar</textarea>'
            '<span class="textodeforiginal evil" style="font-size:99px" onclick="boom()">'
            'Definição segura <img src="/x.png"><a href="javascript:alert(1)" onclick="x()">link</a>'
            '</span>'
        ),
        hide_atual=True,
    )
    entry = parse_aulete_page("teste", raw)
    assert entry.found
    h = entry.original_html
    for bad in ("<script", "alert(1)", "<style", "<textarea", "ignorar", "<img", "onclick", "style=", "evil", "<a "):
        assert bad not in h
    assert 'class="textodeforiginal"' in h
    assert "Definição segura" in h
    assert "link" in h


def test_client_lru_cache_error_and_candidates():
    calls: list[str] = []

    def fetcher(url: str) -> bytes:
        calls.append(url)
        if url.endswith("falha"):
            raise urllib.error.URLError("sem rede")
        if url.endswith(("fazer", "caber")):
            hw = "fazer" if url.endswith("fazer") else "caber"
            return _make_html(
                nocab=hw,
                orig_body='<span class="textodeforiginal">v. tr. || criar.</span>',
                hide_atual=True,
            )
        return _make_html(nocab="", orig_body="Não foi encontrado o verbete", hide_orig=True)

    client = AuleteClient(fetcher=fetcher, cache_max=10)
    e1 = client.lookup("fazer")
    e2 = client.lookup("FAZER")
    assert e1.found and e2 is e1
    assert len(calls) == 1

    # Erro de rede não deve ser cacheado
    err = client.lookup("falha")
    assert err.error and not err.found
    assert client.get_cached("falha") is None

    # Fallback para o segundo candidato (ex.: forma não achada -> lema achado)
    calls.clear()
    res = client.lookup_candidates(["coubesse", "caber"])
    assert res.found and res.headword == "caber"
    assert len(calls) == 2
    # Cache hit via get_cached_candidates
    assert client.get_cached_candidates(["coubesse", "caber"]) is res


class _StubDB:
    def entries(self, key: str):
        return [("fazer", render.SRC_DA, 0, "v.", "<p>Definição local DA.</p>")]

    def freq(self, names: list[str]) -> dict[str, int]:
        return {"fazer": 10}

    def lemma_count(self, names: list[str]) -> dict[str, int]:
        return {"fazer": 1}


class _StubLookup:
    def lemma_forms(self, lemma: str):
        return [("fazer", None)]


def test_render_aulete_priority_and_switcher():
    entry = AuleteEntry(
        query="fazer",
        headword="fazer",
        original_html='<p class="aulete-orig">v. tr. || criar, formar.</p>',
        updated_html='<p class="textodef">1. Criar, elaborar.</p>',
        updated_label="Verbete Atualizado",
    )
    res = LookupResult(query="fazer", form="fazer", main=[Reading("fazer", [], True)])

    html_orig, _, _ = render.entry_html(_StubDB(), _StubLookup(), res, "fazer", aulete=entry, aulete_mode="original")
    pos_aulete = html_orig.index("Caldas Aulete")
    pos_da = html_orig.index("Dicionário Aberto")
    assert pos_aulete < pos_da
    assert "Verbete Original" in html_orig
    assert "criar, formar." in html_orig
    assert 'href="aulete:updated"' in html_orig
    assert "1. Criar, elaborar." not in html_orig

    html_upd, _, _ = render.entry_html(_StubDB(), _StubLookup(), res, "fazer", aulete=entry, aulete_mode="updated")
    assert "1. Criar, elaborar." in html_upd
    assert 'href="aulete:original"' in html_upd

    # Offline / erro exibe aviso e mantém fontes locais
    err_entry = AuleteEntry(query="fazer", error="timed out")
    html_err, _, _ = render.entry_html(_StubDB(), _StubLookup(), res, "fazer", aulete=err_entry)
    assert "Não foi possível consultar o aulete.com.br" in html_err
    assert "Definição local DA." in html_err


def test_render_not_found_with_aulete_verbete_novo():
    res = LookupResult(query="internet", form="internet", suggestions=["interno"])
    entry = AuleteEntry(
        query="internet",
        headword="internet",
        updated_html='<p class="textodef">Rede mundial.</p>',
        updated_label="Verbete Novo",
    )
    out = render.not_found_html(res, aulete=entry, aulete_mode="original")
    assert "<h1>internet</h1>" in out
    assert "Verbete Novo" in out
    assert "sem Verbete Original" in out
    assert "Rede mundial." in out
    assert "Palavra não encontrada" not in out


def test_disk_cache_persists_between_sessions_offline(tmp_path):
    cache_db = tmp_path / "aulete_cache.db"
    calls: list[str] = []

    def online_fetcher(url: str) -> bytes:
        calls.append(url)
        return _make_html(
            nocab="fazer",
            orig_body='<span class="textodeforiginal">v. tr. || criar, formar.</span>',
            atual_body='<p><span class="numdef">1.</span> <span class="textodef">Criar.</span></p>',
        )

    c1 = AuleteClient(fetcher=online_fetcher, cache_path=cache_db)
    try:
        e1 = c1.lookup("fazer")
        assert e1.found and not e1.from_cache
        assert e1.preferred_kind == "original"
        assert c1.cached_count() == 1
        assert len(calls) == 1
    finally:
        c1.close()

    # Nova sessão totalmente offline: deve abrir instantaneamente do disco
    offline_calls: list[str] = []

    def offline_fetcher(url: str) -> bytes:
        offline_calls.append(url)
        raise urllib.error.URLError("sem internet")

    c2 = AuleteClient(fetcher=offline_fetcher, cache_path=cache_db)
    try:
        cached = c2.get_cached("fazer")
        assert cached is not None and cached.from_cache
        e2 = c2.lookup("fazer")
        assert e2.found and e2.from_cache
        assert e2.preferred_kind == "original"
        assert "criar, formar." in e2.original_html
        assert "Criar." in e2.updated_html
        assert offline_calls == []
    finally:
        c2.close()


def test_disk_cache_accent_alias_and_homograph_isolation(tmp_path):
    cache_db = tmp_path / "aulete_cache.db"

    def fetcher(url: str) -> bytes:
        if url.endswith("coracao") or url.endswith("cora%C3%A7%C3%A3o"):
            return _make_html(
                nocab="coração",
                orig_body='<span class="textodeforiginal">s. m. || órgão muscular.</span>',
                hide_atual=True,
            )
        if url.endswith("sabi%C3%A1"):
            return _make_html(
                nocab="sabiá",
                orig_body='<span class="textodeforiginal">s. m. || pássaro.</span>',
                hide_atual=True,
            )
        if url.endswith("sabia"):
            return _make_html(
                nocab="sabia",
                orig_body='<span class="textodeforiginal">s. f. || variedade de uva.</span>',
                hide_atual=True,
            )
        raise AssertionError(url)

    c1 = AuleteClient(fetcher=fetcher, cache_path=cache_db)
    try:
        e_cor = c1.lookup("coracao")
        e_sab_ac = c1.lookup("sabiá")
        e_sab = c1.lookup("sabia")
        assert e_cor.headword == "coração"
        assert e_sab_ac.headword == "sabiá"
        assert e_sab.headword == "sabia"
        assert c1.cached_count() == 3
    finally:
        c1.close()

    c2 = AuleteClient(fetcher=lambda _u: (_ for _ in ()).throw(urllib.error.URLError("offline")), cache_path=cache_db)
    try:
        assert c2.lookup("coracao").headword == "coração"
        assert c2.lookup("coração").headword == "coração"
        assert "pássaro." in c2.lookup("sabiá").original_html
        assert "variedade de uva." in c2.lookup("sabia").original_html
    finally:
        c2.close()


def test_disk_cache_ignores_not_found_and_errors(tmp_path):
    cache_db = tmp_path / "aulete_cache.db"

    def fetcher(url: str) -> bytes:
        if url.endswith("falha"):
            raise urllib.error.URLError("timeout")
        return _make_html(nocab="", orig_body="Não foi encontrado o verbete", hide_orig=True)

    c1 = AuleteClient(fetcher=fetcher, cache_path=cache_db)
    try:
        assert not c1.lookup("inexistente").found
        assert c1.lookup("falha").error
        assert c1.cached_count() == 0
    finally:
        c1.close()

    c2 = AuleteClient(fetcher=fetcher, cache_path=cache_db)
    try:
        assert c2.get_cached("inexistente") is None
        assert c2.get_cached("falha") is None
    finally:
        c2.close()


def test_force_refresh_updates_and_preserves_cache_on_error(tmp_path):
    cache_db = tmp_path / "aulete_cache.db"
    state = {"mode": "v1"}

    def fetcher(_url: str) -> bytes:
        if state["mode"] == "offline":
            raise urllib.error.URLError("sem rede")
        txt = "versão um" if state["mode"] == "v1" else "versão dois"
        return _make_html(
            nocab="casa",
            orig_body=f'<span class="textodeforiginal">s. f. || {txt}.</span>',
            hide_atual=True,
        )

    c = AuleteClient(fetcher=fetcher, cache_path=cache_db)
    try:
        e1 = c.lookup("casa")
        assert "versão um." in e1.original_html

        state["mode"] = "offline"
        err = c.lookup("casa", force_refresh=True)
        assert err.error
        # A cópia salva em disco continua preservada e acessível offline
        still = c.lookup("casa")
        assert still.found and "versão um." in still.original_html

        state["mode"] = "v2"
        refreshed = c.lookup("casa", force_refresh=True)
        assert refreshed.found and not refreshed.from_cache
        assert "versão dois." in refreshed.original_html
    finally:
        c.close()

    c2 = AuleteClient(fetcher=lambda _u: (_ for _ in ()).throw(urllib.error.URLError("offline")), cache_path=cache_db)
    try:
        assert "versão dois." in c2.lookup("casa").original_html
    finally:
        c2.close()


def test_lookup_candidates_falls_back_to_cached_when_first_errors(tmp_path):
    cache_db = tmp_path / "aulete_cache.db"

    c1 = AuleteClient(
        fetcher=lambda _u: _make_html(
            nocab="caber",
            orig_body='<span class="textodeforiginal">v. || estar contido.</span>',
            hide_atual=True,
        ),
        cache_path=cache_db,
    )
    try:
        assert c1.lookup("caber").found
    finally:
        c1.close()

    c2 = AuleteClient(
        fetcher=lambda _u: (_ for _ in ()).throw(urllib.error.URLError("offline")),
        cache_path=cache_db,
    )
    try:
        res = c2.lookup_candidates(["coubesse", "caber"])
        assert res.found and res.from_cache and res.headword == "caber"
    finally:
        c2.close()


def test_clear_cache_and_default_cache_path(tmp_path, monkeypatch):
    cache_db = tmp_path / "aulete_cache.db"
    c = AuleteClient(
        fetcher=lambda _u: _make_html(
            nocab="casa",
            orig_body='<span class="textodeforiginal">s. f. || morada.</span>',
            hide_atual=True,
        ),
        cache_path=cache_db,
    )
    try:
        assert c.lookup("casa").found
        assert c.cached_count() == 1
        assert c.clear_cache() >= 1
        assert c.cached_count() == 0
        assert c.get_cached("casa") is None
    finally:
        c.close()

    # Resolução de caminho padrão
    monkeypatch.setenv("ABONARIO_AULETE_CACHE", str(tmp_path / "custom.db"))
    assert default_cache_path() == tmp_path / "custom.db"

    monkeypatch.setenv("ABONARIO_AULETE_CACHE", "")
    assert default_cache_path() is None

    monkeypatch.delenv("ABONARIO_AULETE_CACHE", raising=False)
    portable_dir = tmp_path / "portatil"
    portable_dir.mkdir()
    db_file = portable_dir / "abonario.db"
    db_file.write_bytes(b"")
    portable_cache = portable_dir / "aulete_cache.db"
    portable_cache.write_bytes(b"")
    assert default_cache_path(db_file) == portable_cache

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    assert default_cache_path(tmp_path / "outro" / "abonario.db") == tmp_path / "localappdata" / "Abonario" / "aulete_cache.db"


def test_render_offline_indicator_and_refresh_links():
    cached_entry = AuleteEntry(
        query="fazer",
        headword="fazer",
        original_html='<p class="aulete-orig">v. tr. || criar.</p>',
        updated_html='<p class="textodef">Criar.</p>',
        updated_label="Verbete Atualizado",
        from_cache=True,
    )
    html_orig = render.aulete_section_html(cached_entry, mode="original")
    assert "salvo offline" in html_orig
    assert 'href="aulete:updated"' in html_orig
    assert 'href="aulete:refresh"' in html_orig

    html_upd = render.aulete_section_html(cached_entry, mode="updated")
    assert "salvo offline" in html_upd
    assert 'href="aulete:original"' in html_upd
    assert 'href="aulete:refresh"' in html_upd

    err_entry = AuleteEntry(query="fazer", error="offline")
    html_err = render.aulete_section_html(err_entry)
    assert "ainda não está salvo offline" in html_err
    assert 'href="aulete:refresh"' in html_err


def test_main_window_aulete_offline(tmp_path, request):
    pytest.importorskip("PySide6")
    qt = request.getfixturevalue("qt")
    database = request.getfixturevalue("database")
    from PySide6.QtCore import QThreadPool
    from app.ui.main_window import MainWindow

    cache_db = tmp_path / "aulete_cache.db"
    seed = AuleteClient(
        fetcher=lambda _u: _make_html(
            nocab="fazer",
            orig_body='<span class="textodeforiginal">v. tr. || criar, formar.</span>',
            atual_body='<p><span class="numdef">1.</span> <span class="textodef">Criar.</span></p>',
        ),
        cache_path=cache_db,
    )
    try:
        assert seed.lookup("fazer").found
    finally:
        seed.close()

    offline_calls: list[str] = []

    def offline_fetcher(url: str) -> bytes:
        offline_calls.append(url)
        raise urllib.error.URLError("sem conexão")

    client = AuleteClient(fetcher=offline_fetcher, cache_path=cache_db)
    win = MainWindow(database, aulete=client)
    win.persist = False
    try:
        win.navigate("fizéramos")
        qt.processEvents()
        assert "Caldas Aulete" in win._entry_body
        assert "salvo offline" in win._entry_body
        assert "criar, formar." in win._entry_body
        assert offline_calls == []

        # Tentar atualizar offline não deve apagar o verbete salvo em tela
        win.refresh_aulete()
        QThreadPool.globalInstance().waitForDone()
        qt.processEvents()
        assert len(offline_calls) >= 1
        assert "criar, formar." in win._entry_body
    finally:
        win.close()
        client.close()


def test_build_aulete_resolve_cache_path(tmp_path, monkeypatch):
    import build_aulete

    db_file = tmp_path / "data" / "abonario.db"
    db_file.parent.mkdir()
    db_file.write_bytes(b"")

    monkeypatch.delenv("ABONARIO_AULETE_CACHE", raising=False)
    assert build_aulete.resolve_cache_path(db_file) == (db_file.parent / "aulete_cache.db").resolve()

    monkeypatch.setenv("ABONARIO_AULETE_CACHE", str(tmp_path / "env_cache.db"))
    assert build_aulete.resolve_cache_path(db_file) == (tmp_path / "env_cache.db").resolve()

    explicit = tmp_path / "explicit.db"
    assert build_aulete.resolve_cache_path(db_file, explicit) == explicit.resolve()


def test_build_aulete_progress_formatting_and_reporter():
    import io
    import build_aulete

    assert build_aulete._fmt_duration(-1) == "--:--"
    assert build_aulete._fmt_duration(float("inf")) == "--:--"
    assert build_aulete._fmt_duration(65) == "01:05"
    assert build_aulete._fmt_duration(3661) == "01:01:01"

    line = build_aulete._format_progress(
        done=4,
        target=20,
        elapsed=2.0,
        stats={"found": 3, "not_found": 1, "errors": 0},
        cache_total=14,
        current="palavramuitolongaextraordinaria",
    )
    assert "[####----------------]" in line
    assert "20.0% (4/20)" in line
    assert "ok=3 miss=1 err=0" in line
    assert "cache=14" in line
    assert "2.0/s" in line
    assert "decorrido 00:02 ETA 00:08" in line
    assert "palavramuitolongaextr..." in line

    class _FakeTTY(io.StringIO):
        def isatty(self) -> bool:
            return True

    tty_stream = _FakeTTY()
    rep = build_aulete._ProgressReporter(target=4, every=2, stream=tty_stream)
    rep.update(1, {"found": 1, "not_found": 0, "errors": 0}, 1, current="casa")
    rep.update(2, {"found": 2, "not_found": 0, "errors": 0}, 2, current="amor")
    rep.break_line()
    out = tty_stream.getvalue()
    assert out.startswith("\r[#####---------------]") and out.endswith("\n")

    logs: list[str] = []
    orig_log = build_aulete.log
    build_aulete.log = lambda *a: logs.append(" ".join(str(x) for x in a))
    try:
        rep2 = build_aulete._ProgressReporter(target=5, every=2, stream=io.StringIO())
        for i in range(1, 6):
            rep2.update(i, {"found": i, "not_found": 0, "errors": 0}, i, current=f"w{i}")
        assert len(logs) == 4  # done=1, 2, 4, 5
    finally:
        build_aulete.log = orig_log


def test_build_aulete_populate_resume_and_checkpoint(tmp_path):
    import sqlite3
    import threading
    import build_aulete

    db_path = tmp_path / "abonario.db"
    cache_path = tmp_path / "aulete_cache.db"
    misses_path = tmp_path / "aulete_misses.txt"

    con = sqlite3.connect(db_path)
    con.executescript(
        """
        CREATE TABLE headwords(key TEXT PRIMARY KEY, lemma TEXT NOT NULL, fold TEXT NOT NULL, srcmask INTEGER NOT NULL) WITHOUT ROWID;
        CREATE TABLE alt(old TEXT PRIMARY KEY, modern TEXT NOT NULL) WITHOUT ROWID;
        CREATE TABLE term_freq(term TEXT PRIMARY KEY, n INTEGER NOT NULL) WITHOUT ROWID;
        INSERT INTO headwords VALUES ('casa', 'casa', 'casa', 3);
        INSERT INTO headwords VALUES ('inexistente', 'inexistente', 'inexistente', 2);
        INSERT INTO headwords VALUES ('instavel', 'instavel', 'instavel', 2);
        INSERT INTO headwords VALUES ('&', '&', '&', 2);
        INSERT INTO term_freq VALUES ('casa', 100), ('inexistente', 50), ('instavel', 10);
        """
    )
    con.commit()
    con.close()

    lock = threading.Lock()
    calls: list[str] = []
    state = {"fail": True}

    def fake_fetch(url: str) -> bytes:
        with lock:
            calls.append(url)
        if url.endswith("/casa"):
            return _make_html(
                nocab="casa",
                orig_body='<span class="textodeforiginal">s. f. || morada.</span>',
                hide_atual=True,
            )
        if url.endswith("/inexistente"):
            return _make_html(nocab="", orig_body="Não foi encontrado o verbete", hide_orig=True)
        if url.endswith("/instavel"):
            if state["fail"]:
                raise urllib.error.URLError("timeout simulado")
            return _make_html(
                nocab="instavel",
                orig_body='<span class="textodeforiginal">adj. || variável.</span>',
                hide_atual=True,
            )
        raise AssertionError(url)

    s1 = build_aulete.populate(
        db_path,
        cache_path,
        misses_path,
        delay=0,
        workers=2,
        batch_size=2,
        retries=0,
        progress_every=1,
        fetcher=fake_fetch,
    )
    assert s1["candidates"] == 3
    assert s1["fetched"] == 3
    assert s1["found"] == 1
    assert s1["not_found"] == 1
    assert s1["errors"] == 1
    assert "casa" in build_aulete.load_cached_keys(cache_path)
    assert build_aulete.load_misses(misses_path) == {"inexistente"}
    assert not (tmp_path / "aulete_cache.db-wal").exists()
    assert not (tmp_path / "aulete_cache.db-shm").exists()

    calls.clear()
    state["fail"] = False
    s2 = build_aulete.populate(
        db_path,
        cache_path,
        misses_path,
        delay=0,
        workers=2,
        batch_size=2,
        retries=0,
        progress_every=1,
        vacuum=True,
        fetcher=fake_fetch,
    )
    assert len(calls) == 1 and calls[0].endswith("/instavel")
    assert s2["fetched"] == 1 and s2["found"] == 1 and s2["errors"] == 0
    assert {"casa", "instavel"}.issubset(build_aulete.load_cached_keys(cache_path))
    assert not (tmp_path / "aulete_cache.db-wal").exists()
    assert not (tmp_path / "aulete_cache.db-shm").exists()


def test_build_aulete_retry_and_backoff_on_429(tmp_path):
    import email.message
    import sqlite3
    import build_aulete

    db_path = tmp_path / "abonario.db"
    cache_path = tmp_path / "aulete_cache.db"
    misses_path = tmp_path / "aulete_misses.txt"

    con = sqlite3.connect(db_path)
    con.executescript(
        """
        CREATE TABLE headwords(key TEXT PRIMARY KEY, lemma TEXT NOT NULL, fold TEXT NOT NULL, srcmask INTEGER NOT NULL) WITHOUT ROWID;
        CREATE TABLE alt(old TEXT PRIMARY KEY, modern TEXT NOT NULL) WITHOUT ROWID;
        CREATE TABLE term_freq(term TEXT PRIMARY KEY, n INTEGER NOT NULL) WITHOUT ROWID;
        INSERT INTO headwords VALUES ('casa', 'casa', 'casa', 3);
        """
    )
    con.commit()
    con.close()

    attempts = {"n": 0}

    def flaky_429(url: str) -> bytes:
        attempts["n"] += 1
        if attempts["n"] == 1:
            hdrs = email.message.Message()
            hdrs["Retry-After"] = "0.01"
            raise urllib.error.HTTPError(url, 429, "Too Many Requests", hdrs, None)
        return _make_html(
            nocab="casa",
            orig_body='<span class="textodeforiginal">s. f. || morada.</span>',
            hide_atual=True,
        )

    s = build_aulete.populate(
        db_path,
        cache_path,
        misses_path,
        delay=0,
        workers=1,
        retries=1,
        fetcher=flaky_429,
    )
    assert attempts["n"] == 2
    assert s["found"] == 1 and s["errors"] == 0
    assert "casa" in build_aulete.load_cached_keys(cache_path)


def test_keep_alive_fetcher_reuses_connection_gzip_and_errors():
    import gzip
    import http.server
    import threading
    import build_aulete

    seen_ports: list[int] = []

    class _Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format, *args):  # noqa: A002
            pass

        def do_GET(self):  # noqa: N802
            seen_ports.append(self.client_address[1])
            if self.path == "/gzip":
                payload = gzip.compress(b"conteudo comprimido")
                self.send_response(200)
                self.send_header("Content-Encoding", "gzip")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            elif self.path == "/plain":
                payload = b"conteudo simples"
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            elif self.path == "/rate":
                payload = b"slow down"
                self.send_response(429)
                self.send_header("Retry-After", "0.05")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            else:
                self.send_response(503)
                self.send_header("Content-Length", "0")
                self.end_headers()

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    fetcher = build_aulete._KeepAliveFetcher(timeout=5.0)
    try:
        base = f"http://127.0.0.1:{port}"
        assert fetcher(f"{base}/gzip") == b"conteudo comprimido"
        assert fetcher(f"{base}/plain") == b"conteudo simples"
        # Reutilizou a mesma porta de origem (conexão TCP keep-alive)
        assert len(seen_ports) == 2 and seen_ports[0] == seen_ports[1]

        with pytest.raises(urllib.error.HTTPError) as exc_429:
            fetcher(f"{base}/rate")
        assert exc_429.value.code == 429
        assert exc_429.value.headers["Retry-After"] == "0.05"

        with pytest.raises(urllib.error.HTTPError) as exc_503:
            fetcher(f"{base}/err")
        assert exc_503.value.code == 503
    finally:
        fetcher.close()
        srv.shutdown()
        srv.server_close()
