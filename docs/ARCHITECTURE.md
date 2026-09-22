# Arquitetura — atual e alvo

> Documento vivo. Toda decisão relevante tem justificativa aqui ou em [DECISIONS.md](DECISIONS.md).

## 1. Estado atual (auditoria de 2026-09-22)

### 1.1 Infraestrutura Railway

Projeto `gallant-emotion` (ID `0655e0f9-0ad1-49b8-b08f-0c7baad584fa`), ambiente `production`:

| Serviço | Estado | Papel |
|---|---|---|
| `ninaofertas` | Online | O bot. Worker Python, sem porta HTTP exposta. |
| `evolution-api` | Online | Gateway WhatsApp (WhatsApp Web protocol). Volume 0.1/4.9 GB. |
| `Postgres` | Online | Banco do bot **e** da evolution-api. Sem URL pública (só rede interna). |
| `rogstools` | Online | **Não relacionado.** App Vite/Supabase de outro projeto. Não tocar. |

O Postgres não tem `DATABASE_PUBLIC_URL` nem TCP proxy — só é acessível de dentro
da rede Railway. Isso é uma boa postura de segurança e **deve ser mantida**: a API
nova roda dentro da mesma rede e fala com o banco pelo domínio interno.

### 1.2 O bot

Python 3, ~2.000 linhas, repositório `DiegoMiuraDev/ninaofertas`, branch `master`.

```
main.py         APScheduler: 2 jobs de ciclo (um por canal) + 1 job Instagram
  └ monitor.ciclo()      busca → filtra → dedup → afiliado → formata → envia
      ├ scraper/         CupomScraper, MercadoLivreScraper, ShopeeScraper
      ├ filters.py       critérios do config.json do canal
      ├ dedup.py         evita reenvio; reenvia se preço cair ≥ REENVIO_QUEDA_MINIMA
      ├ affiliate.py     Shopee GraphQL (HMAC) + ML createLink (cookie de sessão)
      ├ formatter.py     template de mensagem
      └ whatsapp.py      evolution-api /message/sendText|sendMedia
database.py     SQLAlchemy: 2 tabelas (ofertas, envios) + freios anti-ban
config.py       .env (Settings) + config.json/config.auto.json (filtros por canal)
```

**O pipeline funciona.** Logs ao vivo confirmam Mercado Livre (~690 ofertas/ciclo)
e Shopee (~480/ciclo) capturando normalmente, com os freios anti-ban ativos
(hoje travando em `limite 80/dia neste grupo`). Qualquer refatoração precisa
preservar esse comportamento.

### 1.3 Banco de dados atual

Schema criado por `Base.metadata.create_all()` — **não há migrations**.

```
ofertas(id, nome, preco, preco_anterior, desconto, loja, categoria,
        url UNIQUE, imagem, sku, capturado_em)
envios (id, oferta_id→ofertas, enviado_em, grupo, mensagem,
        preco_enviado, status)   -- status: 'sucesso' | 'falha' | 'visto'
```

`envios` é hoje a única fonte de métricas: os freios anti-ban contam linhas dessa
tabela por grupo/hora/dia. É também o único registro histórico da operação.

### 1.4 Problemas encontrados

Ordenados por impacto operacional.

**P1 — Canais/bots são hardcoded.** `config.py:CANAIS` define exatamente dois
canais, com `"ativo": True/False` no código-fonte. Criar um terceiro bot hoje
exige editar Python, commitar e redeployar. O canal `auto` está desligado por uma
constante. Isso é o núcleo do que você pediu para eliminar.

**P2 — Filtros em arquivos versionados.** `config.json` e `config.auto.json`
carregam nicho, termos de busca, palavras-chave, bloqueios, limites de ritmo e o
template da mensagem. Mudar um limite = commit + deploy. O `load_filtros()` já
relê o arquivo a cada ciclo, então a leitura dinâmica já existe — falta só trocar
a origem de arquivo para banco.

**P3 — Grupos e telefone em variável de ambiente e no código.** `WHATSAPP_GROUP_ID`
e `WHATSAPP_GROUP_ID_AUTO` são env vars; pior, o número do bot está **literal no
código** em `whatsapp.py:avisar_permissao_grupos()` (`"558531791835"`). Trocar
telefone exige editar código.

**P4 — Credenciais de plataforma são globais, uma por plataforma.** `Settings`
tem um `SHOPEE_APP_ID`, um `MERCADOLIVRE_AFFILIATE_COOKIE`. A arquitetura atual
**não comporta** múltiplas contas por plataforma — que é requisito central do
projeto.

**P5 — Cookie do ML expira e não há sinalização.** `STATUS.md` registra
`createLink: cookie expirou (401)`. Hoje a única forma de perceber é ler log, e a
única forma de corrigir é editar a env var na Railway e redeployar. Não há status
de autenticação, validade, nem alerta.

