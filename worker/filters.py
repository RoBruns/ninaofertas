"""Aplica os critérios de `config.json` sobre uma oferta capturada."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from unicodedata import combining, normalize

from core.platforms.base import OfertaCapturada
from worker.ranking import comissao_estimada_reais

# Casa + público feminino (campanhas Shopee off-topic).
_NICHOS_CASA_PADRAO = (
    "casa",
    "lar",
    "decor",
    "cozinha",
    "sala",
    "quarto",
    "beleza",
    "make",
    "unha",
    "cabelo",
    "femin",
    "mulher",
    "planta",
    "jardim",
    "eletro",
    "poltrona",
    "sofá",
    "sofa",
)

# Título precisa parecer casa, eletro, beleza ou acessório feminino.
_FOCO_CASA_PADRAO = (
    "poltrona",
    "sofá",
    "sofa",
    "puff",
    "tapete",
    "carpete",
    "cortina",
    "almofada",
    "travesseiro",
    "edredom",
    "jogo de cama",
    "colchão",
    "colchao",
    "mesa",
    "cadeira",
    "estante",
    "nichos",
    "organizador",
    "luminária",
    "luminaria",
    "abajur",
    "espelho",
    "quadro",
    "vaso",
    "planta",
    "suculenta",
    "jardim",
    "cachepot",
    "decoração",
    "decoracao",
    "difusor",
    "aroma",
    "vela arom",
    "toalha",
    "panela",
    "frigideira",
    "air fryer",
    "airfryer",
    "liquidificador",
    "batedeira",
    "cafeteira",
    "mixer",
    "sanduicheira",
    "aspirador",
    "ventilador",
    "umidificador",
    "ferro de passar",
    "máquina de lavar",
    "maquina de lavar",
    "geladeira",
    "fogão",
    "fogao",
    "micro-ondas",
    "microondas",
    "cooktop",
    "forno",
    "unha",
    "unhas",
    "esmalte",
    "alongamento",
    "nail",
    "maquiagem",
    "batom",
    "rímel",
    "rimel",
    "paleta",
    "skincare",
    "sérum",
    "serum",
    "hidratante",
    "perfume",
    "colônia",
    "colonia",
    "bolsa",
    "carteira",
    "brinco",
    "colar",
    "pulseira",
    "anel",
    "cabelo",
    "chapinha",
    "secador",
    "progressiva",
    "lingerie",
    "sutiã",
    "sutia",
    "calcinha",
    "vestido",
    "blusa",
    "cropped",
    "saia",
    "scarpin",
    "salto",
    "rasteira",
    "sandália",
    "sandalia",
    "feminina",
    "feminino",
    "para mulheres",
    "make",
    "pincel",
    "esfoliante",
    "máscara facial",
    "mascara facial",
    "creme",
    "óleo essencial",
    "oleo essencial",
    "porta-joia",
    "porta joia",
    "necessaire",
    "nécessaire",
    "tiara",
    "presilha",
    "elástico cabelo",
    "elastico cabelo",
    "cozinha",
    "jogo de cozinha",
    "jogos de cozinha",
    "jogo de panelas",
    "faqueiro",
    "talher",
    "assadeira",
    "xícara",
    "xicara",
    "caneca",
    "body splash",
    "body kit",
    "loção",
    "locao",
    "corporal",
    "gloss",
    "blush",
    "corretivo",
    "delineador",
    "iluminador",
    "primer",
    "cílios",
    "cilios",
    "demaquilante",
    "acetona",
    "árvore de natal",
    "arvore de natal",
    "pinheiro",
    "pisca-pisca",
    "pisca pisca",
    "guirlanda",
    "enfeite de natal",
    "bola de natal",
    "bolas de natal",
    "enfeites de natal",
    "natalina",
    "natalino",
    "presépio",
    "presepio",
    "luzes de natal",
    "adorno de natal",
)

_BOMBA_AUTO = (
    "motor",
    "radiador",
    "arrefecimento",
    "automot",
    "carro",
    "gol ",
    "fiat",
    "volkswagen",
    "vw ",
    "chevrolet",
    "honda",
    "toyota",
    "ford",
    "hyundai",
    "renault",
    "nissan",
    "peugeot",
    "palio",
    "uno ",
    "onix",
    "celta",
    "corsa",
    "kombi",
    "fusca",
    "saveiro",
    "siena",
    "civic",
    "corolla",
    "hilux",
    "cabeçote",
    "cabecote",
)

_BOMBA_NAO_AUTO = (
    "irrig",
    "centrifug",
    "piscina",
    "poco",
    "poço",
    "cisterna",
    "submers",
    "aspersor",
    "horta",
    "drenagem",
    "esgoto",
    "chafariz",
    "pressurizador",
    "sap ",
    "lavadora",
    "alta pressao",
    "alta pressão",
    "hidropon",
)


def _contem_alguma(texto: str, termos: list[str]) -> bool:
    def sem_acento(valor: str) -> str:
        return "".join(char for char in normalize("NFD", valor.lower()) if not combining(char))

    texto_lower = sem_acento(texto)
    return any(
        re.search(r"(?<![a-z0-9])" + re.escape(sem_acento(termo)), texto_lower)
        for termo in termos
    )


def _bomba_dagua_ok_no_auto(nome: str) -> bool:
    """Bomba d'água só vale se for de motor/carro, não irrigação/centrífuga."""
    n = nome.lower().replace("á", "a").replace("à", "a")
    if "bomba" not in n or "agua" not in n:
        return True
    if _contem_alguma(n, list(_BOMBA_NAO_AUTO)):
        return False
    return _contem_alguma(n, list(_BOMBA_AUTO))


