# Bot de Ofertas → WhatsApp

Monitora ofertas (Pelando, Mercado Livre, Amazon, Magalu), filtra pelos seus
critérios, evita duplicidade e envia automaticamente para um grupo do
WhatsApp via [evolution-api](https://github.com/EvolutionAPI/evolution-api).

## Como rodar

### 1. Suba a evolution-api (WhatsApp)

A API oficial do WhatsApp (Meta Cloud API) **não permite enviar para grupos**,
só conversas 1:1 com opt-in — por isso o envio usa evolution-api, que fala o
protocolo do WhatsApp Web, é gratuita, self-hosted e suporta grupos.

```bash
# Na raiz do projeto (sobe Postgres + Redis + Evolution):
docker compose up -d
# Evolution fica em http://127.0.0.1:8080 — defina POSTGRES_PASSWORD e EVOLUTION_API_KEY no .env
```

Depois:
1. Crie uma instância e escaneie o QR Code com o WhatsApp do número que vai enviar as ofertas (`POST /instance/create`, docs da evolution-api).
2. Descubra o ID do grupo de destino (algo como `120363xxxxxx@g.us`) — a própria API lista os grupos em `GET /group/fetchAllGroups/{instance}`.

### 2. Configure o bot

```bash
cd ofertas-bot
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env         # edite com suas credenciais
```

Preencha no `.env`:
- `EVOLUTION_API_URL`, `EVOLUTION_API_KEY`, `EVOLUTION_INSTANCE`, `WHATSAPP_GROUP_ID`, `EVOLUTION_BOT_NUMBER`
- `POSTGRES_PASSWORD` (Docker Compose da Evolution)
- `SHOPEE_APP_ID` / `SHOPEE_APP_SECRET`, `MERCADOLIVRE_AFFILIATE_TAG` / `MERCADOLIVRE_AFFILIATE_COOKIE`

Varredura de segredos no Git (local): `scripts/scan-secrets.ps1` ou `gitleaks detect --source .`

Ajuste os critérios de filtro em `config.json` (preço, desconto mínimo, lojas, categorias, palavras-chave, limites de envio).

### 3. Rode

```bash
python main.py
```

O bot já roda a primeira verificação imediatamente e depois a cada
`CHECK_INTERVAL` segundos (padrão 60s), em loop, com logs no console e em
`logs/bot.log`.

## Sobre as fontes de ofertas

| Fonte | Método | Situação |
|---|---|---|
| **Shopee** | API oficial de afiliados (GraphQL) | Requer `SHOPEE_APP_ID` / `SHOPEE_APP_SECRET`. |
| **Mercado Livre** | HTML público `/ofertas` + listagem | Afiliado via `MERCADOLIVRE_AFFILIATE_*` no `.env`. |
| **Cupons** | Shopee vouchers + MELI | Mesmas credenciais Shopee quando aplicável. |

Fontes legadas (Amazon, Magalu, Pelando) estão em `scraper/disabled/`.
Cada fonte roda isolada: se uma cair, as outras continuam.

## Adicionando uma nova fonte

Crie `scraper/minha_fonte.py` com uma subclasse de `Scraper` (veja
`scraper/base.py`) implementando `buscar() -> list[OfertaCapturada]`, e
adicione uma instância em `scraper/__init__.py`.

## Estrutura

```
ofertas-bot/
├── main.py          # entrypoint, agenda o loop (APScheduler)
├── monitor.py        # um ciclo completo: busca → filtra → dedup → envia
├── scraper/           # uma fonte por arquivo
├── filters.py         # aplica os critérios de config.json
├── dedup.py            # evita reenviar a mesma oferta (permite reenvio se o preço cair)
├── formatter.py        # monta a mensagem a partir do template configurável
├── whatsapp.py          # envio via evolution-api
├── database.py           # SQLite via SQLAlchemy (ofertas + envios)
├── config.py / config.json / .env
└── logs/bot.log
```
