"""Verificacao automatica de cada chunk gerado (TDD 8, "QA LOOP").

Motivo de existir: o Chatterbox e autoregressivo e falha de forma RARA e SILENCIOSA
-- repete, alucina ou trunca. Na Fase 0 o proprio alignment_stream_analyzer do modelo
detectou repeticao e FORCOU EOS, ou seja, entregou audio incompleto sem erro.
Por isso verificamos duas coisas independentes:

  1. CONTEUDO  -- re-transcreve com ASR e compara com o texto esperado (CER);
  2. DURACAO   -- compara a duracao real com a esperada para o numero de caracteres.

A checagem de duracao e a que pega o truncamento: cortar o fim de uma frase muda
pouco o CER de um texto longo, mas mutila a narracao.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

import numpy as np

# Ritmo de narracao medido em pt-BR: ~14-17 caracteres por segundo de audio.
# Fora desta janela o chunk provavelmente foi truncado (rapido demais)
# ou entrou em loop/arrasto (lento demais).
CPS_MIN = 10.0
CPS_MAX = 24.0

CER_MAX = 0.05


@dataclass
class QAResult:
    ok: bool
    cer: float
    transcript: str
    duration_s: float
    cps: float
    reason: str = ""


def _normalize_for_compare(text: str) -> str:
    """Reduz ambos os lados ao que importa: letras e espacos.

    Antes disso, o texto passa pelo normalizador de narracao. Sem esse passo o QA
    gera falso positivo sistematico: o Whisper faz a normalizacao INVERSA -- ouve
    "mil seiscentos e quarenta e oito" e transcreve "1648" -- e a comparacao
    penalizaria exatamente os numeros que o pipeline acabou de expandir.
    """
    from ..narration.rules import normalize as _narr

    try:
        text = _narr(text).text
    except Exception:
        pass
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def char_error_rate(esperado: str, obtido: str) -> float:
    """Levenshtein normalizado pelo comprimento do esperado."""
    a, b = _normalize_for_compare(esperado), _normalize_for_compare(obtido)
    if not a:
        return 0.0 if not b else 1.0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1] / len(a)


class Verifier:
    """Wrapper do faster-whisper. Carrega o modelo uma vez por processo."""

    def __init__(self, model_size: str = "small", device: str = "cpu",
                 compute_type: str = "int8", language: str = "pt",
                 cpu_threads: int = 8):
        # CPU por padrao de proposito: o CTranslate2 exige cuBLAS 12 e o ambiente
        # e CUDA 13 (misturar cu12/cu13 no mesmo venv quebra o torch). Alem disso,
        # deixar o ASR na CPU libera a GPU inteira para o TTS -- que e o gargalo.
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self.cpu_threads = cpu_threads
        self.model = None

    def load(self) -> None:
        if self.model is not None:      # idempotente: o worker chama sem saber
            return
        from faster_whisper import WhisperModel

        self.model = WhisperModel(self.model_size, device=self.device,
                                  compute_type=self.compute_type,
                                  cpu_threads=self.cpu_threads)

    def transcribe(self, audio: np.ndarray, sample_rate: int) -> str:
        if sample_rate != 16000:
            audio = _resample(audio, sample_rate, 16000)
        segments, _ = self.model.transcribe(audio, language=self.language,
                                            beam_size=1, vad_filter=False)
        return " ".join(s.text for s in segments).strip()

    def check(self, audio: np.ndarray, sample_rate: int, esperado: str,
              cer_max: float = CER_MAX) -> QAResult:
        dur = len(audio) / sample_rate
        cps = len(esperado) / dur if dur > 0 else float("inf")

        # Duracao primeiro: e barata e pega o truncamento sem rodar o ASR.
        if dur < 0.2:
            return QAResult(False, 1.0, "", dur, cps, "audio vazio ou quase vazio")
        if cps > CPS_MAX:
            return QAResult(False, 1.0, "", dur, cps,
                            f"audio curto demais para o texto ({cps:.1f} c/s) - truncado?")
        if cps < CPS_MIN:
            return QAResult(False, 1.0, "", dur, cps,
                            f"audio longo demais para o texto ({cps:.1f} c/s) - loop/arrasto?")

        transcript = self.transcribe(audio, sample_rate)
        cer = char_error_rate(esperado, transcript)
        if cer > cer_max:
            return QAResult(False, cer, transcript, dur, cps,
                            f"CER {cer:.3f} acima do limite {cer_max}")
        return QAResult(True, cer, transcript, dur, cps)


def _resample(audio: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    """Reamostragem linear -- suficiente para ASR de verificacao."""
    n_out = int(round(len(audio) * sr_out / sr_in))
    return np.interp(
        np.linspace(0, len(audio) - 1, n_out, dtype=np.float64),
        np.arange(len(audio), dtype=np.float64),
        audio,
    ).astype(np.float32)
