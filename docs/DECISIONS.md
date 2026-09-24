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

---

## ADR-012 — Baseline legada não materializa `ofertas`/`envios`
**Data:** 2026-09-22 · **Status:** aceita

A revision `0001` habilita `pgcrypto`/`citext`, mas nunca cria nem altera as
tabelas legadas. Em um banco vazio, as revisions seguintes criam todo o schema
novo e omitem condicionalmente as FKs e colunas que dependeriam de `ofertas` e
`envios`. Em produção, onde as tabelas existem, as relações são criadas.

**Motivo:** criar as legadas na baseline contrariaria a regra de adoção e
duplicaria um DDL que pertence ao worker histórico. A condicional mantém tanto a
segurança de produção quanto o teste de `upgrade head` em banco vazio.

**Detalhes de implementação:** os modelos mantêm `Float` e timestamp sem timezone
nas colunas antigas porque mudar tipos seria destrutivo. O fingerprint de
credencial usa os primeiros 16 bytes do SHA-256 (32 caracteres hexadecimais).
Extensões não são removidas no downgrade por serem objetos globais potencialmente
compartilhados por outros schemas.

---

## ADR-013 — Exclusão de usuário é desativação lógica
**Data:** 2026-09-22 · **Status:** aceita

`DELETE /api/users/{id}` define `is_active=false` em vez de remover a linha. A
FK `audit_logs.user_id` não usa `ON DELETE SET NULL`; uma exclusão física apagaria
a identidade do autor ou falharia depois da primeira ação auditada. Usuário
inativo não autentica e seus access/refresh tokens deixam de ser aceitos.

**Consequência:** o e-mail continua reservado e o usuário permanece disponível
para investigação histórica, embora a API responda `204` como operação de
remoção administrativa.

---

## ADR-014 — Receita: Shopee pela API, Mercado Livre pelo painel
**Data:** 2026-09-23 · **Status:** aceita · **Decisor:** usuário + orquestrador
**Refina:** ADR-009

O ADR-009 previa "API onde houver, CSV onde não". A validação com as contas
reais mudou a segunda metade:

- **Shopee:** `conversionReport` da Affiliate Open API responde com as
  credenciais atuais (HTTP 200, sem erros). Zero conversões em 90 dias,
  confirmado pelo usuário como ausência real de venda, não falha de acesso.
- **Mercado Livre:** não oferece API nem export CSV de comissões. O painel
  `/afiliados/dashboard` é renderizado no servidor e embute todas as abas num
  JSON (`_n.ctx.r` → `appProps.pageProps`). A leitura é desse JSON, não do
  HTML visual, com o cookie de sessão da conta (credencial cifrada, ADR-004).
  Validado: a soma das vendas individuais bate ao centavo com os totais do
  painel (R$ 238,30 de comissão, R$ 3.198,80 de vendas no período testado).

O CSV continua existindo como caminho de reserva e de importação histórica.

**Riscos aceitos:**
- O formato do painel do ML pode mudar sem aviso. Mitigação: reconciliação
  automática entre linhas e totais; divergência vira evento e alerta.
- `purchaseId` falta em parte das vendas do ML. A chave de idempotência é `id`.
- O parâmetro de paginação do ML é desconhecido (10 itens por página). A
  sincronização pede um dia por vez e alerta quando um dia estoura a página,
  em vez de perder venda em silêncio.
- A sessão do ML expira. Tratado como credencial `invalid` + alerta de renovar.

---

## ADR-015 — Atribuição no Mercado Livre por etiqueta de rastreamento
**Data:** 2026-09-23 · **Status:** proposta (decisão final na fase 7)

O painel do ML agrega cliques, conversão e ganhos por **etiqueta de
rastreamento** (`earnings.item_list[].tag`). Hoje a conta usa uma só
(`midi5623028`). Com uma etiqueta por bot ou por grupo, o próprio ML entrega a
métrica separada, sem redirect próprio e sem mudar o formato do link enviado.

A venda individual (`sales.item_list`) **não** traz a etiqueta; a atribuição
por etiqueta é agregada (cliques, pedidos e ganhos por etiqueta), não por venda.
Para o produto isso basta: as perguntas são "qual bot/grupo rende mais", não
"quem comprou o quê".

Na Shopee, o equivalente é `utmContent`, que volta por conversão.

**A decidir na fase 7:** granularidade (etiqueta por bot ou por grupo) e o
limite de etiquetas que a conta do ML aceita.

---

## ADR-016 — Deduplicação de alertas por índice único parcial
**Data:** 2026-09-23 · **Status:** aceita · **Corrige:** desenho de `alerts` em DATABASE.md

O desenho original de `alerts` usava `UNIQUE (owner_id, dedup_key, status)`.
Os dois requisitos do ciclo de vida — no máximo um alerta ativo por causa, e
histórico ilimitado de resolvidos — eram violados por ele:

- `open` e `acknowledged` são status diferentes, então a constraint aceitava
  **dois alertas ativos** para a mesma causa;
- ao resolver pela segunda vez um alerta com a mesma chave (o cookie do ML que
  expira toda semana), já existiria um `resolved`, e o UPDATE seria recusado.

A migration `0004` troca a constraint por um índice único **parcial**:
`(owner_id, dedup_key) WHERE status IN ('open','acknowledged')`. A garantia de
"um ativo por causa" fica no banco, protegendo também contra dois jobs de
detecção concorrentes.

**Consequência:** o `downgrade` da 0004 recria a constraint antiga e falha se já
houver dois alertas resolvidos com a mesma chave — ou seja, depois de uso real
a 0004 é de mão única. Aceito: voltar ao desenho antigo reintroduziria o bug.

**Processo:** a spec pedia para relatar antes de criar migration; o agente criou
e relatou depois. A mudança foi revisada e mantida por ser a correção certa de
um erro do orquestrador.
