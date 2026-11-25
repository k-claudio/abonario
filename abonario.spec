# -*- mode: python ; coding: utf-8 -*-
# Empacotamento do Abonário (PyInstaller, pasta única). Os bancos abonario.db e aulete_cache.db (opcional) são instalados à parte.

a = Analysis(
    ["run_abonario.py"],
    pathex=["."],
    datas=[("app/ui/abonario.png", "app/ui")],
    hiddenimports=[],
    excludes=[
        "tkinter", "unittest", "pydoc", "pytest", "mwparserfromhell",
        "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebChannel",
        "PySide6.QtMultimedia", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtSql",
        "PySide6.QtSvg", "PySide6.QtSvgWidgets", "PySide6.QtTest", "PySide6.QtXml", "PySide6.QtDBus",
        "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtConcurrent", "PySide6.QtPrintSupport",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Abonario",
    console=False,
    icon="app/ui/abonario.ico",
)
coll = COLLECT(exe, a.binaries, a.datas, name="Abonario")
