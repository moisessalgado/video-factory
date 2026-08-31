"""CLI do audio-factory (TDD 13). Exposta no dia a dia como `iam voice`."""
from __future__ import annotations

from pathlib import Path

import typer
import yaml
from rich.console import Console
from rich.table import Table

from .. import project as proj_mod
from ..engines.chatterbox_engine import ChatterboxEngine
from ..pipeline import Runner
from ..qa.verify import Verifier
from ..script.models import Script
from ..store.db import Store

app = typer.Typer(help="Audio Factory — audiolivros narrados por IA, 100% local",
                  no_args_is_help=True)
console = Console()


def _proj(slug: str) -> Path:
    p = proj_mod.dir_projeto(slug)
    if not p.exists():
        raise typer.BadParameter(f"projeto não encontrado: {slug}")
    return p


def _lexicon() -> dict[str, str]:
    lex: dict[str, str] = {}
    for f in sorted((proj_mod.RAIZ / "lexicon").glob("*.yaml")):
        lex.update(yaml.safe_load(f.read_text(encoding="utf-8")) or {})
    return lex


@app.command()
def new(slug: str, fonte: Path = typer.Option(..., "--from"),
        narrator: str = "default", titulo: str = typer.Option(None)):
    """Cria um projeto a partir de um arquivo de texto."""
    p = proj_mod.criar(slug, fonte.resolve(), narrator, titulo=titulo)
    console.print(f"[green]projeto criado[/] {p}")
    console.print("[dim]opcional: preencha `rights:` em project.yaml para registrar "
                  "a procedência do texto[/]")


@app.command()
def script(slug: str, max_chars: int = 300,
           llm: bool = typer.Option(False, "--llm/--no-llm",
                                    help="Camada 2: resolve spans ambíguos via Ollama"),
           modelo: str = typer.Option(None, help="modelo do Ollama (padrão: gemma4:12b)")):
    """Ingere, normaliza e gera script.json + diff.md."""
    p = _proj(slug)
    proj_mod.ingerir(p)
    s = proj_mod.montar_script(p, _lexicon(), max_chars, usar_llm=llm, modelo_llm=modelo)
    n_seg = sum(len(c.segments) for c in s.chapters)
    console.print(f"[green]script.json[/] {len(s.chapters)} capítulos, {n_seg} segmentos, "
                  f"{s.total_chars} caracteres")
    console.print(f"revise o diff: {p/'diff.md'}")


@app.command()
def run(slug: str, chapters: str = typer.Option(None, help="ex.: 1,3-5"),
        no_qa: bool = typer.Option(False, "--no-qa"),
        voice: Path = typer.Option(None, help="WAV de referência (sobrepõe o narrator)"),
        ptbr_pack: bool = typer.Option(True),
        workers: int = typer.Option(1, help="processos de síntese em paralelo na GPU"),
        free_ollama: bool = typer.Option(False, "--free-ollama",
                                         help="descarrega os modelos do Ollama antes de sintetizar")):
    """Sintetiza os chunks pendentes. Retomar é o comportamento padrão."""
    p = _proj(slug)
    s = Script.load(p / "script.json")
    from ..voices import carregar

    def _ref(vid: str) -> Path | None:
        if vid in ("default", None):
            return None
        try:
            return carregar(proj_mod.RAIZ, vid).referencia
        except (FileNotFoundError, ValueError) as e:
            console.print(f"[red]voz {vid}:[/] {e}")
            raise typer.Exit(1)

    ref = voice or _ref(s.voice_id)
    # cada papel do elenco resolve para a sua própria referência
    refs = {vid: r for vid in {s.voice_id, *s.cast.values()} if (r := _ref(vid))}
    if s.cast:
        console.print(f"elenco: {s.voice_id} (narrador) + " +
                      ", ".join(f"{k}→{v}" for k, v in s.cast.items()))
    if free_ollama:
        _liberar_ollama()

    fabrica = lambda: ChatterboxEngine(s.params, use_ptbr_pack=ptbr_pack)
    runner = Runner(p, s, fabrica(), None if no_qa else Verifier(), voice_ref=ref,
                    refs_por_voz=refs, engine_factory=fabrica,
                    verifier_factory=Verifier)
    novos, limpos = runner.sync()
    console.print(f"fila: +{novos} novos, {limpos} obsoletos/recuperados")

    caps = _parse_chapters(chapters)
    if workers > 1:
        console.print(f"[dim]{workers} workers — cada um carrega o seu modelo "
                      f"(~3,5 GB de VRAM cada)[/]")
    with console.status("sintetizando…") as st:
        def prog(cid, d):
            st.update(f"{cid} {'ok' if d.aceito else '[red]review[/]'}")
        r = runner.run(caps, progress=prog, workers=workers)
    console.print(f"[green]{r['ok']} ok[/] · [yellow]{r['review']} para revisão[/] · "
                  f"RTF {r.get('rtf')} · {r.get('audio_s')}s de áudio")
    if r.get("review"):
        console.print(f"[dim]revise com `iam voice review {slug}`[/]")