_BLOQUEIO_AUTO_PADRAO = (
    "automot",
    "para carro",
    "p/ carro",
    "ignição",
    "ignicao",
    "bico injetor",
    "escapamento",
    "amortecedor",
    "pastilha de freio",
    "disco de freio",
    "embreagem",
    "calota",
    "pneu aro",
    "roda aro",
    "óleo motor",
    "oleo motor",
    "ngk",
    "para moto",
    "p/ moto",
    "veicular",
    "parachoque",
    "para-choque",
    "spoiler",
    "papel higiênico",
    "papel higienico",
    "câmera",
    "camera",
    "cftv",
)


_BLOQUEIO_INFANTIL_PADRAO = (
    "infantil",
    "infantis",
    "bebê",
    "bebe",
    "baby",
    "criança",
    "crianca",
    "kids",
    "berço",
    "berco",
    "fralda",
    "mamadeira",
    "chocalho",
    "mordedor",
    "carrinho de bebê",
    "carrinho de bebe",
    "cadeirinha bebê",
    "cadeirinha bebe",
    "roupa infantil",
    "sapato infantil",
    "para bebês",
    "para bebes",
    "para crianças",
    "para criancas",
    "brinquedo",
    "brinquedos",
    "toy ",
    " toys",
    "pelúcia",
    "pelucia",
    "boneca",
    "boneco",
    "lego",
    "escola infantil",
    "jardim de infância",
    "jardim de infancia",
)

_EXCECOES_COLECIONADOR_PADRAO = (
    "colecion",
    "colecao",
    "diecast",
    "die-cast",
    "hot wheels",
    "hotwheels",
    "miniatura escala",
    "escala 1:",
    "escala 1/",
    "1/18",
    "1/24",
    "1/43",
    "1/64",
)


def _eh_conteudo_infantil(nome: str, filtros: dict) -> bool:
    bloqueios = list(filtros.get("bloquear_termos") or _BLOQUEIO_INFANTIL_PADRAO)
    excecoes = list(filtros.get("excecoes_bloqueio") or _EXCECOES_COLECIONADOR_PADRAO)

    if _contem_alguma(nome, excecoes):
        bloqueios = [
            t
            for t in bloqueios
            if t.strip().lower()
            not in {"brinquedo", "brinquedos", "toy", "toys", "lego", "boneco", "boneca", "pelúcia", "pelucia"}
        ]

    return _contem_alguma(nome, bloqueios)


