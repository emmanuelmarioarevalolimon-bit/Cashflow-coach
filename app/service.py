from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Iterable

from .engine.budget_engine import (
    CashFlowEvent,
    ForecastResult,
    Intervention,
    OptimizationResult,
    apply_interventions,
    delay_receivable,
    forecast_cash_flow,
    money,
    optimize_interventions,
    result_to_dict,
)
from .models import AnalyzeRequest, EventInput


def event_from_input(item: EventInput) -> CashFlowEvent:
    return CashFlowEvent(
        id=item.id,
        counterparty=item.counterparty,
        amount=money(item.amount),
        direction=item.direction,
        expected_date=item.expected_date,
        category=item.category,
        confidence=item.confidence,
        recurring=item.recurring,
    )


def _find_event(events: Iterable[CashFlowEvent], event_id: str) -> CashFlowEvent:
    try:
        return next(event for event in events if event.id == event_id)
    except StopIteration as exc:
        raise ValueError(f"No existe el evento {event_id!r}") from exc


def build_candidates(
    request: AnalyzeRequest,
    stressed_events: tuple[CashFlowEvent, ...],
) -> tuple[Intervention, ...]:
    candidates: list[Intervention] = []
    settings = request.interventions

    accelerate = settings.accelerate_receivable
    if accelerate and accelerate.enabled:
        source = _find_event(stressed_events, accelerate.event_id)
        if source.direction != "inflow":
            raise ValueError("El evento que se acelerará debe ser una entrada")
        if accelerate.discount >= source.amount:
            raise ValueError("El descuento debe ser menor al monto de la cuenta por cobrar")
        new_date = max(
            request.start_date,
            source.expected_date - timedelta(days=accelerate.days_earlier),
        )
        replacement = replace(
            source,
            expected_date=new_date,
            amount=money(source.amount - accelerate.discount),
        )
        candidates.append(
            Intervention(
                id="accelerate-receivable",
                type="accelerate_receivable",
                description=(
                    f"Acelerar el cobro de {source.counterparty} al {new_date.isoformat()} "
                    f"con un descuento de ${money(accelerate.discount):,.2f}"
                ),
                financial_cost=money(accelerate.discount),
                operational_impact=accelerate.operational_impact,
                replace_events=(replacement,),
            )
        )

    defer = settings.defer_payable
    if defer and defer.enabled:
        source = _find_event(stressed_events, defer.event_id)
        if source.direction != "outflow":
            raise ValueError("El evento que se diferirá debe ser una salida")
        new_date = source.expected_date + timedelta(days=defer.delay_days)
        replacement = replace(source, expected_date=new_date)
        candidates.append(
            Intervention(
                id="defer-payable",
                type="defer_payable",
                description=(
                    f"Diferir {defer.delay_days} días el pago a {source.counterparty} "
                    f"hasta {new_date.isoformat()}"
                ),
                financial_cost=money(defer.financial_cost),
                operational_impact=defer.operational_impact,
                replace_events=(replacement,),
            )
        )

    credit = settings.credit_line
    if credit and credit.enabled:
        draw_date = request.start_date + timedelta(days=credit.days_from_start)
        candidates.append(
            Intervention(
                id="credit-line",
                type="draw_credit",
                description=(
                    f"Usar ${money(credit.amount):,.2f} de la línea de crédito "
                    f"el {draw_date.isoformat()}"
                ),
                financial_cost=money(credit.financial_cost),
                operational_impact=credit.operational_impact,
                add_events=(
                    CashFlowEvent(
                        id="generated-credit-draw",
                        counterparty="Línea de crédito de Capital One",
                        amount=money(credit.amount),
                        direction="inflow",
                        expected_date=draw_date,
                        category="credito",
                    ),
                ),
            )
        )

    return tuple(candidates)


