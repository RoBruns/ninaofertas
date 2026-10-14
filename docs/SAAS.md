# Nina Bot como SaaS

Plano para o sistema atender outros clientes, cada um com a própria operação: suas
contas de afiliado, seus telefones, seus bots e seus grupos. A operação da Nina passa a
ser **um cliente entre outros** (o primeiro, marcado como interno). Cobrança real ainda
não existe; as fases S1 e S2 deixam o terreno pronto para ela.

Produto: **Nina Bot**. Identificadores internos (repositório `ninaofertas`, serviços da
Railway, emissor do JWT) continuam como estão: trocar não traz nada e derrubaria sessões.

## Diagnóstico (2026-10-14)

O ADR-007 já pôs `owner_id` nas tabelas e quase todas as rotas filtram por ele. Um
segundo usuário criado hoje veria o próprio dashboard vazio. Mas o isolamento tem furos
que, com um cliente de verdade, misturam as operações:

| # | Furo | Onde | Efeito para o cliente novo |
|---|---|---|---|
| 1 | Freio anti-ban "da conta" conta os envios de **todos** os bots de produção | `repositories._escopo_envios`, `monitor._freio_anti_ban` | Os envios do cliente gastam o teto diário da Nina, e vice-versa |
| 2 | Recado do Instagram da vó vai para **todos** os bots ativos | `worker/promo_instagram.py` | Os grupos do cliente recebem a propaganda da Nina a cada 4 h |
| 3 | `evolution_instance` do telefone é texto livre | `api/routers/phones.py` | O cliente pode digitar a instância da Nina e publicar pelo número dela |
| 4 | `/api/events` não filtra por dono | `api/routers/events.py` | O cliente lê o log técnico da Nina |
| 5 | `/api/audit-logs` não filtra por dono | `api/routers/audit.py` | O cliente lê a auditoria da Nina |
| 6 | `/api/users` lista e edita **todos** os usuários; papel `admin` é global | `api/routers/users.py`, `api/deps.py` | O admin do cliente desativa ou troca a senha de quem é da Nina |
| 7 | Alerta sem dono cai no primeiro admin | `core/alerts._first_admin` | Pode cair no cliente |
| 8 | Marca "Nina · Central de ofertas" fixa | `dashboard/index.html`, `BrandMark`, `api/main.py` | O cliente vê a marca da operação da Nina |

O que já é isolado e fica: bots, telefones, grupos, contas de afiliado e credenciais,
campanhas, despesas, vendas, métricas, alertas, status do sistema. Credenciais do cliente
são dele (cifradas com a mesma `CREDENTIALS_KEY`, acesso só pelo dono).

O que continua compartilhado, de propósito: o worker (um só, percorre os bots de todos),
o servidor Evolution (uma instância por telefone), o catálogo de ofertas capturadas
(`ofertas`; deduplicação e freio por grupo são isolados por conta, ADR-028) e as chaves do filtro de
público por IA (`TYPESAFE_API_KEY`, `ANTHROPIC_API_KEY`), pagas pela plataforma.

## Modelo: conta (tenant) acima do usuário

- Tabela nova `tenants` (a "conta" do cliente). Cada usuário pertence a uma conta
  (`users.tenant_id`), com papel dentro dela (`admin`, `operator`, `viewer`, os de hoje).
- Os `owner_id` existentes passam a apontar para `tenants`. A migração cria **uma conta
  por usuário existente com o mesmo UUID do usuário**, então nenhuma linha de dado é
  reescrita: só muda o alvo da chave estrangeira. As consultas trocam `user.id` por
  `user.tenant_id`.
- Contas criadas na migração são `is_internal = true` (são a operação da Nina) e ficam
  fora das métricas de SaaS (MRR, churn).
- `users.is_platform_admin`: quem administra a plataforma (o dono). Vê o painel da
  plataforma, cria contas de clientes. Não enxerga os dados operacionais do cliente pelo
  dashboard comum.

Por que conta e não "um usuário = um cliente": o cliente vai querer pôr um ajudante sem
dividir a senha, e a assinatura pertence à conta, não à pessoa. Fazer agora custa uma
troca mecânica de `user.id` por `user.tenant_id`; fazer depois seria a mesma troca com
mais dados e mais rotas.

## Fases

### S1 — Isolamento e marca (antes de dar acesso ao cliente)

1. `tenants`, `users.tenant_id`, `users.is_platform_admin`; FKs de `owner_id` para
   `tenants`; `audit_logs.tenant_id`.