def _fora_do_foco(nome: str, filtros: dict) -> bool:
    termos = filtros.get("bloquear_produtos") or list(_BLOQUEIO_AUTO_PADRAO)
    return _contem_alguma(nome, termos)


def _nome_do_nicho(nome: str, termos: list[str]) -> bool:
    return _contem_alguma(nome, termos)


def passa_nos_filtros(oferta: OfertaCapturada, filtros: dict) -> tuple[bool, str]:
    """Retorna (passou, motivo). `motivo` é usado apenas para log quando falha."""

    cat = (oferta.categoria or "").lower()
    eh_cupom = cat == "cupom"
    eh_campanha = cat in {"campanha", "promocao", "promoção"}

    if eh_cupom:
        if filtros.get("aceitar_cupons") is False:
            return False, "envio de cupons desligado no bot"
        if _eh_conteudo_infantil(oferta.nome, filtros):
            return False, "conteúdo infantil bloqueado"
        lojas = filtros.get("lojas")
        if lojas and oferta.loja and oferta.loja.lower() not in [l.lower() for l in lojas]:
            return False, f"loja '{oferta.loja}' não está na lista permitida"
        return True, ""

    if _fora_do_foco(oferta.nome, filtros):
        return False, "produto fora do foco do grupo"

    if filtros.get("nicho") == "auto" and not _bomba_dagua_ok_no_auto(oferta.nome):
        return False, "bomba d'água fora do automotivo"

    if _eh_conteudo_infantil(oferta.nome, filtros):
        return False, "conteúdo infantil bloqueado"

    if eh_campanha:
        if filtros.get("aceitar_campanhas") is False:
            return False, "campanhas desabilitadas no config"
        termos_nicho = (
            filtros.get("palavras_chave_campanha")
            or filtros.get("termos_busca")
            or list(_NICHOS_CASA_PADRAO)
        )
        if not _contem_alguma(oferta.nome, termos_nicho):
            return False, "campanha fora do nicho do grupo"

    if not eh_campanha:
        preco_maximo = filtros.get("preco_maximo")
        if preco_maximo and oferta.preco > preco_maximo:
            return False, f"preço R${oferta.preco:.2f} acima do máximo R${preco_maximo:.2f}"

        preco_minimo = filtros.get("preco_minimo")
        if preco_minimo and oferta.preco < preco_minimo:
            return False, f"preço R${oferta.preco:.2f} abaixo do mínimo R${preco_minimo:.2f}"

        ignora_regras_ml = oferta.loja.lower() == "mercado livre" and filtros.get(
            "ml_ignora_desconto_e_vendas", False
        )
        desconto_minimo = filtros.get("desconto_minimo")
        if oferta.origem_mais_vendidos and not ignora_regras_ml:
            if oferta.desconto is None:
                return False, "mais vendido sem desconto conhecido"
            min_vendas = int(filtros.get("min_vendas", 100))
            if min_vendas > 0 and oferta.vendas is not None and oferta.vendas < min_vendas:
                return False, f"vendas {oferta.vendas} abaixo do mínimo {min_vendas} para mais vendidos"
        if (
            not ignora_regras_ml
            and desconto_minimo
            and oferta.desconto is not None
            and oferta.desconto < desconto_minimo
        ):
            return False, f"desconto {oferta.desconto}% abaixo do mínimo {desconto_minimo}%"

        max_vendas = filtros.get("max_vendas")
        # 0 = sem limite, como nos tetos diários (decisão do usuário, 2026-09-24).
        # Antes, max_vendas=0 descartava todo produto com 1 venda ou mais — na
        # prática, quase toda a Shopee, a única fonte que informa vendas.
        if (
            not ignora_regras_ml
            and not oferta.origem_mais_vendidos
            and max_vendas not in (None, 0, "0")
            and oferta.vendas is not None
            and oferta.vendas > int(max_vendas)
        ):
            return False, f"vendas {oferta.vendas} acima do máximo {max_vendas} (provável anúncio antigo)"

        max_idade_h = filtros.get("max_idade_oferta_horas")
        if max_idade_h and oferta.oferta_desde is not None:
            agora = datetime.now(timezone.utc)
            desde = oferta.oferta_desde
            if desde.tzinfo is None:
                desde = desde.replace(tzinfo=timezone.utc)
            idade_h = (agora - desde).total_seconds() / 3600
            if idade_h > float(max_idade_h):
                return False, f"oferta com {idade_h:.0f}h (máx {max_idade_h}h) — não é quente"

        piso = filtros.get("comissao_minima_reais") or 0
        estimada = comissao_estimada_reais(oferta)
        if piso and estimada is not None and estimada < float(piso):
            return (
                False,
                f"comissão estimada R${estimada:.2f} abaixo do mínimo R${float(piso):.2f}",
            )

    lojas = filtros.get("lojas")
    if lojas and oferta.loja and oferta.loja.lower() not in [l.lower() for l in lojas]:
        return False, f"loja '{oferta.loja}' não está na lista permitida"

    categorias = filtros.get("categorias")
    if categorias and oferta.categoria and not _contem_alguma(oferta.categoria, categorias):
        return False, f"categoria '{oferta.categoria}' não está na lista permitida"

    termos_nicho = (
        filtros.get("palavras_chave")
        or filtros.get("termos_peca")
        or list(_FOCO_CASA_PADRAO)
    )
    dispensa_nicho_ml = (
        filtros.get("ml_categoria_dispensa_nicho", False)
        and oferta.loja.lower() == "mercado livre"
        and oferta.origem_categoria_meli
    )
    if not dispensa_nicho_ml and termos_nicho and not _nome_do_nicho(oferta.nome, termos_nicho):
        n = oferta.nome.lower().replace("á", "a")
        bomba_auto = (
            filtros.get("nicho") == "auto"
            and "bomba" in n
            and "agua" in n
            and _bomba_dagua_ok_no_auto(oferta.nome)
        )
        if not bomba_auto:
            return False, "fora do nicho do grupo"

    produtos_especificos = filtros.get("produtos_especificos")
    if produtos_especificos and not _contem_alguma(oferta.nome, produtos_especificos):
        return False, "não corresponde a nenhum produto específico monitorado"

    return True, ""


