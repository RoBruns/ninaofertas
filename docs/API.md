# Contrato da API

FastAPI. Base `/api`. JSON, `snake_case`. Todas as datas em ISO-8601 UTC.
OpenAPI gerado em `/api/docs` — este documento define o contrato; o gerado
reflete a implementação. Divergência entre os dois é bug.

## Convenções

**Autenticação.** JWT no header `Authorization: Bearer <token>`. Access token
de 30 min, refresh de 7 dias em cookie `HttpOnly`/`Secure`/`SameSite=Strict`.
Toda rota exige auth, exceto `/api/auth/login`, `/api/health` e o redirect `/r/{code}`.

**Erros.** Sempre o mesmo envelope, nunca stacktrace, nunca detalhe de SQL:
```json
{ "error": { "code": "VALIDATION_ERROR", "message": "...", "fields": {"amount": "deve ser >= 0"} } }
```
Códigos: `UNAUTHORIZED` 401 · `FORBIDDEN` 403 · `NOT_FOUND` 404 ·
`VALIDATION_ERROR` 422 · `CONFLICT` 409 · `RATE_LIMITED` 429 · `INTERNAL` 500.

**Listagem.** `?page=1&page_size=50&sort=-created_at`, resposta
`{ "items": [...], "total": 0, "page": 1, "page_size": 50 }`.

**Filtros de métrica.** Aceitos em toda rota `/api/metrics/*` e em listagens
onde façam sentido — é o conjunto que o produto pede:
`from`, `to` (date), `bot_id`, `platform_id`, `account_id`, `group_id`,
`campaign_id`, `niche_id`, `phone_id`. Combináveis; `AND` entre si.

**Rate limiting.** `/api/auth/login`: 5/min por IP. Rotas de escrita: 60/min por
usuário. `/r/{code}`: 600/min por IP.

**Regra absoluta.** Nenhuma resposta contém cookie, token, secret, senha ou
string de conexão. Não há rota que devolva o valor de uma credencial — nem para
o admin. Credencial é write-only.

---

## Auth

```
POST   /api/auth/login      {email, password} → {access_token, user}
POST   /api/auth/refresh    (cookie)          → {access_token}
POST   /api/auth/logout
GET    /api/auth/me                           → User
```

Todo access token e refresh token carrega a versão de sessão do usuário. `POST
/api/auth/logout` incrementa essa versão no servidor e, portanto, encerra
imediatamente a sessão em **todos os aparelhos**, além de apagar o refresh
cookie. Trocar a senha ou desativar o usuário tem o mesmo efeito. Tokens
emitidos antes desse mecanismo são recusados e exigem um novo login. Mesmo sem
token válido, logout responde `204` e limpa o cookie sem revelar se a sessão
existia.

## Usuários

Todas as rotas abaixo exigem papel `admin`. As listagens usam o envelope
paginado das convenções; `password_hash` nunca é serializado.

```
GET    /api/users                             → {items,total,page,page_size}
POST   /api/users                             → User
PATCH  /api/users/{id}                        → User
DELETE /api/users/{id}                        → 204  (desativação lógica)
```

Um admin não pode excluir a si próprio, desativar a própria conta nem rebaixar
o próprio papel. Essas operações respondem `409 CONFLICT`. A exclusão é lógica
(`is_active=false`) para preservar a autoria imutável de `audit_logs`; tokens do
usuário desativado deixam de ser aceitos imediatamente.

## Plataformas e contas

```
GET    /api/platforms                         → [Platform]  (com capabilities)
GET    /api/accounts?platform_id=&status=     → [PlatformAccount]
POST   /api/accounts                          → PlatformAccount
GET    /api/accounts/{id}                     → PlatformAccount
PATCH  /api/accounts/{id}
DELETE /api/accounts/{id}                     → 409 se houver bot vinculado
POST   /api/accounts/{id}/activate | /pause
```

```jsonc
// PlatformAccount — note que credentials traz só metadado
{
  "id": "uuid", "platform": {"id":1,"slug":"mercadolivre","name":"Mercado Livre"},
  "label": "Conta ML 01", "external_id": "1234", "status": "active",
  "config": {"affiliate_tag": "nina01"},
  "credentials": [
    { "kind": "cookie", "status": "expired", "expires_at": "2026-09-20T10:00:00Z",
      "last_rotated_at": "2026-08-01T10:00:00Z", "last_used_at": "2026-09-22T17:10:00Z",
      "last_success_at": "2026-09-19T22:04:00Z",
      "last_error": "HTTP 401 createLink", "needs_renewal": true }
  ],
  "health": {"status": "error", "message": "Cookie expirado — renove para voltar a gerar links"}
}
```

