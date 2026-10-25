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

**Restauração lógica (2026-10-14):** `scripts/restore_db.py` executa Alembic até
a revisão do manifesto em um banco vazio e materializa por
`Base.metadata.create_all` somente `ofertas`/`envios` que constam no backup.
Não altera a baseline nem cria tabelas administrativas pelo metadata, preservando
as migrations como fonte dos gatilhos, constraints e seeds. O procedimento e
seu teste de restauração em Postgres real estão em `docs/DEPLOYMENT.md`.

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
**Data:** 2026-09-23 · **Status:** aceita em 2026-09-24 — **uma etiqueta por bot** (decisão do usuário)

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

---

## ADR-017 — Granularidade da atribuição: bot no ML, bot+grupo na Shopee; sem redirect
**Data:** 2026-09-24 · **Status:** aceita · **Decisor:** usuário

- **Mercado Livre: uma etiqueta de rastreamento por bot.** Menos etiquetas para
  criar e manter no painel do ML. Consequência aceita: no ML o dashboard mostra
  desempenho por bot, não por grupo dentro do bot.
- **Shopee: identificador automático de bot e grupo no link** (`subIds` do
  `generateShortLink`, que volta como `utmContent` no `conversionReport`). O
  cliente não vê diferença no link.
- **Sem redirect próprio (`/r/{code}`)**: ele trocaria o link que chega aos
  grupos, e o usuário pediu atribuição sem mudança visível. Cliques vêm das
  plataformas (o painel do ML traz cliques por etiqueta), não de um contador
  nosso. A tabela `clicks` fica sem uso por ora.

**Pendência técnica:** a venda individual do ML não traz a etiqueta. O painel
agrega por etiqueta e tem um filtro por etiqueta (`generalAudiences.filterTag`),
mas o parâmetro de URL desse filtro é desconhecido. Descobri-lo exige um spike
com cookie válido da conta — feito pela credencial cifrada do dashboard, não
por cookie colado na conversa.

---

## ADR-018 — Teto diário opcional; teto por hora e intervalo seguem obrigatórios
**Data:** 2026-09-24 · **Status:** aceita · **Decisor:** usuário · **Refina:** ADR-008

Em 2026-09-23 a produção passou a rodar **sem teto diário** (`max_ofertas_por_dia`
e `max_ofertas_globais_por_dia` = `0`, commit `a829256`, de outro desenvolvedor
direto na `master`). A trava do dashboard exigia teto diário entre 1 e 120 e
recusaria essa configuração — inclusive ao converter os canais em bots.

Decisão: `0` nos dois tetos diários significa **desligado** e é aceito. O que
continua obrigatório, com os mesmos tetos de `core/safety.py`, é o ritmo curto:
`max_ofertas_por_hora ≤ 15`, `max_ofertas_globais_por_hora ≤ 20`, intervalo
`≥ 2 min`, rajada `≤ 5`. Com 6/hora, o máximo prático é ~144/dia por grupo.
Valor diário **positivo** continua limitado a 120/150.

**Consequência:** o dashboard deixa de impedir a remoção do teto diário. O
risco de ban passa a ser contido só pelo ritmo por hora e pelo intervalo.

---

## ADR-019 — Integração contínua das mudanças feitas direto na `master`
**Data:** 2026-09-24 · **Status:** aceita · **Decisor:** usuário

Outro desenvolvedor (miura) altera o bot direto na `master`, que é o que roda em
produção, enquanto o dashboard é construído em `feat/dashboard`. Decisão: o
orquestrador integra essas mudanças na branch do dashboard sempre que aparecerem,
**preservando o comportamento de produção** (é a verdade da operação), e avisa o
usuário a cada integração. Antes de qualquer deploy, `git fetch` e verificação de
divergência com `origin/master` são obrigatórios.

## ADR-020 — Sem modo legado: o worker só publica bots do dashboard
**Data:** 2026-09-24 · **Status:** aceita · **Decisor:** usuário · **Substitui:** o
fallback para `config.json`/env descrito em BOT_INTEGRATION (fase 6)

O bot antigo continua rodando em produção até o deploy; a versão nova não precisa
reproduzi-lo. Decisão: **tudo que o worker publica vem do dashboard.**

- Sem bot `active` com telefone e grupo, o worker fica ocioso e avisa no log uma
  vez. Não há mais fallback para `config.json`, `WHATSAPP_GROUP_ID*` nem para as
  credenciais de plataforma da env.
