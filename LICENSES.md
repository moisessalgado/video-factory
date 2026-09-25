# Registro de licenças — Audio Factory

Auditoria exigida pela §14 do TDD. **Nenhum peso entra no pipeline sem uma linha aqui.**
Reconferir o model card a cada atualização de versão — licença de peso pode mudar entre releases.

Última verificação: 2026-09-01.

## Pesos de TTS

| Modelo | Licença | Uso comercial | Fonte verificada |
|---|---|---|---|
| `ResembleAI/chatterbox-multilingual` (V3) | MIT | ✅ Sim | model card HF + repo oficial |
| `ResembleAI/Chatterbox-Multilingual-pt-br` | MIT | ✅ Sim | model card HF (`license: mit`) |
| `ResembleAI/chatterbox-turbo` | MIT | ✅ Sim (só inglês) | model card HF |
| `hexgrad/Kokoro-82M` | Apache-2.0 | ✅ Sim | model card HF |
| `rhasspy/piper-voices` pt_BR | MIT (verificar por voz) | 🟡 Conferir voz a voz | repo HF |

## Pesos de música

| Modelo | Licença | Uso comercial | Fonte verificada |
|---|---|---|---|
| `ACE-Step/ACE-Step-v1-3.5B` | Apache-2.0 | ✅ Sim | model card HF (`license: apache-2.0`) + `LICENSE` do repo, 2026-08-30 |
| `facebook/musicgen-stereo-large` (Meta AudioCraft) | CC-BY-NC-4.0 | ❌ Não, mas **aceito aqui** — ver ressalva abaixo | model card HF (`license: cc-by-nc-4.0`), 2026-09-01 |

Roda na venv isolada `.venv-musica` (ACE-Step) ou `.venv-musica-mg` (MusicGen), nunca no processo
do pipeline — ver `audio/_ace_runner.py` e `audio/_musicgen_runner.py`. Venvs separadas entre si
também: nenhuma razão para as duas dependerem da mesma fixação de `transformers`/`torch`.

⚠️ **MusicGen é NC — por que entra mesmo assim.** Esta tabela registrava o MusicGen como excluído
(ver histórico) porque a restrição de uso não-comercial não convivia com um canal monetizado. Em
2026-09-01 o operador confirmou que **o canal não publica comercialmente** — é público, mas sem
monetização. Sob essa condição, CC-BY-NC-4.0 permite o uso: a trilha entra como teste comparativo
ao lado do ACE-Step, não como substituição automática (`--musica musicgen`, motor explícito na
linha de comando). **Se o canal passar a monetizar, este peso sai do pipeline** — reconferir esta
linha nesse momento, junto com qualquer outro conteúdo já publicado com ele.

⚠️ **Ressalva honesta, registrada de propósito (vale para os dois modelos).** A senoide da V2 tinha
risco de Content ID *zero* — não havia gravação a que se parecer. Um modelo generativo é outra
coisa: o próprio disclaimer do ACE-Step alerta para "unintentional copyright infringement due to
stylistic similarity", e o mesmo raciocínio vale para o MusicGen. O risco real continua baixo,
porque o Content ID casa **gravações**, não estilos, e o leito aqui é instrumental esparso e sem
melodia reconhecível. Mas deixou de ser nulo, e essa é a moeda com que se paga o som melhor. Se um
vídeo levar reclamação de Content ID, trocar a paleta (ou motor, ou voltar para `--musica gerada`)
é a saída, e as peças aprovadas ficam em `assets/musica/` — é o material exato que gerou cada
trilha publicada, guardado como acervo justamente para poder ser apontado numa contestação. O
`cache/musica/` guarda o bruto de cada motor e as sobras de experimento, e é descartável.

## Trilhas de terceiro (gravações reais, não geradas)

| Arquivo | Composição | Gravações | Licença |
|---|---|---|---|
| `assets/musica-terceiros/mozart-k545-k333.flac` | Mozart, Sonatas K.545 e K.333 (domínio público, autor morto em 1791) | Robin Alciatore e Brendan Kinsella (Musopen, domínio público) + Bernd Krueger (piano-midi.de, **CC BY-SA 3.0 DE — exige atribuição**) | ver `assets/musica-terceiros/PROVENANCE.md` para a tabela faixa a faixa |

Usada via `--musica <arquivo>` (`video/musica.py:preparar_trilha`), que só repete o arquivo do
operador até cobrir a duração — nenhum modelo generativo envolvido. O aviso do próprio comando
("trilha de terceiro: confira a licença antes de publicar") existe porque, ao contrário das
trilhas geradas acima, aqui existe uma gravação real específica a que o Content ID do YouTube
pode casar. Pedida pelo operador para conteúdo infantil (ver ESTADO.md, 2026-09-15): sonata de
piano alegre e reconhecível, no lugar da trilha ambiente/contemplativa usada nos suttas.

