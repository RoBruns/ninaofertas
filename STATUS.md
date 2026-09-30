> **Histórico — V1 (2026-09-07).** Este arquivo descreve o bot antigo, antes do
> dashboard, e não reflete o projeto atual. Estado atual: [`AGENTS.md`](AGENTS.md)
> e [`docs/ROADMAP.md`](docs/ROADMAP.md).

# Status do projeto — onde paramos

Última atualização: 2026-09-07

## Foco atual das fontes

- **Ativas:** Shopee (produtos + campanhas/cupons) + Mercado Livre
- Amazon fora do pipeline ativo do canal
- Sempre tenta link afiliado antes do envio (`affiliate.py`)
- Shopee: API OK; `offerLink` já vem afiliado; campanhas via `shopeeOfferV2`
- MELI search: app recebe 403 PolicyAgent no `/sites/MLB/search` (precisa revisar permissões/app)
- MELI createLink: cookie expirou (401) — renovar `MERCADOLIVRE_AFFILIATE_COOKIE`
- OpenAI: opcional depois (ranking/copy com gpt-4o-mini)


## ✅ O que já está pronto (feito e testado)

O bot inteiro já está implementado em `ofertas-bot/` e funcionando:

- `main.py`, `monitor.py`, `filters.py`, `dedup.py`, `formatter.py`, `whatsapp.py`, `database.py`, `logger.py`, `config.py` — tudo escrito e testado rodando de verdade.
- 4 fontes de ofertas em `scraper/`: **Pelando confirmado funcionando com dados reais** (17 ofertas capturadas num teste ao vivo), Mercado Livre (código pronto, falta credencial — ver abaixo), Amazon e Magalu (código pronto, mas bloqueados por anti-bot no momento — HTTP 403/503, é esperado).
- Banco SQLite, dedup (evita reenvio, mas reenvia se o preço cair), formatação de mensagem, filtros — tudo validado com teste ponta a ponta usando dados reais capturados ao vivo.
- `config.json`: `desconto_minimo` ajustado de 30 para **0**, porque o Pelando não expõe preço anterior na listagem (só mostra preço atual) — com 30% nada do Pelando passava no filtro. Documentado em `scraper/pelando.py`.
- Venv Python já criado em `ofertas-bot/venv/` com dependências instaladas.
- **Docker funcionando** (resolvido problema de WSL2/virtualização da sessão anterior).
- **evolution-api rodando via Docker Compose** (`docker-compose.yml` na raiz do projeto — sobe evolution-api + Postgres + Redis juntos). Imagem correta é `evoapicloud/evolution-api` (a antiga `atendai/evolution-api` foi descontinuada).
- **Git configurado**: repositório local criado e código publicado em
  **https://github.com/mencxrini/ofertas-bot** (privado). GitHub CLI (`gh`)
  instalado e autenticado como `mencxrini`. `.env`, `venv/`, `ofertas.db` e
  `logs/` estão no `.gitignore` — nunca vão pro repositório.

Detalhes técnicos completos estão no `README.md` da pasta.

## 🔴 Onde paramos agora (bloqueio ativo)

O WhatsApp **ainda não está pareado**. Tentativas de escanear o QR Code
falharam com a mensagem do próprio WhatsApp:
> "Não é possível conectar novos dispositivos no momento, tente novamente mais tarde"

Isso é o WhatsApp aplicando um **cooldown de segurança** por termos gerado QR
Code várias vezes seguidas em pouco tempo (9+ tentativas) — não é bug do
projeto.

**Próxima ação: esperar pelo menos 30-60 min (idealmente mais) antes de
tentar de novo, e tentar só UMA vez com calma.**

Quando for tentar de novo:
1. Confirma no celular: WhatsApp atualizado, sem VPN ativa, data/hora automática ligada.
2. Pede pra eu gerar um novo QR (endpoint: `GET /instance/connect/ofertas-bot` na evolution-api, chave em `EVOLUTION_API_KEY` do `.env`).
3. Escaneia rápido, sem re-tentar várias vezes seguidas se falhar — espera de novo em vez de martelar.

Depois que parear:
- Listar os grupos desse WhatsApp pra identificar o ID do grupo de ofertas (formato `120363xxxxxx@g.us`) e preencher `WHATSAPP_GROUP_ID` no `.env`.
- Rodar `python main.py` e ver a primeira oferta real chegando no grupo.

## Pendências não-bloqueantes

- Criar app gratuito em https://developers.mercadolivre.com.br/ e preencher `MERCADOLIVRE_APP_ID`/`MERCADOLIVRE_APP_SECRET` no `.env`, pra ativar a fonte Mercado Livre.
- Reavaliar se `desconto_minimo: 0` é bom o suficiente ou se vale a pena voltar a exigir desconto mínimo assim que Amazon/Magalu/ML estiverem funcionando (essas fontes normalmente informam preço anterior).

## Como retomar numa conversa nova

Se essa conversa se perder, é só abrir uma nova e falar algo como:
> "Continua o setup do bot de ofertas, olha o STATUS.md na pasta ofertas-bot"

E colar/apontar esse arquivo. O código sempre pode ser conferido em
https://github.com/mencxrini/ofertas-bot também.
