"""Janela principal do Abonário (Qt Widgets, sem navegador embutido)."""
from __future__ import annotations

from urllib.parse import unquote

from PySide6.QtCore import (QAbstractListModel, QModelIndex, QObject, QRunnable, QSettings, Qt,
                            QThreadPool, Signal)
from PySide6.QtGui import (QAction, QActionGroup, QColor, QFont, QGuiApplication, QIcon, QKeySequence,
                           QPainter)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QHBoxLayout, QLabel, QLineEdit, QListView, QMainWindow, QMessageBox,
                               QPushButton, QSplitter, QStyle, QTabWidget, QTextBrowser, QToolBar, QToolButton, QMenu,
                               QVBoxLayout, QWidget)

from ..core.db import Database, Sentence
from ..core.lookup import Lookup, LookupResult, Reading
from ..core.textnorm import WORD_RE, normalize_token
from . import render, themes

PAGE = 25


def page_html(body: str) -> str:
    return f"<html><head><style>{render.CSS}</style></head><body>{body}</body></html>"


# ---------------------------------------------------------------------------
class HeadwordModel(QAbstractListModel):
    def __init__(self, heads: list[tuple[str, str]]) -> None:
        super().__init__()
        self.heads = heads

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.heads)

    def data(self, index, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and index.isValid():
            return self.heads[index.row()][1]
        return None


class Browser(QTextBrowser):
    link = Signal(str, str)  # tipo, valor

    def __init__(self) -> None:
        super().__init__()
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.anchorClicked.connect(self._clicked)
        self.document().setDocumentMargin(14)

    def _clicked(self, url) -> None:
        s = url.toString()
        kind, _, value = s.partition(":")
        self.link.emit(kind, unquote(value))


# -- contagem em segundo plano ------------------------------------------------------------
class _CountSignals(QObject):
    done = Signal(int, int)


class _CountTask(QRunnable):
    def __init__(self, fn, token: int, signals: _CountSignals) -> None:
        super().__init__()
        self.fn, self.token, self.signals = fn, token, signals

    def run(self) -> None:
        try:
            n = self.fn()
        except Exception:  # noqa: BLE001
            n = -1
        try:
            self.signals.done.emit(self.token, n)
        except RuntimeError:  # painel já fechado (programa encerrando)
            pass


class QuotesList(QWidget):
    """Lista paginada de trechos para um conjunto de termos."""
    counted = Signal()

    def __init__(self, db: Database, owner: "QuotesPanel") -> None:
        super().__init__()
        self.db, self.owner = db, owner
        self.view = Browser()
        self.view.link.connect(self._link)
        self.more = QPushButton("Carregar mais trechos")
        self.more.clicked.connect(self.load_more)
        self.info = QLabel()
        bar = QHBoxLayout()
        bar.addWidget(self.info, 1)
        bar.addWidget(self.more)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.view, 1)
        lay.addLayout(bar)
        self.terms: list[str] = []
        self.termset: set[str] = set()
        self.parts: list[str] = []
        self.sents: dict[int, Sentence] = {}
        self.last_rk = 0
        self.total: int | None = None
        self.token = 0
        self.signals = _CountSignals()
        self.signals.done.connect(self._count_done)
        self.empty_msg = ""
        self._has_more = False
        self.phrase: list[str] | None = None

    def set_terms(self, terms: list[str], empty_msg: str = "", phrase: list[str] | None = None) -> None:
        """terms: formas (busca por qualquer uma); phrase: palavras de uma expressão (em sequência)."""
        self.token += 1
        self.phrase = phrase if phrase and len(phrase) > 1 else None
        self.terms = list(self.phrase) if self.phrase else [t for t in dict.fromkeys(terms) if t]
        self.termset = set(self.terms)
        self.parts, self.sents, self.last_rk, self.total = [], {}, 0, None
        self.empty_msg = empty_msg
        if self.terms:
            db, terms_, words = self.db, list(self.terms), self.phrase
            if words:
                fn = lambda: db.count_filtered(  # noqa: E731
                    list(dict.fromkeys(words)), lambda t: render.contains_phrase(t, words, db.terms_for))
            else:
                fn = lambda: db.count_sentences(terms_)  # noqa: E731
            QThreadPool.globalInstance().start(_CountTask(fn, self.token, self.signals))
        self.load_more(reset=True)

    def _count_done(self, token: int, n: int) -> None:
        if token == self.token:
            self.total = n if n >= 0 else None
            self._update_info()
            self.counted.emit()

    def _update_info(self) -> None:
        shown = len(self.sents)
        tot = "…" if self.total is None else render.fmt_n(self.total)
        self.info.setText(f"{render.fmt_n(shown)} de {tot} trechos" if self.terms else "")
        self.more.setEnabled(bool(self.terms) and (self.total is None or shown < self.total) and self._has_more)

    def load_more(self, reset: bool = False) -> None:
        country, author = self.owner.filters()
        words = self.phrase
        op = "OR"
        if words:  # expressão: todas as palavras, depois confere a sequência exata
            op = "AND"
            accept = lambda t: render.contains_phrase(t, words, self.db.terms_for)  # noqa: E731
        elif not self.owner.proper_query():  # pula trechos em que a palavra só aparece como nome próprio
            accept = lambda t: render.has_common_match(t, self.termset, self.db.terms_for)  # noqa: E731
        else:
            accept = None
        try:
            terms = list(dict.fromkeys(self.terms))
            new, self.last_rk = self.db.sentences(terms, self.last_rk, PAGE, country, author, accept, op)
        except Exception:  # noqa: BLE001  nunca deixa na tela os trechos da busca anterior
            new = []
        self._has_more = len(new) == PAGE
        for s in new:
            self.sents[s.id] = s
            self.parts.append(render.quote_html(s, self.termset, self.db.terms_for, words))
        self.rerender(keep_scroll=not reset)
        self._update_info()

    def rerender(self, keep_scroll: bool = True) -> None:
        """Redesenha os trechos já carregados (usado também ao trocar de tema)."""
        bar = self.view.verticalScrollBar()
        pos = bar.value() if keep_scroll else 0
        if not self.parts:
            msg = self.empty_msg or "Nenhum trecho encontrado nos textos."
            self.view.setHtml(page_html(f'<p class="muted">{render.e(msg)}</p>'))
        else:
            self.view.setHtml(page_html("".join(self.parts)))
        bar.setValue(pos)

    def _link(self, kind: str, value: str) -> None:
        if not value.isdigit():
            return
        s = self.sents.get(int(value))
        if kind == "cp" and s:
            QGuiApplication.clipboard().setText(f"{s.text}\n— {s.work.citation()}")
            self.owner.window().statusBar().showMessage("Trecho copiado com a referência.", 4000)
        elif kind == "ctx" and s:
            ContextDialog(self.db, s, self.termset, self, self.phrase).exec()


