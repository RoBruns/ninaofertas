# ninaofertas — bot + dashboard de gestão

Operação de afiliados: um **bot** captura ofertas de Shopee e Mercado Livre,
gera link de afiliado e publica em grupos de WhatsApp. Esta branch
(`feat/dashboard`) adiciona uma **API** e um **dashboard web** para configurar e
medir a operação sem mexer no servidor: bots, contas, cookies, grupos, vendas,
despesas, métricas (ROI, ROAS, lucro) e alertas.

> **Nada desta branch está em produção.** A Railway publica a `master` de
> `RoBruns/ninaofertas`. Enquanto esta branch não for mesclada, o bot no ar
> continua exatamente como está.

---

## ⚠️ Antes de rodar qualquer coisa localmente

**Não use as credenciais reais do WhatsApp na sua máquina.** Com
`EVOLUTION_API_*` e `WHATSAPP_GROUP_ID` de produção no `.env`, o worker local
**publica nos grupos reais** — e dois processos mandando pelo mesmo número ao
mesmo tempo é o caminho mais rápido para banir o chip. Para testar o worker,
deixe essas variáveis vazias ou use uma instância/grupo de teste.

**Nunca aponte `DATABASE_URL` ou `TEST_DATABASE_URL` para o banco de produção.**
Os testes apagam o schema inteiro do banco de teste. A suíte se recusa a rodar
num banco chamado `railway`, mas não confie só nisso.

---

## Para quem já conhecia o bot: o que mudou

O comportamento do bot **não mudou**. Mudou onde as coisas estão e de onde a
configuração pode vir.

| Antes (raiz) | Agora |
|---|---|
| `main.py` | `worker/main.py` — rodar com `python -m worker.main` |
| `monitor.py`, `filters.py`, `dedup.py`, `formatter.py`, `whatsapp.py` | `worker/` |
| `scraper/` | `core/platforms/` (Shopee, ML, afiliado) e `worker/sources/` (cupons etc.) |
| `database.py` | `core/db.py` (conexão), `core/models.py` (tabelas), `core/repositories.py` (consultas) |
| `config.py` | `core/settings.py` (variáveis de ambiente) e `worker/channels.py` (canais) |
| `logger.py` | `worker/logger.py` |
| `config.json`, `config.auto.json` | continuam na raiz, lidos do mesmo jeito |

**Comando de início:** `railway.toml` e `Procfile` agora usam
`python -m worker.main`. Com o `python main.py` antigo o bot não sobe.

**Modo legado continua sendo o padrão.** O worker lê bots do banco, mas **só
sai do modo de hoje** (config.json + `WHATSAPP_GROUP_ID`) quando existe pelo
menos um bot **ativo, com telefone e grupo** cadastrados no dashboard. O seed
cria os dois canais atuais como bots **pausados**. Ou seja: depois do deploy o
bot continua publicando igual, até alguém ativar um bot pelo dashboard.

**Suas mudanças de 2026-09-23 estão integradas** (sem teto diário, baseline
desligado, dedup ignorando o "visto", falha de envio não conta no limite do
ciclo, aviso "Ciclo sem blip", desconto desconhecido não descarta, log com
fallback em `/tmp`). O `_freio_anti_ban` e os filtros são idênticos aos da
produção, com **uma** diferença decidida pelo Rodrigo:

- **`max_vendas = 0` passou a significar "sem limite"** (como os tetos diários).
  Na produção de hoje, `0` descarta todo produto com 1 venda ou mais — na
  prática quase toda a Shopee, a única fonte que informa vendas.

---

## Rodando na sua máquina

### Pré-requisitos

- **Python 3.12+** (testado em 3.12 e 3.14)
- **Node.js 24** e npm
- **PostgreSQL 16+** — o jeito mais simples é Docker:

```bash
docker run -d --name nina-pg -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:16
docker exec -it nina-pg psql -U postgres -c "CREATE DATABASE ninaofertas;"
docker exec -it nina-pg psql -U postgres -c "CREATE DATABASE ninaofertas_test;"
```

> O sistema usa tipos do Postgres (CITEXT, INET, JSONB). **Não funciona com
> SQLite**, nem em desenvolvimento, nem nos testes.

### 1. Backend (API + worker)

```bash
git checkout feat/dashboard

python -m venv venv
# Windows:        venv\Scripts\activate
# Linux / macOS:  source venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env      # Windows: copy .env.example .env
```

No `.env`, preencha pelo menos:

```bash
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/ninaofertas
JWT_SECRET=<python -c "import secrets;print(secrets.token_urlsafe(64))">
CREDENTIALS_KEY=<python -c "import base64,secrets;print(base64.b64encode(secrets.token_bytes(32)).decode())">
ADMIN_EMAIL=voce@exemplo.com
ADMIN_PASSWORD=<uma senha sua>
```