**P6 — Nenhuma métrica de negócio.** Não existe registro de clique, venda,
comissão, gasto ou campanha. `envios` diz o que foi enviado, nunca o que retornou.
Todo o painel de ROI/ROAS/CPA precisa de entidades novas — não há o que reaproveitar.

**P7 — Sem migrations.** `create_all` só cria tabelas ausentes; nunca altera
coluna existente. Evoluir o schema hoje é manual e arriscado.

**P8 — Estado do baseline em memória.** `_baseline_ciclos_feitos` é um dict de
módulo: todo restart refaz o baseline (5 ciclos sem enviar). Com o dashboard
podendo reconfigurar coisas, restarts ficam mais frequentes — isso vira um
problema real de operação, e é mais um motivo para **não** reiniciar o worker a
cada mudança de config.

**P9 — Sem observabilidade estruturada.** Logs só em texto, sem persistência de
erro, sem health check, sem "última execução com sucesso".

### 1.5 O que se aproveita

Muito, na verdade. O que está bem feito:

- `scraper/base.py` — `executar()` com retry e isolamento de exceção por fonte é
  um bom contrato. Mantido como está.
- `affiliate.py` — a lógica de assinatura Shopee e de createLink ML é conhecimento
  difícil de reconstruir. **Preservar o algoritmo**, mudando só a origem das
  credenciais (de `settings` global para conta de plataforma).
- `filters.py` / `dedup.py` — regras de negócio maduras e testadas em produção.
  Passam a receber os filtros do banco em vez do JSON; a lógica não muda.
- Freios anti-ban em `monitor.py` — a lógica de rajada/hora/dia é o que protege o
  número de ser banido. Preservada integralmente.
- `database.py` — models e helpers ficam; ganham migrations e tabelas novas.

Nada precisa ser jogado fora. A mudança é de **origem de configuração** e de
**modelo de dados**, não de pipeline.

---

## 2. Arquitetura alvo

### 2.1 Visão

```
┌──────────────────────────────────────────┐
│  Dashboard (React + TS + Vite)           │  Railway: nina-dashboard
│  Recharts · TanStack Query · shadcn/ui   │  (estático, servido por Caddy)
└──────────────┬───────────────────────────┘
               │ HTTPS · JWT · JSON
┌──────────────▼───────────────────────────┐
│  API (FastAPI + SQLAlchemy + Pydantic)   │  Railway: nina-api
│  auth · CRUD · métricas · alertas        │  (único serviço com porta pública)
└──────────────┬───────────────────────────┘
               │ Postgres (rede interna)
┌──────────────▼───────────────────────────┐
│  Postgres (a instância que já existe)    │  fonte única de verdade
└──────────────▲───────────────────────────┘
               │ lê config a cada ciclo · escreve eventos/métricas
┌──────────────┴───────────────────────────┐
│  Worker (o bot atual, refatorado)        │  Railway: ninaofertas
│  APScheduler · scrapers · evolution-api  │
└──────────────┬───────────────────────────┘
               │
       ┌───────┴────────┬──────────────┐
  evolution-api    Shopee API     Mercado Livre
   (WhatsApp)      (afiliados)     (ofertas + createLink)
```

**Três processos, um banco, um repositório.**

### 2.2 Decisões estruturais

**D1 — Monorepo, backend Python compartilhado.**
`api/` e o worker compartilham `core/` (models SQLAlchemy, repositórios,
credenciais, clientes de plataforma). A lógica de Shopee/ML existe uma só vez.
Se a API fosse Node, ou duplicaríamos essa lógica ou reescreveríamos scrapers que
hoje funcionam — risco sem retorno. O frontend é React/TS como pedido; a
fronteira entre eles é o contrato HTTP, não a linguagem.

**D2 — Reaproveitar o Postgres existente, em schema separado.**
O banco já está de pé e é interno-only. A evolution-api usa o schema
`evolution_api`; o bot usa `public`. A aplicação nova usa `public` também
(as tabelas `ofertas`/`envios` continuam lá e ganham vizinhas). Criar uma segunda
instância só somaria custo e um join impossível entre métricas e envios.

