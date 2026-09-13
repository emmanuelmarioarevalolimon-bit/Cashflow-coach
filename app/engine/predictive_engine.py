"""Motor de caja: API determinista original + extensión predictiva 5.0.

Parte I: funciones originales, conservadas (Decimal, escenarios y optimizador).
Parte II: recurrencias, STL/SARIMA/Holt-Winters, bootstrap, Poisson,
cópula gaussiana, riesgo de trayectoria y optimización probabilística.

La extensión necesita NumPy, SciPy y statsmodels (ver requirements.txt).
Ejecutar: python algoritmo_budget_avanzado.py --demo --output resultado.json
No conecta a bases de datos, no usa Gemini y no ejecuta pagos.
Ver README.md para supuestos, correspondencia con el documento y límites.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from itertools import combinations
import json
from typing import Iterable, Literal, Sequence


MoneyDirection = Literal["inflow", "outflow"]
InterventionType = Literal[
    "accelerate_receivable",
    "defer_payable",
    "draw_credit",
    "delay_expense",
    "advance_expense",
]

CENT = Decimal("0.01")


def money(value: Decimal | int | float | str) -> Decimal:
    """Convierte y redondea un valor monetario a centavos."""
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class CashFlowEvent:
    id: str
    counterparty: str
    amount: Decimal
    direction: MoneyDirection
    expected_date: date
    category: str
    confidence: Decimal = Decimal("1")
    recurring: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", money(self.amount))
        object.__setattr__(self, "confidence", Decimal(str(self.confidence)))
        if self.amount < 0:
            raise ValueError("amount debe ser no negativo")
        if self.direction not in ("inflow", "outflow"):
            raise ValueError("direction debe ser 'inflow' u 'outflow'")
        if not Decimal("0") <= self.confidence <= Decimal("1"):
            raise ValueError("confidence debe estar entre 0 y 1")


@dataclass(frozen=True)
class DailyProjection:
    day: date
    expected_balance: Decimal
    conservative_balance: Decimal
    liquidity_threshold: Decimal


@dataclass(frozen=True)
class ForecastResult:
    opening_balance: Decimal
    minimum_expected_balance: Decimal
    minimum_conservative_balance: Decimal
    risk_date: date | None
    projected_shortfall: Decimal
    liquidity_threshold: Decimal
    projection: tuple[DailyProjection, ...]


@dataclass(frozen=True)
class Intervention:
    id: str
    type: InterventionType
    description: str
    financial_cost: Decimal
    operational_impact: int
    add_events: tuple[CashFlowEvent, ...] = ()
    remove_event_ids: tuple[str, ...] = ()
    replace_events: tuple[CashFlowEvent, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "financial_cost", money(self.financial_cost))
        if self.financial_cost < 0:
            raise ValueError("financial_cost debe ser no negativo")
        if self.operational_impact < 0:
            raise ValueError("operational_impact debe ser no negativo")


@dataclass(frozen=True)
class OptimizationResult:
    feasible: bool
    selected: tuple[Intervention, ...]
    repaired_forecast: ForecastResult | None
    evaluated_candidates: int
    total_financial_cost: Decimal
    total_operational_impact: int


def forecast_cash_flow(
    opening_balance: Decimal | int | float | str,
    events: Sequence[CashFlowEvent],
    start_date: date,
    days: int,
    liquidity_threshold: Decimal | int | float | str,
) -> ForecastResult:
    """Proyecta saldos esperados y conservadores durante ``days`` dias.

    Regla conservadora del MVP:
    - se cuentan todas las salidas, porque son obligaciones;
    - cada entrada se pondera por su confianza de cobro.

    Esta regla es deliberadamente sencilla y auditable; no es un intervalo de
    confianza estadistico ni una garantia financiera.
    """
    if days <= 0:
        raise ValueError("days debe ser positivo")

    opening = money(opening_balance)
    threshold = money(liquidity_threshold)
    end_date = start_date + timedelta(days=days - 1)

    expected_by_day: dict[date, Decimal] = {}
    conservative_by_day: dict[date, Decimal] = {}

    for event in events:
        if not start_date <= event.expected_date <= end_date:
            continue

        sign = Decimal("1") if event.direction == "inflow" else Decimal("-1")
        expected_delta = sign * event.amount
        conservative_delta = (
            event.amount * event.confidence
            if event.direction == "inflow"
            else -event.amount
        )

        expected_by_day[event.expected_date] = money(
            expected_by_day.get(event.expected_date, Decimal("0"))
            + expected_delta
        )
        conservative_by_day[event.expected_date] = money(
            conservative_by_day.get(event.expected_date, Decimal("0"))
            + conservative_delta
        )

    expected_balance = opening
    conservative_balance = opening
    projection: list[DailyProjection] = []

    for offset in range(days):
        current_day = start_date + timedelta(days=offset)
        expected_balance = money(
            expected_balance + expected_by_day.get(current_day, Decimal("0"))
        )
        conservative_balance = money(
            conservative_balance
            + conservative_by_day.get(current_day, Decimal("0"))
        )
        projection.append(
            DailyProjection(
                day=current_day,
                expected_balance=expected_balance,
                conservative_balance=conservative_balance,
                liquidity_threshold=threshold,
            )
        )

    minimum_expected = min(point.expected_balance for point in projection)
    minimum_conservative = min(
        point.conservative_balance for point in projection
    )
    risk_date = next(
        (
            point.day
            for point in projection
            if point.conservative_balance < threshold
        ),
        None,
    )
    shortfall = money(max(Decimal("0"), threshold - minimum_conservative))

    return ForecastResult(
        opening_balance=opening,
        minimum_expected_balance=minimum_expected,
        minimum_conservative_balance=minimum_conservative,
        risk_date=risk_date,
        projected_shortfall=shortfall,
        liquidity_threshold=threshold,
        projection=tuple(projection),
    )


def delay_receivable(
    events: Sequence[CashFlowEvent], event_id: str, delay_days: int
) -> tuple[CashFlowEvent, ...]:
    """Retrasa una entrada sin modificar la lista original."""
    if delay_days < 0:
        raise ValueError("delay_days no puede ser negativo")

    found = False
    result: list[CashFlowEvent] = []
    for event in events:
        if event.id == event_id:
            if event.direction != "inflow":
                raise ValueError("El evento seleccionado no es una entrada")
            found = True
            result.append(
                replace(
                    event,
                    expected_date=event.expected_date
                    + timedelta(days=delay_days),
                )
            )
        else:
            result.append(event)

    if not found:
        raise KeyError(f"No existe el evento {event_id!r}")
    return tuple(result)


def apply_interventions(
    events: Sequence[CashFlowEvent], interventions: Iterable[Intervention]
) -> tuple[CashFlowEvent, ...]:
    """Aplica intervenciones de forma determinista e inmutable."""
    interventions = tuple(interventions)
    removed = {
        event_id
        for intervention in interventions
        for event_id in intervention.remove_event_ids
    }
    replacements = {
        event.id: event
        for intervention in interventions
        for event in intervention.replace_events
    }

    result = [
        replacements.get(event.id, event)
        for event in events
        if event.id not in removed
    ]

    existing_ids = {event.id for event in result}
    for intervention in interventions:
        for event in intervention.add_events:
            if event.id in existing_ids:
                raise ValueError(f"ID de evento duplicado: {event.id}")
            result.append(event)
            existing_ids.add(event.id)

    return tuple(sorted(result, key=lambda event: (event.expected_date, event.id)))


def optimize_interventions(
    opening_balance: Decimal | int | float | str,
    stressed_events: Sequence[CashFlowEvent],
    candidates: Sequence[Intervention],
    start_date: date,
    days: int,
    liquidity_threshold: Decimal | int | float | str,
    max_actions: int = 2,
) -> OptimizationResult:
    """Elige la solucion factible de menor costo y menor impacto.

    Evalua intervenciones individuales y combinaciones de hasta ``max_actions``.
    El orden de desempate es:
      1. costo financiero total;
      2. impacto operativo total;
      3. identificadores ordenados, para reproducibilidad.
    """
    if max_actions < 1:
        raise ValueError("max_actions debe ser al menos 1")

    stressed_forecast = forecast_cash_flow(
        opening_balance,
        stressed_events,
        start_date,
        days,
        liquidity_threshold,
    )
    if stressed_forecast.projected_shortfall == 0:
        return OptimizationResult(
            feasible=True,
            selected=(),
            repaired_forecast=stressed_forecast,
            evaluated_candidates=0,
            total_financial_cost=money(0),
            total_operational_impact=0,
        )

    evaluated = 0
    feasible_results: list[
        tuple[
            tuple[Decimal, int, tuple[str, ...]],
            tuple[Intervention, ...],
            ForecastResult,
        ]
    ] = []

    ordered_candidates = tuple(sorted(candidates, key=lambda item: item.id))
    maximum_size = min(max_actions, len(ordered_candidates))

    for size in range(1, maximum_size + 1):
        for selection in combinations(ordered_candidates, size):
            evaluated += 1
            adjusted_events = apply_interventions(stressed_events, selection)
            repaired = forecast_cash_flow(
                opening_balance,
                adjusted_events,
                start_date,
                days,
                liquidity_threshold,
            )
            if repaired.projected_shortfall > 0:
                continue

            total_cost = money(
                sum(
                    (item.financial_cost for item in selection),
                    Decimal("0"),
                )
            )
            total_impact = sum(item.operational_impact for item in selection)
            identifiers = tuple(item.id for item in selection)
            feasible_results.append(
                (
                    (total_cost, total_impact, identifiers),
                    selection,
                    repaired,
                )
            )

    if not feasible_results:
        return OptimizationResult(
            feasible=False,
            selected=(),
            repaired_forecast=None,
            evaluated_candidates=evaluated,
            total_financial_cost=money(0),
            total_operational_impact=0,
        )

    score, selected, repaired = min(feasible_results, key=lambda item: item[0])
    return OptimizationResult(
        feasible=True,
        selected=selected,
        repaired_forecast=repaired,
        evaluated_candidates=evaluated,
        total_financial_cost=score[0],
        total_operational_impact=score[1],
    )


def result_to_dict(result: ForecastResult) -> dict[str, object]:
    return {
        "openingBalance": str(result.opening_balance),
        "minimumExpectedBalance": str(result.minimum_expected_balance),
        "minimumConservativeBalance": str(
            result.minimum_conservative_balance
        ),
        "riskDate": result.risk_date.isoformat() if result.risk_date else None,
        "projectedShortfall": str(result.projected_shortfall),
        "liquidityThreshold": str(result.liquidity_threshold),
        "projection": [
            {
                "date": point.day.isoformat(),
                "expectedBalance": str(point.expected_balance),
                "conservativeBalance": str(point.conservative_balance),
                "liquidityThreshold": str(point.liquidity_threshold),
            }
            for point in result.projection
        ],
    }


def demo() -> None:
    """Ejecuta el escenario central del hackathon."""
    start = date(2026, 9, 12)
    opening_balance = money("50000")
    threshold = money("20000")

    baseline_events = (
        CashFlowEvent(
            "receivable-main",
            "Cliente principal",
            money("18000"),
            "inflow",
            start + timedelta(days=7),
            "accounts_receivable",
            Decimal("0.90"),
        ),
        CashFlowEvent(
            "receivable-secondary",
            "Cliente secundario",
            money("9000"),
            "inflow",
            start + timedelta(days=16),
            "accounts_receivable",
            Decimal("0.85"),
        ),
        CashFlowEvent(
            "supplier-critical",
            "Proveedor de acero",
            money("12500"),
            "outflow",
            start + timedelta(days=5),
            "supplier",
        ),
        CashFlowEvent(
            "payroll",
            "Nomina",
            money("26000"),
            "outflow",
            start + timedelta(days=12),
            "payroll",
            recurring=True,
        ),
        CashFlowEvent(
            "supplier-flexible",
            "Proveedor de empaques",
            money("7000"),
            "outflow",
            start + timedelta(days=11),
            "supplier",
        ),
        CashFlowEvent(
            "rent",
            "Renta de bodega",
            money("4500"),
            "outflow",
            start + timedelta(days=21),
            "rent",
            recurring=True,
        ),
    )

    baseline = forecast_cash_flow(
        opening_balance, baseline_events, start, 30, threshold
    )
    stressed_events = delay_receivable(
        baseline_events, "receivable-main", delay_days=7
    )
    stressed = forecast_cash_flow(
        opening_balance, stressed_events, start, 30, threshold
    )

    accelerated_receivable = replace(
        next(
            event
            for event in stressed_events
            if event.id == "receivable-secondary"
        ),
        expected_date=start + timedelta(days=10),
        amount=money("8820"),
    )
    deferred_supplier = replace(
        next(
            event
            for event in stressed_events
            if event.id == "supplier-flexible"
        ),
        expected_date=start + timedelta(days=17),
    )

    candidates = (
        Intervention(
            id="accelerate-secondary",
            type="accelerate_receivable",
            description="Acelerar el cobro secundario con descuento de $180",
            financial_cost=money("180"),
            operational_impact=1,
            replace_events=(accelerated_receivable,),
        ),
        Intervention(
            id="defer-flexible-supplier",
            type="defer_payable",
            description="Diferir seis dias el pago al proveedor flexible",
            financial_cost=money("70"),
            operational_impact=2,
            replace_events=(deferred_supplier,),
        ),
        Intervention(
            id="credit-line-9000",
            type="draw_credit",
            description="Usar $9,000 de la linea de credito",
            financial_cost=money("120"),
            operational_impact=3,
            add_events=(
                CashFlowEvent(
                    "credit-draw",
                    "Linea de credito",
                    money("9000"),
                    "inflow",
                    start + timedelta(days=10),
                    "credit",
                ),
            ),
        ),
    )

    optimized = optimize_interventions(
        opening_balance,
        stressed_events,
        candidates,
        start,
        30,
        threshold,
    )

    output = {
        "baseline": result_to_dict(baseline),
        "stressed": result_to_dict(stressed),
        "optimization": {
            "feasible": optimized.feasible,
            "selectedInterventions": [
                {
                    "id": item.id,
                    "description": item.description,
                    "financialCost": str(item.financial_cost),
                    "operationalImpact": item.operational_impact,
                }
                for item in optimized.selected
            ],
            "totalFinancialCost": str(optimized.total_financial_cost),
            "totalOperationalImpact": optimized.total_operational_impact,
            "evaluatedCandidates": optimized.evaluated_candidates,
            "repaired": (
                result_to_dict(optimized.repaired_forecast)
                if optimized.repaired_forecast
                else None
            ),
        },
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))



# ============================================================================
# PARTE II. EXTENSIÓN ESTADÍSTICA. No cambia las funciones públicas anteriores.
# ============================================================================
from collections import Counter
from dataclasses import asdict, field
from functools import lru_cache
from hashlib import sha256
from math import ceil, comb, isfinite, sqrt
from pathlib import Path
from typing import Any, Mapping
import argparse
import warnings
import unicodedata

import numpy as np
from scipy.signal import lfilter
from scipy.stats import norm, rankdata
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from statsmodels.tsa.seasonal import STL
from statsmodels.tsa.statespace.sarimax import SARIMAX
from statsmodels.tsa.stattools import adfuller, pacf

VERSION = "5.0.0-motor-predictivo"
MODEL_NAMES = ("seasonal_mean", "stl", "holt_winters", "sarima")
MAX_MONEY = Decimal("1000000000")


class InputError(ValueError):
    """Datos o supuestos insuficientes; no se sustituyen silenciosamente."""


def _require_int(value: Any, name: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or not low <= value <= high:
        raise InputError(f"{name} debe ser entero entre {low} y {high}.")
    return int(value)


def _decimal(value: Any, name: str, *, nonnegative: bool = True) -> Decimal:
    try:
        d = Decimal(str(value))
        if not d.is_finite() or abs(d) > MAX_MONEY or (nonnegative and d < 0):
            raise ValueError()
        return d.quantize(CENT, rounding=ROUND_HALF_UP)
    except Exception as exc:
        raise InputError(f"{name}: monto finito válido, máximo {MAX_MONEY}.") from exc


def _day(value: Any, name: str = "fecha") -> date:
    # datetime no se acepta: cada fila representa una fecha local, no un instante.
    if type(value) is date:
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise InputError(f"{name} debe ser una fecha ISO YYYY-MM-DD.")


def _prob(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise InputError(f"{name} debe ser una probabilidad, no un booleano.")
    try:
        f = float(value)
    except (TypeError, ValueError) as exc:
        raise InputError(f"{name} no es numérica.") from exc
    if not isfinite(f) or not 0 <= f <= 1:
        raise InputError(f"{name} debe estar entre 0 y 1.")
    return f


def _name(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode().lower()
    return " ".join("".join(c if c.isalnum() else " " for c in text).split())


def series_key(counterparty: str, direction: str, category: str) -> str:
    """Identidad explícita para conciliar historia y agenda futura."""
    return "|".join((direction, _name(category), _name(counterparty)))


def _rng(seed: int, label: str) -> np.random.Generator:
    # hash estable entre procesos; hash() de Python no es reproducible entre sesiones.
    digest = sha256(f"{seed}:{label}".encode()).digest()
    return np.random.default_rng(int.from_bytes(digest[:16], "big"))


def _cents(values: Any) -> np.ndarray:
    x = np.asarray(values, dtype=float)
    if not np.all(np.isfinite(x)) or np.any(np.abs(x) > 1e12):
        raise InputError("Un modelo produjo valores no finitos o excesivos; revisa escala/tendencia.")
    return (np.sign(x) * np.floor(np.abs(x) * 100.0 + 0.5)).astype(np.int64)


def _cash(value: Any) -> str:
    return str(Decimal(str(float(value))).quantize(CENT, rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class HistoricalTransaction:
    """Solo movimientos REALIZADOS; no facturación, utilidad o facturas pendientes."""
    id: str
    counterparty: str
    amount: Decimal
    direction: MoneyDirection
    occurred_on: date
    category: str = "general"
    irregular: bool = False
    currency: str = "MXN"

    def __post_init__(self) -> None:
        if not self.id or not self.counterparty or not self.category:
            raise InputError("Cada movimiento requiere id, contraparte y categoría.")
        if self.direction not in ("inflow", "outflow"):
            raise InputError("direction debe ser inflow u outflow.")
        if type(self.irregular) is not bool:
            raise InputError("irregular debe ser true o false, asignado tras revisar el documento.")
        object.__setattr__(self, "amount", _decimal(self.amount, "amount"))
        object.__setattr__(self, "occurred_on", _day(self.occurred_on))

    @property
    def key(self) -> str:
        return series_key(self.counterparty, self.direction, self.category)

    @property
    def signed_amount(self) -> float:
        return float(self.amount) * (1 if self.direction == "inflow" else -1)


@dataclass(frozen=True)
class PlannedEvent:
    id: str
    counterparty: str
    amount: Decimal
    direction: MoneyDirection
    expected_date: date
    category: str = "general"
    currency: str = "MXN"
    # No se reutiliza automáticamente confidence del motor anterior como probabilidad.
    collection_probability: float = 1.0
    delay_samples: tuple[int, ...] = (0,)
    client_id: str | None = None
    # Si sustituye un patrón: clave histórica y fecha ORIGINAL de la ocurrencia.
    # Si no es recurrente: la clave excluye TODA esa serie del modelo de fondo;
    # el usuario debe aportar su agenda futura completa para el horizonte.
    history_series_key: str | None = None
    replaces_on: date | None = None
    amount_samples: tuple[float, ...] = ()
    source: str = "agenda"
    risk_anchor: date | None = None
    additional_to_history: bool = False

    def __post_init__(self) -> None:
        if not self.id or not self.counterparty:
            raise InputError("Evento futuro sin id o contraparte.")
        if self.direction not in ("inflow", "outflow"):
            raise InputError("Dirección inválida.")
        object.__setattr__(self, "amount", _decimal(self.amount, "amount"))
        object.__setattr__(self, "expected_date", _day(self.expected_date))
        object.__setattr__(self, "collection_probability", _prob(self.collection_probability, "collection_probability"))
        for attr in ("replaces_on", "risk_anchor"):
            if getattr(self, attr) is not None:
                object.__setattr__(self, attr, _day(getattr(self, attr), attr))
        if type(self.additional_to_history) is not bool:
            raise InputError("additional_to_history debe ser booleano.")
        if self.additional_to_history and self.history_series_key is not None:
            raise InputError("Un evento no puede ser adicional y reemplazo a la vez.")
        delays = tuple(_require_int(d, "delay_samples", 0, 3650) for d in self.delay_samples)
        if not delays:
            raise InputError("delay_samples no puede estar vacío. Usa [0] para una fecha cierta.")
        object.__setattr__(self, "delay_samples", delays)
        amounts = tuple(float(_decimal(m, "amount_samples")) for m in self.amount_samples)
        object.__setattr__(self, "amount_samples", amounts)
        if self.direction == "outflow" and (self.collection_probability != 1 or any(delays)):
            raise InputError("Las obligaciones salen completas en la fecha. Aplázalas con una acción explícita.")

    @property
    def key(self) -> str:
        return series_key(self.counterparty, self.direction, self.category)


@dataclass(frozen=True)
class ForecastConfig:
    start_date: date
    history_start: date
    history_end: date
    # Sin confirmación de cobertura, ausencia de filas NO equivale a cero movimientos.
    history_complete: bool = False
    days: int = 30
    simulations: int = 10_000
    seed: int = 20260912
    currency: str = "MXN"
    model: str = "auto"
    seasonal_period: int = 7
    candidate_periods: tuple[int, ...] = (7, 14, 15, 30, 60, 90)
    recurrence_weights: tuple[float, float, float] = (0.4, 0.3, 0.3)
    recurrence_epsilon: float = 0.18
    max_name_distance: float = 0.35
    acf_threshold: float = 0.5
    acf_adjusted: bool = False
    min_recurrence_count: int = 3
    max_stable_cv: float = 0.2
    bootstrap_block: int = 7
    auto_methods: tuple[str, ...] = MODEL_NAMES
    confidence: float = 0.95
    alpha: float = 0.05
    constraint: str = "any_day"  # "terminal" reproduce la restricción B_H del texto.
    chance_method: str = "wilson_upper"  # "empirical" reproduce p_hat <= alpha.
    probability_confidence: float = 0.95
    max_actions: int = 2
    max_candidates: int = 128
    coverage_days: int = 30
    daily_cogs: Decimal | None = None
    delay_cycle_days: int = 30
    scenario_sample_paths: int = 5

    def __post_init__(self) -> None:
        for attr in ("start_date", "history_start", "history_end"):
            object.__setattr__(self, attr, _day(getattr(self, attr), attr))
        if self.history_complete is not True:
            raise InputError("Confirma history_complete=true solo si el historial cubre TODOS los días del rango.")
        if self.history_end != self.start_date - timedelta(days=1):
            raise InputError("history_end debe ser el día anterior a start_date. No se rellenan huecos desconocidos.")
        if not 1 <= (self.history_end - self.history_start).days + 1 <= 3650:
            raise InputError("La cobertura histórica debe tener entre 1 y 3650 días.")
        for attr, lo, hi in (("days",1,365),("simulations",100,50000),("seed",0,2**63-1),
                             ("seasonal_period",2,365),("bootstrap_block",1,365),
                             ("min_recurrence_count",3,100),("max_actions",0,4),
                             ("max_candidates",1,512),("coverage_days",0,3650),
                             ("delay_cycle_days",1,365),("scenario_sample_paths",0,20)):
            _require_int(getattr(self, attr), attr, lo, hi)
        if self.simulations * self.days > 10_000_000:
            raise InputError("simulations * days excede 10 millones; reduce el tamaño de esta ejecución.")
        if self.model not in (*MODEL_NAMES, "auto") or not self.auto_methods or any(m not in MODEL_NAMES for m in self.auto_methods):
            raise InputError("Modelo inválido.")
        object.__setattr__(self, "candidate_periods", tuple(sorted(set(_require_int(p,"periodo",2,365) for p in self.candidate_periods))))
        if not self.candidate_periods:
            raise InputError("candidate_periods no puede estar vacío.")
        for attr in ("recurrence_epsilon","max_name_distance","acf_threshold","max_stable_cv","confidence","alpha","probability_confidence"):
            object.__setattr__(self, attr, _prob(getattr(self, attr), attr))
        if not 0.5 < self.confidence < 1 or not 0.5 < self.probability_confidence < 1:
            raise InputError("Los niveles de confianza deben estar entre 0.5 y 1, excluidos.")
        if self.constraint not in ("terminal", "any_day") or self.chance_method not in ("empirical","wilson_upper"):
            raise InputError("constraint o chance_method inválido.")
        w = tuple(float(v) for v in self.recurrence_weights)
        object.__setattr__(self, "recurrence_weights", w)
        if len(w) != 3 or any(not isfinite(float(v)) or v < 0 for v in w) or abs(sum(w)-1) > 1e-9:
            raise InputError("recurrence_weights requiere tres pesos no negativos que sumen 1.")
        if self.daily_cogs is not None:
            object.__setattr__(self,"daily_cogs",_decimal(self.daily_cogs,"daily_cogs"))


@lru_cache(maxsize=10_000)
def levenshtein_distance(left: str, right: str) -> int:
    """Distancia exacta, sin dependencias de coincidencia difusa."""
    if len(left) < len(right):
        left, right = right, left
    row = list(range(len(right)+1))
    for i, a in enumerate(left, 1):
        nxt = [i]
        for j, b in enumerate(right, 1):
            nxt.append(min(nxt[-1]+1, row[j]+1, row[j-1]+(a != b)))
        row = nxt
    return row[-1]


def composite_distance(a: HistoricalTransaction, b: HistoricalTransaction,
                       periods: Sequence[int] = (7,14,15,30,60,90),
                       weights: Sequence[float] = (0.4,0.3,0.3)) -> dict[str,float]:
    """d_c, d_m y fase circular d_t de la sección 1.2 del documento."""
    na, nb = _name(a.counterparty), _name(b.counterparty)
    dc = levenshtein_distance(na,nb)/max(1,len(na),len(nb))
    ma,mb = float(a.amount),float(b.amount)
    dm = abs(ma-mb)/max(ma,mb) if max(ma,mb)>0 else 0.0
    if not periods or any(p < 2 for p in periods):
        raise InputError("periods debe contener enteros >= 2.")
    delta = (a.occurred_on-b.occurred_on).days
    dt = min(min((delta%p)/p,1-(delta%p)/p) for p in periods)
    return {"counterparty":dc,"amount":dm,"time":dt,"total":float(weights[0]*dc+weights[1]*dm+weights[2]*dt)}


def autocorrelation(values: Sequence[float], max_lag: int, *, adjusted: bool = False) -> np.ndarray:
    """ACF. adjusted=True reproduce los divisores n-lag del documento.

    Esa estimación finita ajustada puede superar [-1,1]. Por defecto se usa n
    en todos los retardos (como acf(adjusted=False)); no se recortan los valores.
    Una serie constante devuelve [1,0,...]; no demuestra periodicidad.
    """
    x = np.asarray(values,dtype=float)
    if x.ndim != 1 or len(x)<1 or not np.all(np.isfinite(x)):
        raise InputError("ACF requiere una serie finita no vacía.")
    _require_int(max_lag,"max_lag",0,len(x)-1)
    z = x-x.mean(); denom = float(z@z)
    result = np.zeros(max_lag+1); result[0] = 1
    if denom < 1e-15:
        return result
    for lag in range(1,max_lag+1):
        result[lag] = (z[:-lag]@z[lag:])/denom
        if adjusted:
            result[lag] *= len(x)/(len(x)-lag)
    return result


@dataclass(frozen=True)
class RecurringPattern:
    id: str
    counterparty: str
    direction: str
    category: str
    period: int
    last_date: date
    mean_amount: float
    std_amount: float
    cv: float
    acf_value: float
    stable: bool
    history_ids: tuple[str,...]
    series_keys: tuple[str,...]
    amounts: tuple[float,...]


def detect_recurrences(history: Sequence[HistoricalTransaction], config: ForecastConfig) -> tuple[list[RecurringPattern],list[dict[str,Any]]]:
    """Grafo de distancia compuesta -> componentes conexas -> ACF -> periodo.

    Guardias de ingeniería: misma dirección/categoría, distancia de nombre <=
    max_name_distance, >=3 fechas y mediana de intervalos compatible. Evitan que
    el encadenamiento o un armónico conviertan clientes distintos en un patrón.
    """
    rows = sorted((x for x in history if not x.irregular),key=lambda x:(x.occurred_on,x.id))
    if len(rows)>2500:
        raise InputError("La detección exacta O(n²) admite hasta 2500 movimientos; agrega un índice/bloqueo para más.")
    parent = list(range(len(rows)))
    def find(i: int) -> int:
        while parent[i]!=i:
            parent[i]=parent[parent[i]]; i=parent[i]
        return i
    for i,a in enumerate(rows):
        for j in range(i):
            b=rows[j]
            if a.direction!=b.direction or _name(a.category)!=_name(b.category):
                continue
            dist=composite_distance(a,b,config.candidate_periods,config.recurrence_weights)
            if dist["counterparty"] <= config.max_name_distance and dist["total"] < config.recurrence_epsilon:
                parent[find(i)] = find(j)
    groups: dict[int,list[HistoricalTransaction]] = {}
    for i,row in enumerate(rows): groups.setdefault(find(i),[]).append(row)
    patterns=[]; rejected=[]
    for group in groups.values():
        dates=sorted({r.occurred_on for r in group})
        if len(dates)<config.min_recurrence_count:
            rejected.append({"ids":[r.id for r in group],"reason":"menos de tres fechas"}); continue
        span=(config.history_end-config.history_start).days+1
        daily=np.zeros(span)
        for r in group: daily[(r.occurred_on-config.history_start).days]+=float(r.amount)
        ac=autocorrelation(daily,min(max(config.candidate_periods),span-1),adjusted=config.acf_adjusted)
        gaps=np.diff([d.toordinal() for d in dates]); median_gap=float(np.median(gaps))
        valid=[]
        for p in config.candidate_periods:
            if p>=span or (dates[-1]-dates[0]).days < 2*p:
                continue
            # Solo periodos compatibles con el intervalo dominante, no P=7 de una serie P=14.
            if abs(median_gap-p)>max(2,p*0.15): continue
            if ac[p] >= config.acf_threshold: valid.append((p,float(ac[p])))
        if not valid:
            rejected.append({"ids":[r.id for r in group],"reason":"ACF o separación temporal no confirma un periodo"}); continue
        p,acf_value=valid[0]  # primer periodo significativo compatible
        # Sumar importes por fecha permite pagos fraccionados dentro del mismo día.
        observed=tuple(float(daily[(d-config.history_start).days]) for d in dates)
        mu=float(np.mean(observed)); sigma=float(np.std(observed,ddof=1)); cv=sigma/mu if mu>0 else 0.0
        label=Counter(r.counterparty for r in group).most_common(1)[0][0]
        keys=tuple(sorted({r.key for r in group}))
        ident="rec-"+sha256(("/".join(keys)+f":{p}").encode()).hexdigest()[:12]
        patterns.append(RecurringPattern(ident,label,group[0].direction,group[0].category,p,dates[-1],mu,sigma,cv,
                                        acf_value,cv<config.max_stable_cv,tuple(r.id for r in group),keys,observed))
    return sorted(patterns,key=lambda p:p.id),rejected


@dataclass
class TemporalFit:
    method: str
    forecast: np.ndarray
    fitted: np.ndarray
    residuals: np.ndarray
    # Respuesta impulso: propaga innovaciones SARIMA en lugar de sumarlas sin dinámica.
    impulse: np.ndarray
    analytic_flow_interval: np.ndarray | None = None
    diagnostics: dict[str,Any] = field(default_factory=dict)


def _diagnostics(x: np.ndarray, period: int) -> dict[str,Any]:
    result: dict[str,Any] = {"observations":len(x),"seasonalPeriodDays":period}
    result["acf"] = autocorrelation(x,min(len(x)-1,max(12,2*period))).tolist()
    if len(x)<12 or np.std(x)<1e-9:
        result.update(adfPValue=None,pacf=[],adfNote="Serie corta o constante: no se interpreta ADF.")
        return result
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            test=adfuller(x,autolag="AIC",regression="c")
            result.update(adfPValue=float(test[1]),adfStatistic=float(test[0]),adfLags=int(test[2]))
        except (ValueError,np.linalg.LinAlgError) as exc:
            result.update(adfPValue=None,adfNote=type(exc).__name__)
        try:
            result["pacf"]=pacf(x,nlags=min(12,len(x)//2-1),method="ywm").tolist()
        except (ValueError,np.linalg.LinAlgError):
            result["pacf"]=[]
    return result


def _fit_one(values: np.ndarray, horizon: int, method: str, period: int,
             confidence: float) -> TemporalFit:
    x=np.asarray(values,dtype=float)
    if x.ndim!=1 or len(x)<1 or not np.all(np.isfinite(x)):
        raise InputError("El modelo requiere una serie diaria finita no vacía.")
    if method not in MODEL_NAMES:
        raise InputError("Modelo desconocido.")
    diag: dict[str,Any]={"requested":method,"warnings":[]}
    impulse=np.r_[1.,np.zeros(horizon-1)]
    if np.std(x)<1e-10:
        return TemporalFit("constant",np.full(horizon,x[-1]),x.copy(),np.zeros(len(x)),impulse,
                           diagnostics={"requested":method,"warnings":["Serie constante: proyección constante, sin incertidumbre residual estimable."]})
    if method=="seasonal_mean":
        if len(x)<2*period:
            fitted=np.full(len(x),x.mean()); future=np.full(horizon,x.mean())
            diag["warnings"].append("Sin dos ciclos: media global, no estacionalidad validada.")
        else:
            phases=np.array([np.mean(x[i::period]) for i in range(period)])
            fitted=phases[np.arange(len(x))%period]
            future=phases[(len(x)+np.arange(horizon))%period]
        return TemporalFit(method,future,fitted,x-fitted,impulse,diagnostics=diag)
    if len(x)<max(14,2*period):
        raise InputError(f"{method} necesita al menos max(14,2*periodo) observaciones en esta implementación.")
    scale=max(1.0,float(np.std(x)))
    y=x/scale
    if method=="stl":
        decomposition=STL(y,period=period,robust=True).fit()
        window=min(len(y),max(period,7))
        slope=float(np.polyfit(np.arange(window),decomposition.trend[-window:],1)[0])
        future_trend=decomposition.trend[-1]+slope*np.arange(1,horizon+1)
        future_season=np.resize(decomposition.seasonal[-period:],horizon)
        fitted=(decomposition.trend+decomposition.seasonal)*scale
        future=(future_trend+future_season)*scale
        diag.update(trendSlopePerDay=slope*scale,
                    decomposition={"trend":(decomposition.trend*scale).tolist(),
                                   "seasonal":(decomposition.seasonal*scale).tolist(),
                                   "residual":(decomposition.resid*scale).tolist()})
        return TemporalFit(method,future,fitted,x-fitted,impulse,diagnostics=diag)
    if method=="holt_winters":
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            fit=ExponentialSmoothing(y,trend="add",damped_trend=True,seasonal="add",
                                     seasonal_periods=period,initialization_method="estimated").fit(optimized=True)
        diag["warnings"].extend(sorted({type(w.message).__name__ for w in caught}))
        future=np.asarray(fit.forecast(horizon))*scale
        fitted=np.asarray(fit.fittedvalues)*scale
        return TemporalFit(method,future,fitted,x-fitted,impulse,diagnostics=diag)
    # SARIMA: búsqueda ACOTADA por AIC, no una búsqueda exhaustiva de todos los órdenes.
    if period>90:
        raise InputError("SARIMA estacional se limita a period<=90 para controlar costo de esta entrega.")
    diag.update(_diagnostics(y,period))
    adf_p=diag.get("adfPValue")
    d=0 if adf_p is not None and adf_p<0.05 else 1
    candidates=[]; failures=[]
    for p,q in ((1,0),(0,1),(1,1)):
        for D in (0,1):
            order=(p,d,q); seasonal=(0,D,1,period)
            try:
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    fit=SARIMAX(y,order=order,seasonal_order=seasonal,
                                trend="c" if d+D==0 else "n",
                                enforce_stationarity=True,enforce_invertibility=True).fit(disp=False,maxiter=120)
                converged=bool(fit.mle_retvals.get("converged",True))
                if not converged or not isfinite(float(fit.aic)):
                    failures.append({"order":order,"seasonal":seasonal,"reason":"no convergió/AIC no finito"}); continue
                candidates.append((float(fit.aic),fit,order,seasonal,sorted({type(w.message).__name__ for w in caught})))
            except (ValueError,RuntimeError,np.linalg.LinAlgError) as exc:
                failures.append({"order":order,"seasonal":seasonal,"reason":type(exc).__name__})
    if not candidates:
        raise InputError("Ningún SARIMA candidato convergió. No se ha sustituido silenciosamente por otro modelo.")
    aic,best,order,seasonal,fit_warnings=min(candidates,key=lambda z:z[0])
    forecast=best.get_forecast(steps=horizon)
    future=np.asarray(forecast.predicted_mean)*scale
    interval=np.asarray(forecast.conf_int(alpha=1-confidence))*scale
    fitted=np.asarray(best.fittedvalues)*scale
    burn=min(len(x)-1,max(period,int(getattr(best,"loglikelihood_burn",0))))
    residuals=np.asarray(best.resid,dtype=float)[burn:]*scale
    impulse=np.asarray(best.impulse_responses(steps=horizon-1),dtype=float).reshape(-1)
    diag.update(order=order,seasonalOrder=seasonal,aic=aic,converged=True,failures=failures,
                search=[{"aic":v[0],"order":v[2],"seasonalOrder":v[3]} for v in candidates],
                residualBurnIn=burn)
    diag["warnings"].extend(fit_warnings)
    diag["warnings"].append("Simulación SARIMA condicionada al estado ajustado: no muestrea parámetros ni incertidumbre del estado inicial.")
    return TemporalFit(method,future,fitted,residuals,impulse,interval,diag)


def fit_temporal_model(values: Sequence[float], horizon: int, *, method: str="auto",
                       period: int=7, confidence: float=0.95,
                       auto_methods: Sequence[str]=MODEL_NAMES) -> TemporalFit:
    """Auto: holdout temporal del componente de fondo, MAE y desempate por nombre.

    El tramo de validación no se usa para ajustar candidatos. Después se vuelve
    a ajustar el elegido con todo el entrenamiento disponible. Este holdout es
    selección del modelo, no una medición independiente del error final.
    """
    x=np.asarray(values,dtype=float)
    _require_int(horizon,"horizon",1,365)
    _require_int(period,"period",2,365)
    if x.ndim!=1 or len(x)<1 or not np.all(np.isfinite(x)):
        raise InputError("Serie diaria vacía, multidimensional o no finita.")
    if method!="auto":
        fit=_fit_one(x,horizon,method,period,confidence)
    elif np.std(x)<1e-10:
        fit=_fit_one(x,horizon,"seasonal_mean",period,confidence)
    else:
        hold=min(horizon,max(7,period),max(1,len(x)//4))
        train=x[:-hold]; test=x[-hold:]; scores=[]; failures=[]
        if len(train)<max(14,2*period):
            fit=_fit_one(x,horizon,"seasonal_mean",period,confidence)
            fit.diagnostics["autoSelection"]={"note":"Historial insuficiente para comparación; media estacional/global explícita."}
        else:
            for candidate in auto_methods:
                try:
                    model=_fit_one(train,hold,candidate,period,confidence)
                    if not np.all(np.isfinite(model.forecast)): raise InputError("pronóstico no finito")
                    scores.append({"model":candidate,"mae":float(np.mean(abs(test-model.forecast))),
                                   "rmse":float(np.sqrt(np.mean((test-model.forecast)**2)))})
                except (InputError,ValueError,np.linalg.LinAlgError) as exc:
                    failures.append({"model":candidate,"error":str(exc)})
            if not scores: raise InputError("Ningún modelo pudo evaluarse con el historial disponible.")
            scores.sort(key=lambda s:(s["mae"],s["model"]))
            fit=_fit_one(x,horizon,scores[0]["model"],period,confidence)
            fit.diagnostics["autoSelection"]={"holdoutDays":hold,"trainDays":len(train),"scores":scores,"failures":failures}
    if not np.all(np.isfinite(fit.forecast)) or not np.all(np.isfinite(fit.residuals)):
        raise InputError("Ajuste no finito. Revisa el historial antes de proyectar.")
    fit.diagnostics.update(_diagnostics(x,period))
    return fit


def backtest_temporal(values: Sequence[float], *, horizon: int=14, folds: int=3,
                      period: int=7, method: str="auto",
                      auto_methods: Sequence[str]=MODEL_NAMES) -> dict[str,Any]:
    """Evaluación rolling-origin sin usar observaciones futuras al ajustar.

    Evalúa UNA serie diaria, no toda la cadena de detección/conciliación de pagos.
    Si method=auto, la selección se anida dentro de cada ventana de entrenamiento.
    """
    x=np.asarray(values,dtype=float)
    if x.ndim!=1 or not np.all(np.isfinite(x)): raise InputError("Serie de backtest no válida.")
    _require_int(folds,"folds",1,10); _require_int(horizon,"horizon",1,365)
    if len(x)<max(14,2*period)+folds*horizon:
        raise InputError("Historial insuficiente para ese backtest.")
    result=[]
    for origin in range(len(x)-folds*horizon,len(x),horizon):
        train=x[:origin]; actual=x[origin:origin+horizon]
        fit=fit_temporal_model(train,horizon,method=method,period=period,auto_methods=auto_methods)
        err=actual-fit.forecast
        result.append({"trainingDays":origin,"testStartIndex":origin,"model":fit.method,
                       "mae":float(np.mean(abs(err))),"rmse":float(np.sqrt(np.mean(err**2))),
                       "actual":actual.tolist(),"prediction":fit.forecast.tolist()})
    return {"folds":result,"meanMAE":float(np.mean([f["mae"] for f in result])),
            "scope":"serie diaria; no toda la cadena de recurrencias y facturas"}


def bootstrap_residuals(residuals: Sequence[float], simulations: int, horizon: int,
                       rng: np.random.Generator, *, block_length: int=1) -> np.ndarray:
    """Bootstrap circular de bloques; block_length=1 reproduce remuestreo IID.

    Centra residuos para no sumar de nuevo el nivel del modelo. Conserva tramos
    locales, no garantiza conservar heterocedasticidad ni dependencia de largo plazo.
    """
    r=np.asarray(residuals,dtype=float)
    if r.ndim!=1 or not len(r) or not np.all(np.isfinite(r)):
        raise InputError("No hay residuos válidos para bootstrap.")
    _require_int(block_length,"block_length",1,365)
    block=min(block_length,len(r)); blocks=ceil(horizon/block)
    starts=rng.integers(0,len(r),size=(simulations,blocks))
    indices=(starts[:,:,None]+np.arange(block)[None,None,:])%len(r)
    return (r-r.mean())[indices].reshape(simulations,-1)[:,:horizon]


@dataclass
class GaussianDelayCopula:
    """Dependencia entre RETRASOS empíricos; no impagos ni riesgo de cola extremo.

    Cada fila de fit() debe ser un ciclo simultáneo para todos los clientes, en
    el mismo orden temporal. Nunca se fabrican pares alineando filas sin fecha.
    Correlaciones de normales latentes, no correlaciones Pearson de días de pago.
    """
    client_ids: tuple[str,...]
    marginals: tuple[np.ndarray,...]
    correlation: np.ndarray
    diagnostics: dict[str,Any]

    @classmethod
    def fit(cls, client_ids: Sequence[str], observations: Sequence[Sequence[float]],
            *, shrinkage: float=0.05, min_complete: int=12) -> "GaussianDelayCopula":
        _require_int(min_complete,"min_complete",3,10000)
        ids=tuple(client_ids); x=np.asarray(observations,dtype=float)
        if not ids or len(set(ids))!=len(ids) or x.ndim!=2 or x.shape[1]!=len(ids):
            raise InputError("Matriz de retrasos: columnas únicas e iguales a client_ids.")
        if np.any(np.isinf(x)) or np.any(x[np.isfinite(x)]<0) or np.any(x[np.isfinite(x)]>3650):
            raise InputError("Retrasos empíricos deben estar entre 0 y 3650 días, o NaN si faltan.")
        if np.any(x[np.isfinite(x)] != np.rint(x[np.isfinite(x)])):
            raise InputError("Los retrasos de esta API se expresan en días enteros.")
        shrinkage=_prob(shrinkage,"shrinkage")
        marginals=tuple(np.sort(x[np.isfinite(x[:,i]),i]) for i in range(len(ids)))
        if any(len(m)<2 for m in marginals): raise InputError("Cada cliente necesita al menos dos retrasos observados.")
        complete=x[np.all(np.isfinite(x),axis=1)]
        if len(complete)<min_complete:
            raise InputError(f"Se necesitan {min_complete} ciclos completos alineados para estimar la cópula; solo hay {len(complete)}.")
        corr=np.eye(len(ids)); active=[i for i in range(len(ids)) if np.std(complete[:,i])>1e-12]
        if len(active)>1:
            scores=np.column_stack([norm.ppf((rankdata(complete[:,i],method="average")-0.5)/len(complete)) for i in active])
            sub=np.corrcoef(scores,rowvar=False)
            sub=(1-shrinkage)*sub+shrinkage*np.eye(len(active))
            corr[np.ix_(active,active)]=sub
        return cls(ids,marginals,corr,{"completeAlignedCycles":len(complete),"shrinkage":shrinkage,
                                      "constantClients":[ids[i] for i in range(len(ids)) if i not in active],
                                      "assumption":"Cópula gaussiana de retrasos, sin dependencia asintótica de cola."})

    def sample(self, size: int, rng: np.random.Generator) -> np.ndarray:
        z=rng.multivariate_normal(np.zeros(len(self.client_ids)),self.correlation,size=size,check_valid="raise")
        u=norm.cdf(z)
        result=np.empty_like(u)
        for i,m in enumerate(self.marginals):
            # F^-1 empírica por escalones; no interpola retrasos inexistentes.
            index=np.minimum((u[:,i]*len(m)).astype(int),len(m)-1)
            result[:,i]=m[index]
        return np.rint(result).astype(int)


@dataclass(frozen=True)
class IrregularComponent:
    series: str
    rate_per_day: float
    signed_amount_samples: tuple[float,...]


@dataclass
class PreparedForecast:
    config: ForecastConfig
    history: tuple[HistoricalTransaction,...]
    patterns: list[RecurringPattern]
    rejected_patterns: list[dict[str,Any]]
    events: tuple[PlannedEvent,...]
    background_history: np.ndarray
    background_model: TemporalFit
    irregular: tuple[IrregularComponent,...]
    copula: GaussianDelayCopula | None
    warnings: list[str]


def prepare_forecast(history: Sequence[HistoricalTransaction], config: ForecastConfig,
                     planned_events: Sequence[PlannedEvent]=(),
                     copula: GaussianDelayCopula | None=None) -> PreparedForecast:
    """Conciliación explícita para no sumar dos veces el historial y las facturas.

    Las observaciones de origen deben estar verificadas, en una misma moneda y
    empresa. El motor recibe una empresa por llamada; el backend debe filtrar SQL
    por el tenant autenticado ANTES de construir estos objetos.
    """
    if len(history)>2500 or len(planned_events)>4000:
        raise InputError("Límite de esta implementación: 2500 movimientos históricos y 4000 eventos futuros.")
    rows=tuple(sorted(history,key=lambda x:(x.occurred_on,x.id)))
    if len({r.id for r in rows})!=len(rows): raise InputError("IDs históricos duplicados.")
    if len({e.id for e in planned_events})!=len(planned_events): raise InputError("IDs futuros duplicados.")
    for r in rows:
        if r.currency!=config.currency: raise InputError("No se pueden sumar monedas distintas sin conversión explícita.")
        if not config.history_start<=r.occurred_on<=config.history_end:
            raise InputError("Movimiento fuera de cobertura histórica: evita usar datos futuros al entrenar.")
    for e in planned_events:
        if e.currency!=config.currency: raise InputError("Agenda en moneda diferente.")
        if e.id.startswith(("rec-","action:","fee:","repayment:")):
            raise InputError("Prefijo de ID reservado para eventos generados.")
        if e.expected_date<config.start_date:
            raise InputError("Una cuenta vencida requiere una nueva fecha prevista explícita; no se descarta.")
    notices=["Los días sin filas se tratan como cero porque history_complete=true fue confirmado.",
             "Los patrones usan periodos fijos en días; 30 días no equivale a mes calendario.",
             "Las probabilidades dependen del modelo y del historial; no son garantías financieras."]
    patterns,rejected=detect_recurrences(rows,config)
    for i,p in enumerate(patterns):
        if (config.history_end-p.last_date).days>2*p.period:
            patterns[i]=replace(p,stable=False)
            notices.append(f"Patrón {p.id} no proyectado: lleva más de dos periodos sin aparecer.")
        elif not p.stable:
            notices.append(f"Patrón {p.id} variable (CV={p.cv:.3f}): permanece en el modelo de fondo.")
    end=config.start_date+timedelta(days=config.days-1)
    generated: dict[tuple[str,date],PlannedEvent]={}
    for p in patterns:
        if not p.stable: continue
        at=p.last_date+timedelta(days=p.period)
        while at<config.start_date: at+=timedelta(days=p.period)
        while at<=end:
            generated[(p.id,at)]=PlannedEvent(
                id=f"{p.id}:{at.isoformat()}",counterparty=p.counterparty,amount=Decimal(str(p.mean_amount)),
                direction=p.direction,expected_date=at,category=p.category,currency=config.currency,
                client_id=_name(p.counterparty),amount_samples=p.amounts,source="recurrencia",risk_anchor=at)
            at+=timedelta(days=p.period)
    all_keys={r.key for r in rows}
    excluded_keys:set[str]=set(); replaced:set[tuple[str,date]]=set(); known=[]
    for e in planned_events:
        link=e.history_series_key
        possible=[p for p in patterns if p.stable and (link in p.series_keys or link==p.id)] if link else []
        if link is None:
            similar=any(r.direction==e.direction and _name(r.category)==_name(e.category) and
                        levenshtein_distance(_name(r.counterparty),_name(e.counterparty))/max(1,len(_name(r.counterparty)),len(_name(e.counterparty))) <= config.max_name_distance
                        for r in rows)
            if (e.key in all_keys or similar) and not e.additional_to_history:
                raise InputError(f"{e.id}: existe historial compatible. Define history_series_key o declara additional_to_history=true para no duplicarlo.")
            if e.additional_to_history:
                notices.append(f"{e.id}: el usuario declaró que es ADICIONAL al patrón histórico, no un reemplazo.")
        elif len(possible)>1:
            raise InputError(f"{e.id}: enlace ambiguo; usa el ID del patrón concreto como history_series_key.")
        elif possible:
            p=possible[0]; original=e.replaces_on or e.expected_date; slot=(p.id,original)
            if original<=end:
                if slot not in generated or slot in replaced:
                    raise InputError(f"{e.id}: no existe una ocurrencia única {original} del patrón {p.id}.")
                del generated[slot]; replaced.add(slot)
                notices.append(f"{e.id} reemplaza {p.id} del {original}; no se suma otra vez.")
        else:
            if link not in all_keys:
                raise InputError(f"{e.id}: history_series_key no existe en el historial ni en los patrones.")
            excluded_keys.add(link)
        known.append(replace(e,risk_anchor=e.risk_anchor or e.expected_date))
    for key in sorted(excluded_keys):
        notices.append(f"Agenda sustituye TODA la serie {key}; el usuario debe aportar todas sus operaciones futuras del horizonte.")
    recurring_ids={id_ for p in patterns if p.stable for id_ in p.history_ids}
    span=(config.history_end-config.history_start).days+1
    background=np.zeros(span); irregular_groups:dict[str,list[float]]={}
    for r in rows:
        if r.key in excluded_keys or r.id in recurring_ids: continue
        if r.irregular:
            irregular_groups.setdefault(r.key,[]).append(r.signed_amount)
        else:
            background[(r.occurred_on-config.history_start).days]+=r.signed_amount
    irregular=tuple(IrregularComponent(k,len(v)/span,tuple(v)) for k,v in sorted(irregular_groups.items()))
    fit=fit_temporal_model(background,config.days,method=config.model,period=config.seasonal_period,
                           confidence=config.confidence,auto_methods=config.auto_methods)
    notices.extend(fit.diagnostics.get("warnings",[]))
    events=tuple(sorted((*generated.values(),*known),key=lambda e:(e.expected_date,e.id)))
    if len(events)>4000: raise InputError("Demasiados eventos proyectados. Reduce el horizonte o agrupa series verificadas.")
    if copula is None:
        notices.append("Sin cópula configurada: los retrasos de diferentes clientes se simulan independientemente.")
    else:
        notices.append(f"Cópula aplicada por ciclos fijos de {config.delay_cycle_days} días; ciclos diferentes son independientes.")
    if not irregular: notices.append("No hay eventos etiquetados como irregulares: no se añade un Poisson inventado.")
    return PreparedForecast(config,rows,patterns,rejected,events,background,fit,irregular,copula,notices)


def _simulate_background(prepared: PreparedForecast, seed: int) -> np.ndarray:
    c=prepared.config; fit=prepared.background_model
    innovation=bootstrap_residuals(fit.residuals,c.simulations,c.days,_rng(seed,"background"),block_length=c.bootstrap_block)
    # SARIMA: suma psi_j * innovación_(t-j). Otros modelos usan psi=[1,0,...].
    errors=lfilter(fit.impulse,[1.0],innovation,axis=1)
    flows=_cents(fit.forecast[None,:]+errors)
    for component in prepared.irregular:
        rng=_rng(seed,"poisson:"+component.series)
        counts=rng.poisson(component.rate_per_day,size=(c.simulations,c.days))
        total=int(counts.sum())
        if total>5_000_000: raise InputError("Demasiados eventos Poisson; reduce simulaciones/horizonte.")
        if total:
            positions=np.repeat(np.arange(counts.size),counts.ravel())
            marks=_cents(rng.choice(component.signed_amount_samples,size=total,replace=True))
            added=np.zeros(counts.size,dtype=np.int64)
            np.add.at(added,positions,marks)
            flows+=added.reshape(flows.shape)
    return flows


def _event_flows(prepared: PreparedForecast, events: Sequence[PlannedEvent], seed: int,
                 base: np.ndarray | None=None) -> np.ndarray:
    c=prepared.config
    flows=_simulate_background(prepared,seed) if base is None else base.copy()
    scenarios=np.arange(c.simulations); delay_cache:dict[int,np.ndarray]={}
    for e in events:
        rng=_rng(seed,"event:"+e.id)
        if e.amount_samples:
            amount=rng.choice(e.amount_samples,size=c.simulations)
        else:
            amount=np.full(c.simulations,float(e.amount))
        if e.direction=="inflow":
            collected=rng.random(c.simulations)<e.collection_probability
            client=e.client_id or _name(e.counterparty)
            copula=prepared.copula
            if copula is not None and client in copula.client_ids:
                cycle=(e.risk_anchor or e.expected_date).toordinal()//c.delay_cycle_days
                if cycle not in delay_cache:
                    delay_cache[cycle]=copula.sample(c.simulations,_rng(seed,f"copula:{cycle}"))
                delays=delay_cache[cycle][:,copula.client_ids.index(client)]
            else:
                delays=rng.choice(e.delay_samples,size=c.simulations)
        else:
            collected=np.ones(c.simulations,dtype=bool); delays=np.zeros(c.simulations,dtype=int)
        offsets=(e.expected_date-c.start_date).days+delays
        inside=collected & (offsets>=0) & (offsets<c.days)
        sign=1 if e.direction=="inflow" else -1
        flows[scenarios[inside],offsets[inside]]+=sign*_cents(amount[inside])
    return flows


def simulate_cash_flow(prepared: PreparedForecast, opening_balance: Decimal|float|str,
                       events: Sequence[PlannedEvent] | None=None, *, seed: int|None=None) -> np.ndarray:
    """Devuelve N x H saldos en CENTAVOS int64; no un objeto JSON ni floats monetarios."""
    opening=_decimal(opening_balance,"opening_balance",nonnegative=False)
    flows=_event_flows(prepared,prepared.events if events is None else events,prepared.config.seed if seed is None else seed)
    return int(opening*100)+np.cumsum(flows,axis=1,dtype=np.int64)


def _probability_summary(indicators: np.ndarray, confidence: float=0.95) -> dict[str,float|int]:
    v=np.asarray(indicators,dtype=bool); n=v.size
    if not n: raise InputError("No hay simulaciones.")
    k=int(v.sum()); p=k/n; z=float(norm.ppf(confidence)); denom=1+z*z/n
    upper=(p+z*z/(2*n)+z*sqrt(p*(1-p)/n+z*z/(4*n*n)))/denom
    return {"probability":p,"monteCarloSE":sqrt(p*(1-p)/n),"wilsonUpper":min(1.,upper),"breaches":k,"simulations":n}


def empirical_loss_risk(losses: Sequence[float], confidence: float = 0.95) -> dict[str,Any]:
    """VaR de la distribución empírica y ES de la peor masa 1-confidence.

    Diferencia explícita frente a E[L | L >= VaR]: cuando hay empates, la cola
    condicional puede contener más del 5%. Aquí se pondera fraccionalmente la
    observación de frontera para integrar exactamente la masa de cola elegida.
    La convención literal del documento se conserva por separado en la salida.
    """
    x=np.asarray(losses,dtype=float)
    if x.ndim!=1 or not len(x) or not np.all(np.isfinite(x)):
        raise InputError("Se necesita una muestra unidimensional finita de pérdidas.")
    confidence=_prob(confidence,"confidence")
    if not 0<confidence<1: raise InputError("confidence debe estar estrictamente entre 0 y 1.")
    worst=np.sort(x)[::-1]; mass=(1-confidence)*len(x)
    whole=int(np.floor(mass)); fraction=mass-whole
    weighted=float(worst[:whole].sum())
    if fraction>0 and whole<len(worst): weighted+=fraction*float(worst[whole])
    return {"VaR":_cash(np.quantile(x,confidence,method="inverted_cdf")),
            "ES":_cash(weighted/mass),"tailMass":1-confidence,
            "note":"VaR empírico por escalones; ES de masa exacta con ponderación fraccional en empates."}


def risk_metrics(paths_cents: np.ndarray, opening_balance: Decimal|float|str,
                 threshold: Decimal|float|str, config: ForecastConfig,
                 *, nominal_daily_net: Sequence[float] | None=None,
                 historical_daily_outflow: float|None=None) -> dict[str,Any]:
    paths=np.asarray(paths_cents)
    if paths.ndim!=2 or paths.shape[1]!=config.days or len(paths)<1:
        raise InputError("Forma incorrecta de trayectorias.")
    if not np.all(np.isfinite(paths)): raise InputError("Trayectorias no finitas.")
    opening=float(_decimal(opening_balance,"opening_balance",nonnegative=False)); level=float(_decimal(threshold,"threshold"))
    b=paths.astype(float)/100.; terminal=b[:,-1]; minima=b.min(axis=1); tail=1-config.confidence
    q=float(np.quantile(terminal,tail)); tail_mean=float(terminal[terminal<=q].mean())
    term=_probability_summary(terminal<level,config.probability_confidence)
    anyday=_probability_summary(minima<level,config.probability_confidence)
    cumulative=b-opening
    shortfalls=np.maximum(0,level-minima)
    peak_net_outflow=np.maximum(0,-cumulative.min(axis=1))
    nominal=np.asarray(nominal_daily_net,dtype=float) if nominal_daily_net is not None else np.mean(np.diff(np.c_[np.full(len(b),opening),b],axis=1),axis=0)
    burn=float(np.mean(np.maximum(0,-nominal)))
    qmethod="higher"  # cuantil discreto para un colchón basado en simulaciones.
    return {
        "confidenceLevel":config.confidence,
        "terminalBalance":{"mean":_cash(terminal.mean()),"qLow":_cash(q),"median":_cash(np.median(terminal)),
                           "qHigh":_cash(np.quantile(terminal,config.confidence))},
        # Convención L=-B_H del documento; pueden ser negativos con saldos positivos.
        "documentConvention":{"lossDefinition":"L = -B_H","VaR":_cash(-q),"ES":_cash(-tail_mean),
                              "tailFractionWithTies":float(np.mean(terminal<=q))},
        "changeFromOpening":{"lossDefinition":"L = B_0 - B_H",**empirical_loss_risk(opening-terminal,config.confidence)},
        "pdTerminal":term,"pdAnyDay":anyday,
        "dailyBreachProbability":np.mean(b<level,axis=0).tolist(),
        "meanMaximumShortfall":_cash(shortfalls.mean()),
        "runway":{"formula":"B0 / mean(max(0, -nominal_daily_net))", "dailyBurn":_cash(burn),
                  "days":max(0,opening)/burn if burn>0 else None,
                  "note":"Fórmula del documento: usa flujo NETO negativo; no supone ingresos cero.",
                  "withoutIncomeDaysHistoricalOutflow":max(0,opening)/historical_daily_outflow if historical_daily_outflow and historical_daily_outflow>0 else None},
        "workingCapitalBuffer":{
            "cogsTimesCoverage":_cash(float(config.daily_cogs)*config.coverage_days) if config.daily_cogs is not None else None,
            "coverageDays":config.coverage_days,
            "terminalNetOutflowQuantile":_cash(max(0,float(np.quantile(-cumulative[:,-1],config.confidence,method=qmethod)))),
            "peakNetOutflowQuantile":_cash(np.quantile(peak_net_outflow,config.confidence,method=qmethod)),
            "additionalCashToThresholdQuantile":_cash(np.quantile(shortfalls,config.confidence,method=qmethod)),
            "note":"Cuantiles bajo el modelo; no garantía de solvencia. El ES de -B_H no se usa como buffer automático."},
        "openingBelowThreshold":opening<level,
        "timeConvention":"Saldos al cierre diario; no se evalúa liquidez intradía."
    }


@dataclass(frozen=True)
class LiquidityAction:
    id: str
    type: str
    target_event_id: str | None=None
    days: int=0
    amount: Decimal=Decimal("0")
    financial_cost: Decimal=Decimal("0")
    operational_impact: int=0
    effective_date: date | None=None
    repayment_date: date | None=None
    cost_date: date | None=None
    exclusive_group: str | None=None

    def __post_init__(self) -> None:
        if not self.id: raise InputError("Acción sin identificador.")
        allowed=("delay_receivable","accelerate_receivable","defer_payable","delay_expense","advance_expense","draw_credit")
        if self.type not in allowed: raise InputError("Tipo de acción desconocido.")
        _require_int(self.days,"action.days",0,3650)
        _require_int(self.operational_impact,"operational_impact",0,1000000)
        object.__setattr__(self,"amount",_decimal(self.amount,"action.amount"))
        object.__setattr__(self,"financial_cost",_decimal(self.financial_cost,"financial_cost"))
        for attr in ("effective_date","repayment_date","cost_date"):
            if getattr(self,attr) is not None: object.__setattr__(self,attr,_day(getattr(self,attr),attr))
        if self.type=="draw_credit":
            if self.amount<=0 or self.effective_date is None or self.repayment_date is None:
                raise InputError("Crédito requiere monto positivo, fecha de disposición y fecha de devolución del principal.")
            if self.repayment_date<=self.effective_date:
                raise InputError("La devolución del crédito debe ser posterior a la disposición.")
        elif not self.target_event_id:
            raise InputError("La acción necesita target_event_id.")


def apply_liquidity_actions(events: Sequence[PlannedEvent], actions: Sequence[LiquidityAction],
                            config: ForecastConfig) -> tuple[PlannedEvent,...]:
    """Transformación hipotética; no modifica historia, SQL ni ejecuta pagos.

    Los costos se registran como egresos ciertos, UNA sola vez. Si representan un
    descuento, el ingreso permanece bruto y el egreso del descuento ocurre al
    cobrar (cost_date por defecto = fecha acelerada). No se descuenta dos veces.
    """
    if len({a.id for a in actions})!=len(actions): raise InputError("IDs de acciones duplicados.")
    groups=[a.exclusive_group for a in actions if a.exclusive_group]
    if len(groups)!=len(set(groups)): raise InputError("Acciones mutuamente excluyentes del mismo grupo.")
    targets=[a.target_event_id for a in actions if a.target_event_id]
    if len(targets)!=len(set(targets)): raise InputError("Acciones incompatibles sobre el mismo evento.")
    result={e.id:e for e in events}
    def add(e: PlannedEvent) -> None:
        if e.id in result: raise InputError("Colisión de ID generado.")
        result[e.id]=e
    for a in actions:
        at=a.effective_date or config.start_date
        if a.type=="draw_credit":
            add(PlannedEvent("action:"+a.id,"Línea de crédito",a.amount,"inflow",at,"credit",config.currency,source="accion"))
            add(PlannedEvent("repayment:"+a.id,"Devolución del principal",a.amount,"outflow",a.repayment_date,"credit_repayment",config.currency,source="accion"))
        else:
            if a.target_event_id not in result: raise InputError(f"Evento objetivo inexistente: {a.target_event_id}.")
            e=result[a.target_event_id]
            expected_direction="inflow" if a.type in ("delay_receivable","accelerate_receivable") else "outflow"
            if e.direction!=expected_direction: raise InputError("La dirección no corresponde al tipo de acción.")
            offset=-a.days if a.type in ("accelerate_receivable","advance_expense") else a.days
            at=e.expected_date+timedelta(days=offset)
            result[e.id]=replace(e,expected_date=at,risk_anchor=e.risk_anchor or e.expected_date)
        if at<config.start_date:
            raise InputError("La acción situaría un movimiento antes del inicio del pronóstico.")
        if a.financial_cost:
            fee_date=a.cost_date or at
            if fee_date<config.start_date: raise InputError("Costo de acción fuera de la ventana pasada.")
            add(PlannedEvent("fee:"+a.id,"Costo de intervención",a.financial_cost,"outflow",fee_date,"fees",config.currency,source="accion"))
    return tuple(sorted(result.values(),key=lambda e:(e.expected_date,e.id)))


def _chance_assessment(paths: np.ndarray, level_cents: int, config: ForecastConfig) -> dict[str,Any]:
    observed=paths[:,-1] if config.constraint=="terminal" else paths.min(axis=1)
    p=_probability_summary(observed<level_cents,config.probability_confidence)
    criterion=p["probability"] if config.chance_method=="empirical" else p["wilsonUpper"]
    return {**p,"constraint":config.constraint,"criterion":config.chance_method,
            "criterionValue":criterion,"alpha":config.alpha,"passes":bool(criterion<=config.alpha)}


def optimize_chance_constrained(prepared: PreparedForecast, opening_balance: Any,
                                threshold: Any, actions: Sequence[LiquidityAction]) -> dict[str,Any]:
    """Búsqueda acotada con números aleatorios comunes y confirmación independiente.

    Para cada combinación aplica escenarios al MISMO ruido de fondo y mismos
    sorteos de cada evento. El ganador se valida con una semilla independiente.
    Si falla, no se busca otro ganador con esa validación: se declara no validado.
    """
    c=prepared.config; opening=_decimal(opening_balance,"opening_balance",nonnegative=False)
    level=_decimal(threshold,"threshold"); level_cents=int(level*100)
    if len({a.id for a in actions})!=len(actions): raise InputError("IDs de acciones candidatos duplicados.")
    maximum=min(c.max_actions,len(actions)); total=sum(comb(len(actions),k) for k in range(maximum+1))
    if total>c.max_candidates:
        raise InputError(f"Se evaluarían {total} combinaciones; el límite es {c.max_candidates}.")
    ordered=sorted(actions,key=lambda a:a.id)
    for a in ordered:
        # Una acción individual inválida es un error de datos, no un fallo del optimizador.
        apply_liquidity_actions(prepared.events,(a,),c)
    base=_simulate_background(prepared,c.seed)
    records=[]; skipped=[]; feasible=[]
    for size in range(maximum+1):
        for selected in combinations(ordered,size):
            groups=[a.exclusive_group for a in selected if a.exclusive_group]
            if len(set(groups))!=len(groups):
                skipped.append({"actions":[a.id for a in selected],"reason":"mismo grupo excluyente"}); continue
            targets=[a.target_event_id for a in selected if a.target_event_id]
            if len(set(targets))!=len(targets):
                skipped.append({"actions":[a.id for a in selected],"reason":"mismo evento objetivo"}); continue
            transformed=apply_liquidity_actions(prepared.events,selected,c)
            flows=_event_flows(prepared,transformed,c.seed,base)
            paths=int(opening*100)+np.cumsum(flows,axis=1)
            check=_chance_assessment(paths,level_cents,c)
            cost=sum((a.financial_cost for a in selected),Decimal(0)); impact=sum(a.operational_impact for a in selected)
            ids=tuple(a.id for a in selected)
            record={"actions":list(ids),"cost":str(cost),"operationalImpact":impact,**check}
            records.append(record)
            if check["passes"]: feasible.append(((cost,impact,ids),selected,record))
    result:dict[str,Any]={"feasible":False,"evaluatedCandidates":len(records),"candidates":records,"skipped":skipped,
                          "selectedActions":[],"selectionCheck":None,"validationCheck":None,
                          "scope":"Factibilidad empírica bajo el modelo, NO garantía sobre la empresa real."}
    if not feasible:
        result["reason"]="Ninguna combinación del conjunto configurado satisface la restricción."
        return result
    _,chosen,selection=min(feasible,key=lambda r:r[0])
    transformed=apply_liquidity_actions(prepared.events,chosen,c)
    paths=simulate_cash_flow(prepared,opening,transformed,seed=c.seed+1)
    validation=_chance_assessment(paths,level_cents,c)
    result.update(proposedActions=[a.id for a in chosen],selectionCheck=selection,validationCheck=validation,
                  totalFinancialCost=str(sum((a.financial_cost for a in chosen),Decimal(0))),
                  totalOperationalImpact=sum(a.operational_impact for a in chosen),
                  validationSeed=c.seed+1)
    if validation["passes"]:
        result.update(feasible=True,selectedActions=[a.id for a in chosen],
                      reason="Candidato mínimo del conjunto; superó selección y simulación independiente.")
    else:
        result["reason"]="El candidato pasó selección pero NO la simulación independiente. No se recomienda como validado."
    end=c.start_date+timedelta(days=c.days-1)
    result["outsideHorizonObligations"]=[{"id":e.id,"date":e.expected_date.isoformat(),"amount":str(e.amount)}
                                          for e in transformed if e.direction=="outflow" and e.expected_date>end]
    return result


def _nominal_events(prepared: PreparedForecast, events: Sequence[PlannedEvent]) -> tuple[CashFlowEvent,...]:
    """Puente explícito a la API determinista original, sin alterar su contrato."""
    config=prepared.config; background=prepared.background_model.forecast.copy()
    for irr in prepared.irregular: background+=irr.rate_per_day*np.mean(irr.signed_amount_samples)
    converted=[]
    for day,amount in enumerate(background):
        if abs(amount)<0.005: continue
        converted.append(CashFlowEvent(f"model:{day}","Fondo + valor medio de irregulares",money(abs(amount)),
                                       "inflow" if amount>=0 else "outflow",config.start_date+timedelta(days=day),"model"))
    for e in events:
        converted.append(CashFlowEvent(e.id,e.counterparty,e.amount,e.direction,e.expected_date,e.category,
                                       Decimal(str(e.collection_probability)),e.source=="recurrencia"))
    return tuple(converted)


def _scenario_report(prepared: PreparedForecast, opening_balance: Any, threshold: Any,
                     events: Sequence[PlannedEvent], seed: int) -> dict[str,Any]:
    c=prepared.config
    paths=simulate_cash_flow(prepared,opening_balance,events,seed=seed)
    nominal=forecast_cash_flow(opening_balance,_nominal_events(prepared,events),c.start_date,c.days,threshold)
    nominal_balances=np.array([float(p.expected_balance) for p in nominal.projection])
    daily=np.diff(np.r_[float(opening_balance),nominal_balances])
    span=(c.history_end-c.history_start).days+1
    gross=sum(float(r.amount) for r in prepared.history if r.direction=="outflow")/span
    risk=risk_metrics(paths,opening_balance,threshold,c,nominal_daily_net=daily,historical_daily_outflow=gross)
    quantiles=np.quantile(paths.astype(float)/100,[1-c.confidence,0.5,c.confidence],axis=0)
    mean=np.mean(paths.astype(float)/100,axis=0)
    curve=[]
    for i in range(c.days):
        curve.append({"date":(c.start_date+timedelta(days=i)).isoformat(),
                      "nominalBalance":_cash(nominal_balances[i]),"simulatedMean":_cash(mean[i]),
                      "qLow":_cash(quantiles[0,i]),"qMedian":_cash(quantiles[1,i]),"qHigh":_cash(quantiles[2,i]),
                      "liquidityThreshold":_cash(threshold),"breachProbability":risk["dailyBreachProbability"][i]})
    return {"risk":risk,"projection":curve,"deterministicReference":result_to_dict(nominal),
            "samplePaths":[[_cash(v/100) for v in row] for row in paths[:c.scenario_sample_paths]],
            "samplePathsNote":"Primeras trayectorias de ilustración, no una muestra de peores casos.",
            "band":{"quantiles":[1-c.confidence,c.confidence],"pointwiseMass":2*c.confidence-1,
                    "note":"Cuantiles marginales diarios; no banda simultánea para toda la trayectoria."}}


def analyze_advanced(history: Sequence[HistoricalTransaction], config: ForecastConfig,
                     opening_balance: Any, liquidity_threshold: Any, *,
                     planned_events: Sequence[PlannedEvent]=(),
                     candidate_actions: Sequence[LiquidityAction]=(),
                     scenario_actions: Sequence[LiquidityAction]=(),
                     copula: GaussianDelayCopula | None=None) -> dict[str,Any]:
    """Entrada principal para FastAPI o una tarea de cálculo del backend.

    Aprende parámetros del historial ANTERIOR al inicio, calcula distribución de
    saldos y evalúa acciones. El resultado es JSON serializable sin acceso a SQL,
    modelos de lenguaje ni red. Gemini puede explicar este JSON, no reemplazarlo.
    """
    opening=_decimal(opening_balance,"opening_balance",nonnegative=False)
    threshold=_decimal(liquidity_threshold,"liquidity_threshold")
    prepared=prepare_forecast(history,config,planned_events,copula)
    baseline=_scenario_report(prepared,opening,threshold,prepared.events,config.seed)
    scenario_events=apply_liquidity_actions(prepared.events,scenario_actions,config)
    working=replace(prepared,events=scenario_events)
    scenario=_scenario_report(working,opening,threshold,scenario_events,config.seed) if scenario_actions else baseline
    optimization=optimize_chance_constrained(working,opening,threshold,candidate_actions)
    selected_ids=set(optimization["selectedActions"])
    recommended=None
    if optimization["feasible"]:
        chosen=[a for a in candidate_actions if a.id in selected_ids]
        repaired=apply_liquidity_actions(scenario_events,chosen,config)
        # Esta curva utiliza la simulación INDEPENDIENTE de validación.
        recommended=_scenario_report(working,opening,threshold,repaired,config.seed+1)
    event_data=[]
    end=config.start_date+timedelta(days=config.days-1)
    for e in scenario_events:
        event_data.append({"id":e.id,"counterparty":e.counterparty,"amount":str(e.amount),"direction":e.direction,
                           "expectedDate":e.expected_date.isoformat(),"source":e.source,
                           "collectionProbabilityAssumption":e.collection_probability,
                           "outsideNominalHorizon":not config.start_date<=e.expected_date<=end})
    notices=list(prepared.warnings)
    if any(e.direction=="outflow" and e.expected_date>end for e in scenario_events):
        notices.append("Existen obligaciones fuera del horizonte. Desplazarlas no elimina la deuda.")
    notices.extend([
        "collection_probability es un supuesto explícito; no se estima a partir de confidence del motor antiguo.",
        "Los importes de recurrencias se remuestrean empíricamente; las fechas se fijan al periodo salvo retrasos de cobro configurados.",
        "El bootstrap de modelos distintos de SARIMA añade residuos a la media prevista; no simula parámetros ni cambios estructurales.",
        "Los costos se cargan como egresos ciertos. Un descuento condicionado a cobro requeriría otro contrato de simulación.",
        "La selección auto evalúa solo el componente de fondo. Falta validar con datos reales toda la cadena y calibrar las probabilidades."
    ])
    fit=prepared.background_model
    fingerprint=sha256(json.dumps(to_jsonable({"history":[asdict(r) for r in history],"config":asdict(config),
                         "opening":opening,"threshold":threshold,"planned":[asdict(e) for e in planned_events],
                         "scenario":[asdict(a) for a in scenario_actions],"candidates":[asdict(a) for a in candidate_actions],
                         "copula":None if copula is None else {"clients":copula.client_ids,"marginals":copula.marginals,"correlation":copula.correlation}}),
                         sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    result={"version":VERSION,"inputHash":fingerprint,"currency":config.currency,
            "horizon":{"startDate":config.start_date.isoformat(),"endDate":end.isoformat(),"days":config.days},
            "dataCoverage":{"start":config.history_start.isoformat(),"end":config.history_end.isoformat(),
                            "completeConfirmed":config.history_complete,"transactions":len(history)},
            "simulation":{"count":config.simulations,"seed":config.seed,"blockLength":config.bootstrap_block,
                          "modelConditional":True,"moneyRepresentation":"int64 centavos durante simulación; Decimal en API original"},
            "recurrences":[to_jsonable(asdict(p)) for p in prepared.patterns],
            "recurrenceRejected":prepared.rejected_patterns,
            "backgroundModel":{"selected":fit.method,"diagnostics":fit.diagnostics,
                               "dailyMeanForecast":[_cash(v) for v in fit.forecast],
                               "residualObservations":len(fit.residuals),
                               "analyticFlowInterval":fit.analytic_flow_interval.tolist() if fit.analytic_flow_interval is not None else None,
                               "analyticIntervalNote":"Intervalo SARIMA de flujo DIARIO, no de saldo acumulado ni de toda la cartera."},
            "irregularProcesses":[to_jsonable(asdict(i)) for i in prepared.irregular],
            "copula":None if copula is None else {"clients":list(copula.client_ids),"correlation":copula.correlation.tolist(),"diagnostics":copula.diagnostics},
            "events":event_data,"baseline":baseline,"scenario":scenario,"optimization":optimization,
            "recommendedScenario":recommended,"warnings":list(dict.fromkeys(notices))}
    # Rechazar NaN/Infinity; no enviarlos al navegador como JSON inválido.
    json.dumps(to_jsonable(result),allow_nan=False)
    return to_jsonable(result)


def to_jsonable(value: Any) -> Any:
    if isinstance(value, Decimal): return str(value)
    if isinstance(value, date): return value.isoformat()
    if isinstance(value, np.ndarray): return to_jsonable(value.tolist())
    if isinstance(value, np.generic): return value.item()
    if isinstance(value, Mapping): return {str(k):to_jsonable(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)): return [to_jsonable(x) for x in value]
    return value


def analyze_payload(payload: Mapping[str,Any]) -> dict[str,Any]:
    """Contrato JSON snake_case. No acepta expresiones, consultas SQL ni código."""
    allowed={"history","config","opening_balance","liquidity_threshold","planned_events","candidate_actions","scenario_actions","delay_history"}
    if not isinstance(payload,Mapping): raise InputError("La entrada debe ser un objeto JSON.")
    extra=set(payload)-allowed
    if extra: raise InputError(f"Claves desconocidas: {sorted(extra)}.")
    try:
        c=ForecastConfig(**payload["config"])
        history=[HistoricalTransaction(**r) for r in payload["history"]]
        events=[PlannedEvent(**e) for e in payload.get("planned_events",[])]
        candidates=[LiquidityAction(**a) for a in payload.get("candidate_actions",[])]
        scenario=[LiquidityAction(**a) for a in payload.get("scenario_actions",[])]
        delay=payload.get("delay_history"); copula=None
        if delay:
            copula=GaussianDelayCopula.fit(delay["client_ids"],delay["observations"],shrinkage=delay.get("shrinkage",0.05),min_complete=delay.get("min_complete",12))
        return analyze_advanced(history,c,payload["opening_balance"],payload["liquidity_threshold"],
                                planned_events=events,candidate_actions=candidates,scenario_actions=scenario,copula=copula)
    except (TypeError,KeyError) as exc:
        raise InputError(f"Contrato JSON inválido: {exc}") from exc


def synthetic_example_payload() -> dict[str,Any]:
    """Datos sintéticos reproducibles, sin información de ninguna empresa real."""
    start=date(2026,9,12); first=start-timedelta(days=180); rng=np.random.default_rng(814)
    history=[]
    for i in range(180):
        at=first+timedelta(days=i)
        # Ventas diarias variables: el intervalo de 1 día impide confundirlas con nómina semanal.
        sales=max(50,450+0.5*i+100*np.sin(2*np.pi*i/7)+rng.normal(0,75))
        history.append(HistoricalTransaction(f"venta-{i}","Ventas de mostrador",Decimal(str(sales)),"inflow",at,"ventas"))
        history.append(HistoricalTransaction(f"gasto-{i}","Operación diaria",Decimal(str(220+rng.uniform(-80,80))),"outflow",at,"operacion"))
        if i%14==4:
            history.append(HistoricalTransaction(f"nomina-{i}","Nómina",Decimal("8500"),"outflow",at,"nomina"))
        if i%30==9:
            history.append(HistoricalTransaction(f"cliente-{i}","Cliente principal",Decimal("14500"),"inflow",at,"cobros"))
        if i%30==19:
            history.append(HistoricalTransaction(f"otro-{i}","Cliente secundario",Decimal("7500"),"inflow",at,"cobros"))
        if i%30==5:
            history.append(HistoricalTransaction(f"renta-{i}","Arrendador",Decimal("6000"),"outflow",at,"renta"))
        if i%41==11:
            history.append(HistoricalTransaction(f"reparacion-{i}","Reparación extraordinaria",Decimal(str(1200+rng.integers(0,2000))),"outflow",at,"mantenimiento",True))
    config=ForecastConfig(start,first,start-timedelta(days=1),True,model="stl",simulations=10_000,
                           daily_cogs=Decimal("220"),chance_method="wilson_upper")
    # Cliente ya presente en la historia: reemplazar SU ocurrencia, no sumarla dos veces.
    invoice=PlannedEvent("factura-principal","Cliente principal",Decimal("14500"),"inflow",first+timedelta(days=189),"cobros",
                         history_series_key=series_key("Cliente principal","inflow","cobros"),
                         client_id="cliente principal",collection_probability=0.98)
    rent_invoice=PlannedEvent("renta-pendiente","Arrendador",Decimal("6000"),"outflow",first+timedelta(days=185),"renta",
                              history_series_key=series_key("Arrendador","outflow","renta"))
    paired=[]
    for _ in range(36):
        shock=int(rng.choice([0,0,0,3,7,12]))
        paired.append([max(0,shock+int(rng.integers(-1,3))),max(0,shock+int(rng.integers(-1,4)))])
    candidates=[LiquidityAction("credito-10000","draw_credit",amount=Decimal("10000"),financial_cost=Decimal("120"),operational_impact=2,
                                effective_date=start,repayment_date=start+timedelta(days=60),exclusive_group="linea-demo"),
                LiquidityAction("credito-20000","draw_credit",amount=Decimal("20000"),financial_cost=Decimal("220"),operational_impact=3,
                                effective_date=start,repayment_date=start+timedelta(days=60),exclusive_group="linea-demo"),
                LiquidityAction("diferir-renta","defer_payable",target_event_id="renta-pendiente",days=7,
                                financial_cost=Decimal("70"),operational_impact=2),
                LiquidityAction("acelerar-cobro","accelerate_receivable",target_event_id="factura-principal",days=7,
                                financial_cost=Decimal("180"),operational_impact=1)]
    scenario=[LiquidityAction("retraso-7","delay_receivable",target_event_id="factura-principal",days=7)]
    return to_jsonable({"history":[asdict(r) for r in history],"config":asdict(config),"opening_balance":"17000",
                        "liquidity_threshold":"8000","planned_events":[asdict(invoice),asdict(rent_invoice)],
                        "candidate_actions":[asdict(a) for a in candidates],"scenario_actions":[asdict(a) for a in scenario],
                        "delay_history":{"client_ids":["cliente principal","cliente secundario"],"observations":paired}})


def main() -> int:
    parser=argparse.ArgumentParser(description="Motor estadístico de caja. No necesita SQL Server ni claves de IA.")
    source=parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--demo",action="store_true",help="Ejecutar datos sintéticos incluidos.")
    source.add_argument("--input",type=Path,help="Archivo JSON con historia, agenda y configuración.")
    source.add_argument("--legacy-demo",action="store_true",help="Ejecutar el ejemplo original determinista.")
    parser.add_argument("--days",type=int,help="Horizonte en días, incluyendo la fecha inicial.")
    parser.add_argument("--simulations",type=int,help="Número de trayectorias Monte Carlo.")
    parser.add_argument("--model",choices=(*MODEL_NAMES,"auto"))
    parser.add_argument("--output",type=Path,default=Path("resultado_prediccion.json"))
    parser.add_argument("--write-example",type=Path,help="Guardar también la entrada sintética antes de calcular.")
    args=parser.parse_args()
    try:
        if args.legacy_demo: demo(); return 0
        if args.demo:
            payload=synthetic_example_payload()
        else:
            if args.input.stat().st_size>5_000_000: raise InputError("JSON mayor de 5 MB.")
            def invalid_constant(x: str) -> Any:
                raise InputError(f"Constante JSON no válida: {x}")
            payload=json.loads(args.input.read_text(encoding="utf-8-sig"),parse_constant=invalid_constant)
        for attr in ("days","simulations","model"):
            value=getattr(args,attr)
            if value is not None: payload["config"][attr]=value
        if args.write_example:
            args.write_example.write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
        result=analyze_payload(payload)
        args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
        risk=result["scenario"]["risk"]; optimization=result["optimization"]
        print(f"Motor {VERSION}")
        print(f"Horizonte: {result['horizon']['startDate']} a {result['horizon']['endDate']}")
        print(f"Modelo de fondo: {result['backgroundModel']['selected']}")
        print(f"Recurrencias detectadas: {len(result['recurrences'])}")
        print(f"P(saldo final < umbral): {risk['pdTerminal']['probability']:.2%}")
        print(f"P(algun cierre diario < umbral): {risk['pdAnyDay']['probability']:.2%}")
        print(f"Optimizacion: {optimization['reason']}")
        print(f"Acciones validadas: {', '.join(optimization['selectedActions']) or '(ninguna)'}")
        print(f"JSON guardado: {args.output.resolve()}")
        print("Probabilidades bajo supuestos del modelo. No garantizan resultados reales.")
        return 0
    except (InputError,ValueError,OSError,np.linalg.LinAlgError) as exc:
        print(f"ERROR: {exc}",file=__import__('sys').stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