- O envio usa a instância Evolution do **telefone do bot** (`phones.evolution_instance`),
  não `EVOLUTION_INSTANCE`.
- Credenciais só da conta vinculada ao bot. O ciclo só busca e publica ofertas das
  plataformas em que o bot tem conta ativa com credencial não invalidada: sem
  conta, o link sairia sem comissão.
- A API só ativa um bot que o worker consegue rodar: telefone com instância, ao
  menos um grupo e ao menos uma conta com credencial. A mensagem diz o que falta.
- A env do worker fica só com infraestrutura: `DATABASE_URL`, `EVOLUTION_API_URL`,
  `EVOLUTION_API_KEY`, `CHECK_INTERVAL`, `REENVIO_QUEDA_MINIMA`, `LOG_LEVEL`.
- `config.json`/`config.auto.json` servem só ao seed, que os importa como bots
  pausados.

Consequência: pausar todos os bots **para** a publicação (antes, devolvia ao
legado). O deploy configura e ativa os bots no dashboard **antes** de trocar o
worker — o código antigo ignora a tabela `bots` — para não haver janela sem envio.

---

## ADR-021 — Uma oferta por bot é entregue a todos os seus grupos
**Data:** 2026-09-29 · **Status:** aceita · **Decisor:** usuário

Com mais de um grupo, rodar um ciclo completo por grupo fazia o primeiro grupo
consumir sempre a janela do freio anti-ban e deixava os seguintes sem ofertas.
Decisão: o ciclo seleciona a oferta uma vez por bot e a envia aos grupos que
ainda não a receberam; o freio por número conta uma oferta distinta, mesmo que
gere várias mensagens.

**Consequência:** dois grupos dobram o volume de mensagens do número. Para
reduzir esse volume, o controle é o limite por hora do bot; o intervalo segue
entre ofertas, não entre as mensagens da mesma oferta.

---

## ADR-022 — Mudanças da V1 portadas como comportamento geral e opções por bot
**Data:** 2026-09-30 · **Status:** aceita

As melhorias do Miura feitas na V1 foram trazidas para a V2 sem `cozinha.py` ou
IDs fixos de grupo. Validação de cupom, link afiliado, cookie da conta e
bloqueios são comportamentos gerais. Alternância de loja e exceções de filtro do
Mercado Livre são opções em `settings.filters`, editáveis no dashboard e
aplicadas ao bot inteiro, inclusive quando ele publica em mais de um grupo.

---

## ADR-023 — Bot de teste fora do freio anti-ban da conta
**Data:** 2026-10-02 · **Status:** aceita · **Decisor:** usuário

O dashboard passa a ter bots de teste, para validar uma configuração antes de
importá-la para um bot de produção. Os grupos de teste normalmente não têm
pessoas, e o dono decidiu que os envios de teste não devem tirar cota da
produção. Decisão: no freio anti-ban, os controles da conta (intervalo entre
ofertas, rajada, `max_ofertas_globais_por_hora` e `max_ofertas_globais_por_dia`)
ignoram envios de bots de teste quando avaliam um bot de produção, e um bot de
teste é avaliado só contra os próprios envios. Os controles por grupo continuam
contando todos os envios do grupo dentro da mesma conta (escopo explicitado no ADR-028).

**Consequência:** um bot de teste no mesmo número soma mensagens ao volume real
do chip, fora do teto global. O risco fica limitado pelos tetos do próprio bot de
teste (os mesmos de `core/safety.py`) e pelos tetos por grupo, que continuam
valendo quando um teste aponta para um grupo de produção. A importação copia
`settings` e `message_template`, nunca `settings.attribution`, e guarda a
configuração anterior do destino em `bot_config_backups` para desfazer.

---

## ADR-024 — Mais vendidos como origem opcional de produtos
**Data:** 2026-10-02 · **Status:** aceita · **Decisor:** usuário

O bot procurava novidades e descartava produto com mais de 20 vendas
(`max_vendas`). O dono quer recomendar produtos que comprovadamente vendem.
Decisão: cada bot escolhe `filters.origem_produtos` (`novidades`, padrão e
comportamento anterior; `mais_vendidos`; `ambos`). Mais vendido só entra com
desconto conhecido e acima do mínimo do bot, e na Shopee com `min_vendas`; o
`max_vendas` não se aplica a ele. Fora de `novidades`, os produtos de cada loja
são enviados por pontuação (demanda 45%, desconto 35%, nota 10%, comissão 10%).

