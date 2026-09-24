"""Contrato versionado da configuracao operacional consumida pelo worker."""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.json_schema import SkipJsonSchema

from core.safety import validate_safe_pacing

FILTER_KEYS = {
    "preco_minimo",
    "preco_maximo",
    "desconto_minimo",
    "lojas",
    "nicho",
    "categorias",
    "categorias_meli",
    "termos_busca",
    "palavras_chave",
    "produtos_especificos",
    "bloquear_produtos",
    "bloquear_termos",
    "excecoes_bloqueio",
    "max_vendas",
    "max_idade_oferta_horas",
}
PACING_KEYS = {
    "max_ofertas_por_ciclo",
    "intervalo_minutos_entre_ofertas",
    "max_ofertas_por_rajada",
    "janela_rajada_minutos",
    "pausa_entre_rajadas_minutos",
    "max_ofertas_por_hora",
    "max_ofertas_por_dia",
    "max_ofertas_globais_por_hora",
    "max_ofertas_globais_por_dia",
}
CONTENT_KEYS = {
    "aceitar_cupons",
    "aceitar_campanhas",
    "max_cupons_por_dia",
    "cupons_meli",
    "baseline_ciclos",
}
SCHEDULE_KEYS = {"check_interval", "quiet_hours"}
LEGACY_KEYS = FILTER_KEYS | PACING_KEYS | CONTENT_KEYS | SCHEDULE_KEYS | {"mensagem_template"}


class Filters(BaseModel):
    model_config = ConfigDict(extra="allow")

    preco_minimo: float = Field(default=20, ge=0)
    preco_maximo: float = Field(default=5000, ge=0)
    desconto_minimo: float = Field(default=15, ge=0)
    lojas: list[str] = Field(default_factory=list)
    categorias_meli: list[str] = Field(default_factory=list)
    termos_busca: list[str] = Field(default_factory=list)
    palavras_chave: list[str] = Field(default_factory=list)
    bloquear_produtos: list[str] = Field(default_factory=list)
    bloquear_termos: list[str] = Field(default_factory=list)
    excecoes_bloqueio: list[str] = Field(default_factory=list)
    max_vendas: int = Field(default=20, ge=0)
    max_idade_oferta_horas: int = Field(default=0, ge=0)


class Pacing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_ofertas_por_ciclo: int = Field(default=1, ge=1)
    intervalo_minutos_entre_ofertas: int = Field(default=5, ge=0)
    max_ofertas_por_rajada: int = Field(default=3, ge=1)
    janela_rajada_minutos: int = Field(default=15, ge=1)
    pausa_entre_rajadas_minutos: int = Field(default=35, ge=0)
    max_ofertas_por_hora: int = Field(default=6, ge=1)
    # 0 = sem teto diário (ADR-018); o ritmo por hora e o intervalo continuam obrigatórios.
    max_ofertas_por_dia: int = Field(default=80, ge=0)
    max_ofertas_globais_por_hora: int = Field(default=8, ge=1)
    max_ofertas_globais_por_dia: int = Field(default=90, ge=0)

    @model_validator(mode="after")
    def safe_limits(self) -> Self:
        validate_safe_pacing(self.model_dump())
        return self


class Content(BaseModel):
    model_config = ConfigDict(extra="allow")

    aceitar_cupons: bool = True
    aceitar_campanhas: bool = False
    max_cupons_por_dia: int = Field(default=2, ge=0)
    baseline_ciclos: int = Field(default=5, ge=0)


class QuietHours(BaseModel):
    start: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    end: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class Schedule(BaseModel):
    model_config = ConfigDict(extra="allow")

    check_interval: int = Field(default=60, ge=1)
    quiet_hours: QuietHours = Field(default_factory=lambda: QuietHours(start="23:00", end="07:00"))


class Attribution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ml_tag: str | None = Field(
        default=None,
        description=(
            "Etiqueta de rastreamento do Mercado Livre: 3 a 40 caracteres, "
            "somente letras minusculas, numeros, _ e -."
        ),
    )

    @field_validator("ml_tag")
    @classmethod
    def validate_ml_tag(cls, value: str | None) -> str | None:
        import re

        if value is not None and re.fullmatch(r"[a-z0-9_-]{3,40}", value) is None:
            raise ValueError(
                "ml_tag deve ter de 3 a 40 caracteres: apenas letras minusculas, "
                "numeros, _ e -"
            )
        return value


class BotSettings(BaseModel):
    """Formato novo aninhado, com leitura e escrita lossless do config legado.

    `_legacy_input` e interno e excluido do schema. Ele permite que os JSONs que
    hoje alimentam o worker facam round-trip byte-a-byte no nivel de chaves,
    enquanto configuracoes novas sao persistidas no contrato aninhado.
    """

    model_config = ConfigDict(extra="allow")

    schema_version: Literal[1] = 1
    filters: Filters = Field(default_factory=Filters)
    pacing: Pacing = Field(default_factory=Pacing)
    content: Content = Field(default_factory=Content)
    schedule: Schedule = Field(default_factory=Schedule)
    attribution: Attribution = Field(default_factory=Attribution)
    # Internos do round-trip do config.json legado: fora da saída (exclude) e
    # fora do schema publicado (SkipJsonSchema), senão o contrato os exporia
    # como campos que o cliente precisa enviar.
    legacy_input: SkipJsonSchema[bool] = Field(default=False, exclude=True, alias="_legacy_input")
    legacy_keys: SkipJsonSchema[list[str]] = Field(
        default_factory=list, exclude=True, alias="_legacy_keys"
    )

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_config(cls, value: Any) -> Any:
        if not isinstance(value, dict) or any(
            key in value for key in ("filters", "pacing", "content", "schedule", "attribution")
        ):
            return value
        if not (set(value) & LEGACY_KEYS):
            return value
        source = dict(value)
        nested: dict[str, Any] = {
            "schema_version": 1,
            "filters": {key: source[key] for key in FILTER_KEYS if key in source},
            "pacing": {key: source[key] for key in PACING_KEYS if key in source},
            "content": {key: source[key] for key in CONTENT_KEYS if key in source},
            "schedule": {key: source[key] for key in SCHEDULE_KEYS if key in source},
            "_legacy_input": True,
            "_legacy_keys": list(source),
        }
        known = FILTER_KEYS | PACING_KEYS | CONTENT_KEYS | SCHEDULE_KEYS
        nested.update({key: item for key, item in source.items() if key not in known})
        return nested

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        dumped = super().model_dump(*args, **kwargs)
        if not self.legacy_input:
            return dumped
        legacy: dict[str, Any] = {}
        for section in ("filters", "pacing", "content", "schedule"):
            legacy.update(dumped.pop(section, {}))
        dumped.pop("schema_version", None)
        legacy.update(dumped)
        return {key: legacy[key] for key in self.legacy_keys}