def passa_filtros_espelho(oferta: OfertaCapturada, filtros: dict) -> tuple[bool, str]:
    """Gate do espelho: bloqueios, lojas e nicho — sem preço/desconto/vendas.

    Mensagens de WhatsApp raramente trazem preço estruturado; exigir os tetos
    do scraper descartaria quase tudo. Nicho usa palavras_chave / termos_peca
    ou o foco casa padrão (mesmo implícito do ciclo normal).
    """
    if _fora_do_foco(oferta.nome, filtros):
        return False, "produto fora do foco do grupo"
    if filtros.get("nicho") == "auto" and not _bomba_dagua_ok_no_auto(oferta.nome):
        return False, "bomba d'água fora do automotivo"
    if _eh_conteudo_infantil(oferta.nome, filtros):
        return False, "conteúdo infantil bloqueado"

    lojas = filtros.get("lojas")
    if lojas and oferta.loja and oferta.loja.lower() not in [l.lower() for l in lojas]:
        return False, f"loja '{oferta.loja}' não está na lista permitida"

    termos_nicho = (
        filtros.get("palavras_chave")
        or filtros.get("termos_peca")
        or list(_FOCO_CASA_PADRAO)
    )
    if termos_nicho and not _nome_do_nicho(oferta.nome, termos_nicho):
        n = oferta.nome.lower().replace("á", "a")
        bomba_auto = (
            filtros.get("nicho") == "auto"
            and "bomba" in n
            and "agua" in n
            and _bomba_dagua_ok_no_auto(oferta.nome)
        )
        if not bomba_auto:
            return False, "fora do nicho do grupo"
    return True, ""


