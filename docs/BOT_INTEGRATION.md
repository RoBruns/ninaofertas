# Integração dashboard ↔ bot

Como a camada de gestão controla a operação sem reiniciar serviço e sem que o
frontend fale com componente interno do bot.

## Fronteiras

### Público do grupo e palavras-chave

As palavras-chave, bloqueios e exceções usam prefixo de palavra no texto minúsculo
e sem acento: `unha` aceita `unhas`, mas `anel` não aceita `canela` e `colar` não
aceita `escolar`. Termos compostos e pontuação são literais, com fronteira à esquerda.

`filters.publico_alvo` (até 500 caracteres; padrão vazio) habilita a classificação
por bot. `filters.classificador_publico` aceita `jev` (padrão) ou `haiku`, selecionado
no dashboard junto do público. `filters.relevancia_minima` vai de 0 a 1, com padrão 0,6. Fluxo:
filtros locais → deduplicação por grupo → classificador uma vez por oferta/bot → freio anti-ban
→ links de afiliado e envio aos grupos candidatos. Baseline, cupons e campanhas não
consultam o classificador. A dispensa de palavras-chave por categoria do ML não dispensa o público.

O worker usa `TYPESAFE_API_KEY` e o modelo fixo `jev-1.13.0`, conforme o
[contrato REST da TypeSafe](https://docs.typesafe.ai/api). Haiku usa `ANTHROPIC_API_KEY`,
o SDK oficial `anthropic==1.13.0` e o modelo fixo `claude-haiku-5-5`, com thinking
desligado, esforço baixo e schema JSON de probabilidade inteira (0–100 convertida
para 0–1 com clamp). Recusa ou falha do SDK/parse retorna `None`; cliente criado sob
demanda, timeout de 5 s e uma repetição pelo SDK.
O cache em memória usa classificador + público + nome normalizado, TTL de 7 dias
e LRU de até 5000 entradas; falhas não são cacheadas. Jev mantém timeout de 5 s;
HTTP 429 permite uma nova tentativa após `retry-after`,
com espera limitada a 2 s.

Probabilidade abaixo do limiar conta como pulada e grava `visto` em cada grupo
candidato, usando `registrar_visto`. O campo `mensagem` guarda apenas a identificação
da rejeição (hash de classificador, público, limiar e nome normalizado), sem WhatsApp. A consulta
considera o bot e o grupo: esses vistos impedem nova avaliação nos próximos ciclos
e após reinício, sem bloquear os vistos de baseline nem outro bot. Alterar classificador,
público, limiar ou nome permite reavaliação. Probabilidade e classificador aparecem no log de envio.

Sem chave, o filtro fica desligado, inclusive para rejeições anteriores, com um aviso
por processo por provedor. Não há troca automática de provedor. Timeout, erro HTTP
ou resposta malformada retornam `None`: o envio segue
com os filtros e freio habituais, com aviso no máximo a cada 10 minutos por bot.

Para comparar antes de escolher, preencha `esperado` (`sim`/`nao`, ou vazio) no CSV
com 99 produtos reais em `scripts/dados/produtos_nina_enviados.csv`. As duas variáveis,
`TYPESAFE_API_KEY` e `ANTHROPIC_API_KEY`, podem ficar no `.env` local (nunca no Git).
O script carrega esse arquivo sem sobrescrever variáveis já definidas:

```bash
python scripts/comparar_classificadores.py scripts/dados/produtos_nina_enviados.csv --publico "mulheres adultas que buscam achadinhos para casa, beleza e moda feminina" --limiar 0.6 --saida resultado.csv
```

Entrada UTF-8 com `nome,loja,preco,esperado`; preço vazio vale 0. Sem `--saida`, gera
`<entrada>_resultado.csv`. Provedores sem chave são avisados e pulados; cada provedor
usa seu próprio cache. A saída preserva as colunas e acrescenta `p_jev`, `p_haiku`,
`ms_jev`, `ms_haiku`; campos de probabilidade ficam vazios para `None` e os de ambos
probabilidade/latência ficam vazios se o provedor foi pulado.
O resumo mostra avaliados (respostas válidas), `None`, latência média e p95 (posto
mais próximo, incluindo tentativas que retornaram `None`), acertos e precisão/revocação
de `nao` no limiar informado. `p < limiar` significa `nao`; empate aceita o produto.
Linhas sem rótulo ou com `None` não entram nas métricas de qualidade; denominador
zero aparece como `n/d`. Lista discordâncias com o esperado e entre os provedores.
Não acessa banco nem WhatsApp.

### Origem dos produtos por bot

`filters.origem_produtos` aceita `novidades` (padrão, buscas e ordem anteriores),
`mais_vendidos` ou `ambos`. Shopee usa relevância (`sortType: 1`) no caminho atual
e vendas (`sortType: 2`) no ranking, com nota. A taxa `commissionRate` vem nas duas
buscas. ML lê `/mais-vendidos`,
seleciona as categorias do bot (ou `CATEGORIAS_CASA`) e tenta uma página por categoria
ausente na raiz, usando o cookie da conta. Bloqueios não interrompem o ciclo.

Mais vendidos dispensam `max_vendas`, exigem desconto conhecido e o desconto mínimo,
e aplicam `min_vendas` (padrão 100; 0 desliga) quando a fonte informa vendas. A exceção
`ml_ignora_desconto_e_vendas` continua valendo. `comissao_minima_reais` (padrão 0,
desligado) corta só oferta com taxa estimada abaixo do piso; sem taxa, segue.
Os demais filtros permanecem iguais.

Dentro de cada loja, a maior comissão estimada vai na frente. Sem taxa, a ordem
anterior fica no fim. Fora de `novidades`, o score (demanda 45%, desconto 35%,
nota 10%, comissão 10%) só desempata. `prioridade_loja` (padrão `alternar`)
escolhe quem começa: `alternar` reveza Shopee no ciclo ímpar e Mercado Livre no
par; `mercado_livre` ou `shopee` põe a loja na frente com a outra de reserva.
Sem oferta enviável da preferida, a reserva ocupa a vaga. `uma_loja_por_ciclo`
continua alternando uma loja exclusiva e ignora essa prioridade.
`content.cupom_venda_indireta` (padrão false) coloca o cupom afiliado na vaga:
primeiro o da loja preferida, depois o da outra. Shopee usa `voucherOfferV2`;
ML só se houver item em `cupons_meli`. Sem link de afiliado, o produto segue.
Freio,
deduplicação por grupo e reenvio por queda de preço seguem iguais. A opção pode ser
comparada num bot de teste e importada pelo fluxo existente; nenhum bot muda automaticamente.

```
Dashboard ──HTTP/JSON──► API ──SQL──► Postgres ◄──SQL── Worker ──► plataformas
```

Três regras que não se quebram:

1. **O frontend só fala com a API.** Nunca com o Postgres, nunca com a
   evolution-api, nunca com módulo do worker.
2. **A API não invoca o worker.** Escreve no banco e, quando precisa de ação
   imediata, enfileira um comando. Chamar função do bot a partir de uma request
   HTTP acoplaria os dois processos e faria a request esperar um ciclo inteiro.
3. **O worker não depende da API para operar.** Lê config direto do banco. Se a
   API cair, o bot continua publicando — que é o comportamento correto: a camada
   de gestão não pode ser ponto único de falha da operação.

## Configuração: banco como contrato

O worker lê `bots` (e tabelas ligadas) a cada ciclo, com cache de 30s.

```python
# core/config_provider.py — o que substitui config.py:CANAIS e load_filtros()
def bots_ativos(ttl: int = 30) -> list[BotRuntime]:
    """Bots com status='active', com grupos, contas e settings resolvidos.
    Cache de processo com TTL — o ciclo roda a cada 60s, então uma alteração
    no dashboard entra em operação em no máximo ~1 ciclo."""
```

`BotRuntime` é um dataclass congelado, validado por Pydantic contra o schema de
`Bot.settings` ([API.md](API.md#bots)). Config inválida no banco **não derruba o
worker**: ele loga, emite um `event` de nível `error`, e mantém a última config
válida em memória. Um erro de digitação no dashboard não pode parar a operação.

**Sem modo legado (ADR-020).** O worker só publica bots ativos e rodáveis do
banco; sem nenhum, fica ocioso e avisa no log uma vez. Não lê `config.json` nem
grupos, instância ou credenciais da env. Um bot é rodável quando tem telefone com
instância da Evolution e ao menos um grupo ativo; bots ativos incompletos são
ignorados e geram o evento `bot_not_runnable`. A API já recusa ativar um bot sem
telefone com instância, grupo e conta com credencial.

**Token por instância (ADR-029, S1b).** O runtime decifra
`phones.instance_token_ciphertext` com `CREDENTIALS_KEY` e mantém o token só em
memória, excluído do repr do dataclass. `sendText` e `sendMedia` usam esse token
no header `apikey`; telefone sem token usa `EVOLUTION_API_KEY`, preservando a
operação da Nina até sincronizar pelo dashboard. Se o token receber **401**, o
worker registra `warning` `evolution_instance_token_rejected` com `tenant_id` e
tenta uma única vez com a chave geral. O guard rejeita antes do envio, então esse
retry não duplica mensagens. 404, 500 e qualquer outro erro não permitem retry.
Nenhum corpo de resposta de envio vai para o log, pois pode ecoar a chave.
Criação, consulta de instância, QR, estado e grupos continuam usando a chave
geral. Falha de decifração usa a chave geral e avisa sem incluir o segredo.

Cada ciclo busca e publica só as plataformas em que o bot tem conta ativa com
credencial não invalidada (`platforms_with_usable_credentials`): sem conta, o
link sairia sem comissão. A falta é avisada no log quando muda.

O job de ciclo é registrado uma vez, no boot. Os bots são relidos com o cache de
30 s, então ativar ou pausar no dashboard entra no próximo ciclo sem reiniciar.

O ciclo é **por bot**, não por grupo: faz uma só busca e filtragem e entrega cada
oferta escolhida aos grupos que ainda não a receberam. A deduplicação e os links
de afiliado continuam por grupo; os grupos saem em ordem de quem está há mais
tempo sem receber. A telemetria registra uma execução por bot e `offers_sent`
conta mensagens enviadas.

## Comandos: o que precisa ser imediato

Config muda por leitura; ação muda por comando. Tabela `commands` como caixa de
entrada, drenada no início de cada ciclo:

| type | Efeito |
|---|---|
| `pause` / `resume` | Para ou retoma os envios do bot |
| `run_now` | Força um ciclo fora do intervalo |
| `sync_groups` | Busca grupos na evolution-api e atualiza `groups` |
| `reload_config` | Invalida o cache antes do TTL |
| `test_credential` | Testa credencial de conta contra a plataforma |

```python
def drenar_comandos() -> None:
    """SELECT ... WHERE status='pending' FOR UPDATE SKIP LOCKED LIMIT 10"""
```

`SKIP LOCKED` porque dois workers no futuro não podem executar o mesmo comando.
Comando que falha grava `status='failed'` com o erro e **não** bloqueia a fila.
Comando pendente há mais de 10 min vira alerta de worker travado.

## Telemetria: o que o worker escreve

Toda passada do ciclo grava:

- `automation_runs` — início, fim, duração, ofertas encontradas/enviadas, erro.
  É o que responde "o bot está rodando?" e "quando foi a última execução boa?".
- `events` — falhas estruturadas (`auth_expired`, `send_failed`,
  `group_inaccessible`, `platform_error`), com `detail` em JSONB.
- `envios` — como hoje, agora também com `bot_id`, `group_id` e `sub_id`.
- heartbeat via `POST /api/internal/heartbeat` a cada ciclo.

Sem heartbeat por 3 intervalos → alerta `bot_offline`. É assim que o dashboard
sabe que o bot caiu sem ninguém ler log.

## Credenciais em tempo de execução

```python
# core/credentials.py
def credencial(account_id: UUID, kind: str) -> str:
    """Decifra em memória para uso imediato. Registra last_used_at.
    O valor nunca é logado, nunca serializado, nunca devolvido pela API."""
```

Ao receber 401/403 da plataforma, o worker marca a credencial como `invalid`,
grava `last_error` e emite um `event` — o que dispara o alerta de autenticação
expirada e faz aparecer no dashboard o botão de renovar. Hoje esse mesmo evento
só existe como `logger.error` que ninguém lê.

## Vários bots, um telefone

Requisito explícito: o mesmo telefone pode servir vários bots. O risco é que os
freios anti-ban são **por número**, não por grupo — dois bots no mesmo chip
somam envios e podem queimá-lo.

Por isso os limites globais (`max_ofertas_globais_por_hora|dia`) passam a ser
contados **por telefone**, atravessando todos os bots que o usam. `monitor.py` já
faz isso hoje ao contar sem filtrar por grupo; a mudança é tornar a intenção
explícita e ligá-la a `phone_id`.

O dashboard mostra, na tela do telefone, o total consolidado de envios daquele
número no dia — para que ficar acima do teto seja visível antes de virar ban.

## Ordem de migração (fase 6) — histórico

Plano original, com fallback. O ADR-020 removeu o fallback; a troca em produção
segue o plano de deploy em [DEPLOYMENT.md](DEPLOYMENT.md).

1. Worker passa a ler `bots` com fallback para JSON. Nenhum bot no banco ainda —
   comportamento idêntico ao atual.
2. Seed converte os dois canais em linhas de `bots`, sempre pausadas e sem
   sobrescrever o status em reexecuções. Vincular telefone e grupos antes da
   ativação explícita. Até lá o worker continua no legado.
3. Ativar leitura do banco para um bot. Observar 24h.
4. Ativar para o segundo. Remover `config.json` do caminho de execução (o arquivo
   fica no repo como referência até a fase 14).
5. Migrar credenciais de env var para `platform_credentials`. Remover as env vars
   operacionais da Railway **só depois** de confirmar que o banco é a origem.

Em qualquer ponto, reverter = redeploy do commit anterior do worker. O banco novo
é aditivo e não atrapalha a versão antiga.
## Preferências de seleção por bot

O worker confere o link depois da conversão: se a plataforma não produzir URL
rastreável, a oferta é pulada sem criar `envio`. Alternância de loja por ciclo e
exceções de filtro do Mercado Livre ficam em `bots.settings.filters`; por isso
valem para o bot inteiro e todos os seus grupos.
