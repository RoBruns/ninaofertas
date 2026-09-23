"""Contrato e validacao atomica dos CSVs de vendas."""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar
from uuid import UUID

VALID_STATUSES = {"pending", "confirmed", "cancelled", "paid"}


@dataclass(frozen=True)
class RowError:
    line: int
    message: str


class ImportValidationError(ValueError):
    def __init__(self, errors: list[RowError]) -> None:
        self.errors = errors
        super().__init__("CSV invalido")


@dataclass(frozen=True)
class SaleImportRow:
    line: int
    external_id: str
    product_name: str | None
    quantity: int
    gross_amount: Decimal
    commission: Decimal
    commission_rate: Decimal | None
    status: str
    ordered_at: datetime
    confirmed_at: datetime | None
    sub_id: str | None
    bot_id: UUID | None
    group_id: UUID | None
    buyer_hash: str | None
    raw: dict[str, Any]


def _normalized(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.strip()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")


class BaseCSVImporter:
    """Mapeia um CSV inteiro ou devolve todos os erros sem produzir linhas."""

    COLUMN_ALIASES: ClassVar[dict[str, tuple[str, ...]]]
    STATUS_MAP: ClassVar[dict[str, str]]
    REQUIRED = ("external_id", "gross_amount", "commission", "status", "ordered_at")

    def parse(self, content: bytes) -> list[SaleImportRow]:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise ImportValidationError([RowError(1, "arquivo deve estar em UTF-8")]) from None
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        if not reader.fieldnames:
            raise ImportValidationError([RowError(1, "cabecalho ausente")])

        headers = {_normalized(header): header for header in reader.fieldnames if header}
        columns = self._resolve_columns(headers)
        missing = [field for field in self.REQUIRED if field not in columns]
        if missing:
            names = ", ".join(missing)
            raise ImportValidationError([RowError(1, f"colunas obrigatorias ausentes: {names}")])

        rows: list[SaleImportRow] = []
        errors: list[RowError] = []
        seen: dict[str, int] = {}
        try:
            for line, raw in enumerate(reader, start=2):
                if None in raw:
                    errors.append(RowError(line, "quantidade de colunas maior que o cabecalho"))
                    continue
                if not any(str(value or "").strip() for value in raw.values()):
                    continue
                try:
                    row = self._parse_row(line, raw, columns)
                    previous = seen.get(row.external_id)
                    if previous is not None:
                        raise ValueError(
                            f"external_id duplicado no CSV (primeira ocorrencia: linha {previous})"
                        )
                    seen[row.external_id] = line
                    rows.append(row)
                except (ValueError, InvalidOperation) as exc:
                    errors.append(RowError(line, str(exc)))
        except csv.Error as exc:
            errors.append(RowError(reader.line_num or 1, f"CSV malformado: {exc}"))
        if errors:
            raise ImportValidationError(errors)
        if not rows:
            raise ImportValidationError([RowError(1, "CSV nao contem vendas")])
        return rows

    def _resolve_columns(self, headers: dict[str, str]) -> dict[str, str]:
        resolved: dict[str, str] = {}
        for field, aliases in self.COLUMN_ALIASES.items():
            for alias in aliases:
                original = headers.get(_normalized(alias))
                if original is not None:
                    resolved[field] = original
                    break
        return resolved

    @staticmethod
    def _value(raw: dict[str, str | None], columns: dict[str, str], field: str) -> str:
        column = columns.get(field)
        return str(raw.get(column) or "").strip() if column else ""

    @staticmethod
    def _decimal(value: str, field: str, *, required: bool = True) -> Decimal | None:
        if not value:
            if required:
                raise ValueError(f"{field} vazio")
            return None
        cleaned = value.strip().replace("R$", "").replace(" ", "")
        if "," in cleaned:
            cleaned = cleaned.replace(".", "").replace(",", ".")
        try:
            result = Decimal(cleaned)
        except InvalidOperation:
            raise ValueError(f"{field} deve ser decimal") from None
        if not result.is_finite():
            raise ValueError(f"{field} invalido")
        scale = 4 if field == "commission_rate" else 2
        if result.as_tuple().exponent < -scale:
            raise ValueError(f"{field} deve ter no maximo {scale} casas decimais")
        return result

    @staticmethod
    def _datetime(value: str, field: str, *, required: bool = True) -> datetime | None:
        if not value:
            if required:
                raise ValueError(f"{field} vazio")
            return None
        parsed: datetime | None = None
        normalized = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
                try:
                    parsed = datetime.strptime(normalized, fmt)
                    break
                except ValueError:
                    continue
        if parsed is None:
            raise ValueError(f"{field} deve ser data ISO-8601 ou DD/MM/AAAA")
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _uuid(value: str, field: str) -> UUID | None:
        if not value:
            return None
        try:
            return UUID(value)
        except ValueError:
            raise ValueError(f"{field} deve ser UUID") from None

    def _parse_row(
        self, line: int, raw: dict[str, str | None], columns: dict[str, str]
    ) -> SaleImportRow:
        external_id = self._value(raw, columns, "external_id")
        if not external_id:
            raise ValueError("external_id vazio")
        status_raw = _normalized(self._value(raw, columns, "status"))
        status = self.STATUS_MAP.get(status_raw, status_raw)
        if status not in VALID_STATUSES:
            raise ValueError("status deve ser pending, confirmed, cancelled ou paid")
        quantity_raw = self._value(raw, columns, "quantity") or "1"
        try:
            quantity = int(quantity_raw)
        except ValueError:
            raise ValueError("quantity deve ser inteiro") from None
        if quantity < 1:
            raise ValueError("quantity deve ser >= 1")
        gross_amount = self._decimal(self._value(raw, columns, "gross_amount"), "gross_amount")
        commission = self._decimal(self._value(raw, columns, "commission"), "commission")
        assert gross_amount is not None and commission is not None
        if gross_amount < 0 or commission < 0:
            raise ValueError("gross_amount e commission devem ser >= 0")
        ordered_at = self._datetime(self._value(raw, columns, "ordered_at"), "ordered_at")
        assert ordered_at is not None
        return SaleImportRow(
            line=line,
            external_id=external_id,
            product_name=self._value(raw, columns, "product_name") or None,
            quantity=quantity,
            gross_amount=gross_amount,
            commission=commission,
            commission_rate=self._decimal(
                self._value(raw, columns, "commission_rate"), "commission_rate", required=False
            ),
            status=status,
            ordered_at=ordered_at,
            confirmed_at=self._datetime(
                self._value(raw, columns, "confirmed_at"), "confirmed_at", required=False
            ),
            sub_id=self._value(raw, columns, "sub_id") or None,
            bot_id=self._uuid(self._value(raw, columns, "bot_id"), "bot_id"),
            group_id=self._uuid(self._value(raw, columns, "group_id"), "group_id"),
            buyer_hash=self._value(raw, columns, "buyer_hash") or None,
            # Colunas extras podem conter PII do comprador. Os campos seguros
            # ja foram normalizados acima; o CSV bruto nao e persistido.
            raw={},
        )
