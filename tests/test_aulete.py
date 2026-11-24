"""Testes unitários para o cliente, parser, sanitizador e renderização do Caldas Aulete."""
from __future__ import annotations

import urllib.error

from app.core.aulete import AuleteClient, AuleteEntry, decode_aulete_bytes, parse_aulete_page
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
