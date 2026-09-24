# Deploy e operação

## Railway

Projeto `gallant-emotion` · ID `0655e0f9-0ad1-49b8-b08f-0c7baad584fa` ·
ambiente `production` · região US East.

| Serviço | Tipo | Público | Papel |
|---|---|---|---|
| `ninaofertas` | worker Python | não | O bot |
| `nina-api` | FastAPI | **sim** | API do dashboard (a criar) |
| `nina-dashboard` | estático | **sim** | Frontend (a criar) |
| `evolution-api` | imagem | sim | WhatsApp · volume 4.9 GB |
| `Postgres` | banco | **não** | Dados. Sem URL pública — manter assim |
| `Redis` | banco | não | Cache da `evolution-api` (`CACHE_REDIS_URI`, db 6). Adicionado em 2026-09-23; o bot não usa |
| `rogstools` | — | sim | **Outro projeto. Não tocar.** |

Comandos úteis:
```bash
railway status
railway logs --service ninaofertas
railway variables --service ninaofertas
railway up --service ninaofertas
```

> O Postgres não tem `DATABASE_PUBLIC_URL` nem TCP proxy — é acessível apenas de
> dentro da rede Railway. Isso é proposital: **não crie URL pública para o banco.**

### Como acessar o banco a partir da máquina local

`railway run` **não serve** para isso: injeta as variáveis mas executa o processo
localmente, então `postgres.railway.internal` não resolve. O caminho que funciona
é o túnel SSH:

```bash
# uma vez, se ainda não houver chave registrada:
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N ""
railway ssh keys add --key 'C:\Users\<voce>\.ssh\id_ed25519.pub' --name minha-chave

# abre o túnel (não imprime nada; segura o terminal até Ctrl+C):
railway connect Postgres --tunnel-only --port 55432

# em outro terminal:
export PGPASS=$(railway variables --service Postgres --kv | grep '^POSTGRES_PASSWORD=' | cut -d= -f2-)
export DATABASE_URL="postgresql://postgres:${PGPASS}@127.0.0.1:55432/railway"
```

Dois detalhes que custam tempo: o CLI espera **caminho no formato Windows** em
`--key`, e `railway connect` passa o nome do serviço como **argumento posicional**
(`railway connect Postgres`, não `--service Postgres`).

Revogar a chave depois: `railway ssh keys remove`.

## Variáveis de ambiente

### `ninaofertas` (worker)

Hoje: `CHECK_INTERVAL` · `DATABASE_URL` · `EVOLUTION_API_URL` ·
`EVOLUTION_API_KEY` · `EVOLUTION_INSTANCE` · `WHATSAPP_GROUP_ID` ·
`WHATSAPP_GROUP_ID_AUTO` · `REENVIO_QUEDA_MINIMA` · `MERCADOLIVRE_APP_ID` ·
`MERCADOLIVRE_APP_SECRET` · `MERCADOLIVRE_AFFILIATE_TAG` ·
`MERCADOLIVRE_AFFILIATE_COOKIE` · `SHOPEE_APP_ID` · `SHOPEE_APP_SECRET` ·
`LOG_LEVEL`

Classificação para a migração:

| Variável | Destino |
|---|---|
| `DATABASE_URL`, `LOG_LEVEL` | **fica** — infraestrutura |
| `EVOLUTION_API_URL`, `EVOLUTION_API_KEY` | **fica** — infra + segredo de serviço |
| `CHECK_INTERVAL`, `REENVIO_QUEDA_MINIMA` | → `bots.settings` |
| `WHATSAPP_GROUP_ID`, `..._AUTO` | → `groups` + `bot_groups` |
| `EVOLUTION_INSTANCE` | → `phones.evolution_instance` |
| `*_APP_ID`, `*_APP_SECRET`, `*_COOKIE`, `*_TAG` | → `platform_credentials` (cifrado) e `platform_accounts.config` |

O worker novo **não lê** as variáveis migradas (ADR-020): o dashboard é a única
origem. Elas continuam no serviço só enquanto o rollback para o código antigo for
possível, e são removidas no último passo do deploy.

### `nina-api` (novo)

```
DATABASE_URL          ${{Postgres.DATABASE_URL}}
CREDENTIALS_KEY       # 32 bytes base64 — cifra platform_credentials
JWT_SECRET            # 64 bytes aleatórios
WORKER_TOKEN          # autentica /api/internal/*
CORS_ORIGINS          https://<dashboard>.up.railway.app
EVOLUTION_API_URL     http://evolution-api.railway.internal:8080
EVOLUTION_API_KEY     ${{evolution-api.AUTHENTICATION_API_KEY}}
LOG_LEVEL             INFO
```

Gerar:
```bash
python -c "import secrets,base64;print(base64.b64encode(secrets.token_bytes(32)).decode())"  # CREDENTIALS_KEY
python -c "import secrets;print(secrets.token_urlsafe(64))"                                   # JWT_SECRET / WORKER_TOKEN
```

**Guarde `CREDENTIALS_KEY` fora da Railway também** (gerenciador de senhas).
Perdê-la torna ilegível toda credencial cifrada — elas teriam de ser recolocadas
uma a uma.

### `nina-dashboard`

```
VITE_API_URL          https://<api>.up.railway.app/api
```

Só isso. **Nenhum segredo entra no bundle do frontend** — tudo em `VITE_*` é
público para quem abrir o DevTools.

## Migrations

```bash
railway run --service nina-api alembic upgrade head
```

