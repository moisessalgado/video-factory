# Estado da implementação

Documento de handoff. **Leia primeiro [`docs/TDD.md`](docs/TDD.md)** — é o design aprovado e a
justificativa de cada decisão. Este arquivo diz só onde a implementação parou.

Atualizado: 2026-08-30.

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
| **Pack pt-BR dedicado** | ✅ **resolvido — é o padrão** | `engines/chatterbox_engine.py` |
| Camada 2 do LLM + validador | ✅ pronta, testada com gemma4:12b real | `src/audiofactory/narration/llm.py` |
| Subcomando `iam voice` | ✅ pronto | `ai-workspace/ai-stack/bin/iam` (`cmd_voice`) |
| Registry de vozes (Fase 5) | ✅ código pronto e validado | `src/audiofactory/voices.py` |
| **Multivoz (elenco por papel)** | ✅ pronto e validado | `src/audiofactory/text/roles.py` |
| Voz template do canal | ✅ `narrador-v1` registrada e em uso | `voices/narrador-v1/` |
| Motor Kokoro (rascunho/template) | ✅ instalado e funcionando | `iam voice voice template` |
| Checagem de identidade da voz | ✅ pronta e validada contra impostores | `src/audiofactory/qa/speaker.py` |
| Gravar a voz do Moises | ⏸️ adiado — melhoria de autenticidade, não bloqueio | `iam voice voice record` |

## Fase 6 — CONCLUÍDA ✅

| Entrega | Estado | Arquivo |
|---|---|---|
| Ingest de **PDF** (por blocos, sem OCR) | ✅ pronto e testado | `src/audiofactory/ingest/loader.py` |
| `chapters.txt` + arquivo único contínuo | ✅ pronto | `cli/main.py` (`export`) |
| Export multi-formato (`--formato mp3,aac`) | ✅ pronto | `cli/main.py` |
| Relatório de QA contra os alvos do TDD | ✅ pronto | `src/audiofactory/qa/report.py` |
| 2 workers na GPU | ✅ pronto, **ganho medido de 1,25×** | `pipeline.py` (`_repartir`) |
| `--free-ollama` | ✅ pronto | `cli/main.py` (`_liberar_ollama`) |
| Histórico de execuções (tabela `runs`) | ✅ pronto — é o RTF de relógio | `store/db.py` |
| Testes automatizados da fase | ✅ 19 testes | `tests/test_fase6.py` |

### PDF: extração por BLOCOS, não por linhas

`ler_pdf()` usa `page.get_text("blocks")`. Reconstruir parágrafo a partir de
pontuação erra sempre que uma frase termina no meio do parágrafo — e num PDF cada
linha visual é uma quebra. O bloco do PyMuPDF já é, na prática, o parágrafo.

Cabeçalho e rodapé saem por repetição: um bloco curto (≤ 80 chars) na borda da
página que aparece em ≥ 30% das páginas é descartado. A chave de comparação apaga
os dígitos, senão "Página 12" e "Página 13" nunca casariam.

**Guarda que um teste obrigou a existir:** só entram na contagem páginas com ≥ 3
blocos, e a janela de borda encolhe para 1 bloco em páginas curtas. Sem isso, numa
página de dois blocos *todo* bloco é borda — e como a chave apaga dígitos, o corpo
do livro ("Único parágrafo da página 3.") seria descartado como rodapé.

PDF escaneado é **recusado com erro claro**: OCR está fora do escopo (TDD §17), e
um OCR silencioso entregaria lixo ao TTS.

### 2 workers: ganho real de 1,25×, não de 2×

Medido em 46 chunks / 12,4 min de áudio, com QA ligada:

| | 1 worker | 2 workers |
|---|---|---|
| Relógio de parede | 305 s | **244 s** |
| RTF (parede/áudio) | 0,407 | **0,324** |
| VRAM de pico | 6,6 GB | **10,5 GB** de 16 |

**Não é 2×** porque o ASR de QA roda na CPU e a GPU já estava bem ocupada com um
worker. E **em carga pequena 2 workers é mais LENTO**: em 9 chunks deu 48 s contra
36 s de 1 worker — cada worker carrega o seu próprio modelo, e dois carregamentos
não se pagam em 50 s de áudio. Regra prática: `--workers 2` só a partir de alguns
minutos de áudio pendente.

Cada worker tem modelo, ASR e conexão SQLite próprios. Modelo próprio é
obrigatório: `set_voice` guarda os conditionals **dentro** do modelo, e dois
workers compartilhando um trocariam a voz um do outro no meio do lote.
`_repartir()` dá a cada worker fatias contíguas de cada voz, para que `set_voice`
seja chamado uma vez por voz, não uma vez por chunk.

### RTF passou a ser medido pelo relógio de parede

A tabela `runs` (que existia no schema e nunca era usada) agora registra cada
execução. O RTF do relatório é `parede / áudio` somado sobre as execuções, e
**inclui a carga do modelo** — é o tempo que o operador espera de verdade. A soma
de `gen_s` por chunk não serve: com 2 workers ela conta o mesmo intervalo duas
vezes.

