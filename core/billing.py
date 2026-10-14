"""Regras puras das métricas de SaaS do Nina Bot (MRR, pagantes, churn).

Este módulo não acessa banco: recebe dados simples (dataclasses congeladas) e
devolve números. Quem ligar às tabelas `subscriptions` e `subscription_events`
só precisa converter as linhas em `Conta` e `EventoAssinatura`.

Definições
----------

MRR de uma assinatura (`mrr_da_assinatura`)
    Plano mensal: o próprio preço. Plano anual: preço / 12. Arredondado a
    centavos com ROUND_HALF_UP. Só gera receita com status `active` ou
    `past_due` (inadimplente ainda conta até ser cancelado); `trialing`,
    `comp` (cortesia) e `canceled` valem R$ 0,00. Status, intervalo
    desconhecido ou preço negativo levantam `ValueError`.

Evento de assinatura (`EventoAssinatura`)
    Toda mudança de MRR de um tenant vira um evento com `mrr_before` e
    `mrr_after`. O MRR de um tenant num instante é o `mrr_after` do último
    evento com `occurred_at <= instante` (zero se não houver evento). Eventos
    no mesmo instante são desempatados pela ordem em que foram recebidos (o
    último da lista vence).

Pagante num instante
    Tenant cujo MRR naquele instante é maior que zero. Downgrade para o plano
    grátis (mrr_after = 0) deixa de ser pagante, exatamente como cancelar.

Mês
    Mês civil em horário de Brasília (`core.relogio.BR`), nunca no fuso do
    processo. Um evento às 02:30 UTC do dia 1º ainda é 23:30 do último dia do
    mês anterior em Brasília e pertence ao mês anterior.
    - Início do mês: estado imediatamente antes de 00:00 do dia 1º (eventos
      com `occurred_at` estritamente anterior). Um evento às 00:00 em ponto
      já pertence ao mês novo.
    - Fim do mês: estado imediatamente antes de 00:00 do dia 1º do mês
      seguinte. Assim o fim de um mês é exatamente o início do próximo.
    - Mês corrente: o fim é `agora` (eventos com `occurred_at <= agora`).
      Eventos depois de `agora` são ignorados em todos os meses.

Tenants internos (`Conta.is_internal`)
    Excluídos de tudo: não contam em MRR, pagantes, novos tenants nem churn.
    Eventos de tenant sem `Conta` correspondente também são ignorados (com
    aviso no log), pois não há como saber se o tenant é interno.

Métricas de cada mês (`MetricaMes`)
    - `mrr`: soma do MRR dos tenants no fim do mês.
    - `paying_start` / `paying_end`: pagantes no início / fim do mês.
    - `new_tenants`: contas criadas dentro do mês (`created_at` no intervalo
      do mês; no mês corrente, até `agora`).
    - `new_paying`: tenants que não pagavam no início do mês e pagam no fim.
      Inclui quem já pagou antes, saiu e voltou (reativação conta como novo
      pagante do mês em que volta).
    - `churned`: tenants que pagavam no início do mês e não pagam no fim.
      Cancelar e reativar dentro do mesmo mês NÃO é churn; quem assina e
      cancela dentro do mesmo mês também não entra (não pagava no início).
    - `churn_rate`: churned / paying_start, com 4 casas (ROUND_HALF_UP);
      `None` quando paying_start = 0.
    - `expansion_mrr` / `contraction_mrr`: só para tenants pagantes no início
      E no fim do mês; soma das variações positivas / valor absoluto da soma
      das variações negativas de MRR (fim − início). Novos pagantes e churn
      ficam de fora (são `new_paying` e `churned`).
    - `arpa`: mrr / paying_end, a centavos (ROUND_HALF_UP); `None` quando
      paying_end = 0.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal
from uuid import UUID

from loguru import logger

from core.relogio import BR

CENTAVOS = Decimal("0.01")
TAXA = Decimal("0.0001")
ZERO = Decimal("0.00")

STATUS_COM_RECEITA = frozenset({"active", "past_due"})
STATUS_SEM_RECEITA = frozenset({"trialing", "comp", "canceled"})
INTERVALOS = frozenset({"month", "year"})


def _exigir_aware(valor: datetime, campo: str) -> None:
    if valor.tzinfo is None or valor.utcoffset() is None:
        raise ValueError(f"{campo} precisa ter fuso horário (datetime aware, em UTC).")


def _exigir_decimal(valor: object, campo: str) -> None:
    if not isinstance(valor, Decimal):
        raise TypeError(f"{campo} precisa ser Decimal (dinheiro nunca é float).")


@dataclass(frozen=True)
class EventoAssinatura:
    """Mudança de MRR de um tenant (uma linha de `subscription_events`)."""

    tenant_id: UUID
    occurred_at: datetime
    mrr_before: Decimal
    mrr_after: Decimal

    def __post_init__(self) -> None:
        _exigir_aware(self.occurred_at, "occurred_at")
        _exigir_decimal(self.mrr_before, "mrr_before")
        _exigir_decimal(self.mrr_after, "mrr_after")


@dataclass(frozen=True)
class Conta:
    """Tenant (cliente) do SaaS."""

    tenant_id: UUID
    created_at: datetime
    is_internal: bool

    def __post_init__(self) -> None:
        _exigir_aware(self.created_at, "created_at")


@dataclass(frozen=True)
class MetricaMes:
    """Métricas de um mês civil de Brasília (definições no docstring do módulo)."""

    mes: date
    mrr: Decimal
    paying_start: int
    paying_end: int
    new_tenants: int
    new_paying: int
    churned: int
    churn_rate: Decimal | None
    expansion_mrr: Decimal
    contraction_mrr: Decimal
    arpa: Decimal | None


def mrr_da_assinatura(price: Decimal, interval: Literal["month", "year"], status: str) -> Decimal:
    """MRR de uma assinatura: preço mensal, ou anual / 12, só se ativa ou inadimplente."""
    _exigir_decimal(price, "price")
    if price < 0:
        raise ValueError(f"Preço negativo não é válido: {price}.")
    if interval not in INTERVALOS:
        raise ValueError(f"Intervalo de cobrança desconhecido: {interval!r}.")
    if status not in STATUS_COM_RECEITA | STATUS_SEM_RECEITA:
        raise ValueError(f"Status de assinatura desconhecido: {status!r}.")
    if status in STATUS_SEM_RECEITA:
        return ZERO
    mensal = price if interval == "month" else price / 12
    return mensal.quantize(CENTAVOS, rounding=ROUND_HALF_UP)


def mrr_em(eventos: Sequence[EventoAssinatura], instante: datetime) -> Decimal:
    """MRR de um tenant em `instante`: `mrr_after` do último evento até lá (inclusive)."""
    return _mrr_ate(eventos, instante, inclusivo=True)


def pagante_em(eventos: Sequence[EventoAssinatura], instante: datetime) -> bool:
    """Se o tenant paga em `instante` (MRR > 0 pelo último evento até lá)."""
    return mrr_em(eventos, instante) > 0


def _mrr_ate(
    eventos: Sequence[EventoAssinatura], instante: datetime, *, inclusivo: bool
) -> Decimal:
    """`eventos` precisa estar em ordem cronológica estável (ver `_agrupar_eventos`)."""
    mrr = ZERO
    for evento in eventos:
        antes = evento.occurred_at <= instante if inclusivo else evento.occurred_at < instante
        if not antes:
            break
        mrr = evento.mrr_after
    return mrr


def _inicio_do_mes(ano: int, mes: int) -> datetime:
    return datetime(ano, mes, 1, tzinfo=BR)


def _mes_seguinte(ano: int, mes: int) -> tuple[int, int]:
    return (ano + 1, 1) if mes == 12 else (ano, mes + 1)


def _meses_ate(agora_br: datetime, meses: int) -> list[tuple[int, int]]:
    """Os `meses` meses civis terminando no mês de `agora_br`, do mais antigo ao atual."""
    ano, mes = agora_br.year, agora_br.month
    lista: list[tuple[int, int]] = []
    for _ in range(meses):
        lista.append((ano, mes))
        ano, mes = (ano - 1, 12) if mes == 1 else (ano, mes - 1)
    lista.reverse()
    return lista


def _agrupar_eventos(
    eventos: Iterable[EventoAssinatura],
    tenants: set[UUID],
    internos: set[UUID],
    agora: datetime,
) -> dict[UUID, list[EventoAssinatura]]:
    """Eventos até `agora` por tenant externo, em ordem cronológica."""
    por_tenant: dict[UUID, list[EventoAssinatura]] = defaultdict(list)
    desconhecidos: set[UUID] = set()
    for evento in eventos:
        if evento.occurred_at > agora or evento.tenant_id in internos:
            continue
        if evento.tenant_id not in tenants:
            desconhecidos.add(evento.tenant_id)
            continue
        por_tenant[evento.tenant_id].append(evento)
    for lista in por_tenant.values():
        # sort é estável: eventos no mesmo instante mantêm a ordem recebida.
        lista.sort(key=lambda e: e.occurred_at)
    if desconhecidos:
        logger.warning(
            "Métricas de billing ignoraram eventos de {} tenant(s) sem conta correspondente.",
            len(desconhecidos),
        )
    return por_tenant


def metricas_mensais(
    contas: Iterable[Conta],
    eventos: Iterable[EventoAssinatura],
    meses: int,
    agora: datetime,
) -> list[MetricaMes]:
    """Métricas dos últimos `meses` meses civis (Brasília), do mais antigo ao atual."""
    _exigir_aware(agora, "agora")
    if meses < 1:
        raise ValueError(f"meses precisa ser pelo menos 1 (recebido: {meses}).")

    todas = list(contas)
    contas_externas = [conta for conta in todas if not conta.is_internal]
    tenants = {conta.tenant_id for conta in contas_externas}
    internos = {conta.tenant_id for conta in todas if conta.is_internal}
    por_tenant = _agrupar_eventos(eventos, tenants, internos, agora)

    resultado: list[MetricaMes] = []
    lista_meses = _meses_ate(agora.astimezone(BR), meses)
    for indice, (ano, mes) in enumerate(lista_meses):
        inicio = _inicio_do_mes(ano, mes)
        corrente = indice == len(lista_meses) - 1
        fim = agora if corrente else _inicio_do_mes(*_mes_seguinte(ano, mes))

        mrr_total = ZERO
        paying_start = paying_end = new_paying = churned = 0
        expansion = contraction = ZERO
        for tenant in tenants:
            eventos_tenant = por_tenant.get(tenant, [])
            mrr_inicio = _mrr_ate(eventos_tenant, inicio, inclusivo=False)
            mrr_fim = _mrr_ate(eventos_tenant, fim, inclusivo=corrente)
            pagava, paga = mrr_inicio > 0, mrr_fim > 0
            mrr_total += mrr_fim
            paying_start += pagava
            paying_end += paga
            if paga and not pagava:
                new_paying += 1
            elif pagava and not paga:
                churned += 1
            elif pagava and paga:
                variacao = mrr_fim - mrr_inicio
                if variacao > 0:
                    expansion += variacao
                else:
                    contraction -= variacao

        if corrente:
            novos = sum(1 for c in contas_externas if inicio <= c.created_at <= fim)
        else:
            novos = sum(1 for c in contas_externas if inicio <= c.created_at < fim)

        mrr_total = mrr_total.quantize(CENTAVOS, rounding=ROUND_HALF_UP)
        resultado.append(
            MetricaMes(
                mes=date(ano, mes, 1),
                mrr=mrr_total,
                paying_start=paying_start,
                paying_end=paying_end,
                new_tenants=novos,
                new_paying=new_paying,
                churned=churned,
                churn_rate=(
                    (Decimal(churned) / Decimal(paying_start)).quantize(
                        TAXA, rounding=ROUND_HALF_UP
                    )
                    if paying_start
                    else None
                ),
                expansion_mrr=expansion.quantize(CENTAVOS, rounding=ROUND_HALF_UP),
                contraction_mrr=contraction.quantize(CENTAVOS, rounding=ROUND_HALF_UP),
                arpa=(
                    (mrr_total / paying_end).quantize(CENTAVOS, rounding=ROUND_HALF_UP)
                    if paying_end
                    else None
                ),
            )
        )
    return resultado


def resumo_mes_atual(
    contas: Iterable[Conta],
    eventos: Iterable[EventoAssinatura],
    agora: datetime,
) -> MetricaMes:
    """Métricas do mês corrente (Brasília) até `agora`."""
    return metricas_mensais(contas, eventos, 1, agora)[-1]