@app.command()
def status(slug: str):
    """Progresso, falhas e CER médio."""
    db = Store(_proj(slug) / "state.db")
    s = db.stats()
    t = Table("estado", "chunks")
    for k in ("ok", "pending", "running", "needs_review"):
        t.add_row(k, str(s[k]))
    t.add_row("[bold]total", f"[bold]{s['total']}")
    console.print(t)
    console.print(f"áudio pronto: {s['audio_s']/60:.1f} min · "
                  f"CER médio: {s['cer_medio'] if s['cer_medio'] is None else round(s['cer_medio'],4)}")
    if s.get("speaker_medio") is not None:
        console.print(f"identidade da voz: média {s['speaker_medio']:.3f} · "
                      f"pior chunk {s['speaker_min']:.3f} (limiar 0,88)")


@app.command()
def review(slug: str,
           aprovar: str = typer.Option(None, "--aprovar", metavar="CHUNK_ID",
                                       help="aceita o chunk como está, depois de ouvir"),
           regerar: str = typer.Option(None, "--regerar", metavar="CHUNK_ID",
                                       help="devolve o chunk à fila, para outra seed")):
    """Lista — ou resolve — os chunks que precisam de revisão humana."""
    db = Store(_proj(slug) / "state.db")

    if aprovar:
        if db.approve(aprovar):
            console.print(f"[green]aprovado[/] {aprovar} — `build` já pode montar")
        else:
            console.print(f"[red]não está em needs_review:[/] {aprovar}")
            raise typer.Exit(1)
        return
    if regerar:
        db.requeue(regerar)
        console.print(f"[green]de volta à fila[/] {regerar} — rode `run` de novo")
        return

    rows = db.needs_review()
    if not rows:
        console.print("[green]nenhum chunk pendente de revisão[/]")
        return
    for r in rows:
        console.print(f"\n[bold]{r['chunk_id']}[/] — {r['error']}")
        console.print(f"  esperado: {r['text']}")
        console.print(f"  ouvido  : {r['transcript']}")
        console.print(f"  wav     : {r['wav_path']}")
    console.print(f"\n[dim]ouça o wav e decida: `review {slug} --aprovar <chunk_id>` "
                  f"ou `--regerar <chunk_id>`[/]")


@app.command()
def build(slug: str):
    """Monta os capítulos a partir dos chunks aprovados."""
    p = _proj(slug)
    s = Script.load(p / "script.json")
    engine = ChatterboxEngine(s.params)
    engine.sample_rate = 24000
    runner = Runner(p, s, engine)
    for ch in runner.store.chapters():
        destino = runner.build_chapter(ch)
        console.print(f"cap {ch}: {destino or '[yellow]incompleto — faltam chunks[/]'}")