## Pesos de imagem

| Modelo | Licença | Uso comercial | Fonte verificada |
|---|---|---|---|
| `black-forest-labs/FLUX.1-schnell` | Apache-2.0 | ✅ Sim | model card HF (`license: apache-2.0`) |
| `stabilityai/stable-diffusion-3.5-medium` | Stability AI Community License | 🟡 Sim, se receita anual < US$1M | model card HF — condição a reconferir se o canal crescer |
| `stabilityai/stable-diffusion-3.5-large` | Stability AI Community License | 🟡 Sim, se receita anual < US$1M | model card HF — condição a reconferir se o canal crescer |

Roda na venv isolada `.venv-imagem`, nunca no processo do pipeline — ver `video/_imagem_runner.py`.
**Nenhum peso é usado sem revisar o resultado**: `gerar()` só produz rascunhos descartáveis em
`cache/imagens/`; a curadoria (`imagem-aprovar`) é o operador escolhendo o que entra em
`assets/slides/`, não uma etapa automática.

Não usado para teste cujo áudio venha a ser publicado: `FLUX.1-**dev**` (licença não-comercial da
Black Forest Labs) fica fora do pipeline por esse motivo, mesmo tendo qualidade superior ao
`schnell` — decisão do operador em 2026-08-31.

## Excluídos do pipeline — pesos não-comerciais

| Modelo | Licença dos pesos | Motivo |
|---|---|---|
| F5-TTS (e todos os fine-tunes pt-br) | CC-BY-NC-4.0 | Dataset Emilia; a restrição NC é herdada por fine-tunes |
| Fish Speech / OpenAudio S1-mini | CC-BY-NC-SA-4.0 | Código Apache, pesos NC |
| XTTS-v2 (Coqui) | CPML | Não-comercial |
| IndexTTS-2 | Restritiva | Comercial exige contato com os autores |
| `black-forest-labs/FLUX.1-dev` | Não-comercial (BFL) | Melhor qualidade que o `schnell`, mas licença não permite monetização sem acordo à parte |

**Não usar nem para teste cujo áudio venha a ser publicado.**

## Software

| Item | Licença | Nota |
|---|---|---|
| `chatterbox-tts` (código) | MIT | — |
| `acestep` (código) | Apache-2.0 | Geração da trilha, em venv separada |
| `transformers` (código, MusicGen) | Apache-2.0 | Geração da trilha, em venv separada (`.venv-musica-mg`) |
| `diffusers` (código) | Apache-2.0 | Geração de imagem (FLUX/SD3.5), em venv separada |
| PyTorch | BSD-3 | wheels cu130 |
| faster-whisper / CTranslate2 | MIT | QA por ASR |
| FFmpeg | LGPL/GPL conforme build | Usado como ferramenta, não redistribuído |

## Watermark

Todo áudio do Chatterbox carrega o watermark neural **Perth** (Resemble AI), resistente a MP3.
**Política do projeto: manter sempre.** Alinha-se ao disclosure de conteúdo sintético do YouTube.

## Voz

A voz do narrador é a voz do próprio operador do canal, com `voices/<id>/CONSENT.md`.
Proibido usar áudio de terceiros como referência de clonagem sem consentimento escrito.

## Imagens do vídeo

| Item | Origem | Uso comercial | Nota |
|---|---|---|---|
| `assets/slides/*.jpg` (52) | Gerações próprias do operador no **Midjourney** (conta `moisescomsal`, 2023, plano pago) | ✅ **Confirmado** | Os Termos do Midjourney atribuem os direitos sobre a saída ao assinante pago. Confirmado pelo operador em 2026-08-31 que a conta era paga na época das gerações. |
| `assets/slides/*.jpg` (novas, a partir de 2026-08-31) | Geração local com FLUX.1-schnell / SD3.5, curadas via `imagem-aprovar` | ✅ Sim, sob as licenças da tabela "Pesos de imagem" acima | Sem terceiro envolvido — pesos rodam localmente, saída é do próprio operador |

Não há terceiro envolvido: nenhum upload de imagem alheia, nenhum banco de imagens.

## Texto

Cada projeto declara `rights:` em `project.yaml`. `export` é bloqueado sem esse campo.
Atenção ao caso mais perigoso: **traduções têm direito autoral próprio do tradutor**, com prazo
próprio — uma tradução recente de um autor antigo continua protegida.
