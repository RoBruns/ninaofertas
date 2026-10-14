# Deploy e operação

## Railway

Projeto `gallant-emotion` · ID `0655e0f9-0ad1-49b8-b08f-0c7baad584fa` ·
ambiente `production` · região US East.

| Serviço | Tipo | Público | Papel |
|---|---|---|---|
| `nina-worker` | worker Python | não | Bot V2, um único worker |
| `ninaofertas` | worker Python | não | V1 descontinuada, desligado |
| `nina-api` | FastAPI | não | API V2 na rede interna |
| `nina-dashboard` | Caddy + SPA | **sim** | Frontend e proxy `/api` |
| `evolution-api` | imagem | sim | WhatsApp · volume 4.9 GB |
| `nina-db` | Postgres | **não** | Dados. TCP Proxy apenas temporariamente para backup; desligar depois |
| `Redis` | banco | não | Cache da `evolution-api` (`CACHE_REDIS_URI`, db 6). Adicionado em 2026-09-23; o bot não usa |
| `rogstools` | — | sim | **Outro projeto. Não tocar.** |

Comandos úteis:
```bash
railway status
railway logs --service nina-worker
railway variables --service nina-worker
railway up --service nina-worker
```

> O Postgres fica na rede interna. Para backup local, o dono pode habilitar
> temporariamente o TCP Proxy, usar `DATABASE_PUBLIC_URL` e desligar o proxy logo
> depois (procedimento em [Backup](#backup)).

### Como acessar o banco a partir da máquina local

`railway run` **não serve** para isso: injeta as variáveis mas executa o processo
localmente, então `postgres.railway.internal` não resolve. Para backup, use o
TCP Proxy temporário descrito abaixo. Outra opção de acesso é o túnel SSH:

```bash
# uma vez, se ainda não houver chave registrada:
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N ""
railway ssh keys add --key 'C:\Users\<voce>\.ssh\id_ed25519.pub' --name minha-chave

# abre o túnel (não imprime nada; segura o terminal até Ctrl+C):
railway connect nina-db --tunnel-only --port 55432

# em outro terminal:
export PGPASS=$(railway variables --service nina-db --kv | grep '^POSTGRES_PASSWORD=' | cut -d= -f2-)
export DATABASE_URL="postgresql://postgres:${PGPASS}@127.0.0.1:55432/railway"
```

Dois detalhes que custam tempo: o CLI espera **caminho no formato Windows** em
`--key`, e `railway connect` passa o nome do serviço como **argumento posicional**
(`railway connect nina-db`, não `--service nina-db`).

Revogar a chave depois: `railway ssh keys remove`.

## Variáveis de ambiente

### `nina-worker`

Infraestrutura: `DATABASE_URL`, `CREDENTIALS_KEY`, `EVOLUTION_API_URL`,
`EVOLUTION_API_KEY`, `LOG_LEVEL`, `CHECK_INTERVAL`, `REENVIO_QUEDA_MINIMA` e
`TZ=<-03>3`. Heartbeat: `API_URL`, `WORKER_TOKEN`, `WORKER_ID`.
Bots, grupos, instâncias e credenciais de Shopee/ML vêm do dashboard (ADR-020).

`EVOLUTION_API_KEY` é a **chave geral de gerenciamento** do servidor Evolution,
usada tanto na API quanto no worker para criar/consultar instâncias, obter QR,
estado e grupos. Envios usam o token específico de cada telefone, cifrado no
banco com a mesma `CREDENTIALS_KEY` compartilhada por API e worker. Sem token,
ou após 401 do token, a chave geral mantém o envio (ADR-029).
Depois de aplicar a migration 0008, o admin da conta pode usar **Sincronizar
token** no telefone já existente da Nina; não é necessário recriar a instância
ou reparear o WhatsApp. Nenhuma variável de token deve ir ao frontend.

`TYPESAFE_API_KEY` e `ANTHROPIC_API_KEY` são opcionais e pertencem somente ao
**nina-worker**: respectivamente Jev (`jev-1.13.0`, chave Bearer da TypeSafe) e
Claude Haiku (`claude-haiku-5-5`, SDK oficial Anthropic). Não colocar na API, no dashboard ou
em variáveis `VITE_*`. Configure o público e a relevância mínima por bot na seção
Filtros, incluindo o classificador (`jev` por padrão). Sem a chave do provedor
selecionado, o filtro fica desligado e avisa uma vez por processo por provedor;
indisponibilidade da API mantém o envio com os filtros e o freio habituais.
Para a comparação local, ambas as variáveis podem ficar no `.env`, sem commit.
Detalhes do fluxo em [BOT_INTEGRATION.md](BOT_INTEGRATION.md#público-do-grupo-e-palavras-chave).

### `nina-api`

```
DATABASE_URL          ${{nina-db.DATABASE_URL}}
CREDENTIALS_KEY       # 32 bytes base64 — cifra platform_credentials e tokens de phones
JWT_SECRET            # 64 bytes aleatórios
WORKER_TOKEN          # autentica /api/internal/*
CORS_ORIGINS          https://<dashboard>.up.railway.app
EVOLUTION_API_URL     http://evolution-api.railway.internal:8080
EVOLUTION_API_KEY     ${{evolution-api.AUTHENTICATION_API_KEY}}
LOG_LEVEL             INFO
```

Gerar:
```bash
python -c "import secrets,base64;print(base64.b64encode(secrets.token_bytes(32)).decode())"  # CREDENTIALS_KEY
python -c "import secrets;print(secrets.token_urlsafe(64))"                                   # JWT_SECRET / WORKER_TOKEN
```

**Guarde `CREDENTIALS_KEY` fora da Railway também** (gerenciador de senhas).
Perdê-la torna ilegível toda credencial cifrada — elas teriam de ser recolocadas
uma a uma.

### `nina-dashboard`

```
RAILWAY_DOCKERFILE_PATH  deploy/dashboard.Dockerfile
API_UPSTREAM            nina-api.railway.internal:8000
```

O Caddy serve a SPA e encaminha `/api` para `nina-api` na rede interna.
**Nenhum segredo entra no bundle do frontend** — tudo em `VITE_*` é público
para quem abrir o DevTools.


### Fuso horário (worker e API)

`TZ=<-03>3` em **nina-worker** e **nina-api**. A imagem Railpack ignora
`TZ=America/Sao_Paulo` (verificado no container). O código usa `core/relogio.py`
para agenda e exibição em Brasília, independentemente do fuso do container;
o banco guarda datas UTC. O Brasil não tem horário de verão desde 2019.

## Migrations

```bash
railway run --service nina-api alembic upgrade head
```

Antes de qualquer migration que altere tabela existente, gere o ZIP lógico e
teste sua restauração em banco descartável conforme [Backup](#backup).
`railway run` executa localmente e não resolve o endereço interno do banco.

Regras: `ofertas` e `envios` só recebem coluna nullable · nenhuma migration dropa
coluna delas · toda migration tem `downgrade` testado · migration roda antes do
deploy do código que a usa.

## Deploy

Ordem em release que cruza camadas: **migration → API → worker → dashboard**.
O worker é o último entre os backends porque é o que está no ar; se a API subir
quebrada, o bot continua publicando.

A API inicia com `python -m api.serve`, que abre um único socket dual-stack para
atender o healthcheck IPv4 e a rede privada IPv6 da Railway no mesmo processo.

Rollback: `railway redeploy` do deployment anterior do serviço. Como as
migrations são aditivas, a versão antiga do código convive com o schema novo.

## Backup

O `nina-db` usa Postgres 18 e o `pg_dump` local é 16, incompatível com esse
servidor. Os scripts `scripts/backup_db.py` e `scripts/restore_db.py` usam Python
e psycopg 3, sem binários do Postgres. **Ainda não há backup automático** no
plano Hobby. Antes das migrations 0007–0009, gere um backup e restaure uma cópia
em banco descartável. Agendamento diário e retenção de 7 dias continuam pendentes.

Para gerar a partir da máquina local:

1. No serviço **nina-db** da Railway, abra **Settings → Networking** e habilite
   o **TCP Proxy**. Use a URL pública que aparece em `DATABASE_PUBLIC_URL`.
2. Na raiz do repositório, com o venv e dependências instalados, coloque essa URL
   em `DATABASE_URL` no ambiente do terminal (sem exibi-la nem compartilhá-la).
   Execute o comando abaixo. Também é aceito `--url <postgres-url>`; a variável
   evita colocar a senha na linha de comando/histórico. Ambos os prefixos
   `postgres://` e `postgresql://` são aceitos.
3. **Desligue o TCP Proxy logo depois**, inclusive se o comando falhar.

```powershell
# DATABASE_URL já definida com DATABASE_PUBLIC_URL, sem imprimir seu conteúdo:
./venv/Scripts/python.exe scripts/backup_db.py --out C:/Backups/nina/nina-antes-saas.zip
Remove-Item Env:DATABASE_URL
```

Crie a pasta de destino antes. Guarde os ZIPs **fora do repositório e fora da
Railway**, em armazenamento com acesso restrito e cópia separada; `backups/`
também está no `.gitignore` para arquivos locais temporários. O ZIP não é cifrado:
contém dados pessoais e hashes de senha, além das credenciais operacionais já
cifradas. Guarde `CREDENTIALS_KEY` separadamente no gerenciador de senhas para
poder decifrar os tokens depois da restauração. Não anexe backups a commits,
issues, logs ou conversas.

O backup usa uma transação `REPEATABLE READ READ ONLY`: uma foto consistente de
todas as tabelas base de `public`, inclusive `alembic_version`, `ofertas` e
`envios`. Os CSVs vão em streaming para `tables/<tabela>.csv`; `manifest.json`
registra data UTC, versão do servidor, revisão Alembic, colunas/tipos e contagens.
O resumo mostra host/banco, tabelas, linhas e bytes, sem URL ou senha. Um arquivo
de destino existente é recusado; falhas removem o ZIP incompleto.

Para restaurar, crie um **banco de destino vazio**, use o checkout que contém a
revisão do manifesto e configure a URL desse destino em `DATABASE_URL`:

```powershell
# Exemplo: DATABASE_URL aponta para um banco descartável chamado nina_restore.
./venv/Scripts/python.exe scripts/restore_db.py --backup C:/Backups/nina/nina-antes-saas.zip --confirmar nina_restore
Remove-Item Env:DATABASE_URL
```

Também aceita `--url <destino>`. `--confirmar` precisa corresponder exatamente ao
nome do banco da URL. Qualquer tabela em `public` com dados bloqueia a operação,
exceto `platforms` e `plans` (seeds, esvaziados na transação de carga) e
`alembic_version` (metadado mantido pelo Alembic, sem COPY). Use um destino sem
aplicações conectadas. A restauração roda `alembic upgrade <revisão-do-manifesto>`
com `DATABASE_URL` do destino em processo separado; `ofertas`/`envios` presentes
no backup são criadas por `Base.metadata.create_all` (ADR-012). Não migra
automaticamente o backup para `head`: faça isso somente após validar a cópia.

A carga inteira usa uma transação com `session_replication_role = replica`,
sem executar FKs nem o gatilho do livro-razão, e requer um usuário com permissão
para alterar esse parâmetro (por exemplo, superusuário). Ao fim restaura o papel
da sessão, confere cada contagem e ajusta todas as sequências ao máximo existente
(ou 1, ainda não usado, para tabela vazia). Falha na carga/contagem reverte os
dados; a criação inicial do schema pelas migrations pode permanecer no destino.
O formato cobre as tabelas da aplicação reconstruídas por migrations e modelos;
não inclui roles, grants, objetos de outros schemas nem DDL customizado externo.

O teste `tests/test_backup_db.py` faz backup → `DROP SCHEMA public CASCADE` →
restauração em **Postgres real**, compara todas as linhas de todas as tabelas,
incluindo tipos nativos, token cifrado e livro-razão; verifica sequências,
gatilho, revisão anterior à SaaS, foto consistente sob escrita concorrente e
recusas por confirmação errada/destino com dados. Nunca aponte esse teste para
produção: ele só usa `TEST_DATABASE_URL`, com a trava de `tests/_db_guard.py`.

```powershell
$env:TEST_DATABASE_URL = 'postgresql://postgres:postgres@localhost:5432/ninaofertas_test'
./venv/Scripts/python.exe -m pytest -q tests/test_backup_db.py
```

Esse teste valida o procedimento; a cópia real de produção ainda precisa ser
gerada e ensaiada num destino separado antes do deploy.

O volume da `evolution-api` (`/evolution/instances`) guarda a sessão do WhatsApp.
**Perder esse volume significa reparear o número por QR Code** — e o WhatsApp
aplica cooldown de segurança quando há muitas tentativas seguidas (já aconteceu
neste projeto, registrado em `STATUS.md`). Não recriar o serviço sem necessidade.

**Imagem fixada por digest** desde 2026-10-14:
`evoapicloud/evolution-api@sha256:966625532d9076a2381e973a271307d107e6f070450de3abeeea8bd18be07252`
(é a `latest` que já rodava, publicada em 2026-05-06; o log de início diz `v2.3.7`,
mas o digest difere do da tag `v2.3.7`, então é uma recompilação dela). Antes rodava `:latest`, que podia trocar de
versão num reinício e mudar o formato das respostas que a API e o worker leem. Para
atualizar: escolha uma versão **igual ou mais nova** (a Evolution migra o próprio banco;
voltar versão pode quebrar a sessão), teste o contrato de `core/evolution.py` e troque
com `railway service source connect --image <imagem> --service evolution-api
--environment production`, logo depois de um envio ou no silêncio noturno, porque o
serviço reinicia. A Railway manda o e-mail "Deployment crashed for evolution-api" sobre
o deploy **antigo**, que sai com erro ao ser encerrado na troca (aconteceu em
2026-10-14 com o `5decaca1`); confira o id no link do e-mail e o log do deploy novo
("CONNECTED TO WHATSAPP") antes de agir. O log de início mostra a versão real
(`v2.3.7` em 2026-10-14).

## Saúde

```bash
curl https://<api>.up.railway.app/api/health
railway logs --service ninaofertas | tail -50
```

`/api/health` devolve estado de banco, evolution-api e último heartbeat do
worker. Alerta de `bot_offline` dispara com 3 intervalos sem heartbeat.

---

## Plano de deploy — fase 14 (a executar só com aprovação do usuário)

### Fatos que o plano respeita

- A Railway publica o bot a partir de **`RoBruns/ninaofertas`, branch `master`**
  (remoto local `producao`). O `origin` local (`DiegoMiuraDev/ninaofertas`) fica
  atrás da produção. Outro desenvolvedor faz commit direto na `master` de produção.
- **Sem config-as-code no repositório** (removido em 2026-09-30). A Railway
  descontinuou o `railway.toml`/`railway.json` (vale até 2026-12-01) e não aceita mais
  o arquivo em serviço novo. Os serviços da V2 são configurados nas settings da
  Railway (tabela abaixo; pela API GraphQL, `serviceInstanceUpdate`). Antes, o
  `railway.toml` da raiz era herdado por todo serviço criado do repositório e podia
  subir **um segundo bot** no mesmo número; sem o arquivo, esse risco acabou. Serviço
  novo: defina o comando de início **antes** do primeiro deploy.

  | Serviço | Builder | Início | Pré-deploy | Healthcheck |
  |---|---|---|---|---|
  | `nina-api` | Railpack | `python -m api.serve` | `alembic upgrade head` | `/api/health` |
  | `nina-worker` | Railpack | `python -m worker.main` | — | — |
  | `nina-dashboard` | Dockerfile (`RAILWAY_DOCKERFILE_PATH=deploy/dashboard.Dockerfile`) | do Dockerfile | — | `/healthz` |

  Os três publicam a branch `master` de `RoBruns/ninaofertas`. A V1 (serviço
  `ninaofertas`, desligado) está no branch `v1-legado`, com o `railway.toml` dela.
- **Não há modo legado** (ADR-020): o worker novo só publica bots ativos no
  dashboard. O worker **antigo** ignora a tabela `bots`, então os bots podem ser
  configurados e ativados no dashboard enquanto ele ainda roda — é isso que evita
  uma janela sem envio na troca.

### Arquitetura de publicação

```
navegador ──HTTPS──► nina-dashboard (Caddy: SPA estática + proxy /api)
                          │  rede interna
                          ▼
                     nina-api (uvicorn, SEM domínio público)
                          │
                     Postgres (interno) ◄── ninaofertas (worker)
```

O dashboard serve os arquivos e faz proxy de `/api` para a API pela rede interna.
Para o navegador é **uma origem só**: sem CORS, e o cookie de sessão
(`SameSite=Strict`, `path=/api/auth`) funciona sem ajuste. A API **não tem domínio
público** — só é alcançável pelo proxy.

### Sequência

| # | Passo | Reversível? |
|---|---|---|
| 0 | `git fetch producao`: se houver commit novo na produção, integrar antes | — |
| 1 | ZIP com `scripts/backup_db.py`, guardado fora da Railway, e restauração ensaiada em banco descartável (ver Backup) | — |
| 2 | Criar `nina-api` e `nina-dashboard` (sem tráfego ainda), com config própria | apagar serviço |
| 3 | Variáveis da API: `JWT_SECRET`, `CREDENTIALS_KEY`, `WORKER_TOKEN` gerados; `DATABASE_URL` e `EVOLUTION_*` por referência. `ADMIN_EMAIL`/`ADMIN_PASSWORD` **definidos pelo usuário** (a senha não passa pela conversa) | trocar valor |
| 4 | `alembic upgrade head` no banco de produção (só aditivo; `ofertas`/`envios` ganham colunas nullable) e `python -m core.seed` (bots pausados) | downgrade testado; backup do passo 1 |
| 5 | Subir API e dashboard; checar `/api/health`, login, telas | redeploy anterior |
| 6 | No dashboard de produção: contas (Shopee: App ID + App Secret; ML: etiqueta + cookie), telefone com a instância `ofertas-bot`, grupos (sincronizar), e nos bots do seed: vincular telefone, grupos e contas, conferir o ritmo e **ativar**. O worker antigo segue publicando e ignora isso | pausar o bot |
| 7 | Merge de `feat/dashboard` na `master` de produção → a Railway republica o worker com `python -m worker.main`, que passa a publicar pelos bots ativos | redeploy do deployment anterior do worker |
| 8 | Conferir no log do worker: bots e grupos esperados, nenhum aviso "sem conta"; envios com `bot_id` na primeira hora | — |
| 9 | Rodar a suíte **dentro da Railway** (sem túnel) com `METRICS_LATENCY_CHECK=1`, e refazer a verificação V5 | — |
| 10 | Estável: remover do worker as variáveis migradas (`EVOLUTION_INSTANCE`, `WHATSAPP_GROUP_ID*`, `SHOPEE_*`, `MERCADOLIVRE_*`) | recriar as variáveis |

### Rollback

Migrations aditivas: o código antigo do worker roda sobre o schema novo. Se o
worker novo se comportar mal, `railway redeploy` do deployment anterior devolve
o comportamento de hoje sem tocar no banco — por isso as variáveis antigas só
saem no passo 10. Pausar todos os bots no dashboard **para** a publicação; não
há mais volta automática ao legado (ADR-020).