def _forecast_summary(result: ForecastResult) -> dict[str, Any]:
    return {
        "openingBalance": str(result.opening_balance),
        "minimumExpectedBalance": str(result.minimum_expected_balance),
        "minimumConservativeBalance": str(result.minimum_conservative_balance),
        "riskDate": result.risk_date.isoformat() if result.risk_date else None,
        "projectedShortfall": str(result.projected_shortfall),
        "liquidityThreshold": str(result.liquidity_threshold),
    }


def _evaluate_alternatives(
    request: AnalyzeRequest,
    stressed_events: tuple[CashFlowEvent, ...],
    candidates: tuple[Intervention, ...],
) -> list[dict[str, Any]]:
    alternatives: list[dict[str, Any]] = []
    for candidate in candidates:
        adjusted_events = apply_interventions(stressed_events, (candidate,))
        forecast = forecast_cash_flow(
            request.opening_balance,
            adjusted_events,
            request.start_date,
            request.days,
            request.liquidity_threshold,
        )
        alternatives.append(
            {
                "id": candidate.id,
                "type": candidate.type,
                "description": candidate.description,
                "financialCost": str(candidate.financial_cost),
                "operationalImpact": candidate.operational_impact,
                "feasibleAlone": forecast.projected_shortfall == 0,
                "minimumConservativeBalance": str(
                    forecast.minimum_conservative_balance
                ),
                "remainingShortfall": str(forecast.projected_shortfall),
            }
        )
    return alternatives


