"""Aplica os critérios de `config.json` sobre uma oferta capturada."""
from __future__ import annotations

from datetime import datetime, timezone

from core.platforms.base import OfertaCapturada

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
    texto_lower = texto.lower()
    return any(termo.lower() in texto_lower for termo in termos)


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
            return False, "cupons desabilitados no config"
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

        desconto_minimo = filtros.get("desconto_minimo")
        if desconto_minimo and oferta.desconto is not None and oferta.desconto < desconto_minimo:
            return False, f"desconto {oferta.desconto}% abaixo do mínimo {desconto_minimo}%"

        max_vendas = filtros.get("max_vendas")
        # 0 = sem limite, como nos tetos diários (decisão do usuário, 2026-09-24).
        # Antes, max_vendas=0 descartava todo produto com 1 venda ou mais — na
        # prática, quase toda a Shopee, a única fonte que informa vendas.
        if (
            max_vendas not in (None, 0, "0")
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

    produtos_especificos = filtros.get("produtos_especificos")
    if produtos_especificos and not _contem_alguma(oferta.nome, produtos_especificos):
        return False, "não corresponde a nenhum produto específico monitorado"

    return True, ""
