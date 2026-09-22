"""Gera a print do cupom no estilo dos grupos de oferta (card Shopee / MELI)."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from core.platforms.base import OfertaCapturada
from core.settings import BASE_DIR

_DIR = BASE_DIR / "data" / "cupons"
_FONTS = (
    Path(r"C:\Windows\Fonts\segoeui.ttf"),
    Path(r"C:\Windows\Fonts\arial.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
)
_FONTS_BOLD = (
    Path(r"C:\Windows\Fonts\segoeuib.ttf"),
    Path(r"C:\Windows\Fonts\arialbd.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
)


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for p in _FONTS_BOLD if bold else _FONTS:
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


def _rounded(draw: ImageDraw.ImageDraw, xy, r: int, fill) -> None:
    draw.rounded_rectangle(xy, radius=r, fill=fill)


def _preco_txt(valor: float | None) -> str:
    if valor is None:
        return ""
    if abs(valor - round(valor)) < 0.001:
        return str(int(round(valor)))
    return f"{valor:.2f}".replace(".", ",")


def gerar_card(oferta: OfertaCapturada) -> str | None:
    _DIR.mkdir(parents=True, exist_ok=True)
    loja = (oferta.loja or "").lower()
    sku = (oferta.codigo_cupom or oferta.sku or "cupom").replace(":", "_").replace("/", "_")[-40:]
    dest = _DIR / f"{sku}.png"
    if "shopee" in loja:
        img = _card_shopee(oferta)
    else:
        img = _card_meli(oferta)
    img.save(dest, "PNG")
    return str(dest)


def _titulo_desconto(oferta: OfertaCapturada) -> str:
    if oferta.beneficio:
        return oferta.beneficio
    if oferta.desconto and oferta.desconto >= 1:
        return f"{int(oferta.desconto)}% de desconto"
    if oferta.preco and oferta.preco > 0:
        return f"R${_preco_txt(oferta.preco)} de desconto"
    return "Cupom de desconto"


def _card_shopee(oferta: OfertaCapturada) -> Image.Image:
    w, h = 900, 520
    img = Image.new("RGB", (w, h), "#f3f3f3")
    d = ImageDraw.Draw(img)
    _rounded(d, (36, 48, w - 36, h - 48), 28, "#ffffff")

    d.rounded_rectangle((36, 48, 200, 96), radius=12, fill="#F6C344")
    d.text((58, 56), "Limitado", font=_font(22, True), fill="#3a2a00")

    # fita "Novo"
    d.polygon([(w - 170, 48), (w - 36, 48), (w - 36, 130), (w - 92, 130)], fill="#EE4D2D")
    d.text((w - 128, 62), "Novo", font=_font(20, True), fill="#ffffff")

    # logo S
    d.ellipse((70, 140, 178, 248), fill="#EE4D2D")
    d.text((102, 158), "S", font=_font(64, True), fill="#ffffff")

    d.text((200, 150), "TODAS AS LOJAS", font=_font(22, True), fill="#9a9a9a")
    d.text((200, 188), _titulo_desconto(oferta), font=_font(36, True), fill="#222222")
    min_txt = f"Compras acima de R${_preco_txt(oferta.min_gasto)}" if oferta.min_gasto else "Válido no app"
    d.text((200, 242), min_txt, font=_font(24), fill="#888888")

    d.line((70, 310, w - 70, 310), fill="#eeeeee", width=2)
    validade = oferta.validade or "hoje"
    d.text((70, 340), f"Termina em: {validade}", font=_font(22), fill="#888888")
    d.text((360, 340), "Condições", font=_font(22), fill="#2ea7e0")

    _rounded(d, (w - 250, 325, w - 70, 395), 22, "#EE4D2D")
    d.text((w - 200, 340), "Usar", font=_font(28, True), fill="#ffffff")
    return img


def _card_meli(oferta: OfertaCapturada) -> Image.Image:
    w, h = 900, 520
    img = Image.new("RGB", (w, h), "#FFF159")
    px = img.load()
    for y in range(h):
        t = y / max(h - 1, 1)
        r = int(255 - t * (255 - 52))
        g = int(241 - t * (241 - 131))
        b = int(89 + t * (250 - 89))
        for x in range(w):
            px[x, y] = (r, g, b)

    d = ImageDraw.Draw(img)
    cx, cy, rad = 450, 210, 118
    d.ellipse((cx - rad, cy - rad, cx + rad, cy + rad), fill="#FFF159")
    emoji_path = Path(r"C:\Windows\Fonts\seguiemj.ttf")
    if emoji_path.exists():
        d.text(
            (cx - 52, cy - 58),
            "🤝",
            font=ImageFont.truetype(str(emoji_path), 96),
            embedded_color=True,
            anchor="lt",
        )
    d.text((cx - 132, 360), "mercado livre", font=_font(40, True), fill="#2D3277")
    return img