Fontes, medidas em 2026-10-02: a API oficial do Mercado Livre (`/highlights`,
`/trends`) responde 403 PolicyAgent mesmo com token de aplicativo, então o ML usa
a página pública `/mais-vendidos` (top 20 por categoria), guardada por 30 minutos
para não multiplicar acessos com o cookie da conta. A Shopee usa a API de
afiliados com `sortType: 2`; o `sortType: 1` usado até aqui é relevância, não
"mais recentes".

**Consequência:** a mudança só vale para quem trocar a opção, de preferência
primeiro num bot de teste (ADR-023). A deduplicação por grupo impede repetir o
mesmo mais vendido, salvo queda de preço.

---

## ADR-025 — Classificador de público selecionável por bot, com falha aberta
**Data:** 2026-10-13 · **Status:** aceita · **Decisor:** usuário

O dono vai comparar Jev e Claude Haiku antes de escolher o classificador. Cada bot
seleciona `filters.classificador_publico` (`jev`, padrão; `haiku`), quando tem
`publico_alvo` preenchido. Haiku usa o SDK oficial da Anthropic, com modelo e
parâmetros fixos conforme a especificação da etapa 2; ambas as chaves são opcionais
e ficam somente no worker ou no `.env` local para a comparação.

Cache e avisos de chave ausente são separados por provedor. A rejeição persistida
inclui o classificador, permitindo reavaliar após uma troca. Sem a chave selecionada
ou em falha/recusa, a classificação não bloqueia o envio e não troca de provedor;
os filtros locais, deduplicação e freio anti-ban continuam valendo.

O script de comparação não envia mensagens nem acessa o banco. Avalia a capacidade
de barrar produtos fora do público pela precisão e revocação de `nao` no limiar
informado, excluindo respostas `None` das métricas de qualidade e contando-as à parte.
Nenhuma escolha de provedor em produção foi feita nesta etapa.

---

## ADR-026 — Sincronização financeira e conciliação por conta e data
**Data:** 2026-10-13 · **Status:** aceita

Uma sincronização sem vendas novas é bem-sucedida, mas a última venda importada
não muda. A saúde de sincronização e o histórico passam a usar um registro de
sucesso em `audit_logs` (`sale_import`, `sync_success`), independente das vendas
e de `platform_credentials.last_success_at` (também atualizado ao gerar links).
Persistimos origem automática/manual, dono, conta e contagens, sem credenciais.
Usar a auditoria existente evita uma migration e preserva o histórico além da
retenção dos eventos técnicos. Falhas continuam nos eventos existentes e não
avançam a data de sucesso. Não fabricamos histórico de sincronizações passadas.

A conciliação do ML compara **comissão** das linhas com comissão do painel. O
bruto do painel e o bruto das linhas podem ter bases distintas de itens e
quantidades; com comissão igual, diferença de bruto não é falha financeira.
Os dois brutos permanecem no diagnóstico quando a comissão diverge.
O evento é emitido uma vez por conta/data e a chave do alerta inclui essa data,
com o índice parcial da ADR-016 garantindo um único alerta ativo. Uma causa
resolvida dessa mesma data não reabre a cada reimportação.

**Atualização 2026-10-13 — escolha do classificador.** Com os 99 produtos que o
Nina enviou, marcados em `scripts/dados/produtos_nina_enviados.csv` (29 fora do
público, 70 dentro; marcação feita pelo Claude a pedido do dono), o Jev no corte
0,6 acertou 91/99: barrou 27 dos 29 fora do público e 6 do público, quase todos
chuveiros e torneira, casos de fronteira. O Haiku 5.5 acertou no máximo 86/99
(corte 0,4) e barra eletrodomésticos e móveis em qualquer corte. Decisão: Jev,
corte 0,6. `TYPESAFE_API_KEY` está no `nina-worker`; o filtro está ligado no bot
de teste e o Nina segue sem ele até a importação.

---

## ADR-027 — Conta acima do usuário no Nina Bot
**Data:** 2026-10-14 · **Status:** aceita · **Decisor:** usuário (fase S1)

A operação pertence a `tenants`, e cada usuário pertence a uma conta. `owner_id`
mantém o nome e passa a referenciar `tenants.id`; `created_by`, `requested_by` e
`audit_logs.user_id` continuam referenciando o usuário autor. Papéis admin,
operator e viewer valem dentro da conta. `is_platform_admin` é uma permissão
separada, usada apenas para administrar a plataforma e configurar instâncias.

