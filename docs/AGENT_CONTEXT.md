# Contexto para agentes

Leia este arquivo antes de tocar em qualquer código. Ele existe para que um
agente novo (Codex, Claude ou humano) entenda o projeto sem depender de nenhuma
conversa anterior.

## O que é

`ninaofertas` é uma operação de marketing de afiliados. Um bot Python captura
ofertas de Shopee e Mercado Livre, filtra por nicho, gera link de afiliado e
publica em grupos de WhatsApp via evolution-api. O projeto atual adiciona uma
camada de gestão: API + dashboard web para configurar e medir a operação sem
mexer no servidor.

## Regra número um

**O bot está em produção e funcionando.** Roda na Railway, captura ~1.200
ofertas por ciclo e publica em grupo real. Toda mudança precisa manter o pipeline
funcionando. Se uma alteração sua pode derrubar o envio, ela está errada — pare e
sinalize em vez de arriscar.

Especificamente, **nunca**:
- remova ou afrouxe os freios anti-ban de `monitor.py` (protegem o número contra
  banimento no WhatsApp — perder o chip é perder os grupos);
- altere o schema de `ofertas`/`envios` de forma destrutiva;
- exponha cookie, token, secret ou senha em resposta de API, log ou frontend;
- commite `.env`, credencial ou dump de banco.

## Como se orientar

| Pergunta | Documento |
|---|---|
| O que existe hoje, o que está errado, para onde vamos | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Tabelas, campos, fórmulas de métrica | [DATABASE.md](DATABASE.md) |
| Rotas, payloads, regras de erro | [API.md](API.md) |
| Como worker e API se comunicam | [BOT_INTEGRATION.md](BOT_INTEGRATION.md) |
| Fases, dependências, critérios de conclusão | [ROADMAP.md](ROADMAP.md) |
| Por que algo foi decidido assim | [DECISIONS.md](DECISIONS.md) |
| Railway, env vars, deploy | [DEPLOYMENT.md](DEPLOYMENT.md) |
| O que o produto precisa entregar | [PRODUCT_SPEC.md](PRODUCT_SPEC.md) |

## Estado atual

Fase 0 (documentação) concluída em 2026-09-22. Fases 1–14 pendentes — o quadro
com o estado de cada uma está em [ROADMAP.md](ROADMAP.md) e é a fonte de verdade.

Branch de trabalho: `feat/dashboard`. `master` é o que está em produção.

## Infraestrutura

Railway, projeto `gallant-emotion`, ambiente `production`:
`ninaofertas` (worker) · `evolution-api` (WhatsApp) · `Postgres` (interno-only) ·
`rogstools` (**outro projeto — não tocar**).

## Convenções

**Idioma.** O domínio é em português (`ofertas`, `envios`, `filtros`) e assim
continua — renomear em massa quebraria o que funciona. Código novo usa inglês
para tabelas e rotas. Comentário e mensagem de log em português, como o resto do
projeto. Não misture dentro do mesmo módulo.

**Python.** Type hints sempre. Pydantic v2 para entrada/saída. SQLAlchemy 2.0
(estilo `select()`). `ruff` + `black`. Sem `print` — use o logger.

**TypeScript.** Strict. Sem `any`. Tipos da API gerados do OpenAPI, nunca escritos
à mão (divergem em silêncio).

**Dinheiro.** `NUMERIC(14,2)` no banco, `Decimal` em Python, **string** em JSON.
Float em dinheiro perde centavo — isso já derrubou relatório em produção antes.

**Datas.** `TIMESTAMPTZ`, UTC no banco. O bot opera em `America/Sao_Paulo`;
converta na borda, nunca no meio do cálculo.

**Erro.** Nunca engula exceção silenciosamente. O worker isola falha por fonte
(uma plataforma cair não pode derrubar o ciclo) — esse padrão de
`scraper/base.py:executar()` é o modelo a seguir.

## Ao terminar uma tarefa

1. Rode os testes e o linter.
2. Confirme cada critério de conclusão da fase, um a um.
3. Atualize o estado da fase em [ROADMAP.md](ROADMAP.md).
4. Se tomou decisão técnica relevante, registre em [DECISIONS.md](DECISIONS.md).
5. Se descobriu algo que contradiz estes documentos, **corrija o documento** —
   documento errado é pior que documento ausente.
6. Relate o que não conseguiu fazer. Tarefa parcialmente feita e reportada como
   pronta custa mais caro que tarefa não feita.
