"""Politica de regeneracao (TDD 8, "falhou -> regenera com nova seed").

Racional economico: gerar um chunk custa ~2 s (RTF 0,29 medido), enquanto um defeito
que escapa custa uma revisao manual -- ou, pior, um audiolivro publicado com um trecho
mutilado. Entao o CER e usado como TRIAGEM, nao como juiz: na duvida, regenera.

O ASR `small` na CPU tem imprecisao propria (~0,06 de CER em prosa limpa, medido na
Fase 0), o que impede um limiar apertado unico. Por isso duas faixas:

  CER <= aceite            -> ok
  aceite < CER <= piso     -> regenera; no fim fica a MELHOR das tentativas
  CER > piso               -> regenera; se nem a melhor passar do piso, needs_review

Falha de duracao (truncamento/loop) nunca e aceita por "melhor das tentativas":
audio mutilado e defeito objetivo, nao ruido de medicao.

A identidade da voz entra na MESMA politica: uma tentativa abaixo do limiar de
similaridade e motivo para regenerar, como um CER alto. Medido: chunks curtos
ficam a 0,879 numa seed e passam folgado na seguinte -- mandar para revisao
humana sem sequer tentar outra seed e desperdicio.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .speaker import SIMILARIDADE_MINIMA
from .verify import QAResult

CER_ACEITE = 0.05
CER_PISO = 0.15
MAX_TENTATIVAS = 3


@dataclass
class Tentativa:
    audio: np.ndarray
    qa: QAResult
    seed: int
    speaker_sim: float | None = None   # None = sem voz de referencia para comparar


@dataclass
class Decisao:
    aceito: bool
    melhor: Tentativa
    tentativas: int
    motivo: str = ""


def escolher(tentativas: list[Tentativa], cer_aceite: float = CER_ACEITE,
             cer_piso: float = CER_PISO,
             sim_minima: float = SIMILARIDADE_MINIMA) -> Decisao:
    """Decide entre as tentativas de um mesmo chunk."""
    if not tentativas:
        raise ValueError("nenhuma tentativa")

    validas = [t for t in tentativas if not _falha_de_duracao(t.qa)]
    pool = validas or tentativas
    # Entre as que servem, prefira as que tambem batem a identidade da voz: nao
    # adianta o texto estar certo se o timbre mudou no meio do capitulo.
    na_voz = [t for t in pool if _voz_ok(t, sim_minima)]
    melhor = min(na_voz or pool, key=lambda t: t.qa.cer)

    if not validas:
        return Decisao(False, melhor, len(tentativas),
                       f"todas as tentativas com duracao invalida: {melhor.qa.reason}")
    if not na_voz:
        pior = max(pool, key=lambda t: t.speaker_sim or 0.0)
        return Decisao(False, pior, len(tentativas),
                       f"voz divergente da referência (similaridade "
                       f"{pior.speaker_sim:.3f}) em {len(tentativas)} tentativas")
    if melhor.qa.cer <= cer_aceite:
        return Decisao(True, melhor, len(tentativas))
    if melhor.qa.cer <= cer_piso:
        return Decisao(True, melhor, len(tentativas),
                       f"aceito na melhor de {len(tentativas)} (CER {melhor.qa.cer:.3f}, "
                       "provavel imprecisao do ASR)")
    return Decisao(False, melhor, len(tentativas),
                   f"CER {melhor.qa.cer:.3f} acima do piso {cer_piso} em "
                   f"{len(tentativas)} tentativas")


def _voz_ok(t: Tentativa, minima: float) -> bool:
    """Sem referencia de voz (speaker_sim None) nao ha o que reprovar."""
    return t.speaker_sim is None or t.speaker_sim >= minima


def _falha_de_duracao(qa: QAResult) -> bool:
    return not qa.ok and ("truncado" in qa.reason or "loop" in qa.reason
                          or "vazio" in qa.reason)


def deve_repetir(qa: QAResult, tentativa: int, cer_aceite: float = CER_ACEITE,
                 max_tentativas: int = MAX_TENTATIVAS,
                 speaker_sim: float | None = None,
                 sim_minima: float = SIMILARIDADE_MINIMA) -> bool:
    if tentativa >= max_tentativas:
        return False
    if speaker_sim is not None and speaker_sim < sim_minima:
        return True
    return not qa.ok or qa.cer > cer_aceite
