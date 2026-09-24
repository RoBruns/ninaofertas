# Roadmap de implementação

14 fases. Cada uma é uma tarefa fechada para o Codex, com critério objetivo de
conclusão. Nenhuma fase pode deixar o bot fora do ar.

**Estado:** ⬜ não iniciada · 🟡 em execução · 🔵 em revisão · ✅ concluída

| # | Fase | Estado | Depende de | Agente |
|---|---|---|---|---|
| 0 | Documentação e baseline | ✅ | — | Claude |
| 1 | Estrutura do monorepo + `core/` | ✅ | 0 | Codex A |
| 2 | Migrations e modelo de dados | ✅ | 1 | Codex A |
| 3 | API: auth, usuários, auditoria | ✅ | 2 | Codex A |
| 4 | API: plataformas, contas, credenciais | ✅ | 3 | Codex A |
| 5 | API: bots, telefones, grupos | ✅ | 4 | Codex A |
| 6 | Worker lê config do banco | ✅ | 5 | Codex B (**sozinho**) |
| 7 | Atribuição: sub_id + redirect | ⬜ | 6 | Codex B |
| 8 | API: despesas, campanhas, vendas | ✅ | 4 | Codex C ∥ 6 |
| 8b | Sincronização real de vendas (Shopee API, ML painel) | ✅ | 8 | Codex C |
| 9 | API: métricas e agregações | ✅ | 8 | Codex C |
| 10 | Alertas e observabilidade | ✅ | 6, 9 | Codex C |
| 11 | Frontend: base, auth, layout | ✅ | 3 | Codex D ∥ 6–10 |
| 3b | Logout que encerra a sessão no servidor | ✅ | 3 | Codex A |
| 12 | Frontend: gestão (contas, bots, grupos) | ✅ | 5, 11 | Codex D |
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

## Verificações realizadas

### V1 — Migrations validadas contra Postgres real ✅ (2026-09-22)

As revisions 0001–0003 foram executadas de verdade contra a instância Postgres
da Railway, em bancos descartáveis. **Nada foi aplicado ao banco de produção.**

**Como acessar o Postgres interno** (o método que funciona — `railway run` não
serve, pois injeta as vars mas roda local e o host interno não resolve):

```bash
railway connect Postgres --tunnel-only --port 55432   # não imprime nada; segura o túnel
# em outro terminal:
export PGPASS=$(railway variables --service Postgres --kv | grep '^POSTGRES_PASSWORD=' | cut -d= -f2-)
export DATABASE_URL="postgresql://postgres:${PGPASS}@127.0.0.1:55432/<banco>"
```
Exige chave SSH registrada (`railway ssh keys add --key <caminho windows do .pub>`).

**Cenário 1 — banco vazio.** `upgrade head` criou 22 tabelas + `alembic_version`.
Tipos conferidos no banco: `NUMERIC(14,2)` para dinheiro, `NUMERIC(7,4)` para
percentual, `TIMESTAMPTZ` para timestamp.

**Cenário 2 — simulação de produção.** Recriado o schema legado com o DDL
original (`ofertas`/`envios` sem as colunas novas) e populado com dados, então
`upgrade head` por cima. Resultado medido:

| Verificação | Resultado |
|---|---|
| Colunas perdidas em `ofertas` | **nenhuma** |
| Colunas perdidas em `envios` | **nenhuma** |
| Colunas adicionadas | exatamente as 4 esperadas, todas nullable |
| Contagem de linhas antes/depois | idêntica |
| Conteúdo das linhas | idêntico |
| `downgrade base` | remove só as tabelas novas; `ofertas`/`envios` e dados intactos |

**Suíte completa:** 24/24 passando com `TEST_DATABASE_URL` apontando para o
Postgres real (os 2 testes de migration deixaram de pular).

Bancos de teste removidos ao final; produção conferida intacta (640 ofertas,
608 envios — os mesmos números de antes).

> Mesmo com isso verificado, o passo 1 antes de aplicar em produção continua
> sendo `pg_dump`. Teste bem-sucedido reduz risco; não substitui backup.

---

### V2 — Testes da API exigem Postgres, não SQLite (2026-09-22)

`tests/test_api.py` roda contra Postgres real (`TEST_DATABASE_URL`) e monta o
schema aplicando `alembic upgrade head`, não `create_all` tabela a tabela.
Sem a variável, pula com instrução de como rodar.

O caminho SQLite foi **removido de propósito**. Os models usam tipos e funções
que só existem no Postgres (`CITEXT` no email, `INET` no ip da auditoria,
`now()` e `gen_random_uuid()` como server_default, `JSONB`). Emular isso deixaria
o teste verde contra algo que não é o que roda em produção — e foi exatamente
rodando em Postgres de verdade que apareceu o **B3** abaixo, que o SQLite
escondia atrás de um erro genérico.

---

### V3 — Desempenho das métricas: orçamento de consultas, não cronômetro (2026-09-23)

