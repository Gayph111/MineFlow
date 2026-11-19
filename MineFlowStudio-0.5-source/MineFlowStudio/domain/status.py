"""Russian labels for user-facing results; stable audit codes stay internal."""

AUDIT_TITLES = {
    "PASS": "Пройдено",
    "FAIL": "Ошибка",
    "UNVERIFIED": "Требует подтверждения",
}
PRELIMINARY = "Предварительно"


def status_title(code):
    return AUDIT_TITLES.get(code, code)