@app.command()
def export(slug: str, formato: str = typer.Option("mp3", help="mp3, aac, flac, wav — separados por vírgula"),
           juntar: bool = typer.Option(True, "--juntar/--sem-juntar",
                                       help="também gera o arquivo único contínuo"),
           bitrate: str = "192k"):
    """Masteriza, exporta e escreve o chapters.txt."""
    from ..audio.process import chapters_txt, concatenar, duracao, exportar, masterizar

    p = _proj(slug)
    cfg = proj_mod.carregar_config(p)
    s = Script.load(p / "script.json")
    titulos = {c.idx: c.title for c in s.chapters}
    # `rights` é registro de procedência, não autorização: o export nunca é
    # bloqueado por ele. A decisão sobre o que publicar é do operador.
    status = (cfg.get("rights") or {}).get("status")
    console.print(f"[dim]direitos declarados: {status or '(não preenchido)'}[/]")

    out = p / "output"
    out.mkdir(parents=True, exist_ok=True)
    wavs = sorted((p / "audio" / "chapters").glob("ch*.wav"))
    if not wavs:
        console.print("[red]nenhum capítulo montado[/] — rode `build` antes")
        raise typer.Exit(1)
    formatos = [f.strip() for f in formato.split(",") if f.strip()]

    masters: list[Path] = []
    duracoes: list[tuple[str, float]] = []
    for n, wav in enumerate(wavs, start=1):
        cap = int(wav.stem[2:]) if wav.stem[2:].isdigit() else n
        master = out / f"{wav.stem}-master.wav"
        masterizar(wav, master)
        masters.append(master)
        duracoes.append((titulos.get(cap, wav.stem), duracao(master)))
        meta = {"title": titulos.get(cap, wav.stem), "album": cfg["titulo"],
                "track": str(cap), "artist": cfg.get("narrator", "")}
        for fmt in formatos:
            console.print(f"[green]{exportar(master, out / f'{wav.stem}.{fmt}', fmt, meta, bitrate)}[/]")

    # Os carimbos são cumulativos e só valem contra o arquivo contínuo.
    (out / "chapters.txt").write_text(chapters_txt(duracoes), encoding="utf-8")
    total = sum(d for _, d in duracoes)
    console.print(f"[green]{out/'chapters.txt'}[/] — {len(duracoes)} capítulos, "
                  f"{total/60:.1f} min")

    if juntar and len(masters) > 1:
        completo = out / f"{slug}-completo.wav"
        concatenar(masters, completo)
        meta = {"title": cfg["titulo"], "album": cfg["titulo"],
                "artist": cfg.get("narrator", "")}
        for fmt in formatos:
            console.print(f"[green]{exportar(completo, out / f'{slug}-completo.{fmt}', fmt, meta, bitrate)}[/]")


@app.command()
def report(slug: str, medir: bool = typer.Option(True, "--medir/--sem-medir",
                                                 help="medir loudness dos masters (usa ffmpeg)")):
    """Confronta as métricas do projeto com os alvos objetivos do TDD."""
    from ..qa.report import coletar, markdown

    p = _proj(slug)
    cfg = proj_mod.carregar_config(p)
    db = Store(p / "state.db")
    metricas = coletar(p, db, medir_audio=medir)
    review = db.needs_review()

    t = Table("métrica", "medido", "alvo", "situação", "detalhe")
    for m in metricas:
        if m.valor is None:
            val = "—"
        elif "RTF" in m.nome:
            val = f"{m.valor:.3f}"
        elif "Loudness" in m.nome:
            val = f"{m.valor:.1f} LUFS"
        else:
            val = f"{m.valor*100:.1f}%"
        cor = {True: "green", False: "red", None: "dim"}[m.ok]
        t.add_row(m.nome, val, m.alvo, f"[{cor}]{m.marca}[/]", m.detalhe)
    console.print(t)

    destino = p / "qa" / "report.md"
    destino.write_text(markdown(cfg["titulo"], metricas, review), encoding="utf-8")
    console.print(f"[green]{destino}[/]")
    if any(m.ok is False for m in metricas):
        raise typer.Exit(1)


def _nome_de_arquivo(titulo: str) -> str:
    """Titulo do projeto -> nome de arquivo publicavel, CURTO.

    Mantem espacos e acentos: o YouTube usa o nome do arquivo como titulo
    sugerido, e "Dhammacakkappavattana Sutta" le melhor que um slug com hifens.

    Corta no primeiro travessao ou dois-pontos de proposito. O motivo nao e
    estetico: o player do operador desenha o nome do arquivo sobre o video ao
    iniciar, e um nome de 68 caracteres atravessa o rodape e COLIDE com a
    legenda queimada. O nome completo do projeto vira o subtitulo la no YouTube;
    aqui basta a parte que identifica.
    """
    limpo = "".join(" " if c in '/\\:*?"<>|' else c for c in titulo)
    for corte in ("—", "–", " - ", ":"):
        if corte in limpo:
            limpo = limpo.split(corte)[0]
            break
    return " ".join(limpo.split()).strip(". ") or "video"