def _optimization_to_dict(
    optimized: OptimizationResult,
    alternatives: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "feasible": optimized.feasible,
        "selectedInterventions": [
            {
                "id": item.id,
                "type": item.type,
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
        "alternatives": alternatives,
    }


def _build_explanation(
    baseline: ForecastResult,
    stressed: ForecastResult,
    optimized: OptimizationResult,
) -> dict[str, str]:
    if stressed.projected_shortfall == 0:
        return {
            "status": "safe",
            "title": "La liquidez se mantiene dentro del límite",
            "summary": (
                f"El saldo conservador mínimo es ${stressed.minimum_conservative_balance:,.2f}, "
                f"por encima del umbral de ${stressed.liquidity_threshold:,.2f}."
            ),
            "action": "No se requiere una intervención para este escenario.",
            "comparison": (
                f"El escenario base tenía un mínimo conservador de "
                f"${baseline.minimum_conservative_balance:,.2f}."
            ),
        }

    if optimized.feasible and optimized.repaired_forecast:
        descriptions = "; ".join(item.description for item in optimized.selected)
        return {
            "status": "repaired",
            "title": "Riesgo detectado y plan de corrección encontrado",
            "summary": (
                f"El escenario genera un faltante máximo de ${stressed.projected_shortfall:,.2f} "
                f"y cruza el umbral por primera vez el {stressed.risk_date.isoformat()}."
            ),
            "action": (
                f"Recomendación: {descriptions}. Con ello, el saldo conservador mínimo "
                f"sube a ${optimized.repaired_forecast.minimum_conservative_balance:,.2f}."
            ),
            "comparison": (
                f"Costo financiero total estimado: ${optimized.total_financial_cost:,.2f}; "
                f"impacto operativo: {optimized.total_operational_impact}."
            ),
        }

    return {
        "status": "unresolved",
        "title": "Las intervenciones configuradas no resuelven el riesgo",
        "summary": (
            f"El escenario presenta un faltante de ${stressed.projected_shortfall:,.2f} "
            f"y la primera fecha de riesgo es {stressed.risk_date.isoformat()}."
        ),
        "action": (
            "Aumenta el monto de crédito, agrega otra intervención o permite más acciones "
            "simultáneas."
        ),
        "comparison": (
            f"Saldo conservador mínimo del escenario: "
            f"${stressed.minimum_conservative_balance:,.2f}."
        ),
    }


def analyze(request: AnalyzeRequest) -> dict[str, Any]:
    events = tuple(event_from_input(item) for item in request.events)
    baseline = forecast_cash_flow(
        request.opening_balance,
        events,
        request.start_date,
        request.days,
        request.liquidity_threshold,
    )

    stressed_events = events
    scenario = request.stress_scenario
    if scenario and scenario.enabled and scenario.delay_days > 0:
        stressed_events = delay_receivable(
            events,
            scenario.event_id,
            scenario.delay_days,
        )

    stressed = forecast_cash_flow(
        request.opening_balance,
        stressed_events,
        request.start_date,
        request.days,
        request.liquidity_threshold,
    )
    candidates = build_candidates(request, stressed_events)
    optimized = optimize_interventions(
        request.opening_balance,
        stressed_events,
        candidates,
        request.start_date,
        request.days,
        request.liquidity_threshold,
        max_actions=request.max_actions,
    )
    alternatives = _evaluate_alternatives(request, stressed_events, candidates)

    return {
        "baseline": result_to_dict(baseline),
        "stressed": result_to_dict(stressed),
        "optimization": _optimization_to_dict(optimized, alternatives),
        "explanation": _build_explanation(baseline, stressed, optimized),
        "summary": {
            "baseline": _forecast_summary(baseline),
            "stressed": _forecast_summary(stressed),
            "repaired": (
                _forecast_summary(optimized.repaired_forecast)
                if optimized.repaired_forecast
                else None
            ),
        },
    }


def demo_payload(today: date) -> dict[str, Any]:
    def iso(offset: int) -> str:
        return (today + timedelta(days=offset)).isoformat()

    return {
        "openingBalance": "50000.00",
        "liquidityThreshold": "20000.00",
        "startDate": today.isoformat(),
        "days": 30,
        "events": [
            {
                "id": "receivable-main",
                "counterparty": "Cliente principal",
                "amount": "18000.00",
                "direction": "inflow",
                "expectedDate": iso(7),
                "category": "cuentas_por_cobrar",
                "confidence": "0.90",
                "recurring": False,
            },
            {
                "id": "receivable-secondary",
                "counterparty": "Cliente secundario",
                "amount": "9000.00",
                "direction": "inflow",
                "expectedDate": iso(16),
                "category": "cuentas_por_cobrar",
                "confidence": "0.85",
                "recurring": False,
            },
            {
                "id": "supplier-critical",
                "counterparty": "Proveedor de acero",
                "amount": "12500.00",
                "direction": "outflow",
                "expectedDate": iso(5),
                "category": "proveedor",
                "confidence": "1.00",
                "recurring": False,
            },
            {
                "id": "nomina",
                "counterparty": "Nómina",
                "amount": "26000.00",
                "direction": "outflow",
                "expectedDate": iso(12),
                "category": "nomina",
                "confidence": "1.00",
                "recurring": True,
            },
            {
                "id": "supplier-flexible",
                "counterparty": "Proveedor de empaques",
                "amount": "7000.00",
                "direction": "outflow",
                "expectedDate": iso(11),
                "category": "proveedor",
                "confidence": "1.00",
                "recurring": False,
            },
            {
                "id": "renta",
                "counterparty": "Renta de almacén",
                "amount": "4500.00",
                "direction": "outflow",
                "expectedDate": iso(21),
                "category": "renta",
                "confidence": "1.00",
                "recurring": True,
            },
        ],
        "stressScenario": {
            "enabled": True,
            "eventId": "receivable-main",
            "delayDays": 0,
        },
        "interventions": {
            "accelerateReceivable": {
                "enabled": True,
                "eventId": "receivable-secondary",
                "daysEarlier": 6,
                "discount": "180.00",
                "operationalImpact": 1,
            },
            "deferPayable": {
                "enabled": True,
                "eventId": "supplier-flexible",
                "delayDays": 6,
                "financialCost": "70.00",
                "operationalImpact": 2,
            },
            "creditLine": {
                "enabled": True,
                "amount": "9000.00",
                "daysFromStart": 10,
                "financialCost": "120.00",
                "operationalImpact": 3,
            },
        },
        "maxActions": 2,
    }
