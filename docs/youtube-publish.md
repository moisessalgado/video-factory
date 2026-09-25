# Publicar no YouTube — configuração das credenciais

O comando `audio-factory publish <slug>` sobe o MP4 do projeto usando a YouTube
Data API v3. A ferramenta só sobe o vídeo e preenche os metadados que já estão no
`project.yaml` — a decisão do que e quando publicar continua com você, por isso o
padrão é sempre subir como **privado** (`--privacidade unlisted` ou `public` só se
você pedir explicitamente).

Isso exige um client OAuth próprio no Google Cloud. É um cadastro que só você
consegue fazer (precisa da sua conta Google logada num navegador); depois disso o
comando cuida do resto sozinho.

## 1. Criar o projeto no Google Cloud

1. Acesse https://console.cloud.google.com/ e crie um projeto novo (ou reuse um
   que já tenha), ex.: "audio-factory-youtube".
2. No menu, vá em **APIs e serviços → Biblioteca**, procure **YouTube Data API
   v3** e clique em **Ativar**.

## 2. Configurar a tela de consentimento OAuth

1. **APIs e serviços → Tela de permissão OAuth**.
2. Tipo de usuário: **Externo** (a menos que você tenha Google Workspace).
3. Preencha nome do app, e-mail de suporte e e-mail de contato do
   desenvolvedor — pode ser o seu.
4. Em **Escopos**, não precisa adicionar nada manualmente aqui (o escopo é
   pedido em tempo de execução pelo próprio comando).
5. Em **Usuários de teste**, adicione a conta Google do canal (o app fica em
   modo "Teste", o que é suficiente — não precisa passar pela verificação do
   Google para uso pessoal).

## 3. Criar as credenciais (client OAuth)

1. **APIs e serviços → Credenciais → Criar credenciais → ID do cliente OAuth**.
2. Tipo de aplicativo: **App para computador** ("Desktop app").
3. Dê um nome e clique em **Criar**.
4. Baixe o JSON (botão de download ao lado da credencial criada).

## 4. Instalar o arquivo no projeto

Salve o JSON baixado como:

```
config/youtube_client_secret.json
```

Esse arquivo (e o `config/youtube_token.json` gerado depois) já está no
`.gitignore` — nunca serão versionados.

## 5. Primeiro uso: autorizar no navegador

Na primeira chamada a `audio-factory publish <slug>`, o comando abre uma aba do
navegador pedindo para você logar com a conta do canal e autorizar o escopo
`youtube.upload`. Depois disso ele salva um token de longa duração em
`config/youtube_token.json` e não pede login de novo (renova sozinho até você
revogar o acesso em https://myaccount.google.com/permissions).

## Uso

```bash
audio-factory publish dhammacakka
audio-factory publish dhammacakka --privacidade unlisted --tags "budismo,pali,dhamma"
```

O comando recusa subir se `rights.status` estiver vazio, `PREENCHER` ou contiver
"TESTE" / "NAO-PUBLICAR" — use `--forcar` só depois de conferir manualmente que é
isso mesmo que você quer.

## Branding do canal (`audio-factory canal`) — SEO

Descrição, palavras-chave e banner do canal usam `channels.update` e
`channelBanners.insert`, que **não** cabem no escopo `youtube.upload` de cima —
esse token é intencionalmente restrito ao upload, para o pipeline automático
(`sutta`/`publish`) nunca ter acesso de mais. O comando `canal` usa um escopo
próprio (`.../auth/youtube`) e um **token separado**,
`config/youtube_canal_token.json` — não mexe no `youtube_token.json` do upload.

O `client_secret.json` é o mesmo (mesmo app OAuth); na primeira chamada de
`canal ...` o navegador abre de novo, pedindo consentimento para o escopo maior.

```bash
audio-factory canal mostrar                    # descrição/keywords/país atuais
audio-factory canal atualizar --descricao descricao-canal.txt \
    --keywords "budismo,dhamma,suttas,cânone páli,acesso ao insight" --pais BR
audio-factory canal banner arte-capa.png        # arte de capa, 2560×1440 recomendado
```

`canal atualizar` busca o estado atual do canal antes de gravar: só troca o que
você passar na linha de comando, o resto fica como estava (`channels.update`
substitui o recurso inteiro por `part`, então gravar sem isso apagaria campos
não mencionados).

**A foto de perfil (logo) do canal não tem endpoint na Data API v3** — é atributo
da Conta/Marca Google, não do canal. Só se troca à mão em
https://studio.youtube.com (ou na própria Conta Google, se o canal usa a foto
dela).
