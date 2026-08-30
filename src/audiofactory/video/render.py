"""Renderizacao do MP4 para o YouTube (TDD 18, V2).

O YouTube nao aceita audio puro, e um retangulo preto por nove minutos parece
canal abandonado. Aqui o video e gerado a partir do PROPRIO sinal de audio, com
filtros do ffmpeg -- sem dependencia nova e sem arquivo de video para licenciar.

Principio de desenho: a imagem acompanha a narracao, nao compete com ela. Nada de
corte, flash ou movimento rapido; quem poe um audiolivro para tocar quase sempre
nao esta olhando para a tela, e quando olha, precisa achar a tela em repouso.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

# 1080p a 25 fps: o YouTube reencoda tudo, e mais resolucao so aumenta o upload.
LARGURA, ALTURA, FPS = 1920, 1080, 25

# Paleta escura de proposito: video claro por uma hora cansa, e tela escura gasta
# menos bateria em OLED, que e onde a maioria ouve.
FUNDO_A = "0x0d1b2a"
FUNDO_B = "0x1b263b"
COR_ONDA = "0x7ec8e3"


def presets() -> list[str]:
    return ["ondas", "espectro", "estatico"]


def _fundo(preset: str, capa: Path | None) -> tuple[list[str], str]:
    """Entradas do ffmpeg e rotulo do fluxo de video de fundo."""
    if capa is not None:
        return ["-loop", "1", "-framerate", str(FPS), "-i", str(capa)], "capa"
    if preset == "estatico":
        return ["-f", "lavfi", "-i",
                f"color=c={FUNDO_A}:s={LARGURA}x{ALTURA}:r={FPS}"], "cor"
    # gradiente que se move devagar: a 0,01 nao ha movimento perceptivel quadro a
    # quadro, mas a tela nao fica congelada por nove minutos
    return ["-f", "lavfi", "-i",
            f"gradients=s={LARGURA}x{ALTURA}:c0={FUNDO_A}:c1={FUNDO_B}"
            f":speed=0.01:r={FPS}"], "grad"


def _sobreposicao(preset: str, temn_capa: bool) -> str:
    """Filtro que desenha a visualizacao do audio sobre o fundo."""
    if preset == "estatico":
        return f"[0:v]scale={LARGURA}:{ALTURA}:force_original_aspect_ratio=increase," \
               f"crop={LARGURA}:{ALTURA},setsar=1[v]"
    if preset == "espectro":
        # `axis=0` e obrigatorio: por padrao o showcqt desenha a regua de notas
        # (A B C D E F G) sobre a imagem, o que num audiolivro nao faz sentido
        # nenhum. `sono_h=0` tira o sonograma e deixa so as barras, que sao mais
        # calmas. O blend e `lighten` e nao `screen`: screen lava o fundo inteiro.
        return (f"[1:a]showcqt=s={LARGURA}x{ALTURA}:r={FPS}:count=2:axis=0:"
                f"sono_h=0:bar_g=2:basefreq=55:endfreq=6000:"
                f"cscheme=0.4|0.8|1.0|0.1|0.4|0.9[cqt];"
                f"[0:v]scale={LARGURA}:{ALTURA},setsar=1[bg];"
                "[bg][cqt]blend=all_mode=lighten[v]")
    # ondas: linha central sobre o fundo, na altura dos olhos
    return (f"[1:a]showwaves=s={LARGURA}x{int(ALTURA*0.28)}:mode=cline:"
            f"colors={COR_ONDA}:r={FPS}:scale=sqrt[w];"
            f"[0:v]scale={LARGURA}:{ALTURA},setsar=1[bg];"
            f"[bg][w]overlay=0:{int(ALTURA*0.36)}:format=auto[v]")


def renderizar(audio: Path, destino: Path, preset: str = "ondas",
               capa: Path | None = None, gpu: bool = True) -> Path:
    """Gera o MP4 a partir do audio. `capa` sobrepoe o fundo gerado."""
    if preset not in presets():
        raise ValueError(f"preset desconhecido: {preset} (use {presets()})")
    entrada_fundo, _ = _fundo(preset, capa)
    filtro = _sobreposicao(preset, capa is not None)

    video = (["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "31"] if gpu else
             ["-c:v", "libx264", "-preset", "medium", "-crf", "23"])
    destino.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         *entrada_fundo, "-i", str(audio),
         "-filter_complex", filtro, "-map", "[v]", "-map", "1:a",
         *video, "-pix_fmt", "yuv420p",
         # faststart poe o indice no inicio: o YouTube processa antes de terminar
         # o upload, e um player web consegue comecar sem baixar tudo
         "-movflags", "+faststart",
         "-c:a", "aac", "-b:a", "192k", "-shortest", str(destino)],
        capture_output=True, text=True, check=True)
    return destino
