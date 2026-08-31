"""Trilha de fundo por modelo dedicado -- ACE-Step v1 3.5B (TDD 18, V3).

Por que trocar o sintetizador do `musica.py`: o drone modal cumpria o contrato
espectral, mas soava abstrato e ate sinistro. O motivo e de desenho, nao de
ajuste: parciais desafinados, sem ataque, com o meio do espectro cavado em 15 dB,
e a receita de pad de ficcao cientifica. Nenhum instrumento real soa assim.

Por que ACE-Step e nao outro: os pesos sao **Apache-2.0** (model card
`ACE-Step/ACE-Step-v1-3.5B`, conferido). O MusicGen esta fora -- CC-BY-NC nos
pesos, e este canal publica. A licenca era a razao original de sintetizar tudo, e
ela continua satisfeita aqui.

O modelo NAO roda no processo do pipeline: ele vive na `.venv-musica`, atras de
`_ace_runner.py`. Ver o cabecalho daquele arquivo para o motivo.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np

from ..project import RAIZ
from .musica import SAMPLE_RATE, _ffmpeg

VENV = RAIZ / ".venv-musica"
CHECKPOINT = RAIZ / "models" / "ace-step"
CACHE = RAIZ / "cache" / "musica"

# Duracao de cada peca gerada. O ACE-Step aguenta ~4 min, mas peca longa nao
# compra nada aqui: o que combate a monotonia e a VARIEDADE entre pecas, e duas
# de 2 min custam o mesmo que uma de 4 e rendem duas paisagens.
PECA_S = 120.0
# Quantas pecas distintas formam o leito. Seis dao 12 min de material inedito;
# sob a narracao a -26 LUFS, ninguem percebe o retorno de uma peca depois disso.
N_PECAS = 6
# Cruzamento longo de proposito: e ele que faz a troca de peca virar mudanca de
# paisagem em vez de corte. Peca nova entrando em 8 s nao e um "evento".
CRUZAMENTO_S = 8.0

PASSOS = 60
GUIDANCE = 15.0

# Termos que valem para toda paleta. `no vocals` e `no drums` sao os dois que
# nao podem faltar: voz cantada disputa com a narracao, e ataque percussivo
# atravessa o ducking (o sidechain e lento demais para pegar transiente).
_BASE = ("ambient, instrumental, meditative, slow tempo, sparse, gentle, warm, "
         "contemplative, soft reverb, spacious, quiet, "
         "no drums, no percussion, no beat, no vocals")

# Timbres acusticos por padrao. A queixa original era "extraterrestre", e pad de
# sintetizador e exatamente o caminho de volta para la.
PALETAS: dict[str, tuple[str, ...]] = {
    "contemplativo": (
        "felt piano, sustained strings",
        "warm string ensemble, cello, viola",
        "nylon string guitar, harmonics, soft pad",
        "harp, celesta, glass bells",
        "wooden flute, shakuhachi, low drone",
        "kalimba, marimba, soft mallets",
    ),
    "sobrio": (
        "solo cello, long bowed notes",
        "double bass, sustained, dark",
        "piano, low register, sparse notes",
        "viola and cello duet, slow",
        "bass clarinet, breathy, long tones",
        "muted piano, felt, distant",
    ),
}


def prompts(paleta: str = "contemplativo") -> tuple[str, ...]:
    if paleta not in PALETAS:
        raise ValueError(f"paleta desconhecida: {paleta} — use {', '.join(PALETAS)}")
    return tuple(f"{timbre}, {_BASE}" for timbre in PALETAS[paleta])


def disponivel() -> bool:
    """A venv isolada existe? Sem ela, o `video` cai na trilha sintetizada."""
    return (VENV / "bin" / "python").exists()


def _seed(paleta: str, i: int) -> int:
    """Seed derivada do nome da paleta: a mesma paleta rende sempre o mesmo leito.

    Determinismo importa aqui por uma razao pratica: um capitulo regerado nao pode
    trocar de musica de fundo no meio de uma serie ja publicada.
    """
    h = hashlib.sha256(f"{paleta}:{i}".encode()).digest()
    return int.from_bytes(h[:4], "big")


def gerar_pecas(paleta: str = "contemplativo", n: int = N_PECAS,
                peca_s: float = PECA_S, sample_rate: int = SAMPLE_RATE,
                progresso=None) -> list[Path]:
    """Gera (ou reaproveita do cache) as pecas do leito, ja em 24 kHz mono.

    O cache e o que torna a coisa viavel: gerar 12 min de musica custa minutos de
    GPU, e as pecas nao dependem do capitulo -- so da paleta. Um projeto novo
    reusa o leito do anterior sem gastar nada.
    """
    if not disponivel():
        raise RuntimeError(
            f"venv de musica ausente em {VENV} — rode `uv venv --python 3.12 "
            f".venv-musica && uv pip install --python .venv-musica/bin/python "
            f"git+https://github.com/ace-step/ACE-Step.git`")
    CACHE.mkdir(parents=True, exist_ok=True)
    ps = prompts(paleta)
    finais = [CACHE / f"{paleta}-{i:02d}-{int(peca_s)}s-{sample_rate}.wav"
              for i in range(n)]
    # O modelo entrega 48 kHz estereo; o bruto fica ao lado do convertido para
    # que uma troca de sample_rate nao obrigue a gerar tudo de novo.
    brutos = [CACHE / f"{paleta}-{i:02d}-{int(peca_s)}s-bruto.wav" for i in range(n)]

    pendentes = [{"prompt": ps[i % len(ps)], "seed": _seed(paleta, i),
                  "destino": str(brutos[i])}
                 for i in range(n) if not finais[i].exists() and not brutos[i].exists()]
    if pendentes:
        if progresso:
            progresso(f"gerando {len(pendentes)} peça(s) no ACE-Step…")
        _rodar(pendentes, peca_s)

    for bruto, final in zip(brutos, finais):
        if not final.exists():
            _ffmpeg(["-i", str(bruto), "-ar", str(sample_rate), "-ac", "1",
                     "-c:a", "pcm_s24le", str(final)])
    return finais


def _rodar(pecas: list[dict], peca_s: float) -> None:
    pedido = {"pecas": pecas, "duracao_s": peca_s, "passos": PASSOS,
              "guidance": GUIDANCE, "checkpoint": str(CHECKPOINT),
              "hf_home": str(RAIZ / "models")}
    runner = Path(__file__).with_name("_ace_runner.py")
    r = subprocess.run([str(VENV / "bin" / "python"), str(runner), json.dumps(pedido)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ACE-Step falhou:\n{r.stderr[-2000:]}")


def montar(duracao_s: float, pecas: list[Path], sample_rate: int = SAMPLE_RATE,
           cruzamento_s: float = CRUZAMENTO_S) -> np.ndarray:
    """Encadeia as pecas com cruzamento ate cobrir a duracao pedida."""
    import soundfile as sf

    if not pecas:
        raise ValueError("nenhuma peça para montar")
    audios = [sf.read(str(p), dtype="float64", always_2d=False)[0] for p in pecas]
    audios = [a if a.ndim == 1 else a.mean(axis=1) for a in audios]
    audios = [_por_pico(a, 0.7) for a in audios]

    n_total = int(duracao_s * sample_rate)
    n_cruz = int(cruzamento_s * sample_rate)
    saida = np.zeros(n_total, dtype=np.float64)

    # Rampas de potencia constante (seno/cosseno). Um cruzamento linear entre
    # sinais descorrelacionados cava um buraco de 3 dB no meio da emenda --
    # audivel justamente como o "respiro" que denuncia o corte.
    x = np.linspace(0, np.pi / 2, n_cruz)
    sobe, desce = np.sin(x), np.cos(x)

    pos, i = 0, 0
    while pos < n_total:
        a = audios[i % len(audios)]
        n = min(len(a), n_total - pos)
        trecho = a[:n].copy()
        if pos > 0:
            m = min(n_cruz, n)
            trecho[:m] *= sobe[:m]
            saida[pos:pos + m] *= desce[:m]
        saida[pos:pos + n] += trecho
        pos += max(n - n_cruz, 1)
        i += 1

    # Entrada e saida suaves: a trilha nao pode comecar com um acorde ja tocando.
    return _bordas(saida, sample_rate).astype(np.float32)


def _bordas(x: np.ndarray, sample_rate: int, s: float = 3.0) -> np.ndarray:
    n = min(int(s * sample_rate), len(x) // 2)
    if n <= 0:
        return x
    r = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, n))
    x[:n] *= r
    x[-n:] *= r[::-1]
    return x


def _por_pico(x: np.ndarray, alvo: float) -> np.ndarray:
    pico = np.abs(x).max()
    return x * (alvo / pico) if pico > 0 else x


# --- moldagem espectral -----------------------------------------------------
# Aqui esta a segunda metade do conserto. O `_moldar_para_voz` do sintetizador
# derruba 15 dB de 120 a 1400 Hz -- em som harmonico real isso arranca o corpo do
# instrumento e deixa grave + brilho sem meio, que e o timbre "oco" de radio
# quebrado. Musica de verdade precisa de um dip largo e raso; quem tira a trilha
# da frente da fala no momento da fala e o ducking, que ja funciona.
DIP_CENTRO_HZ = 500.0    # centro geometrico de 300-700 Hz, onde a voz tem 49,5%
DIP_LARGURA_OIT = 1.6    # desvio-padrao em oitavas: cobre ~150 Hz a 1,7 kHz
DIP_DB = 5.0
TOPO_HZ = 11000.0        # chiado acima disso so gasta bitrate


def moldar(x: np.ndarray, sr: int, dip_db: float = DIP_DB) -> np.ndarray:
    """Dip gaussiano largo e raso na faixa da fala, em escala logaritmica.

    Gaussiana em log-frequencia, e nao um corte com bordas, porque o ouvido lê
    borda de filtro como coloracao (o "efeito telefone"); uma depressao suave de
    5 dB some como timbre e sobra como espaco.
    """
    X = np.fft.rfft(x.astype(np.float64))
    f = np.fft.rfftfreq(len(x), 1 / sr)
    f = np.maximum(f, 1e-6)
    oitavas = np.log2(f / DIP_CENTRO_HZ)
    db = -dip_db * np.exp(-0.5 * (oitavas / DIP_LARGURA_OIT) ** 2)
    ganho = 10 ** (db / 20) / (1 + (f / TOPO_HZ) ** 4)
    return np.fft.irfft(X * ganho, len(x))


def preparar_trilha(destino: Path, duracao_s: float, paleta: str = "contemplativo",
                    sample_rate: int = SAMPLE_RATE, dip_db: float = DIP_DB,
                    progresso=None) -> Path:
    """Deixa em `destino` um leito do tamanho exato da narracao."""
    import soundfile as sf

    pecas = gerar_pecas(paleta, sample_rate=sample_rate, progresso=progresso)
    leito = montar(duracao_s, pecas, sample_rate=sample_rate)
    leito = _por_pico(moldar(leito, sample_rate, dip_db), 0.5).astype(np.float32)
    destino.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(destino), leito, sample_rate)
    return destino