### Identidade da voz entrou no melhor-de-N

**Era um furo real:** a similaridade de voz era medida *depois* de escolher a
melhor tentativa, então um chunk que só falhava na voz ia direto para
`needs_review` sem que outra seed fosse tentada. Medido no teste do PDF: um chunk
deu 0,879 (limiar 0,88) e passou com folga na seed seguinte.

Agora a similaridade é medida **por tentativa**, dentro de `_gerar_com_qa`, e
entra em `deve_repetir`/`escolher` como qualquer outro defeito. Reprovar por voz
só acontece se **nenhuma** das 3 tentativas bater o limiar.

### Loudness: o `loudnorm` sozinho não chega ao alvo

Os masters saíam a **−16,4 / −16,5 LUFS**, na borda da tolerância de ±0,5 do TDD.
Investigado filtro a filtro: **não é o limiter nem os fades** — é o próprio
`loudnorm`. Quando o ganho necessário estouraria o true peak alvo (aqui: +8,8 dB
sobre um material de −4,1 dBTP), ele abandona o modo linear e cai no dinâmico
(`normalization_type: dynamic` na medição), e o resultado fica sistematicamente
~0,5 LUFS abaixo mesmo com o `target_offset` aplicado.

`_corrigir_ganho()` mede o master e corrige o resíduo com ganho linear (`volume`),
com o limiter depois só como guarda de true peak. Ganho linear não altera
dinâmica, então é seguro. **Medido depois da correção: −16,10 e −16,14 LUFS, TP
−1,44.** O limiter também passou de −1,0 para `TP_ALVO` (−1,5), que era a
inconsistência que sobrava na cadeia.

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
./.venv/bin/audio-factory export bandeiras
```

Verificado: CER médio 0,019 · resume após `running` órfão regenera **só** o chunk morto ·
entregável medido em **−16,0 / −16,3 LUFS**.

**Ponta a ponta a partir de PDF** (Fase 6), verificado em 30/08/2026:

```bash
./.venv/bin/audio-factory new pdfteste --from livro.pdf --narrator narrador-v1
./.venv/bin/audio-factory script pdfteste
HF_HOME=$PWD/models ./.venv/bin/audio-factory run pdfteste --workers 2 --free-ollama
./.venv/bin/audio-factory build pdfteste
./.venv/bin/audio-factory export pdfteste --formato mp3,aac   # + chapters.txt
./.venv/bin/audio-factory report pdfteste
./.venv/bin/python -m pytest tests/ -q                        # 19 passam
```

Resultado: 9/9 chunks ok · CER médio 0,0048 · identidade de voz 0,928 (pior 0,886)
· masters a **−16,10 / −16,14 LUFS**, TP −1,44 · `chapters.txt` com carimbos
cumulativos + `pdfteste-completo.mp3`.

`report` sai com **status 1** se alguma métrica ficar fora do alvo — dá para usar
como portão antes de publicar.

## Pack pt-BR — RESOLVIDO (é o padrão do motor)

O `ResembleAI/Chatterbox-Multilingual-pt-br` não é um checkpoint completo: publica só
`t3_pt_br.safetensors`, `s3gen_v3.pt` e o tokenizer. `montar_ckpt_ptbr()` compõe por symlink
um diretório com os nomes fixos que `from_local` exige, pegando do pack o que existe e do
`ResembleAI/chatterbox` o que falta (`ve.pt`, `conds.pt`, `Cangjie5_TC.json`, `s3gen.pt`).

Duas armadilhas já resolvidas, **não repita**:
1. `snapshot_download` **sem `allow_patterns` puxa o repo inteiro** (vários GB de variantes
   inúteis) e demora minutos. Use sempre a lista de arquivos.
2. O `s3gen_v3.pt` do pack é de uma versão mais nova da lib e falha com
   `Missing key(s): tokenizer._mel_filters, tokenizer.window`. **O vocoder vem do base** — o
   refinamento pt-BR está no T3, e o s3gen é agnóstico ao idioma.

**Ganho medido** (mesmos 5 chunks, mesma seed, QA com whisper small):

| | genérico | pack pt-BR |
|---|---|---|
| CER médio | 0,0274 | **0,0125** (2,2× melhor) |
| RTF | 0,291 | 0,305 |
| VRAM | 3,49 GB | 3,49 GB |

O chunk que eu havia atribuído a ruído do ASR era defeito real do genérico: ele produzia
"Ou que os homens retornaram" onde o pack produz "Poucos homens retornaram". O custo é ~5% de
RTF. Padrão do motor: `use_ptbr_pack=True`; `--no-ptbr-pack` desliga.

## Voz do canal — `narrador-v1` (template, em uso)

Decisão do usuário: usar uma voz template por enquanto; a voz própria fica como
melhoria de autenticidade mais adiante.

A voz em uso é o **Chatterbox clonando uma referência sintetizada pelo Kokoro
(`pm_alex`, Apache-2.0)**. Escolhida em teste cego entre 5 candidatas. O motivo de não
usar o Kokoro direto como motor: assim o motor continua sendo o Chatterbox, e trocar
pela voz real do Moises depois é só registrar outra voz — sem mudar engine, sem
reprocessar nada além do áudio.

`voices/narrador-v1/` tem `PROVENANCE.md` (voz sintética não tem consentimento a
colher, mas tem procedência a documentar) e o hash SHA-256 da referência.

**Para trocar pela voz real depois:**
```bash
iam voice voice record                 # instruções + texto de calibração
iam voice voice new moises-v1 --reference take2.wav
# depois, em cada project.yaml: narrator: moises-v1
```

## Identidade da voz — limiar calibrado com medição própria

`qa/speaker.py` compara cada chunk com a referência usando o voice encoder do próprio
Chatterbox. Medido com a `narrador-v1` (6 chunks, 3 capítulos):

| | similaridade |
|---|---|
| mesma voz (6 chunks, 3 capítulos) | 0,917 – 0,960 |
| voz feminina diferente | 0,833 |
| outra voz masculina (kokoro pm_santa) | 0,823 |
| voz embutida do Chatterbox | 0,679 |

**Limiar 0,88**, no meio do vão. Um chunk abaixo disso vai para `needs_review` mesmo
com CER perfeito — o CER garante que o texto está certo, não que a voz é a mesma.

## Multivoz — elenco por papel

`project.yaml` ganha `cast:` mapeando papel → voice_id. O papel `narrador` é o padrão;
`citacao` (fala entre aspas) é detectado automaticamente; marcação explícita
`[[voz:personagem_a]]` no texto permite elenco nominal.

```yaml
narrator: narrador-v1
cast:
  citacao: citacao-v1
