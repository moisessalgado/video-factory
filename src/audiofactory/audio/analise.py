"""Analise objetiva de uma gravacao de referencia de voz (TDD 7.2).

A referencia e a identidade do canal: ela e congelada por sha256 e todo o audio
publicado depende dela. Um take ruim nao se conserta depois -- se o microfone
cortava em 8 kHz, todo o audiolivro sai com voz de telefone.

Por isso o registro nao aceita "parece bom": mede. As checagens abaixo pegam
justamente o que o ouvido do proprio gravador perdoa por estar acostumado.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

# Alvos vindos das instrucoes de gravacao (TDD 7.2 / `voice record`).
PICO_ALVO_DB = -6.0
PICO_MIN_DB = -20.0        # abaixo disto o sinal e fraco demais: sobe o ruido junto
PICO_MAX_DB = -1.0         # acima disto esta perto do teto, sem margem
RUIDO_MAX_DB = -50.0       # sala silenciosa
SNR_MIN_DB = 35.0
DC_MAX = 0.002
CLIP_MAX_FRACAO = 1e-5

# Um microfone de headset Bluetooth (HFP) corta em 4 ou 8 kHz. Voz masculina tem
# energia util ate ~12 kHz, e e a faixa de 8-14 kHz que da o "ar" da narracao.
CORTE_MIN_HZ = 11000.0
# Queda, em dB abaixo do pico do espectro, que conta como fim da banda util.
QUEDA_DB = 45.0


@dataclass
class Take:
    duracao_s: float
    sample_rate: int
    canais: int
    pico_db: float
    rms_db: float
    ruido_db: float
    snr_db: float
    dc: float
    clip_fracao: float
    corte_hz: float

    @property
    def problemas(self) -> list[str]:
        """Falhas que tornam a referencia inadequada. Vazio = pode registrar."""
        p = []
        if self.clip_fracao > CLIP_MAX_FRACAO:
            p.append(f"clipping em {self.clip_fracao*100:.2f}% das amostras — "
                     "abaixe o ganho de entrada e regrave")
        if self.pico_db > PICO_MAX_DB:
            p.append(f"pico {self.pico_db:.1f} dBFS, sem margem (alvo {PICO_ALVO_DB:.0f})")
        if self.pico_db < PICO_MIN_DB:
            p.append(f"pico {self.pico_db:.1f} dBFS, fraco demais (alvo {PICO_ALVO_DB:.0f}) — "
                     "aproxime o microfone ou suba o ganho")
        if self.ruido_db > RUIDO_MAX_DB:
            p.append(f"ruído de fundo {self.ruido_db:.1f} dBFS — sala/microfone ruidosos")
        if self.snr_db < SNR_MIN_DB:
            p.append(f"relação sinal/ruído {self.snr_db:.1f} dB (mínimo {SNR_MIN_DB:.0f})")
        if self.dc > DC_MAX:
            p.append(f"offset DC de {self.dc:.4f} — problema na placa de entrada")
        if self.corte_hz < CORTE_MIN_HZ:
            p.append(f"banda cortada em {self.corte_hz/1000:.1f} kHz — "
                     "microfone de telefone/Bluetooth? Use um microfone com fio")
        return p

    @property
    def avisos(self) -> list[str]:
        """Nao impedem o registro, mas valem uma segunda gravacao."""
        a = []
        if self.canais > 1:
            a.append(f"{self.canais} canais — será somado para mono")
        if self.sample_rate < 44100:
            a.append(f"{self.sample_rate} Hz — grave a 48 kHz")
        if abs(self.pico_db - PICO_ALVO_DB) > 4:
            a.append(f"pico {self.pico_db:.1f} dBFS, longe do alvo de {PICO_ALVO_DB:.0f}")
        return a


def analisar(caminho: Path) -> Take:
    audio, sr = sf.read(str(caminho), dtype="float32", always_2d=True)
    canais = audio.shape[1]
    mono = audio.mean(axis=1)
    return analisar_audio(mono, sr, canais)


def analisar_audio(mono: np.ndarray, sr: int, canais: int = 1) -> Take:
    if mono.size == 0:
        raise ValueError("arquivo de áudio vazio")
    pico = float(np.abs(mono).max())
    clip = float((np.abs(mono) >= 0.99).mean())
    dc = float(abs(mono.mean()))

    # Ruido de fundo: mediana das janelas mais silenciosas. Media nao serve --
    # uma unica pausa longa a puxaria para baixo e mascararia sala barulhenta.
    jan = max(1, int(sr * 0.05))
    n = (len(mono) // jan) * jan
    if n < jan * 4:
        raise ValueError("áudio curto demais para analisar")
    quadros = mono[:n].reshape(-1, jan)
    rms_quadro = np.sqrt((quadros.astype(np.float64) ** 2).mean(axis=1))
    ordenado = np.sort(rms_quadro)
    ruido = float(np.median(ordenado[:max(1, len(ordenado) // 10)]))
    fala = float(np.median(ordenado[-max(1, len(ordenado) // 4):]))

    return Take(
        duracao_s=len(mono) / sr,
        sample_rate=sr,
        canais=canais,
        pico_db=_db(pico),
        rms_db=_db(float(np.sqrt((mono.astype(np.float64) ** 2).mean()))),
        ruido_db=_db(ruido),
        snr_db=_db(fala) - _db(ruido),
        dc=dc,
        clip_fracao=clip,
        corte_hz=corte_espectral(mono, sr),
    )


def corte_espectral(mono: np.ndarray, sr: int, queda_db: float = QUEDA_DB) -> float:
    """Frequencia acima da qual nao ha mais sinal -- pega microfone de banda estreita.

    Procura a ultima faixa do espectro medio que ainda esta acima de (pico - queda).
    Um microfone Bluetooth despenca num degrau em 4 ou 8 kHz; um microfone decente
    vai perto de Nyquist. E a mesma tecnica usada para flagrar MP3 recodificado.
    """
    n = 4096
    if len(mono) < n * 2:
        n = 1 << max(8, int(np.log2(max(2, len(mono) // 2))))
    passo = n // 2
    janela = np.hanning(n).astype(np.float32)
    quadros = [mono[i:i + n] * janela
               for i in range(0, len(mono) - n, passo)]
    if not quadros:
        return sr / 2
    espectro = np.abs(np.fft.rfft(np.array(quadros), axis=1)).mean(axis=0)
    espectro_db = 20 * np.log10(np.maximum(espectro, 1e-12))
    freqs = np.fft.rfftfreq(n, 1 / sr)

    # ignora o gravissimo (rumble) ao procurar o pico de referencia
    util = freqs > 100
    limiar = espectro_db[util].max() - queda_db
    acima = np.where((espectro_db > limiar) & util)[0]
    return float(freqs[acima[-1]]) if acima.size else 0.0


def _db(x: float) -> float:
    return 20 * float(np.log10(max(x, 1e-12)))
