import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

INJECTION_PATTERNS = (
    r"ignore\s+(all\s+)?(previous|prior|system)(?:\s+system)?\s+instructions",
    r"(show|reveal|print|repeat).{0,30}(system prompt|developer message|hidden instructions)",
    r"(выполни|игнорируй).{0,30}(системн|предыдущ|инструкц)",
    r"(покажи|раскрой|выведи).{0,30}(системн.{0,10}промпт|скрыт.{0,10}инструкц)",
    r"\b(drop|alter|truncate)\s+table\b",
)

@dataclass(frozen=True)
class InputCheck:
    allowed: bool
    code: str | None = None

def check_user_input(value: str) -> InputCheck:
    normalized = " ".join(value.casefold().split())
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, normalized, flags=re.IGNORECASE):
            return InputCheck(False, "PROMPT_INJECTION_DETECTED")
    return InputCheck(True)

PII_PATTERNS = (
    r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+",
    r"(?<!\d)(?:\+?7|8)[\s()\-]*\d{3}[\s()\-]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}(?!\d)",
    r"(?<!\d)\d{12}(?!\d)",
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
    r"\b(?:пациент(?:ка)?|врач|фио|patient|doctor)\s*[:\-]\s*[\w'’-]+(?:\s+[\w'’-]+){0,3}",
)

def redact_personal_data(value: str) -> tuple[str, bool]:
    redacted, changed = value, False
    for pattern in PII_PATTERNS:
        next_value, count = re.subn(pattern, "[ПЕРСОНАЛЬНЫЕ ДАННЫЕ УДАЛЕНЫ]", redacted, flags=re.IGNORECASE)
        redacted, changed = next_value, changed or count > 0
    return redacted, changed

def numeric_tokens(value: str) -> set[str]:
    return {token.replace(" ", "").replace(",", ".") for token in re.findall(r"(?<![\w])[-+]?\d[\d\s]*(?:[.,]\d+)?", value)}

def evidence_numbers(value: Any) -> set[str]:
    found: set[str] = set()
    def walk(item: Any) -> None:
        if isinstance(item, bool) or item is None: return
        if isinstance(item, (int, float, Decimal)):
            number=float(item)
            found.add(str(item)); found.add(str(round(number, 1))); found.add(str(round(number, 2)))
            if 0 <= abs(number) <= 1: found.add(str(round(number*100, 1))); found.add(str(round(number*100, 2)))
        elif isinstance(item, str):
            stripped=item.strip()
            if re.fullmatch(r"[-+]?\d+(?:\.\d+)?",stripped):
                walk(Decimal(stripped))
            elif re.match(r"^\d{4}-\d{2}-\d{2}",stripped):
                found.update(part.lstrip("0") or "0" for part in stripped[:10].split("-"))
        elif isinstance(item, dict):
            for child in item.values(): walk(child)
        elif isinstance(item, list):
            for child in item: walk(child)
    walk(value)
    return {item.rstrip("0").rstrip(".") if "." in item else item for item in found}

def has_ungrounded_numbers(answer: str, tool_payloads: list[dict]) -> bool:
    stated = numeric_tokens(answer)
    if not stated: return False
    allowed = {"0", "1", "2", "7", "14", "30", "100"}
    for payload in tool_payloads: allowed |= evidence_numbers(payload)
    normalized_allowed = {item.replace(",", ".") for item in allowed}
    def normalize(token: str) -> str:
        token=token.lstrip("+")
        return token.rstrip("0").rstrip(".") if "." in token else token
    return any(normalize(token) not in normalized_allowed for token in stated)
