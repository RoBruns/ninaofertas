"""Testes puros (sem banco) das regras de MRR e churn em `core.billing`."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from core.billing import (
    Conta,
    EventoAssinatura,
    MetricaMes,
    metricas_mensais,
    mrr_da_assinatura,
    mrr_em,
    pagante_em,
    resumo_mes_atual,
)

UTC = timezone.utc
D = Decimal


def utc(ano: int, mes: int, dia: int, hora: int = 12, minuto: int = 0) -> datetime:
    return datetime(ano, mes, dia, hora, minuto, tzinfo=UTC)


def conta(tenant: UUID, criada: datetime | None = None, interna: bool = False) -> Conta:
    return Conta(tenant_id=tenant, created_at=criada or utc(2025, 1, 1), is_internal=interna)


def evento(tenant: UUID, quando: datetime, antes: str, depois: str) -> EventoAssinatura:
    return EventoAssinatura(
        tenant_id=tenant, occurred_at=quando, mrr_before=D(antes), mrr_after=D(depois)
    )


def por_mes(metricas: list[MetricaMes]) -> dict[date, MetricaMes]:
    return {m.mes: m for m in metricas}


# --- mrr_da_assinatura -------------------------------------------------------


def test_mrr_mensal_e_o_proprio_preco() -> None:
    assert mrr_da_assinatura(D("49.90"), "month", "active") == D("49.90")
    assert mrr_da_assinatura(D("49.90"), "month", "past_due") == D("49.90")


def test_mrr_anual_divide_por_doze_com_arredondamento_half_up() -> None:
    assert mrr_da_assinatura(D("478.80"), "year", "active") == D("39.90")
    # 100 / 12 = 8.3333… → 8.33; 0.30 / 12 = 0.025 → 0.03 (HALF_UP)
    assert mrr_da_assinatura(D("100"), "year", "active") == D("8.33")
    assert mrr_da_assinatura(D("0.30"), "year", "past_due") == D("0.03")


@pytest.mark.parametrize("status", ["trialing", "comp", "canceled"])
def test_status_sem_receita_vale_zero(status: str) -> None:
    resultado = mrr_da_assinatura(D("49.90"), "month", status)
    assert resultado == D("0.00")
    assert str(resultado) == "0.00"


def test_status_desconhecido_levanta_erro() -> None:
    with pytest.raises(ValueError, match="Status"):
        mrr_da_assinatura(D("49.90"), "month", "paused")


def test_intervalo_desconhecido_e_float_sao_recusados() -> None:
    with pytest.raises(ValueError, match="Intervalo"):
        mrr_da_assinatura(D("49.90"), "week", "active")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        mrr_da_assinatura(49.90, "month", "active")  # type: ignore[arg-type]


def test_dataclasses_exigem_datetime_aware() -> None:
    with pytest.raises(ValueError):
        Conta(tenant_id=uuid4(), created_at=datetime(2026, 1, 1), is_internal=False)
    with pytest.raises(ValueError):
        EventoAssinatura(uuid4(), datetime(2026, 1, 1), D("0"), D("10"))


# --- pagante / MRR num instante ----------------------------------------------


def test_mrr_em_usa_ultimo_evento_ate_o_instante() -> None:
    t = uuid4()
    eventos = [evento(t, utc(2026, 3, 1), "0", "49.90"), evento(t, utc(2026, 3, 10), "49.90", "0")]
    assert mrr_em(eventos, utc(2026, 2, 28)) == D("0.00")
    assert mrr_em(eventos, utc(2026, 3, 1)) == D("49.90")  # <= inclui o próprio instante
    assert pagante_em(eventos, utc(2026, 3, 5))
    assert not pagante_em(eventos, utc(2026, 3, 10))


# --- metricas_mensais --------------------------------------------------------


def test_cancelar_e_reativar_no_mesmo_mes_nao_e_churn() -> None:
    t = uuid4()
    eventos = [
        evento(t, utc(2026, 1, 10), "0", "49.90"),
        evento(t, utc(2026, 2, 5), "49.90", "0"),
        evento(t, utc(2026, 2, 20), "0", "49.90"),
    ]
    fev = por_mes(metricas_mensais([conta(t)], eventos, 3, utc(2026, 3, 15)))[date(2026, 2, 1)]
    assert fev.paying_start == 1
    assert fev.paying_end == 1
    assert fev.churned == 0
    assert fev.new_paying == 0
    assert fev.churn_rate == D("0.0000")
    assert fev.mrr == D("49.90")


def test_downgrade_para_gratis_conta_como_churn() -> None:
    pagante, fica = uuid4(), uuid4()
    eventos = [
        evento(pagante, utc(2026, 1, 10), "0", "49.90"),
        evento(fica, utc(2026, 1, 11), "0", "49.90"),
        evento(pagante, utc(2026, 2, 15), "49.90", "0"),  # plano grátis
    ]
    metricas = por_mes(metricas_mensais([conta(pagante), conta(fica)], eventos, 2, utc(2026, 3, 2)))
    fev = metricas[date(2026, 2, 1)]
    assert fev.paying_start == 2
    assert fev.paying_end == 1
    assert fev.churned == 1
    assert fev.churn_rate == D("0.5000")
    assert fev.mrr == D("49.90")
    assert fev.arpa == D("49.90")
    assert fev.contraction_mrr == D("0.00")  # churn não é contração


def test_tenant_interno_fica_fora_de_tudo() -> None:
    externo, interno = uuid4(), uuid4()
    contas = [conta(externo, utc(2026, 3, 2)), conta(interno, utc(2026, 3, 3), interna=True)]
    eventos = [
        evento(externo, utc(2026, 3, 2), "0", "49.90"),
        evento(interno, utc(2026, 3, 3), "0", "999.00"),
    ]
    mar = resumo_mes_atual(contas, eventos, utc(2026, 3, 20))
    assert mar.mrr == D("49.90")
    assert mar.paying_end == 1
    assert mar.new_tenants == 1
    assert mar.new_paying == 1


def test_mes_sem_pagantes_tem_churn_rate_e_arpa_none() -> None:
    t = uuid4()
    metricas = metricas_mensais([conta(t, utc(2026, 1, 5))], [], 2, utc(2026, 2, 10))
    for mes in metricas:
        assert mes.paying_start == 0
        assert mes.paying_end == 0
        assert mes.churn_rate is None
        assert mes.arpa is None
        assert mes.mrr == D("0.00")
    assert [m.mes for m in metricas] == [date(2026, 1, 1), date(2026, 2, 1)]
    assert metricas[0].new_tenants == 1
    assert metricas[1].new_tenants == 0


def test_expansao_e_contracao_so_entre_pagantes_do_inicio_e_do_fim() -> None:
    sobe, desce, novo = uuid4(), uuid4(), uuid4()
    eventos = [
        evento(sobe, utc(2026, 1, 5), "0", "49.90"),
        evento(desce, utc(2026, 1, 6), "0", "99.90"),
        evento(sobe, utc(2026, 2, 10), "49.90", "99.90"),
        evento(desce, utc(2026, 2, 11), "99.90", "49.90"),
        evento(desce, utc(2026, 2, 12), "49.90", "39.90"),
        evento(novo, utc(2026, 2, 13), "0", "49.90"),  # novo pagante: não é expansão
    ]
    contas = [conta(sobe), conta(desce), conta(novo)]
    fev = por_mes(metricas_mensais(contas, eventos, 2, utc(2026, 3, 1, 12)))[date(2026, 2, 1)]
    assert fev.expansion_mrr == D("50.00")
    assert fev.contraction_mrr == D("60.00")
    assert fev.new_paying == 1
    assert fev.paying_start == 2
    assert fev.paying_end == 3
    assert fev.mrr == D("189.70")
    assert fev.arpa == D("63.23")  # 189.70 / 3 = 63.2333…


def test_limite_do_mes_em_horario_de_brasilia() -> None:
    t = uuid4()
    # 02:30 UTC do dia 1º de março = 23:30 de 28/02 em Brasília (UTC−3).
    eventos = [evento(t, utc(2026, 3, 1, 2, 30), "0", "49.90")]
    metricas = por_mes(metricas_mensais([conta(t)], eventos, 2, utc(2026, 3, 15)))
    fev, mar = metricas[date(2026, 2, 1)], metricas[date(2026, 3, 1)]
    assert fev.new_paying == 1
    assert fev.paying_end == 1
    assert fev.mrr == D("49.90")
    assert mar.paying_start == 1
    assert mar.new_paying == 0


def test_evento_as_tres_utc_do_dia_primeiro_ja_e_do_mes_novo() -> None:
    t = uuid4()
    # 03:00 UTC = 00:00 em Brasília: pertence ao mês que começa.
    eventos = [evento(t, utc(2026, 3, 1, 3, 0), "0", "49.90")]
    metricas = por_mes(metricas_mensais([conta(t)], eventos, 2, utc(2026, 3, 15)))
    assert metricas[date(2026, 2, 1)].paying_end == 0
    assert metricas[date(2026, 3, 1)].new_paying == 1


def test_mes_atual_usa_agora_e_ignora_eventos_futuros() -> None:
    t = uuid4()
    eventos = [
        evento(t, utc(2026, 3, 2), "0", "49.90"),
        evento(t, utc(2026, 3, 20), "49.90", "99.90"),
    ]
    contas = [conta(t, utc(2026, 3, 2)), conta(uuid4(), utc(2026, 3, 25))]
    agora = utc(2026, 3, 10)
    atual = resumo_mes_atual(contas, eventos, agora)
    assert atual.mes == date(2026, 3, 1)
    assert atual.mrr == D("49.90")  # o upgrade de 20/03 ainda não aconteceu
    assert atual.new_tenants == 1  # a conta de 25/03 também é futura

    depois = resumo_mes_atual(contas, eventos, utc(2026, 3, 26))
    assert depois.mrr == D("99.90")
    assert depois.new_tenants == 2
    assert depois.expansion_mrr == D("0.00")  # não pagava no início de março


def test_mes_atual_em_brasilia_quando_utc_ja_virou_o_mes() -> None:
    # 01/04 01:00 UTC ainda é 31/03 22:00 em Brasília: o mês atual é março.
    metricas = metricas_mensais([], [], 3, utc(2026, 4, 1, 1, 0))
    assert [m.mes for m in metricas] == [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)]


def test_meses_atravessa_virada_de_ano_e_valida_parametros() -> None:
    metricas = metricas_mensais([], [], 3, utc(2026, 1, 15))
    assert [m.mes for m in metricas] == [date(2025, 11, 1), date(2025, 12, 1), date(2026, 1, 1)]
    with pytest.raises(ValueError):
        metricas_mensais([], [], 0, utc(2026, 1, 15))
    with pytest.raises(ValueError):
        metricas_mensais([], [], 1, datetime(2026, 1, 15))
