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

from ..audio.process import duracao
from . import slides as slides_mod

# 1080p a 25 fps: o YouTube reencoda tudo, e mais resolucao so aumenta o upload.
LARGURA, ALTURA, FPS = 1920, 1080, 25

# Qualidade do NVENC. O `cq 31` que estava aqui rendia 380 kb/s em 1080p, e o
# codificador gastava esse orcamento onde havia detalhe -- as tarjas borradas,
# que sao quase planas, sobravam com blocos inteiros no mesmo valor e viravam
# listras de cor. `cq 20` custa ~3x o arquivo (46 MB viram ~150 MB em onze
# minutos, irrelevante num upload unico) e devolve a rampa.
#
# `spatial-aq` existe exatamente para este material: ele reparte o orcamento a
# favor das areas LISAS, que e onde o olho enxerga banda, e nao a favor do
# detalhe, que e onde o codificador iria sozinho.
CQ = 20
NVENC = ["-c:v", "h264_nvenc", "-preset", "p6", "-tune", "hq",
         "-rc", "vbr", "-cq", str(CQ), "-b:v", "0",
         "-maxrate", "16M", "-bufsize", "32M",
         "-spatial-aq", "1", "-aq-strength", "8",
         "-bf", "3", "-rc-lookahead", "32", "-profile:v", "high"]
X264 = ["-c:v", "libx264", "-preset", "medium", "-crf", "18"]

# Ultimo elo do grafo, comum a todos os presets: derruba a cadeia de 10 bits
# para os 8 do H.264 com difusao de erro. Sem o `dither`, a conversao arredonda
# e as bandas que os 10 bits evitaram voltam inteiras no ultimo passo.
#
# O `matrix`/`range` nao sao enfeite: o JPEG entra em faixa cheia, e sair sem
# converter marcava o MP4 como `yuvj420p`. Player que ignora a marca (nao sao
# poucos) esmagava preto e branco. Aqui a conversao e explicita e a marca,
# escrita no arquivo pelas flags de cor do ffmpeg.
#
# O `format=gbrp10le` da frente nao e redundancia com os slides (que ja chegam
# assim): ele existe para os OUTROS presets. O `zscale` recusa converter a
# partir de um quadro cuja matriz nao esta marcada -- e o `espectro`, que sai de
# um `blend`, e exatamente um desses ("no path between colorspaces"). Passando
# por RGB primeiro, nao ha matriz de entrada para adivinhar.
SAIDA_8BITS = ("format=gbrp10le,"
               "zscale=matrix=709:range=limited:dither=error_diffusion,"
               "format=yuv420p")
CORES = ["-colorspace", "bt709", "-color_primaries", "bt709",
         "-color_trc", "bt709", "-color_range", "tv"]

# Paleta escura de proposito: video claro por uma hora cansa, e tela escura gasta
# menos bateria em OLED, que e onde a maioria ouve.
FUNDO_A = "0x0d1b2a"
FUNDO_B = "0x1b263b"
COR_ONDA = "0x7ec8e3"


def presets() -> list[str]:
    return ["slides", "ondas", "espectro", "estatico", "gradiente"]


def _fundo(preset: str, capa: Path | None,
           plano: tuple[list[Path], float, float] | None,
           veu: bool) -> list[str]:
    """Entradas de video do ffmpeg. O audio entra depois delas."""
    if capa is not None:
        return ["-loop", "1", "-framerate", str(FPS), "-i", str(capa)]
    if preset == "slides":
        imagens, cada, _ = plano
        return slides_mod.entradas(imagens, cada, FPS, LARGURA, veu)
    if preset == "estatico":
        return ["-f", "lavfi", "-i",
                f"color=c={FUNDO_A}:s={LARGURA}x{ALTURA}:r={FPS}"]
    # `gradiente`: o mesmo fundo dos outros presets, mas SEM visualizacao por
    # cima. O operador achou a onda cansativa em nove minutos, e cor chapada por
    # onze cai no "canal abandonado" que este arquivo existe para evitar. A
    # deriva a 0,01 nao e perceptivel quadro a quadro e ainda assim a tela nao
    # congela.
    # gradiente que se move devagar: a 0,01 nao ha movimento perceptivel quadro a
    # quadro, mas a tela nao fica congelada por nove minutos
    return ["-f", "lavfi", "-i",
            f"gradients=s={LARGURA}x{ALTURA}:c0={FUNDO_A}:c1={FUNDO_B}"
            f":speed=0.01:r={FPS}"]


