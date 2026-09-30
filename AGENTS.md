# AGENTS.md — ninaofertas

Contexto para qualquer agente (Codex, Claude, Cursor) ou pessoa que vá mexer neste
repositório. Leia inteiro antes de tocar em código. Se algo aqui contradisser o código,
o código vence — e corrija este arquivo.

## O que é

Operação de marketing de afiliados. Um worker Python captura ofertas da **Shopee** e do
**Mercado Livre**, filtra por nicho, gera link de afiliado e publica em **grupos de
WhatsApp** pela evolution-api. Uma **API FastAPI** e um **dashboard React** configuram e
medem a operação: bots, telefones, grupos, contas de afiliado, filtros, ritmo, vendas,
despesas e alertas.

- **V2 (este `master`)** = bot + API + dashboard. É o bot principal, em produção desde
  2026-09-30. Grupo de produção: *Achadinhos da Vó Nina*.
- **V1** = bot antigo sem dashboard, **descontinuado**. Está no branch `v1-legado`; o
  serviço dele na Railway (`ninaofertas`) está desligado. Não desenvolva na V1.

## Regra número um

**O bot publica em grupos reais.** Perder o número do WhatsApp por banimento é perder os
grupos. Toda mudança precisa manter o envio funcionando; se ela pode derrubar o envio,
pare e sinalize.

Nunca:
- afrouxe o freio anti-ban (`worker/monitor.py::_freio_anti_ban`, limites em
  `core/safety.py`) — só por decisão explícita do dono, registrada em ADR;
- exponha cookie, token, secret ou senha em resposta da API, log, evento ou frontend
  (credenciais são **só escrita**; a API devolve apenas status e fingerprint);
- commite `.env`, credencial ou dump de banco;
- rode testes contra o banco de produção (`tests/_db_guard.py` recusa o banco `railway`;
  a suíte faz `DROP SCHEMA public`);
- reintroduza "modo legado" (grupo, instância ou credencial vindos de env/`config.json`);
- mexa no serviço `rogstools` da Railway (outro projeto).

## Arquitetura

```
navegador ─HTTPS─► nina-dashboard (Caddy: SPA + proxy /api) ─rede interna─► nina-api (FastAPI)
                                                                              │
nina-worker (APScheduler) ──────────────── nina-db (Postgres, só rede interna) ┘
      │  heartbeat a cada 60 s ─► nina-api /api/internal/heartbeat
      └─► evolution-api (WhatsApp) ─► grupos
```

- **Worker** (`python -m worker.main`): a cada `check_interval` (60 s) roda um ciclo **por
  bot ativo**: busca ofertas nas fontes das plataformas em que o bot tem credencial
  válida, filtra, deduplica por grupo, passa pelo freio e envia **a mesma oferta a todos
  os grupos do bot** (ADR-021). Também: drena comandos do dashboard (`commands`:
  pausar, rodar agora, sincronizar grupos, importar vendas), importa vendas às 06:00,
  detecta alertas a cada 5 min, recado do Instagram a cada 4 h.
- **API** (`python -m api.serve`, socket IPv4+IPv6): auth JWT + refresh em cookie,
  CRUD de bots/contas/telefones/grupos/campanhas/despesas, métricas, alertas, auditoria.
  Migrations Alembic rodam no pré-deploy (`alembic upgrade head`).
- **Dashboard** (`dashboard/`): React 19 + TypeScript strict + Vite + TanStack Query +
  Tailwind 4 + lucide-react. Tipos da API gerados do `openapi.json`.
- **Config do bot vive no banco** (`bots.settings`, contrato em `core/bot_settings.py`:
  `filters`, `pacing`, `content`, `schedule`, `attribution`). O worker lê via
  `core/config_provider.py` com cache de 30 s — mudança no dashboard vale em até ~1 min.

## Mapa do código