O critério "overview < 500 ms" mede tempo de relógio, que inclui a rede até o
banco. Pelo túnel local (~147 ms por ida e volta) o overview leva ~4 s; dentro
da Railway, com API e banco lado a lado (~1 ms), o esperado é bem abaixo de
500 ms. O teste agora verifica o que o código controla: **no máximo 14 consultas
SQL** por overview. O número é constante — 11 sem as tabelas legadas, 13 com
`ofertas`/`envios` como em produção — e não cresce com o volume de dados; os
loops em `core/metrics.py` percorrem listas fixas de tipos de evento, não linhas.

O cronômetro continua no teste, ligado por `METRICS_LATENCY_CHECK=1`. **Rodar
com essa variável na Railway durante a fase 14** para fechar o critério.

### V4 — Trava contra rodar a suíte no banco de produção (2026-09-23)

Os fixtures apagam o schema `public` inteiro para montar um banco limpo.
Apontados para produção por engano, destruiriam `ofertas` e `envios`.
`tests/_db_guard.py` faz os dois fixtures se recusarem a rodar num banco
chamado `railway` (ou sem nome). Validado chamando a função diretamente —
nunca rodando a suíte contra produção.

### V5 — Pendente: resolver o mesmo alerta duas vezes

O cenário que motivou o ADR-016 (alerta que resolve, reabre e resolve de novo)
está coberto só pelos testes do agente. A verificação independente foi
interrompida a pedido do usuário. Refazer antes do deploy.

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

**Status:** adiado por decisão do usuário (2026-09-22) — ele ainda não avaliou
como quer usar cupons na operação. **Não corrigir sem consultá-lo**: o fix liga
uma fonte que hoje está desligada de fato e muda o que chega nos grupos.

Retomar quando o usuário definir o papel do cupom. A essa altura a fase 6 já terá
deixado `max_cupons_por_dia` e `aceitar_cupons` controláveis pelo dashboard, então
dá para ligar com o volume limitado e observar antes de soltar.

### B3 — `audit_logs.ip` é INET e derrubava o login ✅ corrigido

`record_audit` gravava `request.client.host` cru numa coluna `INET`. Qualquer
valor que não seja um IP válido faz o Postgres recusar o INSERT — e como a
auditoria do login acontece dentro da request, **o login inteiro respondia 500**.

Apareceu com o TestClient, que se identifica como `"testclient"`, mas não é
artefato de teste: um proxy mal configurado, um `X-Forwarded-For` forjado ou um
socket Unix produziriam o mesmo 500 em produção — numa rota crítica e sem pista
no corpo da resposta, já que o handler 500 (corretamente) não vaza detalhe.

**Corrigido nesta fase:** `_ip_valido()` valida com `ipaddress.ip_address()` e
grava `NULL` quando não reconhece. Auditoria não pode derrubar a operação que
ela registra.

### B6 — `/api/events` dava 500 sem filtro de data ✅ corrigido (fase 10)

As condições de filtro eram montadas todas antes de conferir quais tinham
valor. `Event.level == None` vira `IS NULL`, mas `Event.created_at >= None`
levanta `ArgumentError` já na construção — então a listagem sem `from`/`to`,
o uso mais comum da área técnica, respondia 500.

### B7 — `/api/system/status` dava 500 sempre ✅ corrigido (fase 10)

`dict(session.execute(...))`: o `Result` do SQLAlchemy tem `.keys()`, e o
`dict()` do Python o trata como mapping e tenta indexá-lo. A resposta para
"está tudo funcionando?" falhava em toda chamada. Corrigido com `.tuples().all()`.

### B8 — Logout não encerrava a sessão no servidor ✅ corrigido (fase 3b)

Verificado ponta a ponta: um cookie de refresh copiado antes do logout
continuava renovando a sessão (200), e o access token antigo seguia válido.
Correção especificada como fase 3b: `users.session_version` na claim dos
tokens, incrementada no logout, na desativação e na troca de senha.

### B4 — Telemetria podia derrubar o ciclo de ofertas ✅ corrigido (fase 8b)

`monitor.ciclo()` desempacotava o retorno de `telemetry.iniciar_ciclo` fora de
qualquer proteção. A função real sempre devolve um par, mas um retorno fora do
formato quebraria o envio — contrariando a regra da fase 6 de que telemetria é
best-effort. Agora retorno inesperado vira "sem run" e o ciclo segue.

### B5 — Migrations silenciavam os logs da aplicação ✅ corrigido (fase 8b)

`migrations/env.py` chamava `fileConfig()` com o padrão
`disable_existing_loggers=True`. Qualquer migration executada no mesmo processo
**desativava todos os loggers já criados** — inclusive os WARNINGs de status
desconhecido e de credencial expirada. Na suíte, aparecia como falha dependente
da ordem dos testes. Mecanismo provado isoladamente (`logger.disabled`
True → False) antes da correção.

### B2 — `E741` nome de variável ambíguo (`l`)

`worker/filters.py:337,392` e `worker/monitor.py:29`. Cosmético, sem impacto.
Corrigir quando esses arquivos forem tocados por outro motivo.

---

## Ordem de valor

Se for preciso parar antes do fim, o ponto de corte com mais valor entregue é
**a fase 6**: a partir dela a operação já é administrável sem SSH, que é o
critério principal do projeto. Fases 7–13 agregam medição; 1–5 sozinhas não
mudam o dia a dia.
