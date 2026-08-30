"""Ingest e limpeza de texto, com deteccao de capitulos (TDD 8, TEXT PROCESSOR)."""
from __future__ import annotations

import re
from pathlib import Path

# Titulos de capitulo em obras em portugues
_CAPITULO = re.compile(
    r"^\s*(cap[ií]tulo|cap\.|parte|livro|se[cç][aã]o)\s+"
    r"([IVXLCDM]+|\d+|[a-zà-ú]+)\s*[-–—.:]?\s*(.*)$",
    re.IGNORECASE)
_TITULO_ROMANO = re.compile(r"^\s*([IVXLCDM]{1,7})\s*[-–—.:]?\s*(.{0,60})$")


def ler(path: Path) -> str:
    """Le TXT, MD ou EPUB e devolve texto bruto."""
    suf = path.suffix.lower()
    if suf in (".txt", ".md"):
        return path.read_text(encoding="utf-8", errors="replace")
    if suf == ".epub":
        return _ler_epub(path)
    raise ValueError(f"formato nao suportado no MVP: {suf}")


def _ler_epub(path: Path) -> str:
    from bs4 import BeautifulSoup
    import ebooklib
    from ebooklib import epub

    livro = epub.read_epub(str(path))
    partes = []
    for item in livro.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        sopa = BeautifulSoup(item.get_content(), "html.parser")
        texto = sopa.get_text("\n")
        if texto.strip():
            partes.append(texto)
    return "\n\n".join(partes)


def limpar(texto: str) -> str:
    """Limpeza conservadora: nao reescreve prosa, so remove artefato de digitalizacao."""
    # de-hifenizacao de quebra de linha: "expedi-\ncao" -> "expedicao"
    texto = re.sub(r"(\w)-\n(\w)", r"\1\2", texto)
    # numeros de pagina isolados
    texto = re.sub(r"^\s*\d{1,4}\s*$", "", texto, flags=re.MULTILINE)
    # cabecalho/rodape repetido em CAIXA ALTA curto
    texto = re.sub(r"^[A-ZÁ-Ú\s]{4,40}$\n", "", texto, flags=re.MULTILINE)
    # aspas e travessoes tipograficos preservados; so normaliza espaco
    texto = texto.replace("\r\n", "\n").replace(" ", " ")
    texto = re.sub(r"[ \t]{2,}", " ", texto)
    # junta linhas quebradas dentro do mesmo paragrafo
    texto = re.sub(r"(?<![.!?:;\n])\n(?![\n\s])", " ", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


def detectar_capitulos(texto: str) -> list[tuple[str, str]]:
    """Devolve [(titulo, corpo)]. Sem marcacao clara, retorna um capitulo unico."""
    linhas = texto.split("\n")
    marcos: list[tuple[int, str]] = []
    for i, linha in enumerate(linhas):
        s = linha.strip()
        if not s or len(s) > 80:
            continue
        m = _CAPITULO.match(s)
        if m:
            marcos.append((i, s))
            continue
        # Romano isolado so conta se a linha seguinte estiver vazia (titulo de secao)
        if _TITULO_ROMANO.match(s) and i + 1 < len(linhas) and not linhas[i + 1].strip():
            marcos.append((i, s))

    if not marcos:
        return [("Texto completo", texto)]

    caps = []
    for n, (ini, titulo) in enumerate(marcos):
        fim = marcos[n + 1][0] if n + 1 < len(marcos) else len(linhas)
        corpo = "\n".join(linhas[ini + 1:fim]).strip()
        if corpo:
            caps.append((titulo, corpo))
    return caps or [("Texto completo", texto)]


def paragrafos(corpo: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", corpo) if p.strip()]
