"""Нормализация казахстанских/российских номеров к формату +7XXXXXXXXXX."""

import re


def normalize_phone(raw: str) -> str:
    """'8 700 111 22 33', '+7(700)1112233', '7001112233' -> '+77001112233'.

    Иначе ValueError.
    """
    if not isinstance(raw, str):
        raise ValueError("Некорректный номер телефона")
    value = raw.strip()
    if re.search(r"[^\d\s()+\-.]", value) or value.count("+") > 1 or "+" in value[1:]:
        raise ValueError(f"Некорректный номер телефона: {raw!r}")
    digits = re.sub(r"\D", "", value)
    if len(digits) == 11 and digits[0] in "78":
        digits = digits[1:]
    elif len(digits) != 10 or value.startswith("+"):
        raise ValueError(f"Некорректный номер телефона: {raw!r}")
    return "+7" + digits
