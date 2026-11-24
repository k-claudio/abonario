"""Gera Instalar-Abonario.exe (Inno Setup) a partir da pasta com o programa e o banco.

Uso:  python build/make_installer.py [pasta_do_programa]
A pasta padrão é a instalação local (%LOCALAPPDATA%\\Programs\\Abonario), como em make_portable.py.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ISS = Path(__file__).resolve().parent / "abonario.iss"
OUT = ROOT / "Instalar-Abonario.exe"
# versão única do programa: app/__init__.py (__version__)
APP_VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")).group(1)


def find_iscc() -> Path:
    bases = [Path(os.environ.get("LOCALAPPDATA", "")) / "Programs",
             Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
             Path(os.environ.get("ProgramFiles", r"C:\Program Files"))]
    for version in ("Inno Setup 7", "Inno Setup 6"):
        for base in bases:
            exe = base / version / "ISCC.exe"
            if exe.exists():
                return exe
    raise SystemExit("ISCC.exe não encontrado: instale o Inno Setup (jrsoftware.org).")


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Abonario"
    for need in ("Abonario.exe", "abonario.db", "_internal"):
        if not (src / need).exists():
            raise SystemExit(f"Falta {need} em {src}")
    iscc = find_iscc()
    print(f"Compilando com {iscc.parent.name} a partir de {src} (pode levar alguns minutos)...", flush=True)
    res = subprocess.run([str(iscc), "/Q", f"/DSourceDir={src}", f"/DAppVersion={APP_VERSION}", str(ISS)],
                         capture_output=True, text=True, errors="replace")
    out = (res.stdout + res.stderr).strip()
    if out:
        print(out)
    if res.returncode != 0 or not OUT.exists():
        raise SystemExit(f"Falha ao gerar o instalador (código {res.returncode}).")
    print(f"{OUT}  ({OUT.stat().st_size / 2**20:.0f} MB)")


if __name__ == "__main__":
    main()
