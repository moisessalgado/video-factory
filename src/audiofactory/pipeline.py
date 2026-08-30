"""Orquestracao: fila -> TTS -> QA -> disco (TDD 8).

Invariantes:
  - retomar e o comportamento padrao: processa tudo que nao esta 'ok';
  - um chunk irrecuperavel vira 'needs_review' e o pipeline SEGUE;
  - os conditionals da voz sao preparados UMA vez, antes do primeiro chunk.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np

from .audio.process import PAUSA_CAPITULO_MS, PAUSA_PARAGRAFO_MS, Segmento, montar, salvar_wav
from .engines.base import TTSEngine
from .qa.policy import Decisao, Tentativa, deve_repetir, escolher
from .qa.verify import Verifier
from .script.models import Script
from .store.db import Store


class Runner:
    def __init__(self, projeto: Path, script: Script, engine: TTSEngine,
                 verifier: Verifier | None = None, voice_ref: Path | None = None,
                 seed_base: int = 0, refs_por_voz: dict[str, Path] | None = None):
        self.projeto = projeto
        self.script = script
        self.engine = engine
        self.verifier = verifier
        self.voice_ref = voice_ref
        # voice_id -> WAV de referencia. Vazio = voz embutida do modelo.
        self.refs_por_voz = refs_por_voz or {}
        self.seed_base = seed_base
        self.store = Store(projeto / "state.db")
        self.speaker: object | None = None
        self.chunks_dir = projeto / "audio" / "chunks"
        self.logs_dir = projeto / "logs"
        for d in (self.chunks_dir, self.logs_dir, projeto / "audio" / "chapters",
                  projeto / "qa", projeto / "output"):
            d.mkdir(parents=True, exist_ok=True)

    # -- preparacao -----------------------------------------------------------

    def sync(self) -> tuple[int, int]:
        novos, obsoletos = self.store.sync_script(self.script)
        recuperados = self.store.reset_stale()
        return novos, obsoletos + recuperados

    # -- execucao -------------------------------------------------------------

    def run(self, chapters: list[int] | None = None, progress=None) -> dict:
        pendentes = self.store.pending(chapters)
        if not pendentes:
            return {"processados": 0, "ok": 0, "review": 0}

        self.engine.load()
        if self.verifier:
            self.verifier.load()

        # Processar AGRUPADO POR VOZ: preparar conditionals custa segundos, e
        # alternar voz a cada fala de diálogo pagaria esse custo milhares de vezes.
        # A ordem de narração é restaurada na montagem do capítulo, que lê do banco.
        pendentes = sorted(pendentes, key=lambda r: (r["voice_id"] or "",
                                                     r["chapter"], r["idx"]))
        voz_atual = object()

        log = (self.logs_dir / f"run-{int(time.time())}.jsonl").open("a")
        n_ok = n_rev = 0
        t_audio = t_gen = 0.0

        for row in pendentes:
            cid, texto = row["chunk_id"], row["text"]
            if row["voice_id"] != voz_atual:
                voz_atual = row["voice_id"]
                self._trocar_voz(voz_atual)
            self.store.claim(cid)
            t0 = time.time()
            decisao, tentativas = self._gerar_com_qa(texto)
            gen_s = time.time() - t0

            wav_path = self.chunks_dir / f"{cid.replace('/', '_')}.wav"
            wav_path.parent.mkdir(parents=True, exist_ok=True)
            salvar_wav(decisao.melhor.audio, wav_path, self.engine.sample_rate)
            dur = len(decisao.melhor.audio) / self.engine.sample_rate
            t_audio += dur
            t_gen += gen_s

            sim = None
            if self.speaker is not None:
                identidade_ok, sim = self.speaker.ok(decisao.melhor.audio,
                                                     self.engine.sample_rate)
                if decisao.aceito and not identidade_ok:
                    decisao.aceito = False
                    decisao.motivo = (f"voz divergente da referência "
                                      f"(similaridade {sim:.3f})")

            if decisao.aceito:
                self.store.finish_ok(cid, str(wav_path), dur, decisao.melhor.qa.cer,
                                     decisao.melhor.qa.transcript, decisao.melhor.seed,
                                     speaker_sim=sim)
                n_ok += 1
            else:
                self.store.finish_review(cid, decisao.motivo, str(wav_path),
                                         decisao.melhor.qa.cer,
                                         decisao.melhor.qa.transcript)
                n_rev += 1

            log.write(json.dumps({
                "chunk_id": cid, "voz": row["voice_id"], "papel": row["role"],
                "aceito": decisao.aceito, "tentativas": tentativas,
                "cer": decisao.melhor.qa.cer,
                "speaker_sim": round(sim, 4) if sim is not None else None,
                "duracao_s": round(dur, 2),
                "gen_s": round(gen_s, 2), "motivo": decisao.motivo,
                "texto": texto,
            }, ensure_ascii=False) + "\n")
            log.flush()
            if progress:
                progress(cid, decisao)

        log.close()
        return {"processados": len(pendentes), "ok": n_ok, "review": n_rev,
                "audio_s": round(t_audio, 1), "gen_s": round(t_gen, 1),
                "rtf": round(t_gen / t_audio, 3) if t_audio else None}

    def _trocar_voz(self, voice_id: str | None) -> None:
        """Congela os conditionals da voz do grupo e ajusta a checagem de identidade."""
        ref = self.refs_por_voz.get(voice_id) if voice_id else None
        ref = ref or self.voice_ref
        self.speaker = None
        if ref is None:
            return
        self.engine.set_voice(ref)
        ve = getattr(self.engine.model, "ve", None)
        if ve is not None:
            from .qa.speaker import SpeakerCheck

            self.speaker = SpeakerCheck(ve, ref)

    def _gerar_com_qa(self, texto: str) -> tuple[Decisao, int]:
        """Gera, verifica e regenera com nova seed enquanto valer a pena."""
        tentativas: list[Tentativa] = []
        for n in range(1, 4):
            seed = self.seed_base + n * 1000 + len(tentativas)
            audio = self.engine.synthesize(texto, seed=seed)
            if self.verifier is None:
                from .qa.verify import QAResult
                dur = len(audio) / self.engine.sample_rate
                qa = QAResult(True, 0.0, "", dur, len(texto) / dur if dur else 0.0)
            else:
                qa = self.verifier.check(audio, self.engine.sample_rate, texto)
            tentativas.append(Tentativa(audio, qa, seed))
            if not deve_repetir(qa, n):
                break
        return escolher(tentativas), len(tentativas)

    # -- montagem -------------------------------------------------------------

    def build_chapter(self, chapter: int) -> Path | None:
        """Monta um capitulo a partir dos chunks 'ok'. Falta chunk -> nao monta."""
        rows = self.store.chapter_chunks(chapter)
        if not rows or any(r["state"] != "ok" for r in rows):
            return None
        import soundfile as sf

        segs = []
        for i, r in enumerate(rows):
            audio, _ = sf.read(r["wav_path"], dtype="float32")
            pausa = PAUSA_CAPITULO_MS if i == len(rows) - 1 else PAUSA_PARAGRAFO_MS
            segs.append(Segmento(audio, pausa))
        full = montar(segs, self.engine.sample_rate)
        destino = self.projeto / "audio" / "chapters" / f"ch{chapter:02d}.wav"
        salvar_wav(full, destino, self.engine.sample_rate)
        return destino