# Linhas de origem que não entram no título (convite, aviso, CTA vazio…).
_LINHA_RUIDO_ESPELHO = re.compile(
    r"(?i)("
    r"chat\.whatsapp\.com|wa\.me/|"
    r"convide\s+uma\s+amiga|participar\s+do\s+grupo|"
    r"sujeita\s+a\s+altera|"
    r"pagamentos?\s+no\s+pix|"
    r"^\s*compre\s+aqui\s*:?\s*$|"
    r"^\s*link\s*:?\s*$|"
    r"grupo\s+da\s+gio|"
    r"ei,?\s*convide|"
    r"pegar\s+promo|"
    r"siga\s+a\s+nossa\s+p[aá]gina|"
    r"^\W*(?:use\s+(?:o\s+)?)?cupom\s*:"
    r")"
)
_LINHA_SO_PRECO = re.compile(
    r"(?i)^\s*(?:de|por)\s*:?\s*(?:R\$\s*)?\d",
)
# "R$1.000 DE DESCONTO" / "50% OFF" — chamada, não nome do produto.
_LINHA_BANNER_DESCONTO = re.compile(
    r"(?i)("
    r"R\$\s*[\d.,]+\s*(?:de\s+)?desconto|"
    r"desconto\s+de\s+R\$\s*[\d.,]+|"
    r"R\$\s*[\d.,]+\s*off|"
    r"[\d.,]+\s*%\s*off|"
    r"^\W*r\$\s*[\d.,]+\s*$"
    r")"
)


def _normalizar_espacos_espelho(texto: str) -> str:
    # NBSP / fine space do WhatsApp quebram o parse de "R$ 169,90".
    return (
        (texto or "")
        .replace("\u00a0", " ")
        .replace("\u202f", " ")
        .replace("\u2007", " ")
    )


_STOP_TITULO = {
    "de", "da", "do", "das", "dos", "com", "para", "por", "mais", "uma", "uns",
    "um", "em", "no", "na", "nos", "nas", "the", "and", "of",
}


def _linha_slogan(texto: str) -> bool:
    """Faixa de seção, tipo 'COZINHA MAIS PRÁTICA', não o nome do item."""
    nucleo = re.sub(r"[^\w\s]", " ", texto, flags=re.UNICODE)
    palavras = [p for p in nucleo.split() if p]
    if not 2 <= len(palavras) <= 8:
        return False
    if any(any(ch.isdigit() for ch in p) for p in palavras):
        return False
    letras = "".join(ch for p in palavras for ch in p if ch.isalpha())
    return bool(letras) and letras == letras.upper()


def _linha_e_preco(linha: str) -> bool:
    if _LINHA_SO_PRECO.search(linha):
        return True
    sem = _PRECO_BR_RE.sub(" ", linha)
    sem = re.sub(r"(?i)\b(de|por)\b", " ", sem)
    sem = re.sub(r"[\d|:./]+", " ", sem)
    return len(re.sub(r"\W+", "", sem, flags=re.UNICODE)) < 3


def _linha_banner_desconto(linha: str) -> bool:
    """Faixa de desconto ('R$1.000 DE DESCONTO'), não o nome do item."""
    return bool(_LINHA_BANNER_DESCONTO.search(linha or ""))


def linhas_uteis_espelho(texto: str) -> list[str]:
    limpo = re.sub(r"https?://\S+", " ", _normalizar_espacos_espelho(texto))
    saida: list[str] = []
    for linha in limpo.splitlines():
        if (
            _LINHA_RUIDO_ESPELHO.search(linha)
            or _linha_e_preco(linha)
            or _linha_banner_desconto(linha)
        ):
            continue
        t = " ".join(linha.split()).strip(" -•*|")
        t = re.sub(r"^[\W_]+", "", t)
        if len(re.sub(r"\W+", "", t, flags=re.UNICODE)) < 3:
            continue
        if len(t) >= 3:
            saida.append(t[:200])
    return saida


