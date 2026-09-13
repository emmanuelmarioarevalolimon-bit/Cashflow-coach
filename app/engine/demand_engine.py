"""Estimación auditable de demanda no atendida para reposición de productos."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP, localcontext
from typing import Any, Iterable, Mapping


THREE_DECIMALS = Decimal("0.001")


def _number(value: Any, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise ValueError(f"{name} debe ser numérico.") from exc
    if not result.is_finite() or result < 0:
        raise ValueError(f"{name} debe ser un número no negativo.")
    return result


def _rounded(value: Decimal) -> str:
    return format(value.quantize(THREE_DECIMALS, rounding=ROUND_HALF_UP), "f")


def estimate_shortage_adjusted_demand(
    base_daily_demand: Any,
    reports: Iterable[Mapping[str, Any]],
    *,
    as_of: date,
    working_weekdays: Iterable[int],
    non_working_dates: Iterable[date] = (),
    lookback_days: int = 90,
    half_life_days: int = 28,
) -> dict[str, Any]:
    """Suma a la demanda base la demanda no atendida reciente por día laborable.

    Los faltantes pierden la mitad de su peso cada ``half_life_days``. El rango
    refleja la dispersión ponderada de las unidades faltantes diarias e incluye
    días laborables sin reporte como cero. No pretende inferir ventas perdidas
    cuando el usuario no las registró.
    """
    base = _number(base_daily_demand, "demanda diaria base")
    weekdays = frozenset(int(day) for day in working_weekdays)
    if not weekdays or any(day < 0 or day > 6 for day in weekdays):
        raise ValueError("Debe existir al menos un día laborable entre 0 y 6.")
    if not 7 <= lookback_days <= 365 or not 1 <= half_life_days <= 365:
        raise ValueError("La ventana o vida media de la estimación es inválida.")
    closures = frozenset(non_working_dates)
    start = as_of - timedelta(days=lookback_days - 1)
    daily_shortages: dict[date, Decimal] = defaultdict(lambda: Decimal("0"))
    report_count = 0
    reported_units = Decimal("0")
    for report in reports:
        try:
            occurred = report["occurred_on"]
            occurred = occurred if isinstance(occurred, date) else date.fromisoformat(str(occurred))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Cada reporte de faltante requiere una fecha válida.") from exc
        units = _number(report.get("missing_units"), "unidades faltantes")
        if start <= occurred <= as_of and units > 0:
            daily_shortages[occurred] += units
            report_count += 1
            reported_units += units

    weighted_days: list[tuple[date, Decimal]] = []
    for offset in range(lookback_days):
        day = start + timedelta(days=offset)
        if day.weekday() not in weekdays or day in closures:
            continue
        age = (as_of - day).days
        weight = Decimal(str(0.5 ** (age / half_life_days)))
        weighted_days.append((day, weight))
    denominator = sum((weight for _, weight in weighted_days), Decimal("0"))
    adjustment = (sum((daily_shortages[day] * weight for day, weight in weighted_days), Decimal("0")) /
                  denominator) if denominator else Decimal("0")
    estimate = base + adjustment
    variance = (sum((weight * (daily_shortages[day] - adjustment) ** 2
                    for day, weight in weighted_days), Decimal("0")) / denominator) if denominator else Decimal("0")
    with localcontext() as context:
        context.prec = 40
        volatility = variance.sqrt() if variance else Decimal("0")
    low = max(base, estimate - volatility)
    high = estimate + volatility
    return {
        "method": "Promedio ponderado de faltantes por día laborable; vida media de 28 días.",
        "asOf": as_of.isoformat(),
        "lookbackDays": lookback_days,
        "workingDaysObserved": len(weighted_days),
        "shortageReports": report_count,
        "reportedMissingUnits": _rounded(reported_units),
        "baseDailyDemand": _rounded(base),
        "shortageAdjustment": _rounded(adjustment),
        "estimatedDailyDemand": _rounded(estimate),
        "fluctuationLow": _rounded(low),
        "fluctuationHigh": _rounded(high),
        "recommendedDailyDemand": _rounded(high),
    }
