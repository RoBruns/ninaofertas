# Roadmap de implementação

14 fases. Cada uma é uma tarefa fechada para o Codex, com critério objetivo de
conclusão. Nenhuma fase pode deixar o bot fora do ar.

**Estado:** ⬜ não iniciada · 🟡 em execução · 🔵 em revisão · ✅ concluída

| # | Fase | Estado | Depende de | Agente |
|---|---|---|---|---|
| 0 | Documentação e baseline | ✅ | — | Claude |
| 1 | Estrutura do monorepo + `core/` | ✅ | 0 | Codex A |
| 2 | Migrations e modelo de dados | ⬜ | 1 | Codex A |
| 3 | API: auth, usuários, auditoria | ⬜ | 2 | Codex A |
| 4 | API: plataformas, contas, credenciais | ⬜ | 3 | Codex A |
| 5 | API: bots, telefones, grupos | ⬜ | 4 | Codex A |
| 6 | Worker lê config do banco | ⬜ | 5 | Codex B (**sozinho**) |
| 7 | Atribuição: sub_id + redirect | ⬜ | 6 | Codex B |
| 8 | API: despesas, campanhas, vendas | ⬜ | 4 | Codex C ∥ 6 |
| 9 | API: métricas e agregações | ⬜ | 8 | Codex C |
| 10 | Alertas e observabilidade | ⬜ | 6, 9 | Codex C |
| 11 | Frontend: base, auth, layout | ⬜ | 3 | Codex D ∥ 6–10 |
| 12 | Frontend: gestão (contas, bots, grupos) | ⬜ | 5, 11 | Codex D |
| 13 | Frontend: dashboard, métricas, despesas | ⬜ | 9, 11 | Codex D |
| 14 | Deploy, hardening, testes E2E | ⬜ | todas | Claude + Codex |

**Paralelismo seguro.** A regra é um agente por diretório. `core/` + `api/` é o
Codex A; o worker é o Codex B **sozinho** (é o código vivo — ninguém mais toca);
`api/routers/metrics|expenses|sales` é o C; `dashboard/` é o D. As fases 8–13
paralelizam com 6–7 porque tocam arquivos disjuntos. A fase 6 nunca roda em
paralelo com outra coisa que toque o worker.

---

## Fase 1 — Estrutura do monorepo

Reorganizar sem mudar comportamento. O bot precisa continuar rodando idêntico.

```
ninaofertas/
├── core/           models, repositórios, cripto, clientes de plataforma, métricas
│   ├── db.py  models.py  crypto.py  safety.py  metrics.py
│   ├── platforms/  base.py  shopee.py  mercadolivre.py  aliexpress.py
│   └── importers/  base.py  shopee_csv.py  mercadolivre_csv.py
├── api/            FastAPI
├── worker/         o bot atual (main, monitor, scraper, filters, dedup, ...)
├── dashboard/      React + Vite + TS
├── migrations/     Alembic
├── tests/
└── docs/
```

Critério: `python -m worker.main` roda como antes · imports resolvem ·
`pytest` passa · `railway up` do worker continua saudável.

## Fase 2 — Migrations

Alembic com `alembic stamp` do schema atual (`ofertas`, `envios` **não são
recriadas**), depois as tabelas de [DATABASE.md](DATABASE.md) e as colunas
aditivas nullable. Seed: plataformas, categorias de despesa, usuário admin,
e conversão dos dois canais de `config.py` em linhas de `bots`.

Critério: `alembic upgrade head` em banco limpo e em cópia do banco de produção
· `downgrade` volta · dados de `ofertas`/`envios` intactos · seed idempotente.

## Fase 3 — API: auth e auditoria

JWT, argon2id, refresh em cookie HttpOnly, RBAC (admin/operator/viewer),
middleware de auditoria com redação de campo sensível, rate limit, envelope de
erro, `/api/health`.

Critério: login funciona · rota protegida devolve 401 sem token · audit_log
grava before/after com segredo redigido · testes de auth passam.

## Fase 4 — API: plataformas, contas, credenciais

CRUD de contas, cripto AES-GCM com `CREDENTIALS_KEY`, credenciais write-only,
`/test` real por plataforma, derivação de status.

Critério: **nenhuma rota devolve valor de credencial** (teste automatizado que
varre as respostas em busca do valor gravado) · `PUT` + `/test` renovam o cookie
do ML de ponta a ponta · múltiplas contas por plataforma funcionam.

## Fase 5 — API: bots, telefones, grupos

CRUD, duplicar bot, ativar/pausar, `bot_groups`/`bot_platform_accounts`,
descoberta de grupos via evolution-api, validação do `settings` com os tetos de
`core/safety.py`.

Critério: criar bot pela API sem tocar em código · duplicar copia grupos e contas
· sync traz os grupos reais do telefone · pacing acima do teto devolve 422.

## Fase 6 — Worker lê config do banco ⚠️

**A fase mais delicada — é o código que está no ar.**

`config.py` passa a montar os canais a partir de `bots` (cache TTL 30s), com
fallback para `config.json` se o banco não tiver bot ativo. O número do bot sai
do literal em `whatsapp.py` e vem de `phones`. Credenciais vêm da conta, não de
`settings`. O worker drena `commands`, grava `automation_runs`/`events`, manda
heartbeat, e persiste o estado de baseline (resolve P8).

Não muda: filtros, dedup, freios anti-ban, formatação, envio.