A migration 0007 cria uma conta interna por usuário existente com o mesmo UUID
(`tenants.id = users.id`), sem reescrever donos operacionais. Só o usuário de
`ADMIN_EMAIL` (sem distinguir maiúsculas) vira platform admin; sem correspondência,
é escolhido o admin ativo mais antigo (`created_at`, UUID como desempate). A
migração promove no máximo um usuário; o seed garante o de `ADMIN_EMAIL`.
Usuários novos de uma conta nunca herdam essa permissão. Um admin comum não pode
trocar e-mail, senha, papel ou atividade de um platform admin, nem removê-lo.
Contas de clientes são externas. Auditoria e eventos carregam a conta, com
eventos de sistema sem dono visíveis apenas a platform admins. Login, refresh
e acesso autenticado recusam contas suspensas; a suspensão pausa bots ativos,
e a reativação mantém os bots pausados até decisão do cliente. Comandos pendentes,
sincronização de vendas e detectores de alerta também respeitam a suspensão.
Ações da plataforma ficam na auditoria da conta afetada, com o usuário autor.

O produto se chama Nina Bot; repositório, serviços Railway e emissor JWT não
mudam. A plataforma gera instâncias Evolution para clientes; nomes livres
continuam permitidos a platform admins para preservar os telefones da Nina.

---

## ADR-028 — Freio anti-ban e deduplicação escopados por tenant
**Data:** 2026-10-14 · **Status:** aceita · **Decisor:** usuário (fase S1)

Intervalo, rajada e tetos da conta contam apenas envios dos seus bots de produção,
mais envios sem bot vinculados a grupos da conta. Quando o histórico não tem
`group_id`, o WhatsApp ID do grupo é usado como fallback, preservando os envios
legados. Um `group_id` conhecido distingue contas mesmo com JID igual.
Bots de teste seguem com escopo próprio nos controles globais. A contagem continua
uma oferta por slot, mesmo com múltiplos grupos. Tetos por grupo, cupons,
deduplicação, histórico de SKU/nome/preço e ordem de envio também exigem a conta,
e são compartilhados entre os bots de produção e teste **dessa conta**. Se dois
clientes publicarem no mesmo grupo físico, cada um tem seu próprio teto.
Consultas sem `tenant_id` falham; o freio sem runtime bloqueia com
"sem bot em execução". A contagem no painel da plataforma usa o mesmo helper.
Nenhum limite de `core/safety.py` foi alterado.

Para a operação da Nina, com os bots sob a mesma conta e os grupos legados
cadastrados, o resultado é o mesmo de antes. Testes comparam os cenários do freio
anterior e verificam que o teto, a deduplicação e o último envio de uma conta não
afetam outra, inclusive com o mesmo JID.
Antes do deploy, o dono deve conferir essa condição nos dados de produção.

O recado do Instagram respeita o mesmo escopo de intervalo e vira opt-in por bot.
Todos os bots existentes recebem `content.recado_instagram=true` na migração;
novos bots recebem false. Os novos recados registram bot e grupo, mantendo
mensagem, horário de silêncio e intervalo de quatro horas.

---

## ADR-029 — Token por instância Evolution com fallback de envio
**Data:** 2026-10-14 · **Status:** aceita · **Decisor:** dono (fase S1b)

Cada telefone tem uma instância própria. O dashboard cria a instância sem
informar token; o servidor gera o segredo. A API guarda esse token cifrado com
AES-GCM e `CREDENTIALS_KEY`, junto de fingerprint e data da gravação. Só status
e fingerprint são expostos; token, ciphertext e corpos contendo segredo nunca
entram em resposta pública, log, evento ou auditoria.

Gerenciamento (criar, consultar, QR, estado e grupos) usa `EVOLUTION_API_KEY`.
Envio usa o token da instância. Sem token, usa a chave geral para preservar a
Nina durante a transição; 401 do token permite uma única tentativa com a chave
geral e emite `evolution_instance_token_rejected` com nível warning e tenant.
O guard rejeita 401 antes do envio; nenhum outro erro permite repetir a mensagem.

O telefone é bloqueado para conexão e o nome é reservado e flushed no banco
antes da chamada externa. Falha de criação reverte a reserva; conflito de nome
no provedor recupera token de uma tentativa anterior. Nome e token são commitados
antes da consulta adicional de QR, preservando o vínculo se o QR falhar. Nomes
livres de platform admin aceitam só letras ASCII, números, ponto, hífen e
underscore, até 64 caracteres. Alterar nome limpa o token da instância anterior.