Antes de qualquer migration que altere tabela existente:
```bash
railway run --service nina-api pg_dump "$DATABASE_URL" -Fc -f backup-$(date +%F).dump
```

Regras: `ofertas` e `envios` só recebem coluna nullable · nenhuma migration dropa
coluna delas · toda migration tem `downgrade` testado · migration roda antes do
deploy do código que a usa.

## Deploy

Ordem em release que cruza camadas: **migration → API → worker → dashboard**.
O worker é o último entre os backends porque é o que está no ar; se a API subir
quebrada, o bot continua publicando.

Rollback: `railway redeploy` do deployment anterior do serviço. Como as
migrations são aditivas, a versão antiga do código convive com o schema novo.

## Backup

`pg_dump` diário do Postgres (job na Railway ou cron externo), retenção 7 dias.
Testar a restauração uma vez — backup não verificado não é backup.

O volume da `evolution-api` (`/evolution/instances`) guarda a sessão do WhatsApp.
**Perder esse volume significa reparear o número por QR Code** — e o WhatsApp
aplica cooldown de segurança quando há muitas tentativas seguidas (já aconteceu
neste projeto, registrado em `STATUS.md`). Não recriar o serviço sem necessidade.

## Saúde

```bash
curl https://<api>.up.railway.app/api/health
railway logs --service ninaofertas | tail -50
```

`/api/health` devolve estado de banco, evolution-api e último heartbeat do
worker. Alerta de `bot_offline` dispara com 3 intervalos sem heartbeat.

---

## Plano de deploy — fase 14 (a executar só com aprovação do usuário)

### Fatos que o plano respeita

- A Railway publica o bot a partir de **`RoBruns/ninaofertas`, branch `master`**
  (remoto local `producao`). O `origin` local (`DiegoMiuraDev/ninaofertas`) fica
  atrás da produção. Outro desenvolvedor faz commit direto na `master` de produção.
- O `railway.toml` da raiz vale para **todo serviço criado do repositório**. Se a
  API fosse criada do mesmo repo sem config própria, herdaria
  `startCommand = "python -m worker.main"` e subiria **um segundo bot** no mesmo
  número — risco de ban. Cada serviço novo usa um arquivo de config próprio
  (config-as-code por serviço na Railway).
- **Não há modo legado** (ADR-020): o worker novo só publica bots ativos no
  dashboard. O worker **antigo** ignora a tabela `bots`, então os bots podem ser
  configurados e ativados no dashboard enquanto ele ainda roda — é isso que evita
  uma janela sem envio na troca.

### Arquitetura de publicação

```
navegador ──HTTPS──► nina-dashboard (Caddy: SPA estática + proxy /api)
                          │  rede interna
                          ▼
                     nina-api (uvicorn, SEM domínio público)
                          │
                     Postgres (interno) ◄── ninaofertas (worker)
```

O dashboard serve os arquivos e faz proxy de `/api` para a API pela rede interna.
Para o navegador é **uma origem só**: sem CORS, e o cookie de sessão
(`SameSite=Strict`, `path=/api/auth`) funciona sem ajuste. A API **não tem domínio
público** — só é alcançável pelo proxy.

### Sequência

| # | Passo | Reversível? |
|---|---|---|
| 0 | `git fetch producao`: se houver commit novo na produção, integrar antes | — |
| 1 | `pg_dump` do banco de produção, guardado fora da Railway | — |
| 2 | Criar `nina-api` e `nina-dashboard` (sem tráfego ainda), com config própria | apagar serviço |
| 3 | Variáveis da API: `JWT_SECRET`, `CREDENTIALS_KEY`, `WORKER_TOKEN` gerados; `DATABASE_URL` e `EVOLUTION_*` por referência. `ADMIN_EMAIL`/`ADMIN_PASSWORD` **definidos pelo usuário** (a senha não passa pela conversa) | trocar valor |
| 4 | `alembic upgrade head` no banco de produção (só aditivo; `ofertas`/`envios` ganham colunas nullable) e `python -m core.seed` (bots pausados) | downgrade testado; backup do passo 1 |
| 5 | Subir API e dashboard; checar `/api/health`, login, telas | redeploy anterior |
| 6 | No dashboard de produção: contas (Shopee: App ID + App Secret; ML: etiqueta + cookie), telefone com a instância `ofertas-bot`, grupos (sincronizar), e nos bots do seed: vincular telefone, grupos e contas, conferir o ritmo e **ativar**. O worker antigo segue publicando e ignora isso | pausar o bot |
| 7 | Merge de `feat/dashboard` na `master` de produção → a Railway republica o worker com `python -m worker.main`, que passa a publicar pelos bots ativos | redeploy do deployment anterior do worker |
| 8 | Conferir no log do worker: bots e grupos esperados, nenhum aviso "sem conta"; envios com `bot_id` na primeira hora | — |
| 9 | Rodar a suíte **dentro da Railway** (sem túnel) com `METRICS_LATENCY_CHECK=1`, e refazer a verificação V5 | — |
| 10 | Estável: remover do worker as variáveis migradas (`EVOLUTION_INSTANCE`, `WHATSAPP_GROUP_ID*`, `SHOPEE_*`, `MERCADOLIVRE_*`) | recriar as variáveis |

### Rollback

Migrations aditivas: o código antigo do worker roda sobre o schema novo. Se o
worker novo se comportar mal, `railway redeploy` do deployment anterior devolve
o comportamento de hoje sem tocar no banco — por isso as variáveis antigas só
saem no passo 10. Pausar todos os bots no dashboard **para** a publicação; não
há mais volta automática ao legado (ADR-020).
