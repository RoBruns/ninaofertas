# Modelo de dados

Postgres (instância `Postgres` do projeto Railway `gallant-emotion`), schema `public`.
Migrations com Alembic. Nomes de tabela em inglês, no plural.

## Princípios

1. **Nada é hardcoded.** Toda configuração operacional é linha de tabela.
2. **Segredo é cifrado e write-only.** Valor em claro nunca sai do backend.
3. **`owner_id` desde o início.** Um usuário hoje, sem migração amanhã.
4. **Métrica é evento, não contador.** Agregamos na leitura; nunca sobrescrevemos
   histórico. Comparação histórica é requisito.
5. **Dinheiro é `NUMERIC(14,2)`.** Nunca `float`. Percentual é `NUMERIC(7,4)`.
6. **Timestamps são `TIMESTAMPTZ`.** O bot roda em `America/Sao_Paulo`, o banco em
   UTC. Bug de fuso em métrica diária é silencioso e caro.

## Tabelas já existentes (preservadas)

`ofertas` e `envios` continuam **exatamente como estão** — o bot depende delas e
os freios anti-ban contam suas linhas. A migration inicial as adota sem recriar.

Em um banco literalmente vazio, a baseline também não as cria: as tabelas novas
são instaladas e as FKs/colunas que apontam para o legado são omitidas. No banco
de produção, onde ambas existem, essas FKs e colunas são adicionadas normalmente.
Isso permite testar `upgrade head` em banco vazio sem transformar a baseline em
uma segunda fonte de DDL para o schema legado.

```
ofertas(id, nome, preco, preco_anterior, desconto, loja, categoria,
        url UNIQUE, imagem, sku, capturado_em)
envios (id, oferta_id, enviado_em, grupo, mensagem, preco_enviado, status)
```

Evolução aditiva apenas (colunas novas, sempre nullable):
- `envios.bot_id` → `bots(id)`, nullable — liga envio ao bot que o fez
- `envios.group_id` → `groups(id)`, nullable — liga ao grupo normalizado
- `envios.sub_id` TEXT — chave de atribuição de comissão
- `ofertas.platform_account_id` → `platform_accounts(id)`, nullable

> Nullable porque as linhas históricas não têm esses valores. Nenhum backfill
> inventado: o que é desconhecido fica `NULL`.

---

## Identidade e auditoria

```sql
users (
  id            UUID PK DEFAULT gen_random_uuid(),
  email         CITEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,             -- argon2id
  name          TEXT,
  role          TEXT NOT NULL DEFAULT 'admin',   -- admin | operator | viewer
  is_active     BOOLEAN NOT NULL DEFAULT TRUE,
  last_login_at TIMESTAMPTZ,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
)

audit_logs (
  id          BIGSERIAL PK,
  user_id     UUID REFERENCES users(id),        -- NULL = ação do sistema
  entity_type TEXT NOT NULL,                     -- 'bot' | 'platform_account' | ...
  entity_id   TEXT NOT NULL,
  action      TEXT NOT NULL,                     -- create | update | delete | activate | ...
  before      JSONB,
  after       JSONB,
  ip          INET,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
)
CREATE INDEX ON audit_logs (entity_type, entity_id, created_at DESC);
```

`before`/`after` passam por um redator que substitui qualquer campo sensível por
`"***"` **antes** de gravar. Auditoria nunca vira vazamento de segredo.

---

## Plataformas e contas

```sql
platforms (
  id            SERIAL PK,
  slug          TEXT UNIQUE NOT NULL,        -- 'shopee' | 'mercadolivre' | 'aliexpress'
  name          TEXT NOT NULL,
  is_active     BOOLEAN NOT NULL DEFAULT TRUE,
  capabilities  JSONB NOT NULL DEFAULT '{}'  -- {"offers":true,"affiliate_link":true,
)                                            --  "commission_api":false,"coupons":true}

platform_accounts (
  id           UUID PK DEFAULT gen_random_uuid(),
  owner_id     UUID NOT NULL REFERENCES users(id),
  platform_id  INT  NOT NULL REFERENCES platforms(id),
  label        TEXT NOT NULL,               -- "Conta ML 01"
  external_id  TEXT,                        -- id do afiliado na plataforma
  status       TEXT NOT NULL DEFAULT 'active',  -- active | paused | error | disabled
  config       JSONB NOT NULL DEFAULT '{}', -- não-sensível: tag, sub_id base, categorias
  notes        TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (owner_id, platform_id, label)
)
```

