# Estado da implementação

Documento de handoff. **Leia primeiro [`docs/TDD.md`](docs/TDD.md)** — é o design aprovado e a
justificativa de cada decisão. Este arquivo diz só onde a implementação parou.

Atualizado: 2026-08-29.

## Ambiente (já provisionado)

```bash
cd /home/moises/dev/audio-factory
./.venv/bin/python -c "import torch; print(torch.__version__)"   # 2.13.0+cu130
```

⚠️ **Armadilha de instalação (custou tempo, não repita):** `chatterbox-tts` fixa
`torch==2.6.0+cu124`, que **não roda em sm_120** (`no kernel image is available`). A ordem correta é:

```bash
uv venv --python 3.12 .venv
uv pip install chatterbox-tts                       # arrasta torch 2.6 cu124
uv pip install --index-url https://download.pytorch.org/whl/cu130 torch==2.13.0 torchaudio==2.11.0
uv pip uninstall $(uv pip list | grep -oE '^nvidia-[a-z-]+-cu12')   # senão o NCCL cu12 sequestra o link
uv pip install --reinstall --index-url https://download.pytorch.org/whl/cu130 torch==2.13.0 torchaudio==2.11.0
```

Também: `torchaudio.save` no torch 2.11 exige `torchcodec` — use **`soundfile`**.
Modelos ficam em `models/` (aponte `HF_HOME` para lá).

## Fase 0 — CONCLUÍDA ✅

Benchmark real (`bench/fase0_bench.py`, dados em `bench/out/bench.json`), RTX 5060 Ti:

| Métrica | Medido |
|---|---|
| RTF global | **0,291** (1 h de áudio em ~17,5 min) |
| VRAM de pico | **3,49 GB** de 16 GB |
| Carga do modelo | 5,0 s |
| Sample rate | 24 kHz |

- Qualidade do pt-BR **ouvida e aprovada pelo usuário** (WAVs em `bench/out/`).
- Sobra VRAM: o `gemma4:12b` do Ollama pode coexistir; `--free-ollama` virou opcional.
- **A alucinação é real:** o `alignment_stream_analyzer` do Chatterbox detectou repetição de token e
  **forçou EOS**, ou seja, truncou o áudio silenciosamente. Por isso o QA precisa checar
  **duração real vs. esperada**, não só o texto transcrito.
- Licenças auditadas em [`LICENSES.md`](LICENSES.md).

## Fases 1–2 — EM ANDAMENTO

| Módulo | Estado | Arquivo |
|---|---|---|
| Documento canônico (`script.json`, ids por hash) | ✅ pronto e testado | `src/audiofactory/script/models.py` |
| Normalizador determinístico pt-BR (Camada 1) | ✅ pronto e testado | `src/audiofactory/narration/rules.py` |
| Chunker (≤300 chars, funde fragmentos curtos) | ✅ pronto e testado | `src/audiofactory/chunk/splitter.py` |
| Contrato de motor TTS | ✅ pronto | `src/audiofactory/engines/base.py` |
| Motor Chatterbox (+ pack pt-br, conditionals congelados) | ✅ escrito, **falta testar com voz de referência** | `src/audiofactory/engines/chatterbox_engine.py` |
| Fila SQLite / resume | ✅ pronto e testado | `src/audiofactory/store/db.py` |
| QA por ASR (CER + duração) | ✅ pronto, validado em áudio real | `src/audiofactory/qa/verify.py` |
| Política de retry melhor-de-N | ✅ pronta e testada | `src/audiofactory/qa/policy.py` |
| Pós-processamento (FFmpeg, loudnorm) | ✅ pronto, entrega −16,0 LUFS medido | `src/audiofactory/audio/process.py` |
| Orquestrador (fila → TTS → QA → disco) | ✅ pronto, resume validado | `src/audiofactory/pipeline.py` |
| Ingest TXT/EPUB + detecção de capítulos | ✅ pronto | `src/audiofactory/ingest/loader.py` |
| Projeto (project.yaml, script.json, diff.md) | ✅ pronto | `src/audiofactory/project.py` |
| CLI Typer | ✅ pronta | `src/audiofactory/cli/main.py` |
| **Pack pt-BR dedicado** | ⚠️ **em aberto — ver abaixo** | `engines/chatterbox_engine.py` |
| Camada 2 do LLM + validador | ⬜ | `src/audiofactory/narration/llm.py` |
| Subcomando `iam voice` (delega ao venv) | ⬜ | `ai-workspace/ai-stack/bin/iam` |
| Voz clonada do Moises (Fase 5) | ⬜ | gravar referência, `voices/moises-v1/` |

## Detalhes que já foram decididos e não devem ser re-litigados