@app.command()
def video(slug: str,
          preset: str = typer.Option("ondas", help="ondas, espectro ou estatico"),
          musica: str = typer.Option("nenhuma",
              help="'ace' (modelo dedicado; 'ace:sobrio' escolhe a paleta), "
                   "'gerada' (sintetizada), 'nenhuma', ou caminho de um arquivo"),
          capa: Path = typer.Option(None, help="imagem de fundo (sobrepõe o preset)"),
          trilha_lufs: float = typer.Option(None, help="nível da trilha (padrão −29,5)"),
          legenda: bool = typer.Option(True, "--legenda/--sem-legenda",
              help="queima o texto sincronizado (usa o .srt gerado pelo build)"),
          musica_pecas: int = typer.Option(1,
              help="peças distintas no leito; 1 repete a mesma o capítulo todo"),
          musica_seg: float = typer.Option(120.0, help="duração de cada peça, em s"),
          musica_peca: int = typer.Option(0, help="qual peça da paleta usar (0 a 5)"),
          nome: str = typer.Option(None,
              help="nome do MP4 (padrão: o título do projeto)"),
          gpu: bool = typer.Option(True, "--gpu/--cpu")):
    """Gera o MP4 para o YouTube, com trilha opcional sob a narração."""
    from ..audio import musica_ace as ace
    from ..audio.musica import TRILHA_LUFS, mixar, preparar_trilha
    from ..audio.process import duracao
    from ..video.render import presets, renderizar

    p = _proj(slug)
    cfg = proj_mod.carregar_config(p)
    if preset not in presets():
        console.print(f"[red]preset desconhecido:[/] {preset} — use {', '.join(presets())}")
        raise typer.Exit(1)

    # Resolve o modo da trilha uma vez, antes do laço: um erro de paleta ou um
    # arquivo inexistente tem de aparecer agora, e não depois de renderizar
    # metade dos capítulos.
    fonte, paleta = None, "contemplativo"
    if musica.startswith("ace"):
        paleta = musica.split(":", 1)[1] if ":" in musica else "contemplativo"
        if paleta not in ace.PALETAS:
            console.print(f"[red]paleta desconhecida:[/] {paleta} — "
                          f"use {', '.join(ace.PALETAS)}")
            raise typer.Exit(1)
        if not ace.disponivel():
            console.print(f"[red]venv de música ausente:[/] {ace.VENV} — "
                          "veja ESTADO.md, ou use `--musica gerada`")
            raise typer.Exit(1)
    elif musica not in ("nenhuma", "gerada"):
        fonte = Path(musica).resolve()
        if not fonte.exists():
            console.print(f"[red]trilha não encontrada:[/] {fonte}")
            raise typer.Exit(1)
        console.print("[yellow]trilha de terceiro:[/] confira a licença antes de "
                      "publicar — o Content ID do YouTube reclama sozinho")
    masters = sorted((p / "output").glob("*-master.wav"))
    if not masters:
        console.print("[red]nenhum master[/] — rode `export` antes")
        raise typer.Exit(1)

    for master in masters:
        audio = master
        if musica != "nenhuma":
            alvo = p / "cache" / f"{master.stem}-trilha.wav"
            with console.status("preparando a trilha…"):
                if musica.startswith("ace"):
                    tr = ace.preparar_trilha(
                        alvo, duracao(master), paleta=paleta,
                        n_pecas=musica_pecas, peca_s=musica_seg,
                        peca_inicial=musica_peca,
                        progresso=lambda m: console.print(f"[dim]{m}[/]"))
                else:
                    tr = preparar_trilha(alvo, duracao(master), fonte)
                audio = p / "cache" / f"{master.stem}-com-trilha.wav"
                mixar(master, tr, audio, trilha_lufs=trilha_lufs or TRILHA_LUFS)

        # O nome do arquivo NAO e detalhe: o YouTube pre-preenche o titulo do
        # video com ele. "ch01.mp4" viraria o titulo sugerido da publicacao.
        base = nome or _nome_de_arquivo(cfg["titulo"])
        if len(masters) > 1:
            base = f"{base} - {master.stem.replace('-master','')}"
        destino = p / "output" / f"{base}.mp4"
        srt = p / "audio" / "chapters" / f"{master.stem.replace('-master','')}.srt"
        if legenda and not srt.exists():
            console.print(f"[yellow]sem legenda:[/] {srt.name} não existe — "
                          "rode `build` de novo para gerá-la")
        with console.status(f"renderizando {destino.name}…"):
            renderizar(audio, destino, preset=preset, capa=capa, gpu=gpu,
                       legenda=srt if (legenda and srt.exists()) else None)
        console.print(f"[green]{destino}[/] ({destino.stat().st_size/1e6:.0f} MB)")

    console.print("[dim]lembre do disclosure de conteúdo sintético ao publicar[/]")