`platforms.capabilities` é o que torna "adicionar plataforma nova sem reconstruir"
real: o dashboard monta a UI a partir dele e a API sabe quais rotas fazem sentido.
AliExpress entra como linha + um cliente em `core/platforms/aliexpress.py`.

## Credenciais

```sql
platform_credentials (
  id               UUID PK DEFAULT gen_random_uuid(),
  account_id       UUID NOT NULL REFERENCES platform_accounts(id) ON DELETE CASCADE,
  kind             TEXT NOT NULL,           -- 'cookie' | 'oauth_token' | 'api_key' | 'app_secret'
  ciphertext       BYTEA NOT NULL,          -- AES-GCM; chave em CREDENTIALS_KEY (env)
  key_version      INT  NOT NULL DEFAULT 1, -- permite rotação de chave-mestra
  fingerprint      TEXT,                    -- sha256 dos 1ºs bytes: detecta "mudou?" sem decifrar
  status           TEXT NOT NULL DEFAULT 'unknown',  -- valid | expiring | expired | invalid | unknown
  expires_at       TIMESTAMPTZ,
  last_rotated_at  TIMESTAMPTZ,
  last_used_at     TIMESTAMPTZ,
  last_success_at  TIMESTAMPTZ,
  last_error       TEXT,
  last_error_at    TIMESTAMPTZ,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (account_id, kind)
)
```

**Esta tabela nunca é serializada para o frontend.** A API expõe apenas
`CredentialStatus` (ver [API.md](API.md)): kind, status, datas, erro. Nunca
`ciphertext`, nunca o valor decifrado.

`status` é derivado: o worker marca `invalid` ao receber 401/403 da plataforma, e
`expiring` quando `expires_at` está a menos de 48h. É isso que alimenta o alerta
"autenticação expirada" sem ninguém precisar ler log. Resolve P5.

---

## Telefones, bots e grupos

```sql
phones (
  id                 UUID PK DEFAULT gen_random_uuid(),
  owner_id           UUID NOT NULL REFERENCES users(id),
  label              TEXT NOT NULL,          -- "Chip principal"
  number             TEXT NOT NULL,          -- E.164: 558531791835
  evolution_instance TEXT,                   -- instância na evolution-api
  status             TEXT NOT NULL DEFAULT 'unknown',  -- connected | disconnected | banned | unknown
  last_seen_at       TIMESTAMPTZ,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (owner_id, number)
)
```
Resolve P3: o `"558531791835"` literal em `whatsapp.py` passa a ser esta linha.

```sql
niches (
  id       SERIAL PK,
  owner_id UUID NOT NULL REFERENCES users(id),
  slug     TEXT NOT NULL,                   -- 'casa' | 'automotivo' | 'tecnologia'
  name     TEXT NOT NULL,
  UNIQUE (owner_id, slug)
)

bots (
  id            UUID PK DEFAULT gen_random_uuid(),
  owner_id      UUID NOT NULL REFERENCES users(id),
  name          TEXT NOT NULL,              -- "Achadinhos da Nina"
  slug          TEXT NOT NULL,              -- substitui config.py:CANAIS
  niche_id      INT  REFERENCES niches(id),
  phone_id      UUID REFERENCES phones(id), -- MESMO telefone pode servir vários bots
  status        TEXT NOT NULL DEFAULT 'paused',  -- active | paused | disabled
  settings      JSONB NOT NULL DEFAULT '{}',     -- o antigo config.json inteiro
  message_template TEXT,
  last_run_at      TIMESTAMPTZ,
  last_success_at  TIMESTAMPTZ,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (owner_id, slug)
)
```