- **`num2words` pt_BR insere vírgula** ("mil, seiscentos e quarenta e oito") — `_num()` remove, senão
  vira pausa espúria na narração.
- **Fragmentos curtos são fundidos ao vizinho** (`MIN_CHARS=25`) — chunk curto faz o Chatterbox
  produzir gibberish.
- **`Store.sync_script` preserva os chunks já `ok`** e apaga os órfãos: corrigir o capítulo 3 não
  regenera o livro inteiro.
- **`reset_stale()`** devolve chunks presos em `running` para a fila — é a recuperação de `kill -9`.
- **Conditionals de voz são calculados uma vez por livro** (`engine.set_voice`), nunca por capítulo —
  é o que impede a voz de derivar de identidade entre capítulos.

## Teste ponta a ponta que JÁ PASSA

```bash
cd /home/moises/dev/audio-factory
./.venv/bin/audio-factory doctor
./.venv/bin/audio-factory new bandeiras --from books/teste.txt --titulo "A História das Bandeiras"
./.venv/bin/audio-factory script bandeiras       # gera script.json + diff.md
HF_HOME=$PWD/models ./.venv/bin/audio-factory run bandeiras --no-ptbr-pack
./.venv/bin/audio-factory status bandeiras
./.venv/bin/audio-factory build bandeiras
# preencher rights: em projects/bandeiras/project.yaml, senão o export é bloqueado
./.venv/bin/audio-factory export bandeiras
```

Verificado: CER médio 0,019 · resume após `running` órfão regenera **só** o chunk morto ·
export bloqueado sem `rights:` · entregável medido em **−16,0 / −16,3 LUFS**.

## PRÓXIMO PASSO — pack pt-BR dedicado (único item em aberto do motor)

O `ResembleAI/Chatterbox-Multilingual-pt-br` **não é um checkpoint completo**. Publica só:

```
t3_pt_br.safetensors · s3gen_v3.pt · grapheme_mtl_merged_expanded_v1.json
```

Faltam `ve.pt` (voice encoder) e `conds.pt`, e os nomes divergem dos que `from_local` exige
(fixos: `t3_mtl23ls_v2.safetensors`, `s3gen.pt`, `ve.pt`).

`montar_ckpt_ptbr()` em `engines/chatterbox_engine.py` já implementa a composição por symlink
(pack + o que falta do `ResembleAI/chatterbox`), **mas ainda não rodou até o fim** — o download do
repo base é grande e foi interrompido. Retomar:

```bash
cd /home/moises/dev/audio-factory
HF_HOME=$PWD/models ./.venv/bin/python -c "
import sys; sys.path.insert(0,'src')
from audiofactory.engines.chatterbox_engine import montar_ckpt_ptbr
print(montar_ckpt_ptbr())"
HF_HOME=$PWD/models ./.venv/bin/audio-factory run bandeiras   # sem --no-ptbr-pack
```

Se o T3 refinado não casar com o s3gen/tokenizer do base, o fallback é o multilingual genérico
(`--no-ptbr-pack`), **já validado e com qualidade pt-BR aprovada em escuta**. O pack é melhoria,
não bloqueio.

## Depois disso

1. **Camada 2 do LLM** (`narration/llm.py`): resolver os `AmbiguousSpan` marcados pelo
   normalizador, via Ollama, com o validador do TDD §6.3 — só o span pode mudar, e os números da
   expansão têm de bater com o original.
2. **Fase 5 — voz própria**: gravar 60–90 s de referência, criar `voices/moises-v1/` com
   `CONSENT.md`, e passar `--voice` ao `run` (`set_voice` já congela os conditionals por livro).
3. `iam voice` em `ai-stack/bin/iam`, delegando ao venv — mesmo padrão da função `iamail()`.

## Calibrações medidas (não re-derivar)

- Whisper **`small` na CPU**: QA custa ~8% do tempo de áudio. `medium` na CPU é inviável (estourou
  10 min para 34 s de áudio). CTranslate2 exige cuBLAS 12 → **não** rodar o ASR na GPU neste venv,
  sob pena de recriar o conflito cu12/cu13.
- **A transcrição do ASR passa pelo mesmo normalizador** antes da comparação. Sem isso o Whisper
  faz a normalização inversa ("mil seiscentos e quarenta e oito" → "1648") e o CER dispara de
  0,0000 para 0,25 — falso positivo sistemático em todo número do livro.
- Limiares: CER ≤ 0,05 aceita; ≤ 0,15 aceita a melhor de N (ruído do ASR); acima, `needs_review`.
  Falha de **duração** nunca é aceita por melhor-de-N — truncamento é defeito objetivo.
- O TTS cru sai com true peak **+0,11 dBTP (clipando)**; o limiter da cadeia não é opcional.