@app.command()
def musica(paleta: str = typer.Option("contemplativo", help="contemplativo ou sobrio"),
           duracao: float = typer.Option(0.0,
               help="se >0, monta também um leito desta duração, para ouvir a emenda")):
    """Gera as peças da trilha e mostra onde ficaram, para ouvir antes de renderizar.

    Existe porque a alternativa é descobrir que a paleta não serve depois de
    renderizar uma hora de vídeo.
    """
    from ..audio import musica_ace as ace

    if paleta not in ace.PALETAS:
        console.print(f"[red]paleta desconhecida:[/] {paleta} — use {', '.join(ace.PALETAS)}")
        raise typer.Exit(1)
    if not ace.disponivel():
        console.print(f"[red]venv de música ausente:[/] {ace.VENV} — veja ESTADO.md")
        raise typer.Exit(1)

    with console.status(f"peças da paleta {paleta}…"):
        pecas = ace.gerar_pecas(paleta, progresso=lambda m: console.print(f"[dim]{m}[/]"))
    t = Table("peça", "timbre", "arquivo")
    for peca, prompt in zip(pecas, ace.PALETAS[paleta]):
        t.add_row(peca.stem.split("-")[1], prompt, str(peca))
    console.print(t)

    if duracao > 0:
        alvo = ace.CACHE / f"leito-{paleta}-{int(duracao)}s.wav"
        with console.status("montando o leito…"):
            ace.preparar_trilha(alvo, duracao, paleta=paleta)
        console.print(f"[green]{alvo}[/]")


voice_app = typer.Typer(help="Registry de vozes do canal", no_args_is_help=True)
app.add_typer(voice_app, name="voice")


def _dispositivos_captura() -> list[tuple[str, str, str]]:
    """Entradas de captura, como (backend, device, descrição).

    PipeWire primeiro: quando ele está rodando, ele abre a placa em modo
    exclusivo, e gravar direto de `hw:X,Y` falha com "Device or resource busy".
    ALSA cru fica como reserva para máquina sem servidor de áudio.
    """
    import json
    import re
    import subprocess

    try:
        dump = subprocess.run(["pw-dump"], capture_output=True, text=True, timeout=10)
        nos = json.loads(dump.stdout)
    except (FileNotFoundError, ValueError, subprocess.SubprocessError):
        nos = []
    achados = []
    for n in nos:
        props = ((n.get("info") or {}).get("props") or {})
        if props.get("media.class") == "Audio/Source" and props.get("node.name"):
            achados.append(("pulse", props["node.name"],
                            props.get("node.description") or props["node.name"]))
    if achados:
        return achados

    saida = subprocess.run(["arecord", "-l"], capture_output=True, text=True).stdout
    for m in re.finditer(r"^card (\d+): (\S+) \[([^\]]+)\], device (\d+): ([^\[]+)",
                         saida, re.MULTILINE):
        card, _, desc, dev, nome = m.groups()
        achados.append(("alsa", f"hw:{card},{dev}", f"{desc} — {nome.strip()}"))
    return achados


def _mostrar_take(take, titulo: str) -> bool:
    """Imprime a análise e devolve True se a gravação serve como referência."""
    t = Table("medida", "valor", "alvo", title=titulo)
    from ..audio.analise import (CORTE_MIN_HZ, PICO_ALVO_DB, RUIDO_MAX_DB,
                                 SNR_MIN_DB)
    t.add_row("duração", f"{take.duracao_s:.1f} s", "20–180 s")
    t.add_row("taxa/canais", f"{take.sample_rate} Hz · {take.canais}", "48000 Hz · 1")
    t.add_row("pico", f"{take.pico_db:.1f} dBFS", f"{PICO_ALVO_DB:.0f} dBFS")
    t.add_row("ruído de fundo", f"{take.ruido_db:.1f} dBFS", f"< {RUIDO_MAX_DB:.0f} dBFS")
    t.add_row("sinal/ruído", f"{take.snr_db:.1f} dB", f"> {SNR_MIN_DB:.0f} dB")
    t.add_row("banda útil", f"{take.corte_hz/1000:.1f} kHz", f"> {CORTE_MIN_HZ/1000:.0f} kHz")
    t.add_row("clipping", f"{take.clip_fracao*100:.3f}%", "0%")
    from ..audio.analise import MODULACAO_MIN_DB, RUMBLE_MAX_FRACAO
    t.add_row("modulação (voz?)", f"{take.modulacao_db:.1f} dB",
              f"> {MODULACAO_MIN_DB:.0f} dB")
    t.add_row("energia < 20 Hz", f"{take.rumble_fracao*100:.1f}%",
              f"< {RUMBLE_MAX_FRACAO*100:.0f}%")
    console.print(t)
    for a in take.avisos:
        console.print(f"[yellow]aviso:[/] {a}")
    for pr in take.problemas:
        console.print(f"[red]problema:[/] {pr}")
    if take.problemas:
        console.print("\n[red]este take não serve como referência[/] — regrave")
        return False
    console.print("\n[green]take aprovado[/] — ouça antes de registrar")
    return True