`bots.settings` recebe o conteúdo de `config.json` (filtros, limites, ritmo)
validado por um schema Pydantic versionado. JSONB e não colunas porque esse
conjunto muda com frequência e é lido sempre inteiro — colunizar exigiria
migration a cada critério novo. O que é consultado transversalmente (status,
nicho, telefone) é coluna. Resolve P1 e P2.

```sql
groups (
  id            UUID PK DEFAULT gen_random_uuid(),
  owner_id      UUID NOT NULL REFERENCES users(id),
  phone_id      UUID REFERENCES phones(id),
  whatsapp_id   TEXT NOT NULL,              -- 120363xxxxxx@g.us
  name          TEXT,
  participants  INT,
  is_announce   BOOLEAN,                    -- "somente admins"
  bot_is_admin  BOOLEAN,                    -- se false + announce → msg é engolida
  status        TEXT NOT NULL DEFAULT 'active',  -- active | inaccessible | archived
  discovered_at TIMESTAMPTZ,
  last_synced_at TIMESTAMPTZ,
  UNIQUE (phone_id, whatsapp_id)
)

bot_groups (
  bot_id   UUID REFERENCES bots(id) ON DELETE CASCADE,
  group_id UUID REFERENCES groups(id) ON DELETE CASCADE,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  PRIMARY KEY (bot_id, group_id)
)

bot_platform_accounts (
  bot_id     UUID REFERENCES bots(id) ON DELETE CASCADE,
  account_id UUID REFERENCES platform_accounts(id) ON DELETE CASCADE,
  is_active  BOOLEAN NOT NULL DEFAULT TRUE,
  PRIMARY KEY (bot_id, account_id)
)
```

`is_announce` + `bot_is_admin` vêm da descoberta automática via evolution-api
(`GET /group/fetchAllGroups`) e alimentam o alerta de grupo inacessível — hoje
isso é só um `logger.error` na partida.

---

## Campanhas, gastos e receita

```sql
campaigns (
  id           UUID PK DEFAULT gen_random_uuid(),
  owner_id     UUID NOT NULL REFERENCES users(id),
  name         TEXT NOT NULL,
  channel      TEXT,                        -- 'meta_ads' | 'organic' | 'influencer'
  external_id  TEXT,                        -- id da campanha no Meta Ads
  bot_id       UUID REFERENCES bots(id),
  niche_id     INT  REFERENCES niches(id),
  objective    TEXT,                        -- 'group_join' | 'sales'
  status       TEXT NOT NULL DEFAULT 'active',
  started_at   DATE,
  ended_at     DATE
)

expense_categories (
  id       SERIAL PK,
  owner_id UUID NOT NULL REFERENCES users(id),
  slug     TEXT NOT NULL,        -- 'trafego' | 'infra' | 'chips' | 'ferramentas'
  name     TEXT NOT NULL,
  UNIQUE (owner_id, slug)
)

expenses (
  id           UUID PK DEFAULT gen_random_uuid(),
  owner_id     UUID NOT NULL REFERENCES users(id),
  description  TEXT NOT NULL,
  amount       NUMERIC(14,2) NOT NULL CHECK (amount >= 0),
  currency     TEXT NOT NULL DEFAULT 'BRL',
  incurred_on  DATE NOT NULL,
  category_id  INT  REFERENCES expense_categories(id),
  platform_id  INT  REFERENCES platforms(id),
  campaign_id  UUID REFERENCES campaigns(id),
  bot_id       UUID REFERENCES bots(id),
  niche_id     INT  REFERENCES niches(id),
  source       TEXT NOT NULL DEFAULT 'manual',   -- manual | meta_ads | csv_import
  external_id  TEXT,                              -- dedup de import automático
  notes        TEXT,
  created_by   UUID REFERENCES users(id),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (source, external_id)                     -- reimportar não duplica
)
CREATE INDEX ON expenses (owner_id, incurred_on DESC);
```

`source` + `external_id` únicos é o que permite plugar o importador do Meta Ads
depois sem duplicar o que foi lançado à mão. A entrada manual é a de hoje; o
importador é fase 11.

