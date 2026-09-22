"""Definição compartilhada dos canais legados."""

from __future__ import annotations

CANAIS = {
    "achadinhos": {
        "arquivo": "config.json",
        "grupo_env": "WHATSAPP_GROUP_ID",
        "nome": "Achadinhos da Nina",
        "ativo": True,
    },
    "auto": {
        "arquivo": "config.auto.json",
        "grupo_env": "WHATSAPP_GROUP_ID_AUTO",
        "nome": "Nina Ofertas",
        "ativo": False,
    },
}