@voice_app.command("check")
def voice_check(arquivo: Path):
    """Mede uma gravação e diz se ela serve como referência."""
    from ..audio.analise import analisar

    if not _mostrar_take(analisar(arquivo), f"Análise — {arquivo.name}"):
        raise typer.Exit(1)


@voice_app.command("record")
def voice_record(
        saida: Path = typer.Option(None, "--saida", help="WAV a gravar"),
        segundos: int = typer.Option(90, help="duração da gravação"),
        dispositivo: str = typer.Option(None, help="entrada ALSA, ex.: hw:2,0"),
        listar: bool = typer.Option(False, "--listar", help="só lista as entradas")):
    """Instruções, texto de calibração e — com --saida — a gravação em si."""
    import subprocess

    from ..voices import TEXTO_CALIBRACAO

    entradas = _dispositivos_captura()
    if listar:
        if not entradas:
            console.print("[red]nenhuma entrada de captura ALSA encontrada[/]")
            raise typer.Exit(1)
        for backend, dev, desc in entradas:
            console.print(f"  [bold]{dev}[/]  [dim]({backend})[/]  {desc}")
        console.print("\n[yellow]Não use microfone de headset Bluetooth:[/] o perfil "
                      "HFP corta a banda em 8 kHz e aplica denoise que não se desliga.")
        return

    console.print("[bold]Como gravar a referência[/] (TDD §7.2)\n")
    for linha in [
        "60–90 s de fala contínua, em [bold]tom de narração[/] — não de conversa",
        "microfone [bold]com fio[/], fixo, sala com pouco eco (um closet com roupas serve)",
        "WAV 48 kHz / 24-bit mono · [bold]sem[/] compressor, EQ, denoise ou reverb",
        "picos por volta de −6 dBFS: se clipar, o registro é recusado",
        "[bold]deixe 2 s de silêncio[/] antes de começar a falar — é o que permite "
        "medir o ruído da sala",
        "grave [bold]3 takes[/] e escolha o melhor por teste cego com `voice test`",
    ]:
        console.print(f"  • {linha}")
    console.print("\n[bold]Texto de calibração[/] (fonética variada — leia duas vezes):\n")
    console.print(f"[italic]{TEXTO_CALIBRACAO}[/]\n")

    if saida is None:
        console.print("Para gravar aqui: [bold]iam voice voice record --saida take1.wav[/]")
        console.print("Entradas disponíveis: [bold]iam voice voice record --listar[/]")
        console.print("Já tem o arquivo? [bold]iam voice voice check take1.wav[/]")
        return

    if not entradas:
        console.print("[red]nenhuma entrada de captura encontrada[/]")
        raise typer.Exit(1)
    backend, padrao, _ = entradas[0]
    if dispositivo:
        backend = "alsa" if dispositivo.startswith("hw:") else backend
    dispositivo = dispositivo or padrao

    saida.parent.mkdir(parents=True, exist_ok=True)
    console.print(f"gravando de [bold]{dispositivo}[/] por {segundos}s em {saida}")
    with console.status("3…"):
        subprocess.run(["sleep", "3"])
    console.print("[bold green]FALE AGORA[/]")
    bruto = saida.with_suffix(".bruto.wav")
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", backend, "-i", dispositivo,
         "-t", str(segundos), "-ar", "48000", "-ac", "1", "-c:a", "pcm_s24le",
         str(bruto)],
        capture_output=True, text=True)
    if proc.returncode != 0:
        bruto.unlink(missing_ok=True)
        console.print(f"[red]falha na gravação:[/] {proc.stderr.strip()[:300]}")
        raise typer.Exit(1)

    from ..audio.analise import CORTE_SUBSONICO_HZ, RUMBLE_MAX_FRACAO, analisar

    # O subsônico é medido no sinal CRU e depois removido. Medido nesta máquina:
    # a captura do ALC897 tem deriva lenta abaixo de 20 Hz mesmo sem nada plugado,
    # e ela some do arquivo com um passa-altas. Não é processar a voz -- é tirar o
    # que não é som, e a cadeia de masterização já corta em 65 Hz de qualquer jeito.
    cru = analisar(bruto)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(bruto), "-af", f"highpass=f={CORTE_SUBSONICO_HZ:.0f}",
                    "-c:a", "pcm_s24le", str(saida)], capture_output=True, text=True)
    bruto.unlink(missing_ok=True)

    console.print()
    if cru.rumble_fracao > RUMBLE_MAX_FRACAO:
        console.print(f"[dim]sinal cru tinha {cru.rumble_fracao*100:.0f}% de energia "
                      f"abaixo de {CORTE_SUBSONICO_HZ:.0f} Hz — removida no arquivo "
                      f"final[/]")
        if cru.clip_fracao > 0:
            console.print("[yellow]atenção:[/] esse subsônico chegou a saturar o "
                          "conversor. Baixe o ganho de entrada — o corte não desfaz "
                          "o que já clipou")
    if not _mostrar_take(analisar(saida), f"Análise — {saida.name}"):
        raise typer.Exit(1)
    console.print(f"\nRegistre: [bold]iam voice voice new moises-v1 --reference {saida}[/]")


