"""Motor principal: Chatterbox Multilingual V3 / pack pt-br (TDD 5).

Os conditionals da voz sao calculados uma vez e reaproveitados em todos os chunks
do livro -- e o que impede a identidade da voz de derivar entre capitulos.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import torch

from ..script.models import SynthParams
from .base import TTSEngine

REPO_PTBR = "ResembleAI/Chatterbox-Multilingual-pt-br"


class ChatterboxEngine(TTSEngine):
    name = "chatterbox"

    def __init__(self, params: SynthParams, device: str = "cuda",
                 ckpt_dir: Path | None = None, use_ptbr_pack: bool = True):
        self.params = params
        self.device = device
        self.ckpt_dir = ckpt_dir
        self.use_ptbr_pack = use_ptbr_pack
        self.model = None
        self.version = "chatterbox-mtl-v3-ptbr" if use_ptbr_pack else "chatterbox-mtl-v3"

    def load(self) -> None:
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS

        if self.ckpt_dir is not None:
            self.model = ChatterboxMultilingualTTS.from_local(str(self.ckpt_dir), self.device)
        elif self.use_ptbr_pack:
            from huggingface_hub import snapshot_download

            path = snapshot_download(repo_id=REPO_PTBR, repo_type="model")
            self.model = ChatterboxMultilingualTTS.from_local(path, self.device)
        else:
            self.model = ChatterboxMultilingualTTS.from_pretrained(device=self.device)
        self.sample_rate = self.model.sr

    def set_voice(self, reference_wav: Path | None) -> None:
        """Prepara os conditionals a partir da voz de referencia, uma unica vez."""
        if reference_wav is None:
            return
        self.model.prepare_conditionals(str(reference_wav),
                                        exaggeration=self.params.exaggeration)

    def synthesize(self, text: str, seed: int | None = None) -> np.ndarray:
        if seed is not None:
            torch.manual_seed(seed)
        with torch.inference_mode():
            wav = self.model.generate(
                text,
                language_id=self.params.language_id,
                exaggeration=self.params.exaggeration,
                cfg_weight=self.params.cfg_weight,
                temperature=self.params.temperature,
                repetition_penalty=self.params.repetition_penalty,
            )
        return wav.detach().cpu().squeeze().numpy().astype(np.float32)
