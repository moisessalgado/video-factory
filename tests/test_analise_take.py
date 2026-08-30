"""Analise da gravacao de referencia: cada defeito tem de ser pego por medicao."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from audiofactory.audio.analise import CORTE_MIN_HZ, analisar_audio, corte_espectral

SR = 48000


def fala_sintetica(segundos=30.0, sr=SR, pico=0.5, ruido=1e-4, corte_hz=None,
                   seed=0):
    """Ruido rosa modulado em silabas: nao e fala, mas tem a estatistica que a
    analise mede (picos, pausas, espectro largo)."""
    rng = np.random.default_rng(seed)
    n = int(sr * segundos)
    x = rng.standard_normal(n)
    # ruido rosa: filtro 1/f no dominio da frequencia
    X = np.fft.rfft(x)
    f = np.maximum(np.fft.rfftfreq(n, 1 / sr), 1.0)
    X /= np.sqrt(f)
    if corte_hz:
        X[f > corte_hz] = 0.0            # microfone de banda estreita
    x = np.fft.irfft(X, n)
    # envelope de sílabas com pausas, para haver "fundo" a medir
    t = np.arange(n) / sr
    env = np.clip(np.sin(2 * np.pi * 3.0 * t) ** 2, 0.02, None)
    env[(t % 5.0) > 4.2] = 0.0           # pausas de respiração
    x *= env
    x = x / np.abs(x).max() * pico
    return (x + rng.standard_normal(n) * ruido).astype(np.float32)


def test_take_bom_nao_tem_problema():
    t = analisar_audio(fala_sintetica(pico=0.5), SR)
    assert t.problemas == [], t.problemas


def test_pega_clipping():
    x = fala_sintetica(pico=1.0)
    t = analisar_audio(np.clip(x * 3, -1, 1), SR)
    assert any("clipping" in p for p in t.problemas)


def test_pega_sinal_fraco():
    t = analisar_audio(fala_sintetica(pico=0.02), SR)
    assert any("fraco demais" in p for p in t.problemas)


def test_pega_sala_barulhenta():
    t = analisar_audio(fala_sintetica(pico=0.5, ruido=0.02), SR)
    assert any("ruído de fundo" in p or "sinal/ruído" in p for p in t.problemas)


def test_pega_offset_dc():
    t = analisar_audio(fala_sintetica(pico=0.5) + 0.05, SR)
    assert any("DC" in p for p in t.problemas)


@pytest.mark.parametrize("corte", [4000, 8000])
def test_pega_microfone_de_banda_estreita(corte):
    """Headset Bluetooth (HFP) corta em 4 ou 8 kHz — o defeito mais caro, porque
    o ouvido acostumado nao percebe e a voz do canal inteiro sai de telefone."""
    t = analisar_audio(fala_sintetica(pico=0.5, corte_hz=corte), SR)
    assert any("banda cortada" in p for p in t.problemas)
    assert t.corte_hz < CORTE_MIN_HZ


def test_microfone_de_banda_larga_passa():
    t = analisar_audio(fala_sintetica(pico=0.5), SR)
    assert t.corte_hz >= CORTE_MIN_HZ


def test_corte_espectral_encontra_o_degrau():
    """Precisao da medida: um corte em 6 kHz tem de ser lido perto de 6 kHz."""
    medido = corte_espectral(fala_sintetica(pico=0.5, corte_hz=6000), SR)
    assert 5000 < medido < 7000, medido


def test_estereo_vira_aviso_e_nao_erro():
    t = analisar_audio(fala_sintetica(pico=0.5), SR, canais=2)
    assert t.problemas == []
    assert any("mono" in a for a in t.avisos)


def test_audio_curto_demais_e_recusado():
    with pytest.raises(ValueError, match="curto demais"):
        analisar_audio(np.zeros(100, dtype=np.float32), SR)


# -- o registry recusa take ruim ---------------------------------------------

def _gravar(tmp_path, nome, audio, sr=SR):
    import soundfile as sf
    p = tmp_path / nome
    sf.write(str(p), audio, sr, subtype="PCM_24")
    return p


def test_registry_recusa_microfone_bluetooth(tmp_path):
    """O gate que importa: banda cortada não se conserta depois do registro."""
    from audiofactory.voices import criar

    ref = _gravar(tmp_path, "bt.wav", fala_sintetica(30, pico=0.5, corte_hz=8000))
    with pytest.raises(ValueError, match="banda cortada"):
        criar(tmp_path / "raiz", "moises-v1", ref, consentimento="ok")


def test_registry_recusa_sala_barulhenta(tmp_path):
    from audiofactory.voices import criar

    ref = _gravar(tmp_path, "ruido.wav", fala_sintetica(30, pico=0.5, ruido=0.02))
    with pytest.raises(ValueError, match="ruído de fundo|sinal/ruído"):
        criar(tmp_path / "raiz", "moises-v1", ref, consentimento="ok")


def test_registry_aceita_take_bom(tmp_path):
    from audiofactory.voices import criar

    ref = _gravar(tmp_path, "bom.wav", fala_sintetica(30, pico=0.5))
    v = criar(tmp_path / "raiz", "moises-v1", ref, consentimento="ok")
    assert v.referencia.exists()
    assert (v.dir / "CONSENT.md").exists()


def test_voz_template_nao_passa_pelo_gate_de_microfone(tmp_path):
    """Template vem de TTS a 24 kHz: medir microfone e sala não faz sentido."""
    from audiofactory.voices import criar

    ref = _gravar(tmp_path, "kokoro.wav",
                  fala_sintetica(16, sr=24000, pico=0.5), sr=24000)
    v = criar(tmp_path / "raiz", "dora-v1", ref, template_de="Kokoro-82M")
    assert (v.dir / "PROVENANCE.md").exists()