@voice_app.command("new")
def voice_new(voice_id: str, reference: Path = typer.Option(..., "--reference"),
              quem: str = typer.Option("Moises", help="nome no termo de consentimento"),
              forcar: bool = typer.Option(False, "--forcar",
                  help="registra apesar dos defeitos medidos, que ficam no profile.yaml")):
    """Registra uma voz. Exige consentimento documentado."""
    from ..voices import criar, modelo_consentimento

    try:
        v = criar(proj_mod.RAIZ, voice_id, reference.resolve(),
                  consentimento=modelo_consentimento(voice_id, quem), forcar=forcar)
    except ValueError as e:
        console.print(f"[red]recusado:[/] {e}")
        raise typer.Exit(1)
    console.print(f"[green]voz registrada[/] {v.dir}")
    if forcar:
        console.print("[yellow]registrada com ressalvas[/] — os defeitos medidos "
                      f"ficaram anotados em {v.dir/'profile.yaml'}")
    console.print(f"assine o termo: {v.dir/'CONSENT.md'}")
    console.print("[yellow]voices/ não é versionado — inclua no backup cifrado[/]")


@voice_app.command("template")
def voice_template(voice_id: str = typer.Argument(..., help="id a registrar, ex.: dora-v1"),
                   kokoro_voice: str = typer.Option("pf_dora",
                       help="voz do Kokoro: pf_dora, pm_alex, pm_santa"),
                   segundos: int = typer.Option(16, help="duração da referência"),
                   velocidade: float = typer.Option(1.0,
                       help="ritmo da referência (0,75 = mais pausado)")):
    """Cria uma voz template a partir de uma voz do Kokoro (Apache-2.0).

    Sintetiza uma referência com o Kokoro e a registra como voz de clonagem do
    Chatterbox: timbre brasileiro, sem trocar de motor quando a voz própria chegar.

    `velocidade` existe porque o Chatterbox clona o ANDAMENTO junto com o timbre:
    referência apressada rende narração apressada, e nenhum parâmetro de geração
    corrige isso depois — medido, `cfg_weight` de 0,5 a 0,2 não move as palavras
    por minuto. O lugar de decidir o ritmo é aqui.

    Vem do Kokoro, e não de esticar o WAV com `atempo`, porque assim não há
    artefato de time-stretch no sinal que condiciona o clone.
    """
    import warnings

    import numpy as np
    import soundfile as sf

    warnings.filterwarnings("ignore")
    from kokoro import KPipeline

    from ..voices import TEXTO_CALIBRACAO, criar

    with console.status(f"sintetizando referência com {kokoro_voice}…"):
        pipe = KPipeline(lang_code="p")
        audio = np.concatenate([g.audio.numpy() for g in pipe(TEXTO_CALIBRACAO,
                                                             voice=kokoro_voice,
                                                             speed=velocidade)])
    tmp = proj_mod.RAIZ / "cache" / f"ref-{voice_id}.wav"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(tmp), audio, 24000)
    v = criar(proj_mod.RAIZ, voice_id, tmp,
              template_de=f"Kokoro-82M (Apache-2.0), voz {kokoro_voice}"
                          + (f", velocidade {velocidade:g}" if velocidade != 1.0 else ""))
    console.print(f"[green]voz template registrada[/] {v.dir}")
    console.print(f"procedência: {v.dir/'PROVENANCE.md'}")
    console.print(f"teste: [bold]iam voice voice test {voice_id}[/]")


