# Integração dashboard ↔ bot

Como a camada de gestão controla a operação sem reiniciar serviço e sem que o
frontend fale com componente interno do bot.

## Fronteiras

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

**Fallback.** Sem bot ativo no banco, o worker cai para `config.json`/`config.py`
como hoje. É o que torna a fase 6 reversível: se algo der errado, basta não haver
linha em `bots` e o comportamento antigo volta.

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

## Ordem de migração (fase 6)

Incremental, cada passo reversível:

1. Worker passa a ler `bots` com fallback para JSON. Nenhum bot no banco ainda —
   comportamento idêntico ao atual.
2. Seed converte os dois canais em linhas de `bots`. Comparar lado a lado os logs
   de um ciclo antes e depois: mesmas ofertas, mesmas decisões de filtro.
3. Ativar leitura do banco para um bot. Observar 24h.
4. Ativar para o segundo. Remover `config.json` do caminho de execução (o arquivo
   fica no repo como referência até a fase 14).
5. Migrar credenciais de env var para `platform_credentials`. Remover as env vars
   operacionais da Railway **só depois** de confirmar que o banco é a origem.

Em qualquer ponto, reverter = redeploy do commit anterior do worker. O banco novo
é aditivo e não atrapalha a versão antiga.