_LOJAS_TITULO = {
    "shopee", "mercado", "livre", "magalu", "magazine", "luiza", "amazon", "meli",
}
_VITRINE_RE = re.compile(r"(?i)direto\s+do\s+estoque")
# Post/landing de cupom (não PDP). Só no começo do título — "use o cupom" em
# produto real não casa.
_TITULO_CUPOM_OFERTA_RE = re.compile(
    r"(?i)^\W*("
    r"cupom(?:s)?\s+de\s+desconto|"
    r"cupons?\s+di[aá]rios?|"
    r"resgate\s+(?:o\s+)?cupom|"
    r"cupom\s+(?:shopee|meli|mercado(?:\s+livre)?|magalu|amazon)|"
    r"cupom(?:s)?\b"
    r")"
)
_PAGINA_CUPOM_RE = re.compile(
    r"(?i)cupons?\s+di[aá]rios?|daily\s+coupons?|voucher\s+offer|"
    r"cupom\s+de\s+desconto|resgate\s+(?:o\s+)?cupom|coupon\s+center|"
    r"central\s+de\s+cupons?"
)


def titulo_de_vitrine(titulo: str) -> bool:
    """Título da loja, não do item. Ex.: 'Direto do estoque da Shopee'."""
    limpo = limpar_titulo_pagina(titulo)
    nucleo = re.sub(r"\b20\d{2}\b", " ", limpo)
    tokens = _tokens_titulo(nucleo)
    produto = tokens - _LOJAS_TITULO - {"brasil", "oficial", "ofertas"}
    if _VITRINE_RE.search(limpo) and not (produto - {"direto", "estoque"}):
        return True
    return bool(tokens) and not produto


def pagina_de_cupom(titulo: str | None) -> bool:
    """OG/título de landing de cupom (ex.: 'Cupons Diários'), não de produto."""
    limpo = limpar_titulo_pagina(titulo or "")
    return bool(limpo) and bool(_PAGINA_CUPOM_RE.search(limpo))


def mensagem_eh_cupom_espelho(
    titulo: str,
    *,
    pagina: str | None = None,
) -> bool:
    """True quando a origem é cupom/campanha, não anúncio de um item.

    O espelho ainda envia; só não deve montar 'De x por' com preço ornamental.
    """
    if pagina_de_cupom(pagina):
        return True
    limpo = limpar_titulo_pagina(titulo or "")
    if not limpo:
        return False
    return bool(_TITULO_CUPOM_OFERTA_RE.search(limpo))


def titulo_mensagem_espelho(texto: str) -> str:
    """Nome do item. Faixa e título de vitrine não servem."""
    linhas = linhas_uteis_espelho(texto)
    for linha in linhas:
        if not _linha_slogan(linha) and not titulo_de_vitrine(linha):
            return linha
    if linhas:
        return linhas[0]
    limpo = re.sub(r"https?://\S+", " ", _normalizar_espacos_espelho(texto))
    t = " ".join(limpo.split()).strip()
    return (t or "oferta espelhada")[:200]


def _tokens_titulo(texto: str) -> set[str]:
    bruto = re.sub(r"[^\w\s]", " ", (texto or "").lower(), flags=re.UNICODE)
    return {
        p
        for p in bruto.split()
        if len(p) >= 3 and p not in _STOP_TITULO and not p.isdigit()
    }


def _tokens_produto(texto: str) -> set[str]:
    return _tokens_titulo(texto) - _LOJAS_TITULO


def titulo_bate_com_pagina(titulo: str, pagina: str) -> bool:
    """True se o título e o nome da página falam do mesmo item."""
    nosso = _tokens_produto(titulo)
    deles = _tokens_produto(pagina)
    if not nosso or not deles:
        return True
    return bool(nosso & deles)


def titulo_confirmado(titulo: str, pagina: str | None) -> str:
    """Nome do anúncio; página só entra se o anúncio for fraco e ela nomear o item.

    Dois nomes de produto sem tokens em comum (ex.: 'Saco de lixo' vs 'KIT
    PRINCIPIA') mantêm o caption — a foto da mensagem costuma bater com ele,
    e o og:title do short link às vezes aponta outro item.
    """
    if not pagina or titulo_de_vitrine(pagina) or pagina_de_cupom(pagina):
        return titulo
    if titulo_bate_com_pagina(titulo, pagina):
        return titulo
    anuncio_fraco = (
        titulo_de_vitrine(titulo)
        or _linha_slogan(titulo)
        or not _tokens_produto(titulo)
    )
    if not anuncio_fraco:
        return titulo
    return limpar_titulo_pagina(pagina)