### Credenciais (write-only)

```
PUT    /api/accounts/{id}/credentials/{kind}   {value} → 204
       // grava cifrado, zera erro, marca last_rotated_at, escreve audit_log
DELETE /api/accounts/{id}/credentials/{kind}   → 204
POST   /api/accounts/{id}/credentials/{kind}/test → {ok, checked_at, message}
       // faz uma chamada real e barata na plataforma e atualiza status
GET    /api/accounts/{id}/credentials          → [CredentialStatus]   (metadado apenas)
```

`PUT` é o que substitui "entrar no servidor para trocar o cookie": cola-se o
valor novo no dashboard e o `test` confirma na hora se funcionou. O valor entra;
nunca sai.

## Telefones e grupos

```
GET    /api/phones                            → [Phone]  (com status da evolution-api)
POST   /api/phones · PATCH · DELETE
GET    /api/phones/{id}/qrcode                 → {qrcode_base64, expires_at}
POST   /api/phones/{id}/sync-groups            → 202 {command_id}   (descoberta)

GET    /api/groups?phone_id=&status=&bot_id=   → [Group]
POST   /api/groups                             → Group   (cadastro manual)
PATCH  /api/groups/{id}
```

`Group` inclui `is_announce` e `bot_is_admin` — se `is_announce && !bot_is_admin`,
a resposta traz `"warning": "Grupo somente-admins e o bot não é admin: mensagens
não serão entregues"`. Hoje isso só existe como log na partida do bot.

## Bots

```
GET    /api/bots?status=&niche_id=&phone_id=  → [Bot]
POST   /api/bots                              → Bot
GET    /api/bots/{id}                         → BotDetail
PATCH  /api/bots/{id}
DELETE /api/bots/{id}
POST   /api/bots/{id}/duplicate               → Bot   (copia settings, grupos e contas)
POST   /api/bots/{id}/activate | /pause | /disable
POST   /api/bots/{id}/run-now                 → 202 {command_id}
GET    /api/bots/{id}/runs                    → [AutomationRun]
GET    /api/bots/{id}/health                  → BotHealth
PUT    /api/bots/{id}/groups    {group_ids:[]}
PUT    /api/bots/{id}/accounts  {account_ids:[]}
```

```jsonc
// Bot.settings — schema versionado, valida o que hoje mora em config.json
{
  "schema_version": 1,
  "filters": { "preco_minimo": 20, "preco_maximo": 5000, "desconto_minimo": 15,
               "lojas": ["Mercado Livre","Shopee"], "categorias_meli": ["MLB1574"],
               "termos_busca": [], "palavras_chave": [], "bloquear_produtos": [],
               "bloquear_termos": [], "excecoes_bloqueio": [],
               "max_vendas": 20, "max_idade_oferta_horas": 0 },
  "pacing":  { "max_ofertas_por_ciclo": 1, "intervalo_minutos_entre_ofertas": 5,
               "max_ofertas_por_rajada": 3, "janela_rajada_minutos": 15,
               "pausa_entre_rajadas_minutos": 35,
               "max_ofertas_por_hora": 6, "max_ofertas_por_dia": 80,
               "max_ofertas_globais_por_hora": 8, "max_ofertas_globais_por_dia": 90 },
  "content": { "aceitar_cupons": true, "aceitar_campanhas": false,
               "max_cupons_por_dia": 2, "baseline_ciclos": 5 },
  "schedule":{ "check_interval": 60, "quiet_hours": {"start":"23:00","end":"07:00"} }
}
```

**Guarda de segurança no `pacing`.** A API valida contra tetos definidos em
`core/safety.py` (ex.: `max_ofertas_por_hora ≤ 15`, `intervalo ≥ 2 min`). Acima
disso responde `422` com aviso explícito de risco de ban. Esses freios são o que
protege o número do WhatsApp — o dashboard não pode ser o caminho fácil para
desarmá-los por engano.

## Métricas

```
GET /api/metrics/overview      → KPIs do período + variação vs. período anterior
GET /api/metrics/timeseries?metric=&granularity=day|week|month
GET /api/metrics/by-platform | /by-account | /by-bot | /by-group | /by-campaign | /by-niche
GET /api/metrics/funnel        → envios → cliques → pedidos → compradores
GET /api/metrics/anomalies     → quedas de conversão e custos fora da curva
```

