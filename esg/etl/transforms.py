"""
Named, auditable column transforms.

A mapping may declare a transform by name. Names are resolved here rather than
by evaluating expressions from the mapping table, so an approved mapping can
never become a code-execution path.
"""

import re

from esg.etl import validation


class UnknownTransform(KeyError):
    pass


def _strip(value):
    return None if value is None else str(value).strip()


def _upper(value):
    return None if value is None else str(value).strip().upper()


def _lower(value):
    return None if value is None else str(value).strip().lower()


def _title(value):
    return None if value is None else str(value).strip().title()


def _number(value):
    try:
        return validation.coerce_number(value)
    except (TypeError, ValueError):
        return value


def _thousands_to_units(value):
    number = _number(value)
    return number * 1000 if isinstance(number, (int, float)) else value


def _millions_to_units(value):
    number = _number(value)
    return number * 1_000_000 if isinstance(number, (int, float)) else value


def _percent_to_fraction(value):
    number = _number(value)
    return number / 100 if isinstance(number, (int, float)) else value


def _kt_to_t(value):
    """Kilotonnes to tonnes — the commonest unit mismatch in emissions data."""
    number = _number(value)
    return number * 1000 if isinstance(number, (int, float)) else value


def _mwh_to_gj(value):
    number = _number(value)
    return number * 3.6 if isinstance(number, (int, float)) else value


def _yes_no_to_bool(value):
    try:
        return validation.coerce_bool(value)
    except (TypeError, ValueError):
        return value


def _year_from_date(value):
    match = re.search(r"(19|20)\d{2}", str(value or ""))
    return int(match.group(0)) if match else value


def _fiscal_year_label(value):
    """'FY24', 'FY2023-24', '2023-24' -> the closing calendar year."""
    text = str(value or "").upper().replace("FY", "").strip()
    match = re.match(r"^(\d{4})\s*[-/]\s*(\d{2,4})$", text)
    if match:
        tail = match.group(2)
        return int(tail) if len(tail) == 4 else int(match.group(1)[:2] + tail)
    match = re.match(r"^(\d{2})\s*[-/]\s*(\d{2})$", text)
    if match:
        return 2000 + int(match.group(2))
    if re.fullmatch(r"\d{4}", text):
        return int(text)
    if re.fullmatch(r"\d{2}", text):
        return 2000 + int(text)
    return value


def _blank_to_none(value):
    text = "" if value is None else str(value).strip()
    return None if text == "" else value


REGISTRY = {
    "strip": _strip,
    "upper": _upper,
    "lower": _lower,
    "title_case": _title,
    "to_number": _number,
    "thousands_to_units": _thousands_to_units,
    "millions_to_units": _millions_to_units,
    "percent_to_fraction": _percent_to_fraction,
    "kt_to_t": _kt_to_t,
    "mwh_to_gj": _mwh_to_gj,
    "yes_no_to_bool": _yes_no_to_bool,
    "year_from_date": _year_from_date,
    "fiscal_year_label": _fiscal_year_label,
    "blank_to_none": _blank_to_none,
}


def apply(name, value):
    if name not in REGISTRY:
        raise UnknownTransform(
            f"Unknown transform {name!r}. Available: {', '.join(sorted(REGISTRY))}"
        )
    return REGISTRY[name](value)


def available():
    return sorted(REGISTRY)