def limpar_titulo_pagina(titulo: str) -> str:
    partes = re.split(r"\s+[|\-–]\s+", (titulo or "").strip())
    return (partes[0] or titulo).strip()[:200]


_NUM_PRECO = r"(\d{1,3}(?:\.\d{3})*,\d{2}|\d{1,3}(?:\.\d{3})+|\d+(?:,\d{2})?)"
_PRECO_BR_RE = re.compile(
    rf"R\$\s*{_NUM_PRECO}",
    re.IGNORECASE,
)
# "De: 2.309 | Por: R$1.017" — R$ opcional, mas exige ":" ou "R$" (não "de 10 peças").
_PRECO_DE_RE = re.compile(
    rf"(?i)\bde\s*(?:R\$\s*|:\s*(?:R\$\s*)?){_NUM_PRECO}",
)
# "Por: R$1.017", "por R$ 248,31", "Por apenas: R$208" (até 3 palavras no meio).
_PRECO_POR_RE = re.compile(
    rf"(?i)\bpor(?:\s+[A-Za-zÀ-ÿ]{{1,20}}){{0,3}}\s*(?:R\$\s*|:\s*(?:R\$\s*)?){_NUM_PRECO}",
)
# Só a keyword — o código vem nos tokens seguintes (pula loja/ruído).
_CUPOM_KW_RE = re.compile(
    r"(?ix)"
    r"(?:use\s+(?:o\s+)?|aplica(?:r)?\s+(?:o\s+)?|com\s+|mais\s+|\+\s*)?"
    r"cupom(?:\s+de\s+desconto)?"
    r"|"
    r"c[oó]digo(?:\s+do\s+cupom)?"
)
# Linha só com ticket + código (sem a palavra cupom): "🎟️ SUPEROFERTA"
_CUPOM_TICKET_RE = re.compile(
    r"(?i)(?:🎟️|🎫)\s*[*_~`]{0,2}([A-Za-z0-9][A-Za-z0-9\-]{2,15})[*_~`]{0,2}\b"
)
_CUPOM_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-]{2,15}")
_CUPOM_DENY = frozenset(
    {
        "HTTP",
        "HTTPS",
        "MLB",
        "JSON",
        "TYPE",
        "CUPOM",
        "CUPONS",
        "OFF",
        "PIX",
        "LINK",
        "AQUI",
        "SHOP",
        "SHOPEE",
        "MAGALU",
        "MELI",
        "AMAZON",
        "MERCADO",
        "LIVRE",
        "PARA",
        "HOJE",
        "LIBERADO",
        "DISPONIVEL",
        "DISPONÍVEL",
        "DESCONTO",
        "GANHAR",
        "PROMOCIONAL",
        "PRODUTO",
        "COMPRA",
        "USAR",
        "USE",
        "APLICAR",
        "CODIGO",
        "CÓDIGO",
        "VALIDO",
        "VÁLIDO",
        "CHECKOUT",
        "APENAS",
        "INFORMADO",
        "CHEGAR",
        "VALOR",
    }
)


def _parse_preco_br(raw: str) -> float | None:
    texto = _normalizar_espacos_espelho(raw).strip()
    if not texto:
        return None
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    else:
        texto = texto.replace(".", "")
    try:
        valor = float(texto)
    except ValueError:
        return None
    return valor if valor > 0 else None


def _texto_sem_banner_desconto(texto: str) -> str:
    """Tira faixas 'R$1.000 DE DESCONTO' pra não virar preço do produto."""
    linhas = []
    for linha in (texto or "").splitlines():
        if _linha_banner_desconto(linha):
            continue
        linhas.append(linha)
    return "\n".join(linhas)


