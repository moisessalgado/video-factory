"""Calibracao do QA: duracao esperada e limiar de voz.\n\nOs numeros destes testes sao medicoes do discurso do Krishnamurti\n(133 chunks) e do experimento de corte por duracao. Nao sao chutes:\nmudar um limiar sem refazer a medicao quebra estes testes de proposito."""
from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from audiofactory.qa.speaker import (DUR_PLENA_S, MIN_JULGAVEL_S,
                                     SIMILARIDADE_MINIMA,
                                     limiar_por_duracao)
from audiofactory.qa.verify import (FATOR_MAX, FATOR_MIN,
                                    duracao_esperada)

# -- duracao esperada: overhead fixo + ritmo ----------------------------------

def _razao(chars: int, dur: float) -> float:
    return dur / duracao_esperada("x" * chars)


def test_chunk_curto_correto_nao_e_reprovado_por_duracao():
    """Medidos no discurso do Krishnamurti, todos com CER 0,000 e antes reprovados
    pelo piso fixo de 10 c/s."""
    for chars, dur in [(27, 2.96), (32, 3.56), (38, 3.96), (25, 2.32), (56, 5.68)]:
        assert FATOR_MIN < _razao(chars, dur) < FATOR_MAX, (chars, dur)


def test_titulo_curto_lido_com_pausa_passa():
    """22 chars em 3,88 s: razao 1,70, CER 0,000 — audio correto, so pausado."""
    assert _razao(22, 3.88) < FATOR_MAX


def test_truncamento_ainda_e_pego_em_texto_longo():
    """Cortar metade de um chunk de 200 chars fica bem abaixo do piso."""
    assert _razao(200, duracao_esperada("x" * 200) * 0.5) < FATOR_MIN


def test_truncamento_ainda_e_pego_em_texto_curto():
    assert _razao(40, duracao_esperada("x" * 40) * 0.4) < FATOR_MIN


def test_overhead_domina_no_texto_curto():
    """O overhead fixo nao encolhe com o texto: e por isso que c/s puro nao serve."""
    curto, longo = duracao_esperada("x" * 20), duracao_esperada("x" * 200)
    assert 20 / curto < 10.0          # reprovado pelo piso antigo de 10 c/s
    assert 200 / longo > 13.0         # o mesmo modelo, em texto longo, e rapido


# -- limiar de voz que acompanha a duracao ------------------------------------

def test_limiar_cheio_em_audio_longo():
    assert limiar_por_duracao(DUR_PLENA_S) == SIMILARIDADE_MINIMA
    assert limiar_por_duracao(30.0) == SIMILARIDADE_MINIMA


def test_limiar_afrouxa_em_audio_curto():
    assert limiar_por_duracao(3.0) < limiar_por_duracao(6.0) < SIMILARIDADE_MINIMA


def test_chunks_curtos_corretos_passam_no_limiar_novo():
    """Medidos no discurso: CER 0,000, voz certa, reprovados pelo limiar fixo."""
    for dur, sim in [(2.5, 0.865), (3.9, 0.879), (3.0, 0.875), (2.6, 0.839),
                     (4.0, 0.850)]:
        assert sim >= limiar_por_duracao(dur), (dur, sim)


def test_impostor_continua_reprovado_em_qualquer_duracao():
    """Máximos medidos da citacao-v1 contra a referência do narrador."""
    for dur, sim in [(3.0, 0.756), (4.0, 0.779), (6.0, 0.791), (10.0, 0.791)]:
        assert sim < limiar_por_duracao(dur), (dur, sim)


def test_mesma_voz_continua_passando_em_qualquer_duracao():
    """Mínimos medidos do narrador-v1 cortado nas mesmas durações."""
    for dur, sim in [(3.0, 0.866), (4.0, 0.898), (6.0, 0.911), (10.0, 0.928)]:
        assert sim >= limiar_por_duracao(dur), (dur, sim)


def test_abaixo_do_minimo_julgavel_a_checagem_nao_opina():
    """Vão de só +0,070 aos 2 s: a checagem não discrimina e não deve palpitar."""
    assert MIN_JULGAVEL_S > 2.0
