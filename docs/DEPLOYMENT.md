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
| `rogstools` | — | sim | **Outro projeto. Não tocar.** |

Comandos úteis:
```bash
railway status
railway logs --service ninaofertas
railway variables --service ninaofertas
railway up --service ninaofertas
```

> O Postgres não tem `DATABASE_PUBLIC_URL` nem TCP proxy — é acessível apenas de
> dentro da rede Railway. Isso é proposital. Para rodar migration ou inspecionar
> o banco, use `railway run` (injeta as vars no processo local mas **não** dá
> rota de rede ao host interno) a partir de um serviço, ou `railway ssh` com
> chave SSH configurada. Não crie URL pública para o banco.

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

A remoção das env vars migradas é o **último** passo (fase 14), depois de
confirmar em produção que o banco é a origem. Enquanto isso elas permanecem como
fallback.

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