def extrair_precos_mensagem(texto: str) -> tuple[float | None, float | None]:
    """Retorna (preço atual, preço anterior) a partir de 'R$ …' / De:/Por:."""
    texto_n = _texto_sem_banner_desconto(_normalizar_espacos_espelho(texto))
    de = _PRECO_DE_RE.search(texto_n)
    por = _PRECO_POR_RE.search(texto_n)
    if de and por:
        anterior = _parse_preco_br(de.group(1))
        atual = _parse_preco_br(por.group(1))
        if atual and anterior and anterior - atual >= 0.01:
            return atual, anterior
        if atual:
            return atual, None
    valores = [
        v
        for m in _PRECO_BR_RE.finditer(texto_n)
        if (v := _parse_preco_br(m.group(1))) is not None
    ]
    if not valores:
        return None, None
    if len(valores) == 1:
        return valores[0], None
    primeiro, segundo = valores[0], valores[1]
    if abs(primeiro - segundo) < 0.01:
        return primeiro, None
    # "De R$ maior por R$ menor" — ou o inverso na ordem do texto.
    atual = min(primeiro, segundo)
    anterior = max(primeiro, segundo)
    return atual, anterior


def _cupom_espelho_ok(codigo: str | None) -> str | None:
    raw = (codigo or "").strip().upper().replace("-", "")
    if re.fullmatch(r"[A-Z0-9]{4,16}", raw) is None:
        return None
    if raw in _CUPOM_DENY:
        return None
    return raw


def _sem_urls(texto: str) -> str:
    """Tira http(s) pra o slug do meli.la/shopee não virar 'cupom'."""
    return re.sub(r"https?://\S+", " ", texto or "", flags=re.I)


def _candidatos_cupom(bloco: str) -> list[str]:
    """Todos os códigos possíveis no bloco; preferir os que têm dígito."""
    limpo = _sem_urls(bloco)
    encontrados: list[str] = []
    for match in _CUPOM_KW_RE.finditer(limpo):
        # Até o fim da linha + um pouco — para antes de onde estava a URL.
        cauda = limpo[match.end() : match.end() + 80]
        # Corta no próximo "cupom"/"use" de outra frase longa.
        for tok in _CUPOM_TOKEN_RE.findall(cauda):
            codigo = _cupom_espelho_ok(tok)
            if codigo:
                encontrados.append(codigo)
    for match in _CUPOM_TICKET_RE.finditer(limpo):
        codigo = _cupom_espelho_ok(match.group(1))
        if codigo:
            encontrados.append(codigo)
    for bruto in re.findall(r"\*([A-Za-z0-9\-]{4,16})\*", limpo):
        codigo = _cupom_espelho_ok(bruto)
        if codigo:
            encontrados.append(codigo)
    # Dedup preservando ordem.
    vistos: set[str] = set()
    unicos: list[str] = []
    for code in encontrados:
        if code not in vistos:
            vistos.add(code)
            unicos.append(code)
    # Preferir dígito só se o token misturar letra+dígito (L40FH…), não "10" puro.
    mistos = [
        c
        for c in unicos
        if any(ch.isdigit() for ch in c) and any(ch.isalpha() for ch in c)
    ]
    return mistos or unicos


def mensagem_menciona_cupom(texto: str) -> bool:
    """True se a origem fala em cupom (mesmo sem código digitável)."""
    limpo = _sem_urls(texto or "").casefold()
    # Evita cupons?+re.I (no CPython, `s?` com IGNORECASE não casa "cupom").
    return "cupom" in limpo or "🎟️" in (texto or "") or "🎫" in (texto or "")


def extrair_cupom_mensagem(texto: str) -> str | None:
    """Cupom digitável na origem — prioriza linha perto do link de compra."""
    texto_n = _normalizar_espacos_espelho(texto)
    linhas = texto_n.splitlines()
    # 1) Linhas vizinhas a URL de marketplace (onde o cupom costuma aparecer).
    idxs_link = [
        i
        for i, linha in enumerate(linhas)
        if re.search(
            r"https?://(?:\S+\.)?(?:shopee|meli\.la|mercadolivre|amazon|magalu|magazinevoce)",
            linha,
            re.I,
        )
    ]
    vizinhas: list[str] = []
    for i in idxs_link:
        for j in range(max(0, i - 4), min(len(linhas), i + 5)):
            vizinhas.append(linhas[j])
    for bloco in ("\n".join(vizinhas), texto_n):
        candidatos = _candidatos_cupom(bloco)
        if candidatos:
            return candidatos[0]
    return None