```jsonc
// GET /api/metrics/overview?from=2026-09-01&to=2026-09-22
{
  "period": {"from":"2026-09-01","to":"2026-09-22"},
  "kpis": {
    "revenue":      {"value":"12450.00","previous":"9800.00","change_pct":27.0},
    "commission":   {"value":"934.00","previous":"720.00","change_pct":29.7},
    "orders":       {"value":312,"previous":250,"change_pct":24.8},
    "buyers":       {"value":287,"previous":230,"change_pct":24.8},
    "spend":        {"value":"400.00","previous":"400.00","change_pct":0.0},
    "traffic_spend":{"value":"300.00","previous":"300.00","change_pct":0.0},
    "profit":       {"value":"534.00","previous":"320.00","change_pct":66.9},
    "roi":          {"value":1.335,"previous":0.80,"change_pct":66.9},
    "roas":         {"value":41.5,"previous":32.7,"change_pct":26.9},
    "cost_per_sale":   {"value":"1.28","previous":"1.60","change_pct":-20.0},
    "cost_per_buyer":  {"value":"1.39","previous":"1.74","change_pct":-20.0},
    "cost_per_join":   {"value":"0.85","previous":null,"change_pct":null},
    "group_joins":  {"value":352,"previous":null,"change_pct":null},
    "conversion":   {"value":0.041,"previous":0.038,"change_pct":7.9},
    "sends":        {"value":1680,"previous":1540,"change_pct":9.1}
  },
  "warnings": ["Sem dados de venda para AliExpress no período"]
}
```

Valores monetários são **string decimal**, não float — float em JSON perde
centavo. `null` em `previous`/`change_pct` significa "sem base de comparação".
`warnings` é como a API diz "este número está incompleto" sem esconder o número.

## Despesas

```
GET    /api/expenses?from=&to=&category_id=&campaign_id=&bot_id=&platform_id=
POST   /api/expenses · PATCH · DELETE
GET    /api/expense-categories · POST
POST   /api/expenses/import      multipart CSV → {imported, skipped, errors[]}
```

## Campanhas

```
GET/POST/PATCH/DELETE /api/campaigns
GET    /api/campaigns/{id}/metrics
```

## Vendas e comissões

```
GET    /api/sales?from=&to=&platform_id=&bot_id=&status=
POST   /api/sales/import         multipart CSV + platform_id → {imported, skipped, errors[]}
POST   /api/sales/sync           {account_id} → 202  (API ou painel autenticado suportado)
GET    /api/sales/imports        → histórico de importações
```

O CSV é mapeado por plataforma em `core/importers/<slug>.py`. Dedup por
`(platform_id, external_id)`: reimportar o mesmo relatório é idempotente e
seguro.

A sincronização automática usa `conversionReport` na Shopee e, no Mercado
Livre, lê o JSON server-side do painel de afiliados um dia por requisição nos
últimos 14 dias, sempre limitado a D-1. O worker executa todas as contas ativas
diariamente às 06:00 em `America/Sao_Paulo`.

## Observabilidade

```
GET    /api/alerts?status=open&severity=       → [Alert]
POST   /api/alerts/{id}/acknowledge | /resolve
GET    /api/events?level=&bot_id=&type=&from=  → [Event]   (área técnica)
GET    /api/health                             → {status, db, worker_last_seen}
GET    /api/system/status                      → visão consolidada por bot/conta/telefone
GET    /api/audit-logs?entity_type=&entity_id=&user_id=&from=&to=
                                               → {items,total,page,page_size}
```

`/api/audit-logs` exige papel `admin` e também aceita `page`, `page_size` e
`sort`. O health desta fase deliberadamente não consulta serviços externos; o
estado consolidado deles pertence a `/api/system/status`.

## Interno (worker ↔ API)

O worker fala direto com o Postgres — não passa pela API para ler config, o que
evita acoplamento e um ponto de falha a mais. Estas rotas existem só para o que
precisa de resposta síncrona:

```
POST   /api/internal/heartbeat   {worker_id, bots_running[]}   # header X-Worker-Token
POST   /api/internal/events      [Event]
```

Autenticadas por `WORKER_TOKEN` (env var, comparação em tempo constante), nunca
por JWT de usuário, e recusadas se vierem de fora da rede interna.

## Redirect de atribuição

```
GET    /r/{code}   → 302 para a URL afiliada, gravando clicks
```
Sem auth (é link público de grupo). Só faz lookup, grava clique e redireciona —
qualquer trabalho extra vira latência entre o clique e a loja.