**D3 — Config no banco, lida a cada ciclo. Sem reiniciar serviço.**
O worker já relê o config a cada ciclo (`load_filtros()`). Trocamos o `open(json)`
por uma query com cache curto (TTL 30s). Mudança no dashboard aparece na operação
em ≤ 1 ciclo, sem restart, sem fila, sem pub/sub.
Para o que precisa ser imediato (pausar um bot, forçar um ciclo, renovar cookie),
uma tabela `commands` funciona como caixa de entrada que o worker drena a cada
loop. É a solução proporcional: Redis/pub-sub aqui seria complexidade sem ganho
para uma operação com um worker. Documentado em [DECISIONS.md](DECISIONS.md#adr-003).

**D4 — Segredos cifrados no banco, nunca no frontend.**
Credencial de plataforma (cookie ML, secret Shopee) vira linha em
`platform_credentials` com o valor cifrado em Fernet/AES-GCM. A chave-mestra
(`CREDENTIALS_KEY`) continua sendo env var da Railway — **secret não vira config**.
A API expõe só metadados: status, validade, última renovação, último uso, último
erro. O valor em claro nunca cruza a fronteira HTTP, em nenhuma rota, nem para o
admin. Escrita é write-only: manda-se o valor novo, nunca se lê o atual.

**D5 — Migrations com Alembic desde o primeiro dia.**
`create_all` não evolui schema. A primeira migration adota o schema existente
(`ofertas`, `envios`) sem recriá-lo, e as seguintes constroem o resto.

**D6 — Multi-tenancy pronta, sem multi-tenancy agora.**
Toda tabela relevante nasce com `user_id`/`owner_id` e as queries filtram por ele,
mas existe um único usuário admin. Adicionar o segundo usuário depois é criar
linha, não migrar schema.

### 2.3 Fluxo de dados

**Configuração (dashboard → operação)**
```
usuário salva bot no dashboard
  → POST /api/bots/{id}         (valida, grava, escreve audit_log)
  → Postgres
  → worker, no próximo ciclo (≤60s), lê bots ativos e aplica
```

**Operação (bot → métricas)**
```
ciclo do worker
  → captura ofertas → filtra → dedup → link afiliado → envia
  → grava: envios (já existe) + automation_runs + events
  → dashboard lê agregações via /api/metrics/*
```

**Atribuição de receita (o elo que falta hoje)**
```
envio  →  link afiliado com tracking sub_id = {bot}:{grupo}:{oferta}
                                    ↓
              relatório de comissão (API onde houver, CSV onde não)
                                    ↓
              sales / commissions, reconciliados pelo sub_id
                                    ↓
              ROI, ROAS, custo por venda, custo por comprador
```
O `sub_id` é o que torna possível atribuir receita a bot/grupo/campanha. Sem ele
as métricas por bot e por grupo seriam estimativa. Shopee e ML aceitam sub_id no
link de afiliado — a fase 6 implementa e valida isso.

### 2.4 Serviços Railway ao final

| Serviço | Novo? | Porta pública | Observação |
|---|---|---|---|
| `ninaofertas` | existente, refatorado | não | worker |
| `nina-api` | **novo** | sim | única superfície exposta |
| `nina-dashboard` | **novo** | sim | estático |
| `evolution-api` | existente, intocado | sim | já exposto hoje |
| `Postgres` | existente | não | interno-only, mantido |
| `rogstools` | alheio | — | não tocar |

### 2.5 O que explicitamente não faremos agora

Registrado para não virar escopo por inércia:

- **Redis / fila de jobs.** Um worker, ciclo de 60s. `commands` + APScheduler
  resolve. Entra quando houver múltiplos workers concorrendo.
- **Kubernetes, microserviços, event sourcing.** Operação de um usuário.
- **WebSocket.** O dashboard faz polling via TanStack Query (10–30s). Métrica de
  afiliado não muda em tempo real; ninguém fica olhando o painel esperando o
  número mexer. Revisitar se houver tela de operação ao vivo.
- **Reescrever scrapers em TS.** Funcionam. Reescrever é risco puro.

---

## 3. Riscos

| Risco | Impacto | Mitigação |
|---|---|---|
| Quebrar o bot que está no ar | alto | Cada fase mantém o worker rodando. Migração de config é aditiva: lê do banco, cai para o JSON se vazio. Rollback = reverter deploy do worker. |
| Migration corromper `ofertas`/`envios` | alto | Migration inicial só faz `stamp` do schema existente. Backup via `pg_dump` antes de cada migration destrutiva. Nenhuma fase dropa coluna dessas tabelas. |
| Cookie ML expira durante a obra | médio | Já é problema hoje. Fase 5 entrega renovação pelo dashboard + alerta — melhora, não piora. |
| Shopee/ML mudarem a API | médio | Isolado em `core/platforms/`. Contrato do scraper não muda. |
| Ban do número no WhatsApp | alto | Freios anti-ban preservados **integralmente**. O dashboard valida limites contra um teto de segurança e avisa ao afrouxar. |
| Codex quebrar código que funciona | médio | Cada fase tem critério objetivo de conclusão, roda em branch própria, e eu reviso e testo antes do merge. Fases que tocam o pipeline vivo são as mais tardias. |
| Sub_id não ser aceito pelas plataformas | médio | Validar cedo (fase 6, spike antes de construir). Se falhar, atribuição cai para nível de conta/campanha e as métricas por grupo viram estimativa — documentado como limitação, não bug. |
