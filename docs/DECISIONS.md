# Registro de decisões (ADR)

Toda decisão relevante, com alternativa considerada e motivo. Decisão que mudar
ganha um ADR novo com "supersedes" — nunca se reescreve o histórico.

---

## ADR-001 — Backend em Python/FastAPI no mesmo repositório
**Data:** 2026-09-22 · **Status:** aceita · **Decisor:** usuário

O bot é Python e funciona. Colocar a API em Node exigiria duplicar a lógica de
Shopee (assinatura HMAC), Mercado Livre (createLink com cookie) e filtros — ou
reescrever tudo, arriscando o que está em produção. Com FastAPI, API e worker
compartilham `core/` e a lógica de plataforma existe uma vez só.

**Alternativas:** NestJS + Prisma (stack única com o front, mas duplica lógica);
reescrever o bot em TS (coerência total, risco alto sem ganho operacional).

**Consequência:** duas linguagens no repo. Aceitável — a fronteira é HTTP, e o
frontend segue React/TS como pedido.

---

## ADR-002 — Reaproveitar o Postgres existente
**Data:** 2026-09-22 · **Status:** aceita

A instância da Railway está de pé, é interno-only e já guarda `ofertas`/`envios`.
Instância nova significaria custo adicional e impossibilidade de fazer join entre
métricas e envios — que é exatamente o que o dashboard precisa.

**Consequência:** um banco com três inquilinos (evolution-api em schema próprio,
bot e aplicação em `public`). Migrations passam a ser obrigatórias.

---

## ADR-003 — Config no banco com cache curto, em vez de fila/pub-sub
**Data:** 2026-09-22 · **Status:** aceita

O worker já relê o config a cada ciclo (`load_filtros()`), então leitura dinâmica
custa quase nada: troca-se `open(json)` por query com TTL de 30s. Para ações
imediatas (pausar, rodar agora, sincronizar grupos), a tabela `commands` é a
caixa de entrada drenada a cada loop.

**Alternativas:** Redis pub/sub (mais um serviço, mais um ponto de falha, para
um único worker); WebSocket worker↔API (acoplamento); reiniciar o serviço a cada
mudança (o usuário pediu explicitamente para evitar, e restart refaz o baseline).

**Consequência:** latência de até ~60s entre salvar e aplicar. Aceitável para
configuração de afiliado. Revisitar se surgir múltiplo worker.

---

## ADR-004 — Segredos cifrados no banco; chave-mestra em env var
**Data:** 2026-09-22 · **Status:** aceita

Credenciais de plataforma são operacionais (mudam toda semana — o cookie do ML
expira), então precisam ser editáveis pelo dashboard. Mas continuam segredo: vão
cifradas (AES-GCM) em `platform_credentials`, e `CREDENTIALS_KEY` permanece env
var da Railway. Segredo não virou config pública; virou segredo gerenciável.

A API é **write-only**: não existe rota que devolva valor de credencial, nem para
o admin. Expõe status, validade, último uso, último erro.

**Consequência:** perder `CREDENTIALS_KEY` invalida todas as credenciais — elas
precisam ser recolocadas. `key_version` permite rotação. Sem custódia externa por
ora (KMS seria overengineering aqui); documentado como risco aceito.

---

## ADR-005 — `sales` com comissão embutida, sem tabela `commissions`
**Data:** 2026-09-22 · **Status:** aceita

Em programa de afiliado a comissão é atributo do pedido: um pedido, uma comissão,
mesmo ciclo de vida (pendente → confirmada → estornada). Separar criaria um 1:1
que só adiciona join em toda query de métrica.

**Consequência:** se alguma plataforma pagar comissão desacoplada do pedido
(bônus, campanha de incentivo), entra `commission_entries` separada — sem mexer
em `sales`.

---

## ADR-006 — Polling no frontend, sem WebSocket
**Data:** 2026-09-22 · **Status:** aceita

TanStack Query com refetch de 10–30s. Métrica de afiliado não muda em tempo real
e ninguém fica olhando o painel esperando o número mexer. WebSocket exigiria
estado de conexão, reconexão e autenticação de socket — complexidade sem ganho.

**Consequência:** até 30s de atraso no painel. Revisitar se houver tela de
operação ao vivo.

---

## ADR-007 — `owner_id` desde o início, um usuário só
**Data:** 2026-09-22 · **Status:** aceita

Tabelas nascem com `owner_id` e as queries filtram por ele, com um único admin.
Adicionar usuário depois é inserir linha; adicionar `owner_id` depois seria
migration em todas as tabelas com backfill e revisão de toda query. O custo agora
é uma coluna e um filtro.

---

## ADR-008 — Freios anti-ban preservados, com teto no dashboard
**Data:** 2026-09-22 · **Status:** aceita

A lógica de rajada/hora/dia de `monitor.py` é o que impede o número de ser banido
pelo WhatsApp — custo de errar: perder o chip e os grupos. Ela migra sem
alteração. O dashboard permite ajustar os limites, mas a API valida contra tetos
em `core/safety.py` e recusa valores perigosos com 422.

**Consequência:** o usuário não consegue, pelo dashboard, afrouxar o ritmo além
do seguro. Intencional: o dashboard não pode ser o caminho fácil para queimar o
número. Mudar teto exige deploy — é raro e merece atenção.

---

## ADR-009 — Vendas por API onde houver, CSV onde não
**Data:** 2026-09-22 · **Status:** aceita · **Decisor:** usuário

Shopee expõe relatório de conversão na Open API; Mercado Livre e AliExpress
variam por programa. `core/importers/` abstrai os dois caminhos atrás do mesmo
contrato, com dedup por `(platform_id, external_id)` — reimportar é idempotente,
e migrar de CSV para API depois não duplica histórico.

---

## ADR-010 — Meta Ads: lançamento manual agora, importador projetado
**Data:** 2026-09-22 · **Status:** aceita · **Decisor:** usuário

O usuário roda Meta Ads mas prefere lançar gasto manualmente por ora.
`expenses.source` + `external_id` únicos deixam o importador pronto para plugar
sem duplicar o que foi lançado à mão.

**Consequência:** ROAS depende de lançamento manual em dia. O alerta de "dados
não atualizados" cobre gasto de tráfego sem lançamento há mais de X dias.

---

## ADR-011 — `rogstools` não faz parte deste projeto
**Data:** 2026-09-22 · **Status:** aceita

Serviço Railway no mesmo projeto, mas é app Vite/Supabase de outro contexto
(vars `VITE_SUPABASE_*`, nenhuma referência ao bot). **Não tocar.** Registrado
para que nenhum agente futuro o interprete como parte do sistema.