```

Três decisões que o teste real impôs:

1. **Síntese agrupada por voz.** Preparar conditionals custa segundos; alternar voz a
   cada fala pagaria isso milhares de vezes. O pipeline ordena por `voice_id`, e a ordem
   de narração é restaurada na montagem do capítulo (que lê do banco).
2. **`MIN_SINTETIZAVEL = 25`.** Se a divisão por papel produzir qualquer caco menor que
   isso, a divisão inteira é abandonada e o parágrafo vira narração. Motivo medido:
   "respondeu o diabo." (18 chars) saiu a **5,8 c/s** contra 14–17 c/s do normal — o
   modelo arrasta o áudio. Diálogo picado (fala curta / atribuição curta / fala curta)
   **não** sobrevive à troca de voz; lido inteiro pelo narrador fica correto, só menos
   teatral. Citação longa mantém voz própria.
3. **Checagem de identidade por voz.** Cada papel é comparado com a *sua* referência.
   Verificado: chunk de citação deu 0,955 contra `citacao-v1` (contra a do narrador daria
   ~0,83, e seria barrado indevidamente).

O `chunk_id` embute a voz: trocar a voz de um papel invalida só os chunks daquele papel.

## `rights` é registro, não autorização

**Decisão do operador (2026-08-30): o export não é bloqueado por `rights.status`.**
O campo continua no `project.yaml` como registro de procedência — útil para o próprio
histórico e para os metadados —, e o `export` apenas ecoa o valor declarado.

A decisão editorial sobre o que publicar é do operador do canal, não da ferramenta.
**Não reintroduza um gate aqui** sem que ele peça: já foi removido deliberadamente.

`RIGHTS_CONHECIDOS` em `project.py` lista só os valores convencionais, para consulta.

## Depois disso

1. **Primeiro livro real** de domínio público, ponta a ponta, com a `narrador-v1`.
   É o único item que falta do MVP — o pipeline está completo.
2. **V2**: música/trilha com ducking no Chapter Builder.
3. **UI de revisão** (TDD §18, Fase 7): só se `needs_review` virar gargalo real.

### Krishnamurti: o teste rodou só com um trecho

`projects/krishnamurti/` foi gerado a partir de `books/krishnamurti-trecho.txt`,
que tem **1 KB** — três parágrafos, escolhidos para testar multivoz. O `ch01.mp3`
que está em `output/` é esse trecho, e é por isso que soa incompleto: **o texto é
que está incompleto**, não o pipeline. Para o discurso inteiro basta substituir a
fonte e rodar de novo; o `rights:` do projeto registra que a tradução é do site da
KF e o status é `TESTE-LOCAL-NAO-PUBLICAR`.

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
- **Pack pt-BR: CER 0,0125 vs 0,0274 do genérico** (2,2× melhor), mesmo VRAM, +5% de RTF.
  É o padrão; `--no-ptbr-pack` desliga.
- **Camada 2 (LLM)**: `gemma4:12b` gasta ~230 tokens raciocinando antes de responder —
  `num_predict` precisa ser ≥600, senão devolve string vazia com `done_reason: length`.
  Ela roda **antes** das regras (sobre o texto cru), senão os offsets ficam obsoletos.
  A chave do cache inclui a palavra anterior: sem isso "Elizabeth II"→"Segunda"
  contaminaria "Dom Pedro II"→"Segundo". Valor real da camada: concordância de gênero.
