# Abonário

Dicionário da língua portuguesa para desktop (Windows) com busca primária no **Caldas Aulete**
([aulete.com.br](https://aulete.com.br), priorizando o **Verbete Original**), além de base
offline com abonações de escritores brasileiros e portugueses e lematização de qualquer forma
flexionada.

## Baixar

A versão pronta para Windows 10/11 (64 bits) está em
[Releases](https://github.com/k-claudio/abonario/releases), em duas formas:

- **`Instalar-Abonario.exe`** (recomendado): abra e siga o assistente. Instala só para o seu usuário,
  sem senha de administrador, cria os atalhos e pode ser desinstalado em *Configurações → Aplicativos*.
- **`Abonario-portatil.zip`**: não instala nada. Clique com o botão direito em **Extrair tudo** e abra o
  `Abonario.exe` **dentro da pasta extraída** (ele não funciona se for tirado da pasta).

Se o Windows mostrar "O Windows protegeu o computador", clique em **Mais informações → Executar assim mesmo**
(o aviso aparece porque o programa não tem assinatura digital paga).

## Uso

Abra **Abonário** pelo Menu Iniciar ou pela Área de Trabalho e digite uma palavra ou forma:
`fizéramos`, `coubesse`, `meninas`, `dir-lhe-ia`, `pharmacia`, `coracao`, `*ção`.

- O verbete realiza consulta primária online no **Caldas Aulete** (`aulete.com.br`), dando
  prioridade ao **Verbete Original** (com alternância para o *Verbete Atualizado* / *Verbete Novo*
  quando disponível e fallback para as fontes locais se estiver offline ou não encontrado).
  Mostra ainda a análise da forma (ex.: "1ª pessoa do plural do pretérito mais-que-perfeito do
  indicativo de **fazer**"), as definições do Dicionário Aberto e do Wikcionário, a conjugação
  e todas as formas encontradas nos textos.
- O painel de abonações tem duas abas: trechos com a forma pesquisada e trechos com
  todas as formas do lema. Filtros: Brasil/Portugal, autor, excluir formas ambíguas.
  "contexto" mostra as frases vizinhas; "copiar" copia o trecho com a referência.

## Reconstruir os dados (requer internet só nesta etapa)

```
py -3.12 -m venv .venv
.venv\Scripts\pip install PySide6-Essentials pyinstaller mwparserfromhell pytest
cd build
..\.venv\Scripts\python fetch.py            # baixa as fontes para cache/
..\.venv\Scripts\python build_lexicon.py    # formas -> lemas, grafias antigas
..\.venv\Scripts\python build_corpus.py     # Wikisource + Gutenberg -> trechos e índice
..\.venv\Scripts\python build_dictionary.py # Dicionário Aberto + Wikcionário
..\.venv\Scripts\python finalize.py         # VACUUM e relatório
cd ..
.venv\Scripts\python -m pytest -q
.venv\Scripts\pyinstaller --workpath cache\pyinstaller abonario.spec
powershell -ExecutionPolicy Bypass -File build\install.ps1
.venv\Scripts\python build\make_portable.py    # Abonario-portatil.zip
.venv\Scripts\python build\make_installer.py   # Instalar-Abonario.exe (requer o Inno Setup 6 ou 7)
```

O `install.ps1` **move** o banco (`data\abonario.db`) para a pasta instalada
(`%LOCALAPPDATA%\Programs\Abonario`). Os testes encontram o banco lá automaticamente.
Para liberar espaço depois de instalar, podem ser apagadas as pastas `cache\` (fontes baixadas,
~300 MB) e `.venv\`; elas só são necessárias para reconstruir os dados.

## Estrutura

- `app/core/aulete.py`: cliente HTTP com cache LRU, decodificador híbrido UTF-8/cp1252 e parser/sanitizador do `aulete.com.br` (prioridade ao Verbete Original).
- `app/core/textnorm.py`: tokenização, pronomes átonos (fazê-lo, dir-lhe-ia, separal-os) e
  modernização da grafia antiga (mettido → metido, quasi → quase). É usado na construção do índice.
- `app/core/lookup.py`: resolve a busca (forma → lema, grafia antiga, sem acento, coringas).
- `app/core/db.py`: consultas somente leitura ao `abonario.db` (SQLite + FTS5).
- `app/ui/`: interface Qt Widgets (sem navegador embutido).
- `build/`: scripts de construção dos dados.

## Licença

O código do Abonário é software livre, distribuído sob a **GNU General Public License v3.0**
(arquivo [LICENSE](LICENSE)). Os dados embutidos no programa seguem as licenças de suas fontes,
listadas abaixo.

## Fontes e licenças

- Caldas Aulete Digital (`aulete.com.br`) — consultado online na hora da busca (não embutido no banco local)
- Dicionário Aberto (Cândido de Figueiredo, 1913; ed. digital de Alberto Simões) — CC BY-SA 2.5 PT
- Wikcionário (pt) e Wiktionary (en), extrações de kaikki.org — CC BY-SA 4.0
- Lista de lematização do português, Michal Měchura — ODbL
- Projeto Gutenberg e Wikisource em português — textos em domínio público
