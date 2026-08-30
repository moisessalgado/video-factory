"""Verificacao de identidade da voz (TDD 7.1, mecanismo 3).

O CER garante que o chunk diz o texto certo; nao garante que diz na voz certa.
Deriva de timbre e o defeito que o ouvinte percebe como "trocaram o narrador no
meio do livro", e passa despercebida por qualquer checagem textual.

Limiar calibrado com medicao propria (voz template narrador-v1, 6 chunks, 3 capitulos):
  - mesma voz .............. 0,917 a 0,960 (amplitude 0,042)
  - voz diferente (controle)  0,833
0,88 fica no meio do vao, longe das duas pontas.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

SIMILARIDADE_MINIMA = 0.88


class SpeakerCheck:
    """Compara cada chunk com a referencia usando o voice encoder do proprio motor."""

    def __init__(self, voice_encoder, referencia: Path,
                 minima: float = SIMILARIDADE_MINIMA):
        self.ve = voice_encoder
        self.minima = minima
        self.ref = self._embed_path(referencia)

    def _embed(self, audio: np.ndarray, sample_rate: int) -> np.ndarray:
        v = np.asarray(self.ve.embeds_from_wavs([audio], sample_rate=sample_rate)).squeeze()
        norma = np.linalg.norm(v)
        return v / norma if norma else v

    def _embed_path(self, path: Path) -> np.ndarray:
        audio, sr = sf.read(str(path), dtype="float32")
        return self._embed(audio, sr)

    def similaridade(self, audio: np.ndarray, sample_rate: int) -> float:
        # trechos muito curtos dao embedding instavel; nao vale julgar
        if len(audio) / sample_rate < 1.0:
            return 1.0
        return float(self.ref @ self._embed(audio, sample_rate))

    def ok(self, audio: np.ndarray, sample_rate: int) -> tuple[bool, float]:
        s = self.similaridade(audio, sample_rate)
        return s >= self.minima, s