```sql
clicks (                                 -- só se o redirect próprio for adotado
  id          BIGSERIAL PK,
  sub_id      TEXT NOT NULL,
  bot_id      UUID REFERENCES bots(id),
  group_id    UUID REFERENCES groups(id),
  oferta_id   INT  REFERENCES ofertas(id),
  clicked_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  user_agent  TEXT,
  ip_hash     TEXT                       -- hash, nunca IP cru
)

sales (
  id             UUID PK DEFAULT gen_random_uuid(),
  owner_id       UUID NOT NULL REFERENCES users(id),
  account_id     UUID REFERENCES platform_accounts(id),
  platform_id    INT  NOT NULL REFERENCES platforms(id),
  external_id    TEXT NOT NULL,          -- id do pedido na plataforma
  sub_id         TEXT,                   -- atribuição → bot/grupo/oferta
  bot_id         UUID REFERENCES bots(id),
  group_id       UUID REFERENCES groups(id),
  oferta_id      INT  REFERENCES ofertas(id),
  product_name   TEXT,
  quantity       INT NOT NULL DEFAULT 1,
  gross_amount   NUMERIC(14,2) NOT NULL,          -- faturamento
  commission     NUMERIC(14,2) NOT NULL DEFAULT 0,
  commission_rate NUMERIC(7,4),
  status         TEXT NOT NULL DEFAULT 'pending', -- pending | confirmed | cancelled | paid
  buyer_hash     TEXT,                            -- comprador único, sem PII
  ordered_at     TIMESTAMPTZ NOT NULL,
  confirmed_at   TIMESTAMPTZ,
  source         TEXT NOT NULL,                   -- api | csv_import | manual
  raw            JSONB,
  imported_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (platform_id, external_id)
)
CREATE INDEX ON sales (owner_id, ordered_at DESC);
CREATE INDEX ON sales (bot_id, ordered_at DESC);
```

