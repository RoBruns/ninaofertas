"""Loop principal: busca ofertas, filtra, deduplica e envia ao WhatsApp.

1ª fase (baseline): marca estoque atual sem enviar.
Depois: só ofertas novas/quentes — com freio anti-ban no WhatsApp.
"""
from __future__ import annotations

import affiliate
import cupom_card
import dedup
import database
import formatter
import whatsapp
from config import canal_atual, grupo_whatsapp, load_filtros, nome_canal, settings
from filters import passa_nos_filtros
from logger import logger
from scraper import FONTES
from scraper.base import OfertaCapturada

_baseline_ciclos_feitos: dict[str, int] = {}
_ciclo_n: dict[str, int] = {}


def _intercalar_lojas(ofertas: list[OfertaCapturada], prioridade: str) -> list[OfertaCapturada]:
    """MELI e Shopee se revezam; `prioridade` começa a fila pra não ficar só uma loja."""
    from collections import defaultdict, deque

    filas: dict[str, deque] = defaultdict(deque)
    for o in ofertas:
        filas[o.loja].append(o)
    lojas = sorted(filas.keys(), key=lambda l: (0 if l == prioridade else 1, l))
    out: list[OfertaCapturada] = []
    while any(filas.values()):
        for loja in lojas:
            if filas[loja]:
                out.append(filas[loja].popleft())
    return out


def _ordenar_envio(ofertas: list[OfertaCapturada], n: int, prioridade: str) -> list[OfertaCapturada]:
    cupons = [o for o in ofertas if (o.categoria or "").lower() == "cupom"]
    produtos = [o for o in ofertas if (o.categoria or "").lower() != "cupom"]
    produtos = _intercalar_lojas(produtos, prioridade)
    if n % 4 == 0 and cupons:
        return cupons[:1] + produtos + cupons[1:]
    return produtos + cupons


def _salvar_oferta(session, oferta: OfertaCapturada):
    return database.upsert_oferta(
        session,
        {
            "nome": oferta.nome,
            "preco": oferta.preco,
            "preco_anterior": oferta.preco_anterior,
            "desconto": oferta.desconto,
            "loja": oferta.loja,
            "categoria": oferta.categoria,
            "url": oferta.url,
            "imagem": oferta.imagem,
            "sku": oferta.sku,
        },
    )


def _baseline_oferta(session, oferta: OfertaCapturada, filtros: dict) -> bool:
    passou, motivo = passa_nos_filtros(oferta, filtros)
    if not passou:
        logger.debug(f"Baseline descartada '{oferta.nome[:60]}': {motivo}")
        return False

    oferta_db = _salvar_oferta(session, oferta)
    grupo = grupo_whatsapp()
    if database.ja_conhecida(session, oferta_db.id, grupo=grupo):
        return False
    database.registrar_visto(session, oferta_db.id, oferta.preco, grupo=grupo)
    return True


