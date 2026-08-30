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
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .verify import QAResult

CER_ACEITE = 0.05
CER_PISO = 0.15
MAX_TENTATIVAS = 3


@dataclass
class Tentativa:
    audio: np.ndarray
    qa: QAResult
    seed: int


@dataclass
class Decisao:
    aceito: bool
    melhor: Tentativa
    tentativas: int
    motivo: str = ""


def escolher(tentativas: list[Tentativa], cer_aceite: float = CER_ACEITE,
             cer_piso: float = CER_PISO) -> Decisao:
    """Decide entre as tentativas de um mesmo chunk."""
    if not tentativas:
        raise ValueError("nenhuma tentativa")

    validas = [t for t in tentativas if not _falha_de_duracao(t.qa)]
    pool = validas or tentativas
    melhor = min(pool, key=lambda t: t.qa.cer)

    if not validas:
        return Decisao(False, melhor, len(tentativas),
                       f"todas as tentativas com duracao invalida: {melhor.qa.reason}")
    if melhor.qa.cer <= cer_aceite:
        return Decisao(True, melhor, len(tentativas))
    if melhor.qa.cer <= cer_piso:
        return Decisao(True, melhor, len(tentativas),
                       f"aceito na melhor de {len(tentativas)} (CER {melhor.qa.cer:.3f}, "
                       "provavel imprecisao do ASR)")
    return Decisao(False, melhor, len(tentativas),
                   f"CER {melhor.qa.cer:.3f} acima do piso {cer_piso} em "
                   f"{len(tentativas)} tentativas")


def _falha_de_duracao(qa: QAResult) -> bool:
    return not qa.ok and ("truncado" in qa.reason or "loop" in qa.reason
                          or "vazio" in qa.reason)


def deve_repetir(qa: QAResult, tentativa: int, cer_aceite: float = CER_ACEITE,
                 max_tentativas: int = MAX_TENTATIVAS) -> bool:
    if tentativa >= max_tentativas:
        return False
    return not qa.ok or qa.cer > cer_aceite
