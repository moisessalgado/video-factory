# Suttas do Acesso ao Insight — do endereço ao vídeo

```bash
audio-factory sutta https://www.acessoaoinsight.net/sutta/ANIV.45.php.html
```

Um comando, o pipeline inteiro: baixa a página, limpa o texto, monta o
`script.json`, sintetiza com a voz do canal, masteriza, renderiza o MP4 com
trilha e legenda queimada, e sobe para o YouTube **como privado**.

Vários de uma vez, que é para o que ele existe:

```bash
audio-factory sutta ANIV.45 SNLVI.11 MN58 It.63
```

A voz é a **`narrador-v2`**: mesma `pm_alex` da `v1`, sintetizada a 0,75 da
velocidade. Ler devagar não é preferência estética — é o ritmo em que um sutta se
acompanha, e é a voz que os projetos `dhammacakka` e `satipatthana` já usam.
`--narrator narrador-v1` volta ao ritmo normal.

O endereço pode vir de três formas — a URL que você copiou do navegador, o
caminho (`sutta/ANIV.45.php.html`) ou só o código do índice (`ANIV.45`).
Um endereço que falha não derruba os seguintes; no fim o comando lista o que
deu errado e sai com status 1.

## Antes de publicar: a licença do texto

O site publica sob **"Somente para distribuição gratuita"**:

> Este trabalho pode ser impresso para distribuição gratuita. Este trabalho pode
> ser re-formatado e distribuído para uso em computadores e redes de
> computadores contanto que nenhum custo seja cobrado pela distribuição ou uso.
> De outra forma todos os direitos estão reservados.

Duas consequências práticas, e nenhuma delas é a ferramenta que decide:

1. **Monetizar estes vídeos vai contra os termos.** "Nenhum custo cobrado pela
   distribuição ou uso" é explícito. O comando avisa isso em toda execução que
   inclui a etapa de publicação; ele não bloqueia nada (ESTADO.md: `rights` é
   registro, não autorização).
2. **`rights.status` fica `licenciado`, não `dominio-publico`.** O sutta é
   antigo; a *tradução* é obra derivada com direito próprio do tradutor — é o
   risco alto da tabela do TDD §14.3. Declarar domínio público aqui seria falso.

A procedência é colhida da própria página e gravada no `project.yaml`, e a
descrição do vídeo reproduz os termos literalmente:

```yaml
rights:
  status: licenciado
  autor: Cânone Páli
  tradutor: Acesso ao Insight (Michael Beisert, editor)
  fonte: Anguttara Nikaya IV.45 — https://www.acessoaoinsight.net/sutta/ANIV.45.php.html
  licenca: Somente para distribuição gratuita. (...)
  verificado_em: null      # data de download não é data de conferência
```

`verificado_em` fica vazio de propósito: quem verifica direitos é uma pessoa.

## Parar antes do fim

`--ate` corta a fila em qualquer etapa. A ordem é
`texto → script → audio → video → publicar`.

```bash
audio-factory sutta ANIV.45 --ate script     # para para você ler o diff.md
audio-factory sutta ANIV.45 --ate video      # gera o MP4, não publica
```

`--ate script` é o corte que o TDD pede: nada vai ao TTS sem o diff em disco.

## Retomar

Rodar o mesmo comando de novo **retoma** — é assim que se recupera um lote
interrompido. Cada etapa sabe o que já está pronto:

| Etapa | Ao repetir |
|---|---|
| texto | relê a página do cache em `cache/acessoaoinsight/` |
| projeto | **preserva** o `project.yaml` existente — é onde você escreve `cast:` |
| script | refaz (barato); `sync()` preserva os chunks já `ok` |
| áudio | retoma a fila; só o que falta é sintetizado |
| vídeo | pula se já há MP4 em `output/` |
| publicar | **recusa** se já há `output/publicado.json` |

`--refazer` desfaz tudo isso: baixa a página de novo, reescreve o
`project.yaml` e re-renderiza o MP4.

A recusa de republicar não é zelo: `videos.insert` não é idempotente. Um
segundo upload cria **outro** vídeo no canal em vez de atualizar o primeiro, e
este comando existe justamente para ser re-rodado. Use `--republicar` para
subir outra cópia de propósito.

## Chunks em revisão param o sutta

Se a QA mandar algum chunk para `needs_review`, o comando para naquele sutta com
a mensagem e segue para o próximo — `build` recusa capítulo incompleto, e
continuar só daria um erro pior lá na frente. Ouça e resolva:

```bash
audio-factory review aniv45-rohitassa                      # lista e mostra o wav
audio-factory review aniv45-rohitassa --aprovar ch01/00007-…
audio-factory sutta ANIV.45                                # retoma daí
```

## Publicar como público

O padrão é `private`, porque vídeo privado se desfaz apagando e vídeo público já
foi visto. Para os outros modos o comando pergunta antes:

```bash
audio-factory sutta ANIV.45 --privacidade unlisted
audio-factory sutta ANIV.45 --privacidade public --sim     # sem perguntar
```

As credenciais OAuth são as mesmas de sempre — veja
[`youtube-publish.md`](youtube-publish.md).

## O que a ferramenta faz com a página

A página é HTML exportado do Word, servido com `charset=ISO-8859-1` que **não é
verdade** (é windows-1252 — as aspas curvas do Word são caracteres de controle
em latin-1). A estrutura, medida em 40 páginas sorteadas do índice, é regular:
um `<p class=Tit3>` com a referência da coleção, dois `<p class=Tit1>` com o
nome em pali e o título em português, o bloco da licença, e o corpo entre o
primeiro e o último `<hr>`.

Fica **de fora** do que é narrado: notas de rodapé, "Veja também",
">> Próximo Sutta", os marcadores `[1]` no corpo e a numeração de parágrafo das
edições (`1. Assim ouvi.` — narrada, viraria "um. Assim ouvi.").

Fica de fora também a **referência da coleção**, e por medição: o normalizador
transforma "Anguttara Nikaya IV.45" em "Anguttara Nikaya IVquarenta e cinco".
Ela vive no título do vídeo e na descrição, que ninguém lê em voz alta.

O título do projeto sai como `Rohitassa Sutta — Anguttara Nikaya IV.45`. O
travessão não é enfeite: `_nome_de_arquivo` corta ali, e o MP4 fica com o nome
em pali, curto o bastante para o player não atravessar a legenda queimada.

## Endereço que não existe

O servidor devolve **HTTP 200** com uma página de busca genérica para qualquer
endereço inválido. O comando detecta isso pela ausência do marcador
`INICIO DO TEXTO` e falha com a mensagem — sem essa guarda, um código errado
criaria um projeto vazio e só quebraria no `export`, depois da síntese.

O índice completo está em
<https://www.acessoaoinsight.net/sutta/indice_suttas.php.html>.