| Onde | O quê |
|---|---|
| `worker/main.py` | agendador, jobs, heartbeat |
| `worker/monitor.py` | ciclo do bot, freio anti-ban, envio multigrupo |
| `worker/filters.py` | filtros de nicho, bloqueios, preço, desconto (compara sem acento) |
| `worker/formatter.py` | mensagem do WhatsApp (`*negrito*`, `~riscado~`); espelhada em `dashboard/src/lib/messagePreview.ts` |
| `worker/dedup.py`, `worker/commands.py`, `worker/telemetry.py`, `worker/whatsapp.py` | dedup por grupo, comandos do dashboard, runs/eventos, Evolution |
| `core/platforms/` | scrapers Shopee/ML, `affiliate.py` (links de afiliado, `link_rastreado`) |
| `core/sales_sync.py`, `core/importers/` | importação de vendas (Shopee: API `conversionReport`; ML: JSON do painel `/afiliados/dashboard`) |
| `core/models.py`, `core/repositories.py`, `migrations/` | modelo de dados e consultas (Alembic 0001–0005) |
| `core/credentials.py`, `core/crypto.py` | segredos cifrados (`CREDENTIALS_KEY`), status de credencial |
| `core/relogio.py` | hora de Brasília independente do fuso do container; silêncio noturno |
| `core/alerts.py`, `core/metrics.py` | detectores de alerta, métricas (ROI, ROAS, lucro) |
| `api/routers/` | rotas; `api/schemas/` contratos; `api/errors.py` formato de erro |
| `core/seed.py`, `config.json` | seed inicial; `config.json` **só** alimenta o seed |

## Rodar e testar (Windows, máquina do dono)

- **Venv**: `./venv` sobre o Python 3.12 **oficial** (python.org). Não recrie com o Python
  da Microsoft Store — a sandbox do Codex não consegue executá-lo.
- **Postgres de teste**: portátil em `C:/Users/SnyX/pgsql`, banco `ninaofertas_test`
  (postgres/postgres). Costuma estar parado depois de reiniciar o PC. Inicie **destacado**:
  `Start-Process -FilePath "C:\Users\SnyX\pgsql\bin\pg_ctl.exe" -ArgumentList 'start','-D','C:\Users\SnyX\pgsql\data','-l','C:\Users\SnyX\pgsql\pg.log' -WindowStyle Hidden`
  (iniciado de dentro de um comando que termina, ele morre com `0xC0000142`).
- **Backend**: `TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/ninaofertas_test ./venv/Scripts/python.exe -m pytest -q`
  (~40–50 s) e `./venv/Scripts/python.exe -m ruff check .`
  Os testes rodam em Postgres real — não troque por SQLite (escondia bugs reais).
- **Dashboard** (`cd dashboard`): `npm run lint`, `npm test`, `npm run build`. Mudou o
  contrato da API? Regere `openapi.json` e rode `npm run gen:api`.
- Sem Docker/WSL nesta máquina. `docker-compose.yml` é da época da V1 (evolution local).

## Produção (Railway, projeto `gallant-emotion`, ambiente `production`)

| Serviço | Início | Observação |
|---|---|---|
| `nina-api` | `python -m api.serve` | pré-deploy `alembic upgrade head`; healthcheck `/api/health`; sem domínio público |
| `nina-worker` | `python -m worker.main` | um único worker — dois workers = dois bots no mesmo número |
| `nina-dashboard` | Dockerfile `deploy/dashboard.Dockerfile` | domínio público; proxy `/api` |
| `nina-db` | Postgres | só rede interna; **sem backup automático** (plano Hobby) |
| `evolution-api` | imagem oficial | sessão do WhatsApp em volume |
| `ninaofertas` | — | V1, desligado |

- Os três serviços da V2 publicam o branch **`master`** de `RoBruns/ninaofertas`
  automaticamente a cada push. Não há config-as-code no repo: build/start/healthcheck
  estão nas settings da Railway (ver `docs/DEPLOYMENT.md`). Serviço novo: defina o
  comando de início **antes** do primeiro deploy.
- Fuso: worker e API com `TZ=<-03>3` (a imagem ignora `America/Sao_Paulo`); o código
  usa `core/relogio.py` para não depender disso.
- Logs: `railway logs --service nina-worker` (chegam com atraso de ~1 min).

## Git

- `master` = produção. Remotos: `producao` = `RoBruns/ninaofertas` (o que a Railway
  publica); `origin` = `DiegoMiuraDev/ninaofertas` (fork antigo, atrasado).
- O dono faz o push. Commits em português, no formato `tipo(escopo): resumo`
  (`fix(worker): …`, `feat(api): …`, `docs: …`), corpo explicando o porquê.
