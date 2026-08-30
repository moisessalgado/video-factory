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
                 seed_base: int = 0):
        self.projeto = projeto
        self.script = script
        self.engine = engine
        self.verifier = verifier
        self.voice_ref = voice_ref
        self.seed_base = seed_base
        self.store = Store(projeto / "state.db")
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
        if self.voice_ref:
            self.engine.set_voice(self.voice_ref)
        if self.verifier:
            self.verifier.load()

        log = (self.logs_dir / f"run-{int(time.time())}.jsonl").open("a")
        n_ok = n_rev = 0
        t_audio = t_gen = 0.0

        for row in pendentes:
            cid, texto = row["chunk_id"], row["text"]
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

            if decisao.aceito:
                self.store.finish_ok(cid, str(wav_path), dur, decisao.melhor.qa.cer,
                                     decisao.melhor.qa.transcript, decisao.melhor.seed)
                n_ok += 1
            else:
                self.store.finish_review(cid, decisao.motivo, str(wav_path),
                                         decisao.melhor.qa.cer,
                                         decisao.melhor.qa.transcript)
                n_rev += 1

            log.write(json.dumps({
                "chunk_id": cid, "aceito": decisao.aceito, "tentativas": tentativas,
                "cer": decisao.melhor.qa.cer, "duracao_s": round(dur, 2),
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