@voice_app.command("list")
def voice_list():
    """Lista as vozes registradas."""
    from ..voices import listar

    vozes = listar(proj_mod.RAIZ)
    if not vozes:
        console.print("nenhuma voz registrada — use [bold]voice record[/] para começar")
        return
    import yaml as _yaml

    for v in vozes:
        cfg = _yaml.safe_load(
            (proj_mod.RAIZ / "voices" / v / "profile.yaml").read_text(encoding="utf-8"))
        tipo = cfg.get("tipo", "pessoa")
        origem = f" — {cfg['origem']}" if cfg.get("origem") else ""
        console.print(f"  [bold]{v}[/] ({tipo}){origem}")


@voice_app.command("test")
def voice_test(voice_id: str, ptbr_pack: bool = True):
    """Sintetiza o texto de calibração com a voz, para conferência auditiva."""
    import soundfile as sf

    from ..voices import TEXTO_CALIBRACAO, carregar

    v = carregar(proj_mod.RAIZ, voice_id)
    engine = ChatterboxEngine(v.params, use_ptbr_pack=ptbr_pack)
    with console.status("carregando modelo…"):
        engine.load()
        engine.set_voice(v.referencia)
    with console.status("sintetizando…"):
        audio = engine.synthesize(TEXTO_CALIBRACAO, seed=v.params.seed or 1234)
    destino = v.dir / "samples" / f"calibracao-{voice_id}.wav"
    sf.write(str(destino), audio, engine.sample_rate)
    console.print(f"[green]{destino}[/] ({len(audio)/engine.sample_rate:.1f}s) — ouça antes de usar")


@app.command()
def doctor():
    """Verifica GPU, torch, FFmpeg e licenças dos pesos."""
    import shutil
    import torch

    ok = lambda b: "[green]OK[/]" if b else "[red]FALHOU[/]"
    console.print(f"torch {torch.__version__} · CUDA {ok(torch.cuda.is_available())}")
    if torch.cuda.is_available():
        cap = torch.cuda.get_device_capability(0)
        console.print(f"GPU {torch.cuda.get_device_name(0)} sm_{cap[0]}{cap[1]}")
        try:
            x = torch.randn(64, 64, device="cuda"); (x @ x).sum().item()
            console.print(f"kernels na GPU {ok(True)}")
        except Exception as e:
            console.print(f"kernels na GPU {ok(False)} — {e}")
    console.print(f"ffmpeg {ok(shutil.which('ffmpeg'))} · ffprobe {ok(shutil.which('ffprobe'))}")
    lic = proj_mod.RAIZ / "LICENSES.md"
    console.print(f"registro de licenças {ok(lic.exists())} — {lic}")


def _liberar_ollama() -> None:
    """Descarrega os modelos do Ollama da GPU antes da sintese.

    Nao e obrigatorio -- a Fase 0 mediu 3,5 GB de pico para o TTS em 16 GB, e o
    gemma4:12b cabe junto. Vira util com varios workers, ou se a GPU estiver
    dividida com outra coisa.
    """
    import shutil
    import subprocess

    if not shutil.which("ollama"):
        console.print("[yellow]ollama não encontrado — nada a liberar[/]")
        return
    ps = subprocess.run(["ollama", "ps"], capture_output=True, text=True)
    modelos = [l.split()[0] for l in ps.stdout.splitlines()[1:] if l.strip()]
    for m in modelos:
        subprocess.run(["ollama", "stop", m], capture_output=True, text=True)
    console.print(f"[dim]ollama: {len(modelos) or 'nenhum'} modelo(s) descarregado(s)[/]")


def _parse_chapters(spec: str | None) -> list[int] | None:
    if not spec:
        return None
    out: list[int] = []
    for parte in spec.split(","):
        if "-" in parte:
            a, b = parte.split("-")
            out += list(range(int(a), int(b) + 1))
        else:
            out.append(int(parte))
    return out


if __name__ == "__main__":
    app()
