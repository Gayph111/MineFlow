from math import isfinite
from decimal import Decimal, InvalidOperation

from domain.models import Category, RowRef, Severity, ValidationIssue, Value


def as_text(value: Value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def numeric(value: Value) -> float:
    if isinstance(value, bool):
        raise ValueError("логическое значение")
    try:
        result = float(as_text(value).replace(",", "."))
    except (ValueError, OverflowError) as exc:
        raise ValueError("требуется число") from exc
    if not isfinite(result) or abs(result) > 1e15:
        raise ValueError("число вне диапазона")
    return result



def horizon_key(value: Value, *, elevation=False) -> str:
    """Normalize only the logical level key; never change a survey coordinate.

    RL-derived levels use 8 decimal places to remove accumulated floating point
    noise. Explicit textual horizon identifiers retain their original spelling.
    """
    label=as_text(value)
    if not label or not elevation:
        return label
    try:
        number=Decimal(label.replace(",","."))
        if not number.is_finite() or abs(number)>Decimal("1e15"):
            return label
        normalized=number.quantize(Decimal("0.00000001"))
        return format(normalized,"f").rstrip("0").rstrip(".") if normalized else "0"
    except InvalidOperation:
        return label


def category(value: Value) -> Category | None:
    token = as_text(value).upper()
    if token in {"P", "П", "ПОРОДА", "ГПР", "ПГР"} or token.endswith("_P"):
        return "P"
    if token in {"R", "Р", "РУДА", "НР"} or token.endswith("_R"):
        return "R"
    return None


class IssueLog:
    def __init__(self):
        self.items: list[ValidationIssue] = []

    def add(self, severity: Severity, code: str, text: str, refs: tuple[RowRef, ...]) -> None:
        self.items.append(ValidationIssue(severity, code, text, refs))