Critério: com banco vazio o bot se comporta **exatamente** como hoje · com bot no
banco, alterar limite no dashboard reflete em ≤1 ciclo sem restart · pausar pelo
dashboard para os envios em ≤1 ciclo · restart não refaz baseline · 24h em
produção sem regressão de envio.

## Fase 7 — Atribuição

**Spike primeiro** (1–2h, antes de construir): confirmar que Shopee e ML aceitam
`sub_id` no link e o devolvem no relatório de comissão. O resultado decide se a
atribuição por grupo é real ou estimada — e é registrado em DECISIONS.md antes de
qualquer código.

Depois: `sub_id = {bot_slug}:{group_short}:{oferta_id}` na geração do link,
gravado em `envios.sub_id`, e o redirect `/r/{code}` com `clicks`.

Critério: link enviado carrega sub_id · clique grava linha · relatório da
plataforma devolve o sub_id (ou a limitação está documentada).

## Fase 8 — Despesas, campanhas, vendas

CRUD de despesa com todos os campos pedidos, categorias, campanhas, import CSV
idempotente de vendas/comissões por plataforma, `sales/sync` onde houver API.

Critério: despesa manual completa · reimportar o mesmo CSV não duplica ·
CSV malformado devolve erro por linha, sem importar nada pela metade.

## Fase 9 — Métricas

`core/metrics.py` com todas as fórmulas de DATABASE.md, rotas de overview,
timeseries, breakdowns, funil, comparação de período, `null` em denominador zero.

Critério: testes com dataset fixo conferem cada fórmula · divisão por zero devolve
`null` · overview responde < 500 ms no volume atual · filtros combinam.

## Fase 10 — Alertas e observabilidade

Detectores: bot offline, auth expirada, conta desconectada, grupo inacessível,
falha de publicação, erro recorrente, queda de conversão, custo anormal,
automação parada, dados desatualizados. Dedup por `dedup_key`, ack/resolve,
retenção de eventos.

Critério: expirar um cookie de propósito gera **um** alerta (não um por ciclo) ·
alerta resolve sozinho quando a causa some · dashboard não é inundado por log.

## Fase 11 — Frontend: base

Vite + React + TS + TanStack Query + React Router + shadcn/ui + Tailwind,
cliente de API tipado, login, layout, tratamento de erro, dark mode, responsivo.

Critério: login e refresh funcionam · 401 redireciona · build limpo · sem `any`
solto · nenhum segredo no bundle.

## Fase 12 — Frontend: gestão

Telas de contas (com estado de credencial e renovação), bots (CRUD, duplicar,
pausar, settings), telefones (QR, status), grupos (descoberta e associação).

Critério: toda operação do backend tem UI · renovar cookie pelo dashboard
funciona ponta a ponta · aviso claro ao violar teto de pacing.

## Fase 13 — Frontend: dashboard

Overview com KPIs e variação, gráficos (Recharts), breakdowns por
plataforma/conta/bot/grupo/campanha/nicho, filtros globais persistidos na URL,
despesas, área de alertas, área técnica de logs separada.

Critério: os filtros pedidos funcionam e combinam · `null` aparece como "sem
dados" · as perguntas do briefing (onde perco dinheiro, o que performa) são
respondidas em ≤2 cliques · usável no celular.

## Fase 14 — Deploy e hardening

Serviços `nina-api` e `nina-dashboard` na Railway, `CREDENTIALS_KEY`/`JWT_SECRET`
/`WORKER_TOKEN` gerados, CORS restrito, security headers, `pg_dump` agendado,
E2E, revisão de segurança final, migração das env vars operacionais para o banco.

Critério: dashboard no ar com HTTPS · bot rodando normal · nenhum segredo no
frontend · backup verificado · `/api/docs` bate com este contrato.

---

## Bugs encontrados durante a obra

Achados que **já existiam** antes deste projeto. Não foram corrigidos na hora
para não misturar mudança de comportamento com refatoração estrutural.

### B1 — Cupons de campanha Shopee nunca são capturados ⚠️ produção

`worker/sources/cupons.py:191` usa `nome=linha`, mas `linha` nunca é definida
naquela função (`_shopee_offer_como_cupom`) — só nas outras duas, nas linhas 217
e 271. Toda chamada levanta `NameError`, que `Scraper.executar()` engole. É por
isso que o log de produção mostra `[Cupons] 0 cupons capturados` em todo ciclo.

Descoberto na fase 1 por `ruff` (F821). Estava no código desde o commit
`507eaff`. Corrigir provavelmente é usar `_linha_beneficio(beneficio, codigo)`,
como fazem os outros dois caminhos — **mas isso liga uma fonte que hoje está
desligada de fato**, e passaria a enviar cupons de campanha ao grupo. É mudança
de comportamento operacional, então precisa de decisão do usuário, não de um
fix silencioso.

**Status:** aguardando decisão. Corrigir junto com a fase 6 (que já mexe no
worker) ou antes, se o usuário quiser os cupons no ar logo.

### B2 — `E741` nome de variável ambíguo (`l`)

`worker/filters.py:337,392` e `worker/monitor.py:29`. Cosmético, sem impacto.
Corrigir quando esses arquivos forem tocados por outro motivo.

---

## Ordem de valor

Se for preciso parar antes do fim, o ponto de corte com mais valor entregue é
**a fase 6**: a partir dela a operação já é administrável sem SSH, que é o
critério principal do projeto. Fases 7–13 agregam medição; 1–5 sozinhas não
mudam o dia a dia.