- Outro dev (Miura) já commitou direto na V1; desde 2026-09-30 tudo vai no `master`
  da V2. Mudança dele que chegar: integrar preservando o comportamento (ADR-019).

## Regras de negócio que não são óbvias

- **Tudo vem do dashboard** (ADR-020): o worker só publica bots **ativos**; ativar exige
  telefone com instância Evolution, ao menos um grupo e uma conta com credencial.
  Cada bot só publica plataformas em que tem credencial **não invalidada**.
- **Freio anti-ban** conta **1 por oferta**, mesmo que ela vá para vários grupos
  (ADR-021): intervalo entre ofertas, rajada, teto por hora/dia, tetos globais.
  `max_ofertas_por_dia = 0` desliga só o teto diário (ADR-018).
- **Nunca envia oferta sem link de afiliado** (`affiliate.link_rastreado`). ML: link
  `meli.la` via createLink com cookie da conta + etiqueta do bot (`attribution.ml_tag`).
  Shopee: shortLink com subIds de bot e grupo.
- **Cookie do ML**: quem decide se é válido é o createLink. A importação de vendas
  **não** invalida o cookie (bug que tirava o ML do envio toda manhã, corrigido em
  2026-09-30); falha dela vira o evento `ml_sales_sync_failed`.
- **Opções por bot** vindas da V1 (ADR-022): `uma_loja_por_ciclo`,
  `ml_ignora_desconto_e_vendas`, `ml_categoria_dispensa_nicho`.
- **Silêncio noturno** por bot (`schedule.quiet_hours`, padrão 00:00–08:00, Brasília).
- **Cupom** só entra na mensagem se for código digitável (4–16 letras/números).

## Convenções

- **Idioma**: domínio em português (`ofertas`, `envios`, `filtros`) e assim fica; código
  novo pode usar inglês em tabelas/rotas, sem misturar no mesmo módulo. Comentários,
  logs e mensagens ao usuário em **português com acento**.
- **Python**: type hints, Pydantic v2, SQLAlchemy 2.0 (`select()`), ruff. Sem `print` —
  use o logger. Falha de uma fonte/plataforma não derruba o ciclo.
- **TypeScript**: strict, sem `any`; tipos da API gerados, nunca escritos à mão.
- **Dinheiro**: `NUMERIC(14,2)` / `Decimal` / string no JSON. Nunca float.
- **Datas**: `TIMESTAMPTZ` em UTC no banco; Brasília só na borda (exibição, agenda).

## Documentação

| Pergunta | Arquivo |
|---|---|
| Estado das fases e o que falta | `docs/ROADMAP.md` (fonte de verdade do progresso) |
| Por que foi decidido assim | `docs/DECISIONS.md` (ADR-001 a ADR-022) |
| Rotas e contratos | `docs/API.md`, `openapi.json` |
| Tabelas e fórmulas | `docs/DATABASE.md` |
| Worker ↔ API | `docs/BOT_INTEGRATION.md` |
| Railway, env vars, deploy | `docs/DEPLOYMENT.md` |
| Arquitetura e produto | `docs/ARCHITECTURE.md`, `docs/PRODUCT_SPEC.md` |

`STATUS.md` é histórico da V1 (2026-09-07) — não reflete o projeto atual.

## Pendências conhecidas (2026-09-30)

- Backup do `nina-db`: não existe; o plano Hobby não tem backup nativo (opção avaliada:
  dump agendado, criptografado, para Cloudflare R2).
- Importação de vendas do ML: o painel não carrega com o cookie atual; o evento
  `ml_sales_sync_failed` traz o diagnóstico. Shopee retorna 0 conversões (aceito pelo dono).
- Fase 7b (atribuição de vendas do ML por etiqueta) e revisão final de segurança/E2E
  (fase 14).

## Ao terminar uma tarefa

1. Rode a suíte backend inteira, o ruff e, se mexeu no dashboard, lint/test/build.
2. Confira cada critério pedido, um a um; teste que falharia sem a sua mudança.
3. Atualize `docs/ROADMAP.md`; decisão relevante vira ADR em `docs/DECISIONS.md`.
4. Documento que contradiz o código: corrija o documento.
5. Relate o que não fez ou não conseguiu verificar. Parcial reportado como pronto custa
   mais caro que não feito.
