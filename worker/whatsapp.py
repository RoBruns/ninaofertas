"""Envio de mensagens via evolution-api usando a instancia do telefone do bot."""

from __future__ import annotations

import base64
import json
import re
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

import httpx
from PIL import Image, UnidentifiedImageError

from core.http_headers import BROWSER_USER_AGENT
from core.log_safe import safe_log_text
from core.settings import BASE_DIR, settings
from worker.logger import logger


class WhatsAppError(Exception):
    pass


_MEDIA_URL_PREFIXES = (
    "https://http2.mlstatic.com/",
    "https://http.mlstatic.com/",
    "https://cf.shopee.com.br/",
    "https://down-br.img.susercontent.com/",
    "https://down-bs.img.susercontent.com/",
    "https://scontent.",
    "https://m.media-amazon.com/",
    "https://images-na.ssl-images-amazon.com/",
)


def _path_local_permitido(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    for root_name in ("data", "assets"):
        try:
            resolved.relative_to((BASE_DIR / root_name).resolve())
            return True
        except ValueError:
            continue
    return False


def _url_midia_permitida(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").lower()
    if any(url.startswith(prefix) for prefix in _MEDIA_URL_PREFIXES):
        return True
    return host.endswith(
        (
            "shopee.com.br",
            "mercadolivre.com.br",
            "mlstatic.com",
            "susercontent.com",
            "media-amazon.com",
            "ssl-images-amazon.com",
            "magazinevoce.com.br",
            "magazineluiza.com.br",
        )
    )


def enviar_mensagem(
    texto: str,
    imagem: str | None = None,
    grupo: str | None = None,
    *,
    previa_do_link: bool = False,
    previa_imagem: str | None = None,
) -> bool:
    """Envia texto e, apenas quando permitida, uma imagem para o grupo atual.

    previa_imagem pede o cartão só com a foto: sem título nem descrição da
    página, e o toque abre o link do texto. Se a Evolution recusar esse
    formato, a mensagem cai no sendMedia (foto anexada), nunca só texto.
    """
    from worker.channels import grupo_whatsapp, instancia_evolution

    destino = grupo or grupo_whatsapp()
    instancia = instancia_evolution()
    if not instancia or not destino:
        logger.error(
            "WhatsApp não configurado: o telefone do bot precisa de instância Evolution "
            "e o bot, de um grupo (dashboard)."
        )
        return False

    from core.config_provider import bot_runtime_atual, registrar_evento_runtime

    runtime = bot_runtime_atual()
    token = runtime.instance_token if runtime else None
    headers = {"apikey": token or settings.evolution_api_key, "Content-Type": "application/json"}
    url = f"{settings.evolution_api_url}/message/sendText/{instancia}"
    payload: dict[str, object] = {"number": destino, "text": texto}
    imagem_reserva = imagem
    cartao = _cartao_so_foto(texto, previa_imagem) if previa_imagem else None
    if cartao:
        payload["linkPreview"] = cartao
        imagem = None
    elif previa_do_link:
        payload["linkPreview"] = True
        imagem = None
    if imagem:
        media = _media_payload(imagem)
        if media:
            url = f"{settings.evolution_api_url}/message/sendMedia/{instancia}"
            # Evolution (Baileys) faz Buffer.from(media, 'base64') — base64 CRU, não data-URL.
            payload = {
                "number": destino,
                "mediatype": "image",
                "media": media,
                "caption": texto,
            }
            if not str(media).startswith("http"):
                payload["mimetype"] = "image/jpeg"
                payload["fileName"] = "foto.jpg"
        else:
            logger.warning(
                "Imagem rejeitada (URL/base64 inválido); enviando só texto. "
                f"prefixo={str(imagem)[:48]!r}"
            )
    try:
        with httpx.Client(timeout=25.0) as client:
            response = client.post(url, json=payload, headers=headers)
            if response.status_code == 401 and token:
                # O guard rejeita a chave antes de enviar. Apenas 401 permite retry.
                registrar_evento_runtime(
                    "evolution_instance_token_rejected",
                    "Token da instância rejeitado; envio tentado com chave geral",
                    level="warning",
                )
                logger.warning("Token da instância rejeitado; envio tentado com chave geral")
                headers["apikey"] = settings.evolution_api_key
                response = client.post(url, json=payload, headers=headers)
            # 400 = fail-closed da Evolution; 500 = VipsJpeg em GIF/WebP da CDN.
            if (
                response.status_code >= 400
                and isinstance(payload.get("linkPreview"), dict)
            ):
                logger.info(
                    "Evolution recusou a prévia só com foto; anexando a imagem"
                )
                media = _media_payload(
                    imagem_reserva or previa_imagem or "",
                    forcar_jpeg_base64=True,
                )
                if not media:
                    return False
                url = f"{settings.evolution_api_url}/message/sendMedia/{instancia}"
                payload = {
                    "number": destino,
                    "mediatype": "image",
                    "media": media,
                    "caption": texto,
                }
                if not str(media).startswith("http"):
                    payload["mimetype"] = "image/jpeg"
                    payload["fileName"] = "foto.jpg"
                response = client.post(url, json=payload, headers=headers)
        if response.status_code >= 400:
            # O corpo explica a falha (número inválido, sessão caída); as chaves saem dele.
            logger.error(
                f"evolution-api retornou erro {response.status_code}: "
                f"{_sem_chaves(response.text, token, settings.evolution_api_key)}"
            )
            return False
        return True
    except httpx.RequestError as exc:
        logger.error(
            f"Falha ao conectar na evolution-api ({settings.evolution_api_url}): "
            f"{_sem_chaves(exc, token, settings.evolution_api_key)}"
        )
        return False


def _cartao_so_foto(texto: str, imagem: str) -> dict[str, str] | None:
    """Foto clicável, sem título nem descrição.

    Sempre JPEG em base64: a CDN do ML às vezes devolve GIF e a Evolution
    quebra com VipsJpeg ao montar a miniatura do link.
    """
    media = _media_payload(imagem, forcar_jpeg_base64=True)
    if not media or media.startswith("https://"):
        return None
    cartao: dict[str, str] = {"thumbnailBase64": media}
    achado = re.search(r"https://[^\s<>]+", texto or "")
    if achado:
        cartao["canonicalUrl"] = achado.group(0).rstrip(").,]")
    return cartao


def _sem_chaves(texto: object, *chaves: str | None) -> str:
    """Texto para log sem o token da instância nem a chave geral."""
    saida = str(texto)
    for chave in chaves:
        if chave:
            saida = saida.replace(chave, "[REDACTED]")
    return safe_log_text(saida, 300)


def _jpeg_base64(raw: bytes) -> str | None:
    """Converte qualquer formato que o Pillow abra em JPEG base64."""
    try:
        with Image.open(BytesIO(raw)) as img:
            if img.mode in ("RGBA", "LA", "P"):
                rgb = img.convert("RGB")
            elif img.mode != "RGB":
                rgb = img.convert("RGB")
            else:
                rgb = img
            saida = BytesIO()
            rgb.save(saida, format="JPEG", quality=85, optimize=True)
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        logger.warning(f"não deu para virar JPEG a miniatura: {exc}")
        return None
    return base64.b64encode(saida.getvalue()).decode("ascii")


def _baixar_bytes_midia(url: str) -> bytes | None:
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            response = client.get(
                url,
                headers={
                    "User-Agent": BROWSER_USER_AGENT,
                    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                },
            )
        if response.status_code >= 400 or not response.content:
            logger.warning(
                f"download da miniatura falhou HTTP {response.status_code} "
                f"({url[:80]})"
            )
            return None
        if _placeholder_mercado_livre(url, response.headers.get("content-type")):
            logger.warning(f"foto do ML inexistente (GIF de aviso): {url[:80]}")
            return None
        return response.content
    except httpx.HTTPError as exc:
        logger.warning(f"download da miniatura falhou: {exc}")
        return None


def _placeholder_mercado_livre(url: str, content_type: str | None) -> bool:
    """A CDN do ML responde 200 com um GIF de "imagem não encontrada"."""
    host = (urlparse(url).hostname or "").lower()
    return host.endswith("mlstatic.com") and "gif" in (content_type or "").lower()


def _media_payload(imagem: str, *, forcar_jpeg_base64: bool = False) -> str | None:
    if imagem.startswith("https://"):
        if not _url_midia_permitida(imagem):
            logger.warning(f"URL de mídia fora da allowlist: {imagem[:120]}")
            return None
        if forcar_jpeg_base64:
            bruto = _baixar_bytes_midia(imagem)
            return _jpeg_base64(bruto) if bruto else None
        return imagem
    if imagem.startswith("http://"):
        logger.warning("URL http:// não permitida para mídia; use https ou arquivo local.")
        return None
    from core.mirror_media import base64_puro

    # data-URL ou base64 cru → sempre base64 puro (sendMedia / Buffer.from).
    if imagem.startswith("data:image/") or "base64," in imagem[:80]:
        cru = base64_puro(imagem)
        if not cru:
            return None
        if forcar_jpeg_base64:
            try:
                return _jpeg_base64(base64.b64decode(cru, validate=False))
            except (ValueError, TypeError):
                return None
        return cru
    path = Path(imagem)
    # Evita tratar base64 longo como "caminho" inexistente.
    if len(imagem) < 512 and path.is_file():
        if not _path_local_permitido(path):
            logger.warning(f"Arquivo de mídia fora de data/ ou assets/: {imagem}")
            return None
        bruto = path.read_bytes()
        if forcar_jpeg_base64:
            return _jpeg_base64(bruto)
        return base64.b64encode(bruto).decode("ascii")
    cru = base64_puro(imagem)
    if not cru:
        return None
    if forcar_jpeg_base64:
        try:
            return _jpeg_base64(base64.b64decode(cru, validate=False))
        except (ValueError, TypeError):
            return None
    return cru


def _participante_do_numero(part: dict, numero: str) -> bool:
    return numero.lower() in json.dumps(part, ensure_ascii=False).lower()


def avisar_permissao_grupos() -> None:
    from worker.channels import canais_ativos

    ativos = canais_ativos()
    if ativos:
        _avisar_permissao_banco(ativos)


def _avisar_permissao_banco(canais: tuple[str, ...]) -> None:
    from worker.channels import (
        grupo_whatsapp,
        instancia_evolution,
        nome_canal,
        telefone_bot,
        usar_canal,
    )

    headers = {"apikey": settings.evolution_api_key}
    for canal in canais:
        with usar_canal(canal):
            instance = instancia_evolution()
            url = f"{settings.evolution_api_url}/group/fetchAllGroups/{instance}"
            try:
                with httpx.Client(timeout=30.0) as client:
                    response = client.get(
                        url, headers=headers, params={"getParticipants": "true"}
                    )
                response.raise_for_status()
                data = response.json()
            except Exception as exc:
                logger.warning(
                    f"Não deu para checar permissão dos grupos: {safe_log_text(exc)}"
                )
                continue
            groups = (
                data if isinstance(data, list) else data.get("data") or data.get("groups") or []
            )
            wanted = grupo_whatsapp()
            group = next(
                (
                    item
                    for item in groups
                    if isinstance(item, dict)
                    and str(item.get("id") or item.get("jid") or "") == wanted
                ),
                None,
            )
            if group is None:
                logger.warning(f"[{nome_canal()}] grupo {wanted} não apareceu na Evolution")
                continue
            if not bool(group.get("announce")):
                continue
            number = telefone_bot()
            if not number:
                logger.warning(
                    f"[{nome_canal()}] grupo somente admins; cadastre o número do telefone "
                    "no dashboard para conferir se o bot é admin."
                )
                continue
            participant = next(
                (
                    item
                    for item in group.get("participants") or []
                    if _participante_do_numero(item, number)
                ),
                None,
            )
            admin = participant.get("admin") if isinstance(participant, dict) else None
            if not admin:
                logger.error(
                    f"[{nome_canal()}] grupo somente admins e o bot não é admin; "
                    f"promova {number} a admin."
                )
            else:
                logger.info(f"[{nome_canal()}] grupo somente admins; bot é admin ({admin}).")
