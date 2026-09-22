# ninaofertas

Operação de marketing de afiliados: um bot captura ofertas de Shopee e Mercado
Livre, gera link de afiliado e publica em grupos de WhatsApp — e um dashboard web
controla e mede tudo isso.

> **O bot está em produção.** Roda na Railway e publica em grupo real. Antes de
> alterar qualquer coisa, leia [docs/AGENT_CONTEXT.md](docs/AGENT_CONTEXT.md).

## Componentes

| Componente | Stack | Estado |
|---|---|---|
| **Worker** (`worker/`) | Python · APScheduler · SQLAlchemy | ✅ em produção |
| **API** (`api/`) | FastAPI · Pydantic v2 | 🚧 em construção |
| **Dashboard** (`dashboard/`) | React · TypeScript · Vite | 🚧 em construção |
| **Core** (`core/`) | models, plataformas, cripto, métricas | 🚧 em construção |

## Como funciona o bot

```
ciclo (60s)
  → captura       Shopee (Open API) · Mercado Livre (página de ofertas) · cupons
  → filtra        nicho, preço, desconto, bloqueios
  → deduplica     não reenvia; reenvia se o preço cair
  → afilia        link com tracking da conta
  → freia         limites anti-ban por hora/dia/rajada
  → publica       grupo de WhatsApp via evolution-api
```

O freio anti-ban é o que protege o número de ser banido pelo WhatsApp. **Não
afrouxe esses limites** — perder o chip significa perder os grupos.

## Documentação

Comece por [docs/AGENT_CONTEXT.md](docs/AGENT_CONTEXT.md).

- [ARCHITECTURE.md](docs/ARCHITECTURE.md) — estado atual, problemas, arquitetura alvo
- [PRODUCT_SPEC.md](docs/PRODUCT_SPEC.md) — o que o produto entrega
- [DATABASE.md](docs/DATABASE.md) — modelo de dados e fórmulas de métrica
- [API.md](docs/API.md) — contrato HTTP
- [BOT_INTEGRATION.md](docs/BOT_INTEGRATION.md) — como dashboard e bot se falam
- [DEPLOYMENT.md](docs/DEPLOYMENT.md) — Railway, env vars, migrations, backup
- [ROADMAP.md](docs/ROADMAP.md) — fases e estado de cada uma
- [DECISIONS.md](docs/DECISIONS.md) — decisões técnicas e seus porquês

## Desenvolvimento

```bash
python -m venv venv && venv\Scripts\activate    # Windows
pip install -r requirements.txt
copy .env.example .env                           # preencha as credenciais

python -m worker.main                            # bot
uvicorn api.main:app --reload                    # API
cd dashboard && npm install && npm run dev       # dashboard
```

O `.env` nunca vai para o repositório. Credenciais de produção ficam nas
variáveis da Railway e, depois da fase 4, cifradas no banco.

## Infraestrutura

Railway, projeto `gallant-emotion`: `ninaofertas` (worker) · `evolution-api`
(WhatsApp) · `Postgres` (interno-only) · e, em breve, `nina-api` e
`nina-dashboard`. O serviço `rogstools` é de outro projeto — não mexer.

Detalhes em [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).
