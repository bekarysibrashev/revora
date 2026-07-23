"""Deterministic source-row normalization into the Revora canonical shape."""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from typing import Callable

from app.modules.integrations.adapter import SourceRecord
from app.modules.integrations.schemas import (
    FieldMappingRule,
    MappingDefinition,
    MappingIssue,
    MappingResult,
)


def compute_record_hash(source_entity: str, payload: dict[str, object]) -> str:
    """Return a stable idempotency hash independent of dictionary key order."""

    serialized = json.dumps(
        {"source_entity": source_entity.strip().lower(), "payload": payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return sha256(serialized.encode("utf-8")).hexdigest()


class CanonicalMapper:
    """Apply an allow-listed mapping definition without executing user code."""

    def __init__(self, definition: MappingDefinition) -> None:
        self.definition = definition
        self.transforms: dict[str, Callable[[object], object]] = {
            "string": self._to_string,
            "decimal": self._to_decimal,
            "date": self._to_date,
            "datetime": self._to_datetime,
            "integer": self._to_integer,
            "boolean": self._to_boolean,
            # date_time_combine is handled specially in normalize() because it
            # needs a second column's value, not just the primary one.
        }

    def normalize(self, record: SourceRecord) -> MappingResult:
        issues: list[MappingIssue] = []
        output: dict[str, object] = {}
        if record.source_entity.strip().lower() != self.definition.source_entity:
            issues.append(
                MappingIssue(
                    code="SOURCE_ENTITY_MISMATCH",
                    message=(
                        f"Expected source entity '{self.definition.source_entity}', "
                        f"received '{record.source_entity}'"
                    ),
                )
            )
            return MappingResult(
                target_entity=self.definition.target_entity, data=output, issues=issues
            )

        normalized_headers = {
            str(header).strip().casefold(): value for header, value in record.payload.items()
        }
        for target_field, rule in self.definition.fields.items():
            found, raw_value = self._find_value(normalized_headers, rule)
            if not found or self._is_blank(raw_value):
                output[target_field] = rule.default
                if rule.required:
                    issues.append(
                        MappingIssue(
                            code="REQUIRED_FIELD_MISSING",
                            message=f"Required field '{target_field}' is missing",
                            field_name=target_field,
                            raw_value=raw_value,
                        )
                    )
                continue

            try:
                if rule.transform == "date_time_combine":
                    output[target_field] = self._combine_date_time(
                        normalized_headers, rule, raw_value
                    )
                else:
                    output[target_field] = self.transforms[rule.transform](raw_value)
            except (InvalidOperation, TypeError, ValueError) as exc:
                output[target_field] = None
                issues.append(
                    MappingIssue(
                        code="VALUE_TRANSFORM_FAILED",
                        message=f"Cannot convert '{target_field}': {exc}",
                        field_name=target_field,
                        raw_value=raw_value,
                    )
                )

        return MappingResult(
            target_entity=self.definition.target_entity, data=output, issues=issues
        )

    @staticmethod
    def _find_value(
        source: dict[str, object], rule: FieldMappingRule
    ) -> tuple[bool, object | None]:
        for alias in rule.source_fields:
            key = alias.strip().casefold()
            if key in source:
                return True, source[key]
        return False, None

    def _combine_date_time(
        self,
        source: dict[str, object],
        rule: FieldMappingRule,
        date_raw_value: object,
    ) -> datetime:
        """Take the calendar date from the primary column and the clock time
        from `time_source_fields` (e.g. 1С often exports "Дата" as a full
        timestamp and "Начало"/"Окончание" as separate "HH:MM" columns)."""

        date_only_value = date_raw_value
        if isinstance(date_raw_value, str) and " " in date_raw_value.strip():
            # The "date" column sometimes already carries a full timestamp
            # (e.g. 1С export "04.06.2026 15:32:21") - keep only the
            # calendar-date portion before the first space.
            date_only_value = date_raw_value.strip().split(" ", 1)[0]
        day = self._to_date(date_only_value)
        if not rule.time_source_fields:
            return datetime.combine(day, datetime.min.time())

        time_found = False
        time_raw_value: object | None = None
        for alias in rule.time_source_fields:
            key = alias.strip().casefold()
            if key in source and not self._is_blank(source[key]):
                time_found, time_raw_value = True, source[key]
                break
        if not time_found:
            return datetime.combine(day, datetime.min.time())

        text = str(time_raw_value).strip()
        for pattern in ("%H:%M:%S", "%H:%M"):
            try:
                clock = datetime.strptime(text, pattern).time()
                return datetime.combine(day, clock)
            except ValueError:
                continue
        raise ValueError(f"expected HH:MM or HH:MM:SS, got '{text}'")

    @staticmethod
    def _is_blank(value: object | None) -> bool:
        return value is None or (isinstance(value, str) and not value.strip())

    @staticmethod
    def _to_string(value: object) -> str:
        return str(value).strip()

    @staticmethod
    def _to_decimal(value: object) -> Decimal:
        if isinstance(value, Decimal):
            return value
        if isinstance(value, bool):
            raise ValueError("boolean is not a monetary value")
        if isinstance(value, (int, float)):
            return Decimal(str(value))

        text = str(value).strip().replace("\u00a0", "").replace(" ", "")
        for token in ("₸", "KZT", "тенге"):
            text = text.replace(token, "")
        if text.startswith("(") and text.endswith(")"):
            text = f"-{text[1:-1]}"
        if "," in text and "." not in text:
            integer, fraction = text.rsplit(",", 1)
            text = f"{integer}.{fraction}" if len(fraction) <= 2 else integer + fraction
        elif "," in text and "." in text:
            if text.rfind(",") > text.rfind("."):
                text = text.replace(".", "").replace(",", ".")
            else:
                text = text.replace(",", "")
        return Decimal(text)

    @staticmethod
    def _to_date(value: object) -> date:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        text = str(value).strip()
        for pattern in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(text, pattern).date()
            except ValueError:
                continue
        raise ValueError("expected YYYY-MM-DD, DD.MM.YYYY or DD/MM/YYYY")

    @classmethod
    def _to_datetime(cls, value: object) -> datetime:
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return datetime.combine(value, datetime.min.time())
        text = str(value).strip()
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return datetime.combine(cls._to_date(value), datetime.min.time())

    @staticmethod
    def _to_integer(value: object) -> int:
        if isinstance(value, bool):
            raise ValueError("boolean is not an integer")
        return int(str(value).strip())

    @staticmethod
    def _to_boolean(value: object) -> bool:
        if isinstance(value, bool):
            return value
        normalized = str(value).strip().casefold()
        if normalized in {"1", "true", "yes", "да", "активен"}:
            return True
        if normalized in {"0", "false", "no", "нет", "неактивен"}:
            return False
        raise ValueError("expected a recognized boolean value")
