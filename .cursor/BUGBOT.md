# Revisão de infraestrutura do Nina Bot

Revise o diff quanto ao risco operacional. O bot publica em grupos reais de WhatsApp. `AGENTS.md` é o contexto; se contradisser o código, o código vence. `docs/ARCHITECTURE.md` e `STATUS.md` são da V1 e não descrevem o estado atual.

Não sugira afrouxar o freio anti-ban. Não peça para imprimir cookie, token, senha ou variável de ambiente.

Sinalize como bloqueio:

- Afrouxar `worker/monitor.py::_freio_anti_ban` ou `core/safety.py` sem ADR explícito do dono.
- Um segundo worker, ou dois ciclos no mesmo número de WhatsApp.
- Oferta enviada sem `affiliate.link_rastreado`.
- Importação ou scrape do Mercado Livre que invalide o cookie. Só o createLink decide se o cookie vale.
- Credencial devolvida em resposta, log, evento ou frontend. A API só devolve status e fingerprint.
- Segredo em commit, teste, log ou arquivo versionado.
- Teste ou script apontando para o banco `railway`, ou `DROP SCHEMA` fora do banco descartável de teste.
- Grupo, instância ou credencial voltando a vir de env ou `config.json`.
- Qualquer mudança no serviço `rogstools`.
- Default de `bots.settings` que mude o envio assim que o worker subir, antes de salvar no dashboard.
- Dinheiro em float, ou falha de uma fonte derrubando o ciclo inteiro.

Registre, sem tratar como bloqueio sozinho:

- Migration sem o pré-deploy `alembic upgrade head` continuar válido.
- Config tratada como imediata. O worker só a vê depois do cache de 30 s.
- Bot de teste furando teto por grupo ou deduplicação, que são compartilhados na conta.
- Diff que só vale depois de push na `master`. Esse push publica `nina-api`, `nina-worker` e `nina-dashboard`.