Número pode ser null até conectar; ao conectar, a API preenche pelo `ownerJid`
se ainda ausente. O dashboard acompanha o estado a cada 3 s, renova QR a cada
30 s ou na expiração e fecha o painel quando conectado. O contrato aceita hash
string de v2 e objeto apikey antigo. A migration 0008 depende de 0007; nenhum
limite anti-ban ou algoritmo de deduplicação é alterado.

---

## ADR-030 — Cobrança manual por livro-razão de eventos
**Data:** 2026-10-14 · **Status:** aceita · **Decisor:** dono (fase S2)

A plataforma registra planos e assinaturas manualmente, sem gateway, restrição
de uso, pausa automática ou mudança no worker. Cada conta externa pode ter uma
assinatura; contas internas não têm assinatura e ficam fora de todas as métricas
de SaaS. O catálogo começa com o plano mensal gratuito `beta`.

Toda criação ou alteração passa por `core.billing_store.change_subscription`.
O lock da conta serializa alterações, inclusive a criação inicial. Assinatura,
evento de MRR e auditoria são confirmados na mesma transação. O livro-razão
`subscription_events` só admite inserção (trigger recusa UPDATE e DELETE);
eventos no mesmo instante são ordenados por id. Não existe histórico financeiro
retroativo fabricado para contas anteriores à S2: a primeira edição cria o contrato
e seu evento naquele instante. A migration não cria assinaturas para contas existentes.

O preço contratado é independente do catálogo. Trocar o preço do plano não muda
assinaturas; trocar de plano adota preço e periodicidade do destino, salvo valores
explícitos. Plano inativo não aceita novos contratos nem migrações para ele; contratos
existentes continuam editáveis. BRL é a moeda suportada nesta fase, evitando somar
moedas distintas no MRR. Limites são informativos; ausência da chave significa ilimitado.

`core/billing.py` permanece a definição oficial: MRR mensal/anual só para `active`
e `past_due`; pagantes são reconstruídos pelo último evento no instante analisado.
Churn compara pagantes da abertura e do fechamento do mês em Brasília, incluindo
rebaixamentos para gratuito; cancelar e reativar no mesmo mês não é churn.
Expansão e contração só contam quem permaneceu pagante; denominadores zero
retornam null. O frontend apenas apresenta as métricas e usa números para desenhar
o gráfico, preservando strings decimais em valores, formulários e tooltips.

Na S3, webhooks do gateway chamarão a mesma função transacional. Cadastro público,
pagamentos e bloqueios por inadimplência ou limites ficam para essa fase.

---

## ADR-031 — Comissão mínima opt-in e cupom Shopee na vaga existente
**Data:** 2026-10-19 · **Status:** aceita · **Decisor:** usuário

Vendas com comissão de centavos não valem o envio, e o cupom da Shopee quase
nunca saía porque a captura quebrava. Decisão: `filters.comissao_minima_reais`
(padrão 0, desligado) descarta a oferta cuja comissão estimada, preço vezes
taxa, fique abaixo do piso. A taxa da Shopee passa a vir em toda busca. Sem
taxa, a oferta segue — o Mercado Livre não informa comissão na página, e
cortá-lo zeraria a loja. Dentro de cada loja, a maior estimativa vai na frente;
sem taxa, a ordem anterior fica no fim. O score de mais vendidos só desempata.

O cupom da Shopee ocupa a primeira vaga do ciclo enquanto couber em
`max_cupons_por_dia`. Conta 1 no freio, como qualquer oferta. Com o teto cheio,
o cupom é pulado e o produto daquele ciclo segue. Não há mensagem extra.

---

## ADR-032 — Prioridade de loja opt-in, com reserva no mesmo ciclo
**Data:** 2026-10-19 · **Status:** aceita · **Decisor:** usuário

A comissão do Mercado Livre costuma compensar mais que a da Shopee, mas o ciclo
revezava quem começava a fila. Decisão: `filters.prioridade_loja` (`alternar`,
padrão; `mercado_livre`; `shopee`). O padrão preserva o revezamento. Com uma
loja escolhida, os produtos dela vão todos na frente; a outra loja fica de
reserva no mesmo ciclo, para o grupo não ficar em silêncio quando a preferida
não tem oferta enviável. `uma_loja_por_ciclo` continua exclusivo e alternado.
O cupom da Shopee, quando cabe no teto, segue na primeira vaga.