Crie as tabelas e o usuário admin:

```bash
alembic upgrade head      # cria o schema (só acrescenta; não mexe em ofertas/envios)
python -m core.seed       # plataformas, categorias, nichos, admin e os 2 canais como bots pausados
```

Suba a API:

```bash
uvicorn api.main:app --reload --port 8000
```

Documentação interativa em http://localhost:8000/api/docs.

### 2. Dashboard

```bash
cd dashboard
npm ci
npm run dev
```

Abra http://localhost:5173 e entre com `ADMIN_EMAIL` / `ADMIN_PASSWORD`. Em
desenvolvimento o Vite repassa `/api` para `localhost:8000` — suba a API antes.

Com o banco vazio, a Visão geral mostra **"sem dados"** na maioria dos cards.
É proposital: sem venda, o painel não inventa zero.

### 3. Worker (o bot)

```bash
python -m worker.main
```

Releia o aviso do topo antes. Sem `EVOLUTION_*`/`WHATSAPP_GROUP_ID`, ele captura
e filtra ofertas normalmente, loga "WhatsApp incompleto" e não publica nada.

---

## Testes

```bash
# backend: precisa de um Postgres DESCARTÁVEL
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/ninaofertas_test pytest
ruff check .

# frontend
cd dashboard
npm test
npm run typecheck
npm run lint
```

Sem `TEST_DATABASE_URL`, os testes que precisam de banco são **pulados** (com
mensagem), não falham. A suíte completa tem 116 testes de backend e 34 de
frontend.

## Mudou a API? Regenere os tipos do dashboard

O frontend não escreve tipo de payload à mão: tudo vem do contrato OpenAPI.

```bash
JWT_SECRET=x python -c "import json; from api.main import app; json.dump(app.openapi(), open('openapi.json','w',encoding='utf-8'), ensure_ascii=False, indent=1)"
cd dashboard && npm run gen:api && npm run typecheck
```

Se o typecheck quebrar, é o compilador mostrando onde o frontend precisa
acompanhar a mudança.

---

## Estrutura

```
worker/      o bot: ciclo, filtros, dedup, freio anti-ban, envio (WhatsApp)
core/        compartilhado: models, banco, plataformas, credenciais cifradas,
             métricas, alertas, sincronização de vendas
api/         FastAPI: auth, contas, bots, grupos, vendas, despesas, métricas, alertas
dashboard/   React + TypeScript + Vite
migrations/  Alembic (0001–0005, todas aditivas)
deploy/      config dos serviços novos na Railway (API e dashboard)
tests/       pytest (backend)
docs/        arquitetura, banco, API, integração com o bot, decisões, deploy
```

## Regras que protegem a produção

- **Não afrouxe o freio anti-ban** (`_freio_anti_ban` em `worker/monitor.py`).
  O dashboard já recusa ritmo perigoso (máx. 15/hora, intervalo mín. 2 min).
- **Credencial é write-only**: cookie e token entram cifrados e nenhuma rota da
  API os devolve, nem para o admin.
- **Migrations só acrescentam.** `ofertas` e `envios` ganham colunas nullable;
  nada é apagado ou alterado.
- **Sem bot ativo e completo no banco, o worker se comporta como hoje.**

## Documentação

| | |
|---|---|
| [docs/AGENT_CONTEXT.md](docs/AGENT_CONTEXT.md) | comece aqui |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | como era, como ficou e por quê |
| [docs/BOT_INTEGRATION.md](docs/BOT_INTEGRATION.md) | como dashboard e bot se falam |
| [docs/DATABASE.md](docs/DATABASE.md) | tabelas e fórmulas das métricas |
| [docs/API.md](docs/API.md) | contrato da API |
| [docs/DECISIONS.md](docs/DECISIONS.md) | decisões (ADR-001 a 019) |
| [docs/ROADMAP.md](docs/ROADMAP.md) | fases, bugs achados e o que falta |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Railway, variáveis e **plano de deploy** |

## O que ainda falta

- **Deploy** — plano passo a passo em `docs/DEPLOYMENT.md`, aguardando aprovação.
- **Vendas do ML por bot (fase 7b)** — precisa de um cookie válido, cadastrado
  pelo dashboard, para descobrir o filtro por etiqueta do painel do ML.
- **Cupons de campanha da Shopee (B1)** — `worker/sources/cupons.py` tem um
  `NameError` que faz essa fonte capturar zero cupons desde antes deste
  trabalho. Corrigir liga a fonte e muda o que chega aos grupos, então está
  aguardando decisão.