class ContextDialog(QDialog):
    def __init__(self, db: Database, s: Sentence, termset: set[str], parent=None,
                 phrase: list[str] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Contexto")
        self.resize(720, 460)
        view = QTextBrowser()
        parts = []
        for sid, text in db.context(s.id, 4):
            if phrase:
                body = render.highlight_phrase(text, phrase, db.terms_for)
            else:
                body = render.highlight(text, termset, db.terms_for)
            parts.append(f"<p><b>{body}</b></p>" if sid == s.id else f'<p class="muted">{body}</p>')
        parts.append(f'<p class="qcit">— {render.e(s.work.citation())}</p>')
        view.setHtml(page_html("".join(parts)))
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        copy = buttons.addButton("Copiar trecho", QDialogButtonBox.ActionRole)
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(f"{s.text}\n— {s.work.citation()}"))
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(view)
        lay.addWidget(buttons)


class QuotesPanel(QWidget):
    def __init__(self, db: Database) -> None:
        super().__init__()
        self.db = db
        self.title = QLabel("Abonações")
        f = self.title.font()
        f.setBold(True)
        self.title.setFont(f)
        self.country = QComboBox()
        self.country.addItem("Brasil e Portugal", "")
        self.country.addItem("Só autores brasileiros", "BR")
        self.country.addItem("Só autores portugueses", "PT")
        self.author = QLineEdit()
        self.author.setPlaceholderText("filtrar por autor")
        self.author.setClearButtonEnabled(True)
        self.author.setMaximumWidth(220)
        self.no_amb = QCheckBox("excluir formas ambíguas")
        self.no_amb.setToolTip("Na aba de todas as formas, ignora formas que também pertencem a outro lema")
        top = QHBoxLayout()
        top.addWidget(self.title, 1)
        top.addWidget(self.no_amb)
        top.addWidget(self.country)
        top.addWidget(self.author)
        self.tabs = QTabWidget()
        self.exact = QuotesList(db, self)
        self.all = QuotesList(db, self)
        self.tabs.addTab(self.exact, "Esta forma")
        self.tabs.addTab(self.all, "Todas as formas")
        self.exact.counted.connect(self._labels)
        self.all.counted.connect(self._labels)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.addLayout(top)
        lay.addWidget(self.tabs, 1)
        self.country.currentIndexChanged.connect(self.reload)
        self.author.editingFinished.connect(self.reload)
        self.no_amb.toggled.connect(self.reload)
        self.form = ""
        self.lemma = ""
        self.query = ""
        self.forms: list[str] = []

    def filters(self) -> tuple[str, str]:
        return self.country.currentData() or "", self.author.text().strip()

    def proper_query(self) -> bool:
        """O usuário pesquisou um nome próprio (Brasil, Lisboa)? Então não filtra maiúsculas."""
        return bool(self.lemma[:1].isupper() or self.query[:1].isupper())

    def set_queries(self, form: str, lemma: str | None, forms: list[str], query: str = "") -> None:
        lemma = lemma or ""
        self.form, self.lemma, self.forms, self.query = form, lemma, forms, query
        self.reload()
        multi = len(WORD_RE.findall(lemma)) > 1  # expressão: não há "outras formas"
        self.tabs.setCurrentIndex(0 if (not lemma or multi or form != lemma.lower()) else 1)

    def _set_exact(self, form: str) -> None:
        words = [normalize_token(w) for w in WORD_RE.findall(form)] if form else []
        if len(words) > 1:
            self.exact.set_terms([], "A expressão não aparece, nessa sequência, nos textos.", phrase=words)
        else:
            self.exact.set_terms(words)

    def show_form(self, form: str) -> None:
        self.form = form
        self._set_exact(form)
        self._labels()
        self.tabs.setCurrentIndex(0)

    def reload(self) -> None:
        self._set_exact(self.form)
        multi = len(WORD_RE.findall(self.lemma)) > 1
        forms = [] if multi else self.forms
        if self.no_amb.isChecked() and forms:
            amb = self.db.lemma_count(forms)
            forms = [f for f in forms if amb.get(f, 0) <= 1 or f == self.lemma.lower()]
        self.all.set_terms(forms, "Sem trechos para as formas deste lema.")
        self.tabs.setTabEnabled(1, bool(self.lemma) and not multi)
        self._labels()

    def _labels(self) -> None:
        def n(lst: QuotesList) -> str:
            return "" if lst.total is None else f" ({render.fmt_n(lst.total)})"
        multi = len(WORD_RE.findall(self.form)) > 1
        label0 = "Esta expressão" if multi else "Esta forma"
        self.tabs.setTabText(0, f"{label0}: {self.form}{n(self.exact)}" if self.form else label0)
        if self.lemma and len(WORD_RE.findall(self.lemma)) > 1:
            self.tabs.setTabText(1, "Todas as formas")
        else:
            self.tabs.setTabText(1, f"Todas as formas de {self.lemma}{n(self.all)}" if self.lemma else "Todas as formas")
        self.title.setText("Abonações — trechos de escritores brasileiros e portugueses")

    def zoom(self, step: int) -> None:
        for b in (self.exact.view, self.all.view):
            b.zoomIn(step) if step > 0 else b.zoomOut(-step)

    def restyle(self, muted: str) -> None:
        for lst in (self.exact, self.all):
            lst.info.setStyleSheet(f"color:{muted}")
            lst.rerender()


# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self, db: Database) -> None:
        super().__init__()
        self.db = db
        self.lookup = Lookup(db)
        self.settings = QSettings("Abonario", "Abonario")
        self.history: list[tuple[str, str]] = []
        self.hpos = -1
        self.zoom_level = 0
        self.setWindowTitle("Abonário — dicionário da língua portuguesa com abonações")
        self.resize(1280, 860)

        # barra de ferramentas
        tb = QToolBar("Navegação")
        tb.setMovable(False)
        self.addToolBar(tb)
        st = self.style()
        self.act_back = QAction(st.standardIcon(QStyle.SP_ArrowBack), "Voltar", self)
        self.act_back.setShortcut(QKeySequence.Back)
        self.act_back.triggered.connect(lambda: self.go_history(-1))
        self.act_fwd = QAction(st.standardIcon(QStyle.SP_ArrowForward), "Avançar", self)
        self.act_fwd.setShortcut(QKeySequence.Forward)
        self.act_fwd.triggered.connect(lambda: self.go_history(1))
        tb.addAction(self.act_back)
        tb.addAction(self.act_fwd)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Pesquise uma palavra ou forma flexionada — ex.: fizéramos, coubesse, meninas, coracao, *ção")
        self.search.setClearButtonEnabled(True)
        f = self.search.font()
        f.setPointSize(f.pointSize() + 2)
        self.search.setFont(f)
        self.search.returnPressed.connect(self.do_search)
        self.search.textEdited.connect(self.scroll_list)
        self.mode = QComboBox()
        self.mode.addItem("Palavra ou forma", "word")
        self.mode.addItem("Nas definições", "defs")
        go = QPushButton("Pesquisar")
        go.clicked.connect(self.do_search)
        tb.addWidget(self.search)
        tb.addWidget(self.mode)
        tb.addWidget(go)
        find = QAction("Pesquisar", self)
        find.setShortcut(QKeySequence.Find)
        find.triggered.connect(lambda: (self.search.setFocus(), self.search.selectAll()))
        self.addAction(find)
        tb.addSeparator()
        a_minus = QAction("A−", self)
        a_minus.setShortcut(QKeySequence.ZoomOut)
        a_minus.triggered.connect(lambda: self.zoom(-1))
        a_plus = QAction("A+", self)
        a_plus.setShortcut(QKeySequence.ZoomIn)
        a_plus.triggered.connect(lambda: self.zoom(1))
        tb.addAction(a_minus)
        tb.addAction(a_plus)
        # tema: claro, sépia ou escuro
        self.theme_btn = QToolButton()
        self.theme_btn.setText("Tema")
        self.theme_btn.setToolTip("Aparência: claro, sépia ou escuro")
        self.theme_btn.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self)
        group = QActionGroup(self)
        group.setExclusive(True)
        self.theme_actions: dict[str, QAction] = {}
        for key, t in themes.THEMES.items():
            act = QAction(t["label"], self, checkable=True)
            act.triggered.connect(lambda _checked=False, k=key: self.apply_theme(k))
            group.addAction(act)
            menu.addAction(act)
            self.theme_actions[key] = act
        self.theme_btn.setMenu(menu)
        tb.addWidget(self.theme_btn)
        a_about = QAction("Fontes e licenças", self)
        a_about.triggered.connect(self.about)
        tb.addAction(a_about)

        # lista de verbetes
        self.model = HeadwordModel(db.headwords())
        self.list = QListView()
        self.list.setModel(self.model)
        self.list.setUniformItemSizes(True)
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.activated.connect(self.list_open)
        self.list.clicked.connect(self.list_open)
        self.list.setMinimumWidth(190)

        self.entry = Browser()
        self.entry.link.connect(self.on_link)
        self.quotes = QuotesPanel(db)
        right = QSplitter(Qt.Vertical)
        right.addWidget(self.entry)
        right.addWidget(self.quotes)
        right.setStretchFactor(0, 3)
        right.setStretchFactor(1, 2)
        self.vsplit = right
        main = QSplitter(Qt.Horizontal)
        main.addWidget(self.list)
        main.addWidget(right)
        main.setStretchFactor(1, 1)
        main.setSizes([230, 1050])
        self.hsplit = main
        self.setCentralWidget(main)
        s = db.stats
        self.statusBar().showMessage(
            f"{render.fmt_n(s['verbetes'])} verbetes · {render.fmt_n(s['formas'])} formas flexionadas · "
            f"{render.fmt_n(s['trechos'])} trechos de {render.fmt_n(s['obras'])} obras · 100% offline")
        self._restore()
        self._entry_body = ""
        self._native_style = QApplication.instance().style().name()
        self.set_entry(self.welcome())
        self.apply_theme(str(self.settings.value("theme", "claro")), save=False)
        self._nav_buttons()

    # -- tema e conteúdo ---------------------------------------------------------------
    def set_entry(self, body: str) -> None:
        self._entry_body = body
        self.entry.setHtml(page_html(body))

    def apply_theme(self, name: str, save: bool = True) -> None:
        if name not in themes.THEMES:
            name = "claro"
        t = themes.THEMES[name]
        app = QApplication.instance()
        app.setStyle(t["style"] or self._native_style)
        app.setPalette(themes.palette(t) if t["palette"] else app.style().standardPalette())
        render.CSS = themes.css(t)
        bar = self.entry.verticalScrollBar()
        pos = bar.value()
        self.entry.setHtml(page_html(self._entry_body))
        bar.setValue(pos)
        self.quotes.restyle(t["css"]["muted"])
        st = app.style()
        for act, sp in ((self.act_back, QStyle.SP_ArrowBack), (self.act_fwd, QStyle.SP_ArrowForward)):
            icon = st.standardIcon(sp)
            if name == "escuro":  # ícones padrão são escuros: pinta com a cor do texto
                pm = icon.pixmap(32, 32)
                p = QPainter(pm)
                p.setCompositionMode(QPainter.CompositionMode_SourceIn)
                p.fillRect(pm.rect(), QColor(t["css"]["text"]))
                p.end()
                icon = QIcon(pm)
            act.setIcon(icon)
        self.theme_actions[name].setChecked(True)
        self.theme = name
        if save and self.persist:
            self.settings.setValue("theme", name)

    # -- estado ------------------------------------------------------------------
    def _restore(self) -> None:
        g = self.settings.value("geometry")
        if g is not None:
            self.restoreGeometry(g)
        v = self.settings.value("vsplit")
        if v is not None:
            self.vsplit.restoreState(v)
        z = int(self.settings.value("zoom", 0))
        if z:
            self.zoom(z)

    persist = True  # o modo de teste (--smoke) não grava preferências

    def closeEvent(self, ev) -> None:  # noqa: N802
        if self.persist:
            self.settings.setValue("geometry", self.saveGeometry())
            self.settings.setValue("vsplit", self.vsplit.saveState())
            self.settings.setValue("zoom", self.zoom_level)
        super().closeEvent(ev)

    def zoom(self, step: int) -> None:
        self.zoom_level += step
        (self.entry.zoomIn(step) if step > 0 else self.entry.zoomOut(-step))
        self.quotes.zoom(step)

    def welcome(self) -> str:
        s = self.db.stats
        return (
            "<h1>Abonário</h1>"
            "<p>Dicionário da língua portuguesa com abonações de escritores brasileiros e portugueses.</p>"
            "<h2>Como usar</h2><ul>"
            "<li>Digite qualquer palavra ou <b>forma flexionada</b>: <a href='w:fizéramos'>fizéramos</a>, "
            "<a href='w:coubesse'>coubesse</a>, <a href='w:meninas'>meninas</a>, "
            "<a href='w:dir-lhe-ia'>dir-lhe-ia</a>. O programa encontra o verbete-base.</li>"
            "<li>Também reconhece grafias antigas: <a href='w:pharmacia'>pharmacia</a>, "
            "<a href='w:elle'>elle</a>, <a href='w:hontem'>hontem</a>; e palavras sem acento: "
            "<a href='w:coracao'>coracao</a>.</li>"
            "<li>Use <b>*</b> como coringa (<a href='w:*ção'>*ção</a>) ou escolha <i>Nas definições</i> "
            "para buscar dentro dos verbetes.</li>"
            "<li>No painel de abonações, a primeira aba mostra os trechos com a forma pesquisada; a segunda, "
            "com todas as formas do lema. Clique numa forma da conjugação para ver só os trechos dela.</li></ul>"
            f"<p class='muted'>{render.fmt_n(s['verbetes'])} verbetes · {render.fmt_n(s['formas'])} formas · "
            f"{render.fmt_n(s['trechos'])} trechos de {render.fmt_n(s['obras'])} obras.</p>"
        )

    # -- navegação --------------------------------------------------------------------
    def _nav_buttons(self) -> None:
        self.act_back.setEnabled(self.hpos > 0)
        self.act_fwd.setEnabled(self.hpos < len(self.history) - 1)

    def _push(self, kind: str, value: str) -> None:
        if self.hpos >= 0 and self.history[self.hpos] == (kind, value):
            return
        self.history = self.history[: self.hpos + 1] + [(kind, value)]
        self.hpos = len(self.history) - 1
        self._nav_buttons()

    def go_history(self, step: int) -> None:
        i = self.hpos + step
        if 0 <= i < len(self.history):
            self.hpos = i
            kind, value = self.history[i]
            self._open(kind, value, push=False)
            self._nav_buttons()

    def _open(self, kind: str, value: str, push: bool = True) -> None:
        if kind == "w":
            self.navigate(value, push)
        elif kind == "l":
            self.open_lemma(value, push)
        elif kind == "d":
            self.search_defs(value, push)

    def scroll_list(self, text: str) -> None:
        t = text.strip()
        if t and not any(c in t for c in "*?"):
            row = min(self.db.headword_position(t), self.model.rowCount() - 1)
            if row >= 0:
                idx = self.model.index(row)
                self.list.scrollTo(idx, QAbstractItemView.PositionAtTop)
                self.list.setCurrentIndex(idx)

    def list_open(self, idx) -> None:
        key, lemma = self.model.heads[idx.row()]
        self.open_lemma(lemma)

    def do_search(self) -> None:
        q = self.search.text().strip()
        if not q:
            return
        if self.mode.currentData() == "defs":
            self.search_defs(q)
        else:
            self.navigate(q)

    def on_link(self, kind: str, value: str) -> None:
        if kind == "w":
            self.search.setText(value)
            self.navigate(value)
        elif kind == "l":
            self.open_lemma(value)
        elif kind == "f":
            self.quotes.show_form(value)

    def navigate(self, query: str, push: bool = True) -> None:
        res = self.lookup.resolve(query)
        if push:
            self._push("w", query)
        if res.found:
            self.show_entry(res, res.main[0].lemma)
        else:
            self.set_entry(render.not_found_html(res))
            self.quotes.set_queries(res.form if not res.wildcard else "", None, [])

    def open_lemma(self, lemma: str, push: bool = True) -> None:
        if push:
            self._push("l", lemma)
        res = LookupResult(query=lemma, form=lemma.lower(),
                           main=[Reading(lemma, [], self.db.is_headword(lemma))], exact_terms=[lemma.lower()])
        head, others = self.lookup._readings(lemma.lower())
        res.also = [r for r in others if r.lemma != lemma]
        self.show_entry(res, lemma)

    def show_entry(self, res: LookupResult, lemma: str) -> None:
        html, forms, freq = render.entry_html(self.db, self.lookup, res, lemma)
        self.set_entry(html)
        attested = [f for f in forms if freq.get(f)]
        form = res.form
        if res.via == "busca sem acentos":  # coracao -> trechos de "coração"
            form = lemma.lower()
        self.quotes.set_queries(form, lemma, attested, res.query)
        row = self.db.headword_position(lemma)
        if 0 <= row < self.model.rowCount() and self.model.heads[row][0] == lemma.lower():
            idx = self.model.index(row)
            self.list.scrollTo(idx, QAbstractItemView.PositionAtCenter)
            self.list.setCurrentIndex(idx)
        self.setWindowTitle(f"{lemma} — Abonário")

    def search_defs(self, query: str, push: bool = True) -> None:
        if push:
            self._push("d", query)
        keys = self.db.search_definitions(query)
        self.set_entry(render.definitions_html(query, keys))

    def about(self) -> None:
        QMessageBox.about(
            self, "Fontes e licenças",
            "<h3>Abonário</h3><p>Funciona inteiramente offline. Fontes dos dados:</p><ul>"
            "<li><b>Dicionário Aberto</b> (Novo Diccionário da Língua Portuguesa, Cândido de Figueiredo, 1913; "
            "edição digital de Alberto Simões e colaboradores) — CC BY-SA 2.5 PT.</li>"
            "<li><b>Wikcionário</b> (pt.wiktionary.org), extração kaikki.org — CC BY-SA 4.0.</li>"
            "<li><b>Wiktionary</b> (en.wiktionary.org), flexões e grafias antigas, extração kaikki.org — CC BY-SA 4.0.</li>"
            "<li><b>Lista de lematização do português</b>, Michal Měchura — ODbL.</li>"
            "<li><b>Projeto Gutenberg</b> — livros em domínio público.</li>"
            "<li><b>Wikisource em português</b> — textos em domínio público; transcrições CC BY-SA.</li></ul>"
            "<p>O Aulete Digital não está incluído: é obra protegida e sem distribuição livre.</p>")
