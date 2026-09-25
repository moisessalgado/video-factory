"""Geração local de imagem (FLUX/SD3.5): o que dá para verificar sem a GPU.

A geração em si não é testável aqui — depende de dezenas de GB de pesos e de
placa. O que é testável é tudo o que fica *ao redor* dela: resolução de
modelo, defaults por família, determinismo da seed, o atalho de cache e a
conversão para o formato do acervo. Mesma filosofia de `test_musica_ace.py`.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from audiofactory.video import imagem as img


# --- resolução de modelo ------------------------------------------------------

def test_resolve_flux():
    assert img.resolver_modelo("flux") == ("black-forest-labs/FLUX.1-schnell", "flux")


def test_resolve_sd_padrao_e_medium():
    repo, familia = img.resolver_modelo("sd")
    assert "medium" in repo
    assert familia == "sd3"


def test_resolve_sd_large():
    repo, familia = img.resolver_modelo("sd:large")
    assert "large" in repo
    assert familia == "sd3"


def test_modelo_desconhecido_e_recusado():
    with pytest.raises(ValueError, match="modelo desconhecido"):
        img.resolver_modelo("midjourney")


# --- defaults por família -----------------------------------------------------

def test_defaults_flux_sao_poucos_passos_sem_guidance():
    """FLUX-schnell é destilado: guidance != 0 não faz CFG nenhum, só custa tempo."""
    passos, guidance = img._defaults("flux", None, None)
    assert passos == 4
    assert guidance == 0.0


def test_defaults_sd3_sao_convencionais():
    passos, guidance = img._defaults("sd3", None, None)
    assert passos >= 20
    assert guidance > 0


def test_defaults_explicitos_sobrepoem():
    passos, guidance = img._defaults("flux", 10, 3.5)
    assert (passos, guidance) == (10, 3.5)


# --- seed ----------------------------------------------------------------------

def test_seed_e_deterministica_e_distinta():
    """Mesmo prompt, mesma imagem: um candidato aprovado tem de poder ser
    reproduzido se o arquivo se perder, sem guardar a seed em outro lugar."""
    assert img._seed("paisagem", 0) == img._seed("paisagem", 0)
    assert img._seed("paisagem", 0) != img._seed("paisagem", 1)
    assert img._seed("paisagem", 0) != img._seed("retrato", 0)


# --- gerar(): atalho de cache --------------------------------------------------

def test_gerar_pula_destinos_que_ja_existem(tmp_path, monkeypatch):
    monkeypatch.setattr(img, "CACHE", tmp_path)
    monkeypatch.setattr(img, "disponivel", lambda: True)
    prompt = "paisagem oriental"
    marca = __import__("hashlib").sha256(prompt.encode()).hexdigest()[:8]
    for i in range(2):
        (tmp_path / f"flux-{marca}-{img._seed(prompt, i)}.png").write_bytes(b"x")

    with patch.object(img, "_rodar") as rodar:
        destinos = img.gerar(prompt, modelo="flux", n=2)
        rodar.assert_not_called()
    assert len(destinos) == 2
    assert all(d.exists() for d in destinos)


def test_gerar_chama_rodar_so_para_os_pendentes(tmp_path, monkeypatch):
    monkeypatch.setattr(img, "CACHE", tmp_path)
    monkeypatch.setattr(img, "disponivel", lambda: True)
    prompt = "retrato histórico"

    with patch.object(img, "_rodar") as rodar:
        img.gerar(prompt, modelo="flux", n=3)
        rodar.assert_called_once()
        pendentes, repo, familia = rodar.call_args[0]
        assert len(pendentes) == 3
        assert repo == "black-forest-labs/FLUX.1-schnell"
        assert familia == "flux"


def test_gerar_sem_venv_e_recusado(monkeypatch):
    monkeypatch.setattr(img, "disponivel", lambda: False)
    with pytest.raises(RuntimeError, match="venv de imagem ausente"):
        img.gerar("qualquer coisa")


# --- aprovar(): conversão para o acervo ----------------------------------------

def _png(caminho: Path) -> Path:
    from PIL import Image
    Image.new("RGB", (64, 64), color=(200, 100, 50)).save(caminho)
    return caminho


def test_aprovar_converte_para_jpeg_no_acervo_e_limpa_o_cache(tmp_path):
    cache = tmp_path / "cache"
    acervo = tmp_path / "acervo"
    cache.mkdir()
    origem = _png(cache / "flux-abc123-42.png")

    finais = img.aprovar([origem], slides_dir=acervo)

    assert len(finais) == 1
    assert finais[0] == acervo / "flux-abc123-42.jpg"
    assert finais[0].exists()
    assert not origem.exists()  # rascunho descartado depois de virar acervo


def test_aprovar_recusa_arquivo_inexistente_sem_converter_nada(tmp_path):
    cache = tmp_path / "cache"
    acervo = tmp_path / "acervo"
    cache.mkdir()
    ok = _png(cache / "flux-ok-1.png")
    falta = cache / "flux-falta-2.png"

    with pytest.raises(FileNotFoundError, match="flux-falta-2.png"):
        img.aprovar([ok, falta], slides_dir=acervo)

    assert ok.exists()  # nada foi convertido nem apagado
    assert not (acervo / "flux-ok-1.jpg").exists()
