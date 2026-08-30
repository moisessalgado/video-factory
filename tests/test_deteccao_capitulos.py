"""Deteccao de capitulos: o que e titulo e o que e prosa."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from audiofactory.ingest.loader import detectar_capitulos

# -- deteccao de capitulos ----------------------------------------------------

@pytest.mark.parametrize("linha", [
    "Discurso de Dissolução", "Como os homens adoram", "Livro dos dias",
    "Vocês me ouvem há três anos", "Isso não me preocupa", "Minha preocupação",
])
def test_prosa_que_comeca_por_letra_romana_nao_e_titulo(linha):
    """I, V, X, L, C, D e M abrem meia lingua portuguesa: sem separador nao ha titulo."""
    texto = f"{linha}\n\nCorpo do parágrafo seguinte, com prosa de verdade."
    assert [t for t, _ in detectar_capitulos(texto)] == ["Texto completo"]


@pytest.mark.parametrize("linha,titulo", [
    ("IV", "IV"), ("XII.", "XII."), ("I — A partida", "I — A partida"),
    ("III · O regresso", "III · O regresso"), ("II: O retorno", "II: O retorno"),
])
def test_numeral_romano_isolado_ainda_e_titulo(linha, titulo):
    caps = detectar_capitulos(f"Prefácio da obra.\n\n{linha}\n\nCorpo do capítulo.")
    assert titulo in [t for t, _ in caps]


def test_texto_antes_do_primeiro_capitulo_nao_se_perde():
    """Rosto, autor e epigrafe vinham antes do primeiro marco e eram descartados."""
    texto = ("Jiddu Krishnamurti\n\nNota do editor sobre a ocasião do discurso.\n\n"
             "Capítulo I — A abertura\n\nCorpo do primeiro capítulo.")
    caps = detectar_capitulos(texto)
    assert caps[0][0] == "Abertura"
    assert "Jiddu Krishnamurti" in caps[0][1]
    assert "Nota do editor" in caps[0][1]


def test_nenhum_caractere_se_perde_na_divisao_em_capitulos():
    texto = ("Autor da obra\n\nEpígrafe.\n\nCapítulo I — A partida\n\nCorpo um.\n\n"
             "Capítulo II — O retorno\n\nCorpo dois.")
    caps = detectar_capitulos(texto)
    for trecho in ("Autor da obra", "Epígrafe.", "Corpo um.", "Corpo dois."):
        assert any(trecho in corpo for _, corpo in caps), trecho
