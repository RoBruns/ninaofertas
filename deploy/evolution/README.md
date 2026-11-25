# Evolution — cartão só com a foto

A imagem de produção da `evolution-api` (tag 2.3.8 + patch, deploy `ad03115e`)
aceita `linkPreview` como booleano **ou** objeto sem título:

```json
{
  "number": "120363...@g.us",
  "text": "…\nhttps://meli.la/xxxx",
  "linkPreview": {
    "thumbnailBase64": "<base64 cru ou data-url>",
    "canonicalUrl": "https://meli.la/xxxx"
  }
}
```

Sem título nem descrição: o WhatsApp mostra a foto e o domínio do link.
O toque abre o `canonicalUrl` (ou a primeira URL do texto, se o campo faltar).

## Fail-closed

Se a miniatura falhar (download/upload), a Evolution responde **HTTP 400**.
Não cai na prévia automática da página (que traria o título OG).
O worker da Nina, nesse caso, anexa a foto com `sendMedia`.

## Como aplicar de novo

Base: tag Git `2.3.8` do repositório oficial Evolution.

```bash
git checkout 2.3.8
git apply /caminho/para/ninaofertas/deploy/evolution/cartao-so-foto.patch
```

Publicar com `railway up` no serviço `evolution-api`, **sem** recriar o
serviço nem o volume `/evolution/instances`. Preferir o silêncio noturno.
Conferir `CONNECTED TO WHATSAPP` no log antes de mexer em qualquer coisa.

Arquivos tocados pelo patch:

- `src/api/dto/sendMessage.dto.ts` — `LinkPreviewCard`
- `src/validate/message.schema.ts` — `oneOf` boolean|object
- `src/api/integrations/channel/whatsapp/whatsapp.baileys.service.ts` — montagem
- `Dockerfile`, `.dockerignore`, `tsconfig.json` — build na Railway