2. Freio anti-ban da conta passa a contar só os envios da **mesma conta** (furo 1). Para a
   Nina é o comportamento de hoje, desde que todos os bots dela sejam do mesmo usuário
   (conferir na produção antes do deploy). Vira ADR.
3. Recado do Instagram vira opção por bot (`content.recado_instagram`, padrão desligado);
   a migração liga nos bots de produção que já existem (furo 2).
4. Instância Evolution única no sistema e definida pela plataforma: a API cria a
   instância (`/instance/create`) com nome gerado e devolve o QR code; o cliente não
   digita nome de instância (furo 3). O token da instância é guardado cifrado e o envio
   passa a usá-lo; criar, consultar, QR e grupos usam a chave geral (decisão do dono,
   2026-10-14; fase S1b).
5. Eventos, auditoria, usuários e alertas filtrados pela conta (furos 4–7).
6. Marca "Nina Bot" no dashboard e na API (furo 8).
7. Teste de isolamento por rota: duas contas, cada rota de leitura e escrita chamada com
   o id de um recurso da outra conta deve dar 404.

### S1b — Token da instância e conexão pelo dashboard (2026-10-14)

Implementada na branch `feat/saas-s1b`: migration 0008, token cifrado por
telefone, sincronização administrativa do token existente, QR com renovação
automática e estado de conexão. Número pode ficar vazio até a conexão, quando
é preenchido pelo `ownerJid`. Gerenciamento usa a chave geral; envio usa o token
da instância, com fallback para a chave geral quando ausente ou após 401 (uma
tentativa). ADR-029 registra a decisão; validação consta em `ROADMAP.md`.

### S2 — Painel da plataforma e terreno da cobrança

- `plans` (código, nome, preço `NUMERIC(14,2)`, periodicidade, limites em JSON: bots,
  telefones, grupos) com um plano `beta` gratuito.
- `subscriptions` por conta: status `trialing | active | past_due | canceled | comp`,
  período atual, data e motivo de cancelamento, preço praticado, `provider` e
  `provider_ref` vazios até existir gateway.
- `subscription_events`: histórico (criada, trocou de plano, cancelou, reativou). É dele
  que saem MRR e churn, sem depender do estado atual.
- Painel da plataforma (só `is_platform_admin`): contas, plano, status, uso (bots, envios
  e vendas no mês), novos clientes, cancelamentos, churn mensal (cancelados no mês ÷
  pagantes no início do mês), MRR, clientes pagantes. Contas internas ficam fora das
  contas.
- Criar conta de cliente pelo painel: conta + primeiro usuário admin com senha provisória.
- Limites do plano exibidos com o uso; **não bloqueiam** ainda.

### S3 — Depois (não está nesta obra)

- Gateway de cobrança (Asaas ou Mercado Pago para Pix/boleto; Stripe se for cartão
  internacional) com webhook atualizando `subscriptions`.
- Cadastro pelo próprio cliente, teste grátis, bloqueio por limite de plano e por falta
  de pagamento (pausar bots, não apagar).
- Custo do filtro de público por conta (contar chamadas por conta).
- Termos de uso e LGPD: os dados de grupos e vendas do cliente passam a estar sob nossa
  guarda.

## Riscos que crescem com o primeiro cliente

- **E-mail global como login**: o e-mail é único no sistema. A mensagem "e-mail já
  cadastrado" revela sua existência, inclusive em outra conta. Risco aceito pelo dono;
  alteração desse comportamento está fora da S1c.
- **Backup do `nina-db`**: hoje não existe. Com dados de cliente, perder o banco deixa de
  ser problema só nosso. Resolver antes ou junto da S2.
- **IP compartilhado nas fontes**: as buscas do cliente no Mercado Livre e na Shopee
  saem do mesmo IP da Railway que as da Nina. Mais volume pode fazer o ML bloquear o IP e
  derrubar a captura da Nina também. Acompanhar o evento de bloqueio por fonte depois que
  o cliente ativar.
- **Worker único**: percorre os bots em sequência a cada 60 s. Um cliente com poucos bots
  não pesa; muitos clientes alongam o ciclo. Medir a duração do ciclo (`automation_runs`)
  antes de pensar em vários workers.
- **Banimento**: o número do cliente é dele; banimento dele não afeta o da Nina. Os
  limites de `core/safety.py` valem para todos.