def _freio_anti_ban(session, filtros: dict, grupo: str, oferta: OfertaCapturada | None = None) -> tuple[bool, str]:
    """Ritmo da conta inteira: o WhatsApp bane o número, não o grupo."""
    from datetime import datetime, timedelta

    decorridos_conta = database.minutos_desde_ultimo_envio(session)

    intervalo_min = filtros.get("intervalo_minutos_entre_ofertas")
    if intervalo_min and decorridos_conta is not None and decorridos_conta < float(intervalo_min):
        falta = float(intervalo_min) - decorridos_conta
        return False, f"freio: intervalo {intervalo_min} min na conta (faltam ~{falta:.0f} min)"

    max_rajada = int(filtros.get("max_ofertas_por_rajada") or 0)
    janela = float(filtros.get("janela_rajada_minutos") or 12)
    pausa = float(filtros.get("pausa_entre_rajadas_minutos") or 0)
    if max_rajada and pausa:
        n_janela = database.contar_envios_desde(
            session, datetime.now() - timedelta(minutes=janela)
        )
        if n_janela >= max_rajada and decorridos_conta is not None and decorridos_conta < pausa:
            falta = pausa - decorridos_conta
            return False, (
                f"freio: rajada de {n_janela}/{max_rajada} na conta — "
                f"pausa {pausa:.0f} min (faltam ~{falta:.0f} min)"
            )

    max_hora_grupo = filtros.get("max_ofertas_por_hora")
    if max_hora_grupo and database.contar_envios_ultima_hora(session, grupo=grupo) >= int(max_hora_grupo):
        return False, f"freio: limite {max_hora_grupo}/hora neste grupo"

    max_hora_global = filtros.get("max_ofertas_globais_por_hora")
    if max_hora_global and database.contar_envios_ultima_hora(session) >= int(max_hora_global):
        return False, f"freio: limite {max_hora_global}/hora na conta (os dois grupos juntos)"

    max_dia_grupo = filtros.get("max_ofertas_por_dia")
    if max_dia_grupo not in (None, 0, "0") and database.contar_envios_hoje(session, grupo=grupo) >= int(max_dia_grupo):
        return False, f"freio: limite {max_dia_grupo}/dia neste grupo"

    max_dia_global = filtros.get("max_ofertas_globais_por_dia")
    if max_dia_global not in (None, 0, "0") and database.contar_envios_hoje(session) >= int(max_dia_global):
        return False, f"freio: limite {max_dia_global}/dia na conta (os dois grupos juntos)"

    if oferta and (oferta.categoria or "").lower() == "cupom":
        max_cupom = int(filtros.get("max_cupons_por_dia") or 2)
        if database.contar_cupons_hoje(session, grupo=grupo) >= max_cupom:
            return False, f"freio: já foram {max_cupom} cupons hoje neste grupo"

    return True, ""


def _processar_oferta(session, oferta: OfertaCapturada, filtros: dict) -> str:
    """Retorna: 'enviou' | 'pulou' | 'freio' (parar o ciclo de envios)."""
    passou, motivo = passa_nos_filtros(oferta, filtros)
    if not passou:
        logger.debug(f"Descartada '{oferta.nome[:60]}': {motivo}")
        return "pulou"

    oferta_db = _salvar_oferta(session, oferta)
    grupo = grupo_whatsapp()

    pode_enviar, motivo_dedup = dedup.deve_enviar(
        session,
        oferta_db.id,
        oferta.preco,
        settings.reenvio_queda_minima,
        nome=oferta.nome,
        sku=oferta.sku,
        loja=oferta.loja,
        grupo=grupo,
    )
    if not pode_enviar:
        if "duplicata" in motivo_dedup or "igual/parecida" in motivo_dedup:
            if not database.ja_conhecida(session, oferta_db.id, grupo=grupo):
                database.registrar_visto(session, oferta_db.id, oferta.preco, grupo=grupo)
        logger.debug(f"Pulando '{oferta.nome[:60]}': {motivo_dedup}")
        return "pulou"

    ok_ritmo, motivo_freio = _freio_anti_ban(session, filtros, grupo, oferta)
    if not ok_ritmo:
        logger.warning(f"[{nome_canal()}] {motivo_freio}")
        return "freio"

    logger.info(f"[{nome_canal()}] Oferta NOVA: {oferta.nome}")
    if oferta.desconto is not None:
        logger.info(f"Desconto: {oferta.desconto}%")
    logger.info(f"Motivo: {motivo_dedup}")

    oferta.url = affiliate.garantir_afiliado(oferta.loja, oferta.url)
    if oferta.url_carrinho:
        oferta.url_carrinho = affiliate.garantir_afiliado(oferta.loja, oferta.url_carrinho)
    if (oferta.categoria or "").lower() == "cupom":
        try:
            card = cupom_card.gerar_card(oferta)
            if card:
                oferta.imagem = card
        except Exception as e:
            logger.warning(f"Não deu pra gerar print do cupom: {e}")

    mensagem = formatter.montar_mensagem(oferta)

    logger.info(f"[{nome_canal()}] Enviando para WhatsApp...")
    sucesso = whatsapp.enviar_mensagem(mensagem, imagem=oferta.imagem, grupo=grupo)

    database.registrar_envio(
        session,
        oferta_id=oferta_db.id,
        grupo=grupo,
        mensagem=mensagem,
        preco=oferta.preco,
        status="sucesso" if sucesso else "falha",
    )

    if sucesso:
        logger.info("Oferta enviada com sucesso.")
        return "enviou"
    logger.error("Falha ao enviar oferta para o WhatsApp.")
    return "falhou"


