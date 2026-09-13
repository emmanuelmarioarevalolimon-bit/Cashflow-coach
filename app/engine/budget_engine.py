"""Motor determinista de presupuesto y liquidez para COMPRIA.

Incluye:
- proyeccion diaria de saldo;
- escenario de retraso de una cuenta por cobrar;
- deteccion de la primera fecha de riesgo;
- evaluacion de intervenciones individuales y de pares;
- seleccion lexicografica por costo financiero e impacto operativo.

No requiere dependencias externas. Los montos usan Decimal para evitar errores
binarios de punto flotante. El ejemplo al final puede ejecutarse directamente.
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


if __name__ == "__main__":
    demo()