Uma tabela `sales` com a comissão embutida, não `sales` + `commissions`
separadas: na prática de afiliado a comissão é atributo da venda, e separar
criaria um 1:1 que só somaria join. Se uma plataforma pagar comissões
desacopladas do pedido, `commission_entries` entra depois — a decisão fica
registrada em [DECISIONS.md](DECISIONS.md#adr-005).

`status` importa: comissão de afiliado é estornável. O dashboard mostra
confirmado e pendente separados — ROI contando venda cancelada é ROI mentiroso.

`buyer_hash` é hash irreversível do identificador do comprador quando a
plataforma fornece. Permite "custo por comprador" sem guardar dado pessoal.

```sql
group_joins (
  id         BIGSERIAL PK,
  group_id   UUID REFERENCES groups(id),
  bot_id     UUID REFERENCES bots(id),
  campaign_id UUID REFERENCES campaigns(id),
  joined_at  TIMESTAMPTZ NOT NULL,
  member_hash TEXT,                     -- hash do número, nunca o número
  source     TEXT                       -- 'webhook' | 'poll' | 'manual'
)
```
Base de "quantidade de pessoas entrando nos grupos" e de "custo por entrada em
grupo" = gasto da campanha ÷ entradas no período.

---

## Operação e observabilidade

```sql
automation_runs (
  id            BIGSERIAL PK,
  bot_id        UUID REFERENCES bots(id),
  kind          TEXT NOT NULL,           -- 'cycle' | 'group_sync' | 'commission_import'
  status        TEXT NOT NULL,           -- running | success | partial | failed
  started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at   TIMESTAMPTZ,
  duration_ms   INT,
  offers_found  INT,
  offers_sent   INT,
  error         TEXT,
  detail        JSONB
)
CREATE INDEX ON automation_runs (bot_id, started_at DESC);

events (
  id          BIGSERIAL PK,
  bot_id      UUID REFERENCES bots(id),
  entity_type TEXT,
  entity_id   TEXT,
  level       TEXT NOT NULL,             -- info | warning | error | critical
  type        TEXT NOT NULL,             -- 'auth_expired' | 'send_failed' | 'group_inaccessible'
  message     TEXT NOT NULL,
  detail      JSONB,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
)
CREATE INDEX ON events (level, created_at DESC);

alerts (
  id            UUID PK DEFAULT gen_random_uuid(),
  owner_id      UUID NOT NULL REFERENCES users(id),
  type          TEXT NOT NULL,           -- bot_offline | auth_expired | cost_anomaly | ...
  severity      TEXT NOT NULL,           -- warning | critical
  entity_type   TEXT,
  entity_id     TEXT,
  title         TEXT NOT NULL,
  detail        TEXT,
  status        TEXT NOT NULL DEFAULT 'open',   -- open | acknowledged | resolved
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at   TIMESTAMPTZ,
  dedup_key     TEXT NOT NULL,
  UNIQUE (owner_id, dedup_key, status) DEFERRABLE
)
```

A distinção `events` × `alerts` é o que atende "não quero ver todo o ruído":
`events` é o log estruturado (área técnica, retenção 30 dias), `alerts` é o que
pede ação humana e aparece no topo do dashboard. Um alerta recorrente atualiza
`last_seen_at` em vez de criar linha nova — é o que evita 400 alertas do mesmo
cookie expirado. Resolve P9.

```sql
commands (
  id           BIGSERIAL PK,
  bot_id       UUID REFERENCES bots(id),
  type         TEXT NOT NULL,            -- pause | resume | run_now | sync_groups | reload_config
  payload      JSONB NOT NULL DEFAULT '{}',
  status       TEXT NOT NULL DEFAULT 'pending',  -- pending | running | done | failed
  requested_by UUID REFERENCES users(id),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  picked_at    TIMESTAMPTZ,
  finished_at  TIMESTAMPTZ,
  result       TEXT
)
CREATE INDEX ON commands (status, created_at) WHERE status = 'pending';
```
A caixa de entrada do worker (D3). Índice parcial porque a query quente é sempre
"o que está pendente".

```sql
metric_snapshots (
  id          BIGSERIAL PK,
  owner_id    UUID NOT NULL REFERENCES users(id),
  day         DATE NOT NULL,
  bot_id      UUID REFERENCES bots(id),
  group_id    UUID REFERENCES groups(id),
  platform_id INT  REFERENCES platforms(id),
  account_id  UUID REFERENCES platform_accounts(id),
  campaign_id UUID REFERENCES campaigns(id),
  sends INT, clicks INT, orders INT, buyers INT, joins INT,
  revenue NUMERIC(14,2), commission NUMERIC(14,2), spend NUMERIC(14,2),
  computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (owner_id, day, bot_id, group_id, platform_id, account_id, campaign_id)
)
```

Rollup diário, recalculado por job noturno (e sob demanda para o dia corrente).
**Não é fonte de verdade** — é cache derivado das tabelas acima, sempre
reconstruível. Existe porque comparação histórica de 12 meses varrendo `sales`
e `envios` crus fica lenta rápido. Só entra na fase 9; até lá as métricas são
calculadas ao vivo, que para o volume atual basta.

## Fórmulas das métricas

Fonte única de verdade para o cálculo — implementar em `core/metrics.py`, nunca
reimplementar no frontend.

| Métrica | Fórmula |
|---|---|
| Faturamento | `Σ sales.gross_amount` (status confirmed/paid) |
| Comissão / Receita | `Σ sales.commission` |
| Investimento total | `Σ expenses.amount` |
| Investimento em tráfego | `Σ expenses.amount` onde categoria = `trafego` |
| Lucro | `Σ commission − Σ expenses.amount` |
| ROI | `(comissão − investimento) / investimento` |
| ROAS | `faturamento / investimento em tráfego` |
| Custo por venda | `investimento / nº de pedidos` |
| Custo por comprador | `investimento / nº de `buyer_hash` distintos` |
| Custo por entrada em grupo | `gasto da campanha / nº de group_joins` |
| Conversão | `pedidos / cliques` |

Regra em todas: **denominador zero devolve `null`, não `0`.** No frontend `null`
é "sem dados", que é honesto; `0` seria mentira que parece métrica.