def ciclo() -> None:
    canal = canal_atual()
    feitos = _baseline_ciclos_feitos.get(canal, 0)
    n = _ciclo_n.get(canal, 0)

    logger.info(f"[{nome_canal()}] Buscando novas ofertas...")
    filtros = load_filtros()
    baseline_alvo = int(filtros.get("baseline_ciclos") or 0)
    max_por_ciclo = int(filtros.get("max_ofertas_por_ciclo") or 1)
    grupo = grupo_whatsapp()

    todas_ofertas: list[OfertaCapturada] = []
    for fonte in FONTES:
        todas_ofertas.extend(fonte.executar())

    n += 1
    _ciclo_n[canal] = n
    prioridade = "Shopee" if n % 2 == 1 else "Mercado Livre"
    todas_ofertas = _ordenar_envio(todas_ofertas, n, prioridade)

    logger.info(f"[{nome_canal()}] {len(todas_ofertas)} ofertas encontradas na varredura.")

    with database.get_session() as session:
        # Restart no Railway zera a memória; se o grupo já blipou, não marca o catálogo de novo.
        if feitos < baseline_alvo and database.grupo_ja_enviou(session, grupo):
            feitos = baseline_alvo
            _baseline_ciclos_feitos[canal] = feitos
            logger.info(
                f"[{nome_canal()}] Baseline pulada (banco já tem envios). Seguindo com ofertas novas."
            )

        if feitos < baseline_alvo:
            feitos += 1
            _baseline_ciclos_feitos[canal] = feitos
            logger.info(
                f"[{nome_canal()}] Baseline {feitos}/{baseline_alvo}: "
                "marcando estoque atual (sem enviar)."
            )
            novas_marcadas = 0
            for oferta in todas_ofertas:
                try:
                    if _baseline_oferta(session, oferta, filtros):
                        novas_marcadas += 1
                except Exception as e:
                    logger.error(f"Erro no baseline '{oferta.nome[:60]}': {e}")
            logger.info(f"[{nome_canal()}] Baseline: +{novas_marcadas} ofertas marcadas neste ciclo.")
            if feitos >= baseline_alvo:
                logger.info(
                    f"[{nome_canal()}] Baseline concluída. Próximas novidades serão blipadas "
                    "com freio anti-ban."
                )
        else:
            enviadas_ciclo = 0
            puladas = 0
            falhas = 0
            for oferta in todas_ofertas:
                try:
                    resultado = _processar_oferta(session, oferta, filtros)
                except Exception as e:
                    logger.error(f"Erro ao processar oferta '{oferta.nome[:60]}': {e}")
                    falhas += 1
                    continue
                if resultado == "freio":
                    break
                if resultado == "pulou":
                    puladas += 1
                    continue
                if resultado == "falhou":
                    falhas += 1
                    continue
                if resultado == "enviou":
                    enviadas_ciclo += 1
                    if enviadas_ciclo >= max_por_ciclo:
                        logger.info(
                            f"[{nome_canal()}] Freio anti-ban: já enviou {enviadas_ciclo} neste ciclo "
                            f"(máx {max_por_ciclo})."
                        )
                        break
            if enviadas_ciclo == 0:
                logger.warning(
                    f"[{nome_canal()}] Ciclo sem blip: {len(todas_ofertas)} capturadas, "
                    f"{puladas} puladas (filtro/dedup), {falhas} falhas de envio."
                )

    logger.info(f"[{nome_canal()}] Próxima verificação em {settings.check_interval}s.")