def _sobreposicao(preset: str, capa: Path | None, i_audio: int,
                  plano: tuple[list[Path], float, float] | None,
                  veu: bool) -> str:
    """Filtro que desenha a visualizacao do audio sobre o fundo.

    `i_audio` nao e fixo: o preset `slides` abre uma entrada por imagem, e o
    audio passa a ser a ultima delas.
    """
    if preset == "slides" and capa is None:
        imagens, cada, cruzamento = plano
        return slides_mod.filtro(imagens, cada, cruzamento, LARGURA, ALTURA, veu)
    if preset in ("estatico", "gradiente"):
        # 10 bits aqui pelo mesmo motivo dos slides: o `gradiente` e uma rampa
        # de canto a canto, o pior caso possivel para banda em 8 bits.
        return (f"[0:v]scale={LARGURA}:{ALTURA}:force_original_aspect_ratio=increase,"
                f"crop={LARGURA}:{ALTURA},"
                f"format={slides_mod.PROFUNDIDADE},setsar=1[v]")
    if preset == "espectro":
        # `axis=0` e obrigatorio: por padrao o showcqt desenha a regua de notas
        # (A B C D E F G) sobre a imagem, o que num audiolivro nao faz sentido
        # nenhum. `sono_h=0` tira o sonograma e deixa so as barras, que sao mais
        # calmas. O blend e `lighten` e nao `screen`: screen lava o fundo inteiro.
        return (f"[{i_audio}:a]showcqt=s={LARGURA}x{ALTURA}:r={FPS}:count=2:axis=0:"
                f"sono_h=0:bar_g=2:basefreq=55:endfreq=6000:"
                f"cscheme=0.4|0.8|1.0|0.1|0.4|0.9[cqt];"
                f"[0:v]scale={LARGURA}:{ALTURA},setsar=1[bg];"
                "[bg][cqt]blend=all_mode=lighten[v]")
    # ondas: linha central sobre o fundo, na altura dos olhos
    return (f"[{i_audio}:a]showwaves=s={LARGURA}x{int(ALTURA*0.28)}:mode=cline:"
            f"colors={COR_ONDA}:r={FPS}:scale=sqrt[w];"
            f"[0:v]scale={LARGURA}:{ALTURA},setsar=1[bg];"
            f"[bg][w]overlay=0:{int(ALTURA*0.36)}:format=auto[v]")


# Estilo da legenda queimada.
#
# ATENCAO a escala: para um .srt o libass assume uma tela de referencia de 288 px
# de altura, e nao os 1080 reais. Tudo aqui e multiplicado por 1080/288 = 3,75 na
# hora de desenhar. `FontSize=13` vira ~49 px na tela, que e o corpo certo para
# 1080p; um `FontSize=26` "razoavel" viraria 97 px e cobriria o meio da imagem.
# Pelo mesmo motivo `MarginV=20` vira ~75 px do rodape.
#
# Contorno em vez de caixa opaca: caixa cobre o fundo o tempo todo, contorno so
# ocupa o traco da letra.
ESTILO_LEGENDA = (
    "FontName=DejaVu Sans,FontSize=13,PrimaryColour=&H00FFFFFF,"
    "OutlineColour=&HC0000000,BorderStyle=1,Outline=1,Shadow=0,"
    "Alignment=2,MarginV=20"
)


def _escapar(p: Path) -> str:
    """Caminho dentro do filtro do ffmpeg: dois niveis de escape."""
    return str(p).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def renderizar(audio: Path, destino: Path, preset: str = "slides",
               capa: Path | None = None, gpu: bool = True,
               legenda: Path | None = None,
               slides_dir: Path | None = None,
               slides_seg: float = slides_mod.SEGUNDOS_POR_IMAGEM,
               slides_seed: int | None = None) -> Path:
    """Gera o MP4 a partir do audio. `capa` sobrepoe o fundo gerado.

    No preset `slides` o numero de imagens sai da duracao do audio, e quais
    imagens sao sorteadas do acervo -- diferentes a cada render, a menos que
    `slides_seed` fixe o sorteio.
    """
    if preset not in presets():
        raise ValueError(f"preset desconhecido: {preset} (use {presets()})")
    plano = None
    if preset == "slides" and capa is None:
        plano = slides_mod.plano(
            duracao(audio), slides_dir or slides_mod.DIRETORIO_PADRAO,
            segundos_por_imagem=slides_seg, seed=slides_seed)
    # O veu so existe para dar contraste a legenda; sem legenda ele seria um
    # escurecimento sem motivo no rodape da arte.
    veu = legenda is not None
    entrada_fundo = _fundo(preset, capa, plano, veu)
    # Contado, e nao deduzido: `slides` abre uma entrada por imagem mais o veu,
    # e o audio e sempre a proxima. Errar este indice mapeia o audio errado.
    n_video = entrada_fundo.count("-i")
    filtro = _sobreposicao(preset, capa, n_video, plano, veu)
    if legenda is not None:
        if not legenda.exists():
            raise FileNotFoundError(f"legenda nao encontrada: {legenda}")
        # queima DEPOIS da visualizacao, senao a onda passaria por cima do texto.
        # Todo preset termina com exatamente um rotulo [v]; renomea-lo e o
        # suficiente para encadear mais um filtro no fim.
        filtro = filtro.replace("[v]", "[vbase]")
        filtro += (f";[vbase]subtitles='{_escapar(legenda)}'"
                   f":force_style='{ESTILO_LEGENDA}'[v]")

    # O despejo para 8 bits e o ULTIMO elo, depois ate da legenda: feito antes,
    # o `subtitles` receberia 8 bits e o resto do grafo perderia a precisao que
    # os 10 bits existem para dar.
    filtro = filtro.replace("[v]", "[v10]") + f";[v10]{SAIDA_8BITS}[v]"

    video = NVENC if gpu else X264
    destino.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         *entrada_fundo, "-i", str(audio),
         "-filter_complex", filtro, "-map", "[v]", "-map", f"{n_video}:a",
         *video, *CORES, "-pix_fmt", "yuv420p",
         # faststart poe o indice no inicio: o YouTube processa antes de terminar
         # o upload, e um player web consegue comecar sem baixar tudo
         "-movflags", "+faststart",
         "-c:a", "aac", "-b:a", "192k", "-shortest", str(destino)],
        capture_output=True, text=True, check=True)
    return destino
