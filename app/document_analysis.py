"""Herramientas cuantitativas auditables para propuestas extraídas de documentos.

Gemini identifica hechos y explica resultados; este módulo hace toda la aritmética.
No convierte métricas contables en caja ni estima probabilidades de cobro ocultas.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import math
import random
from typing import Any

from .document_models import Candidate, MetricCandidate


CENT = Decimal("0.01")
ZERO = Decimal("0")


def _money(value: Decimal) -> str:
    return format(value.quantize(CENT, rounding=ROUND_HALF_UP), "f")


def _quantile(values: list[Decimal], probability: Decimal) -> Decimal:
    """Cuantil lineal determinista, suficiente para estadística descriptiva de UI."""
    if not values:
        return ZERO
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = probability * Decimal(len(ordered) - 1)
    lower = int(position)
    fraction = position - Decimal(lower)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _quality(candidates: list[Candidate], metrics: list[MetricCandidate], signals: list[dict[str, Any]], unit_count: int) -> dict[str, Any]:
    kinds = {item.kind for item in candidates}
    directions = {item.direction for item in candidates}
    score = (10 if unit_count else 0) + (20 if candidates else 0)
    score += 10 if len(candidates) >= 5 else 0
    score += 10 if len(candidates) >= 12 else 0
    score += 10 if len(directions) == 2 else 0
    score += 10 if "actual" in kinds else 0
    score += 10 if kinds.intersection({"receivable", "payable"}) else 0
    score += 10 if metrics else 0
    score += 10 if signals else 0
    score = min(score, 100)
    gaps: list[str] = []
    if not candidates:
        gaps.append("No hay movimientos de caja explícitos con fecha, monto, moneda y dirección.")
    if "actual" not in kinds:
        gaps.append("No hay movimientos realizados para describir el comportamiento histórico.")
    if not kinds.intersection({"receivable", "payable"}):
        gaps.append("No hay cobros o pagos pendientes explícitos para proyectar compromisos.")
    if not metrics:
        gaps.append("No hay indicadores numéricos comparables con periodo y unidad explícitos.")
    label = "alta" if score >= 75 else "media" if score >= 45 else "limitada"
    return {
        "score": score,
        "label": label,
        "meaning": "Puntaje heurístico de suficiencia documental; no es confianza de Gemini ni probabilidad financiera.",
        "gaps": gaps,
    }


def _descriptive(candidates: list[Candidate]) -> dict[str, Any]:
    amounts = [item.amount for item in candidates]
    count = len(amounts)
    total = sum(amounts, ZERO)
    mean = total / Decimal(count) if count else ZERO
    variance = sum(((value - mean) ** 2 for value in amounts), ZERO) / Decimal(count) if count else ZERO
    by_counterparty: dict[str, Decimal] = defaultdict(Decimal)
    by_category: dict[str, Decimal] = defaultdict(Decimal)
    for item in candidates:
        by_counterparty[item.counterparty] += item.amount
        by_category[item.category] += item.amount
    shares = [(amount / total) if total else ZERO for amount in by_counterparty.values()]
    largest_share = max(shares, default=ZERO)
    hhi = sum((share * share for share in shares), ZERO)
    top_counterparties = sorted(by_counterparty.items(), key=lambda pair: (-pair[1], pair[0].lower()))[:5]
    categories = sorted(by_category.items(), key=lambda pair: (-pair[1], pair[0].lower()))[:8]
    return {
        "count": count,
        "minimum": _money(min(amounts, default=ZERO)),
        "maximum": _money(max(amounts, default=ZERO)),
        "mean": _money(mean),
        "median": _money(_quantile(amounts, Decimal("0.5"))),
        "standardDeviation": _money(variance.sqrt() if variance >= 0 else ZERO),
        "p25": _money(_quantile(amounts, Decimal("0.25"))),
        "p75": _money(_quantile(amounts, Decimal("0.75"))),
        "largestCounterpartyShare": float(largest_share),
        "counterpartyHHI": float(hhi),
        "concentrationNotice": "Participación sobre montos absolutos extraídos; no mide por sí sola dependencia económica.",
        "topCounterparties": [{"name": name, "amount": _money(amount), "share": float(amount / total) if total else 0.0} for name, amount in top_counterparties],
        "categories": [{"name": name, "amount": _money(amount)} for name, amount in categories],
    }


def _probability(item: Candidate, default_collection_probability: Decimal | None) -> Decimal:
    if item.kind == "receivable" and default_collection_probability is not None:
        return default_collection_probability
    return item.confidence


def _timeline(candidates: list[Candidate], default_collection_probability: Decimal | None) -> list[dict[str, Any]]:
    days: dict[date, dict[str, Decimal]] = defaultdict(lambda: {"actual": ZERO, "expected": ZERO, "nominal": ZERO})
    for item in candidates:
        sign = Decimal(1) if item.direction == "inflow" else Decimal(-1)
        if item.kind == "actual":
            days[item.date]["actual"] += sign * item.amount
        else:
            # Las salidas se consideran completas; la confianza solo pondera cobros.
            expected = item.amount * _probability(item, default_collection_probability) if item.direction == "inflow" else item.amount
            days[item.date]["expected"] += sign * expected
            days[item.date]["nominal"] += sign * item.amount
    cumulative_actual = ZERO
    cumulative_expected = ZERO
    cumulative_nominal = ZERO
    result = []
    for day in sorted(days):
        values = days[day]
        cumulative_actual += values["actual"]
        cumulative_expected += values["actual"] + values["expected"]
        cumulative_nominal += values["actual"] + values["nominal"]
        result.append({
            "date": day.isoformat(),
            "actualNet": _money(values["actual"]),
            "pendingExpectedNet": _money(values["expected"]),
            "pendingNominalNet": _money(values["nominal"]),
            "cumulativeActual": _money(cumulative_actual),
            "cumulativeExpected": _money(cumulative_expected),
            "cumulativeNominal": _money(cumulative_nominal),
        })
    return result


def _metric_analysis(metrics: list[MetricCandidate]) -> dict[str, Any]:
    groups: dict[tuple[str, str], list[MetricCandidate]] = defaultdict(list)
    for item in metrics:
        groups[(" ".join(item.name.lower().split()), item.unit.lower())].append(item)
    series=[]
    for items in groups.values():
        ordered=sorted(items,key=lambda item:(item.period_end,item.period_start))
        latest=ordered[-1];change=None
        # Solo comparar periodos separados para no mezclar ventanas que se traslapan.
        previous=next((item for item in reversed(ordered[:-1]) if item.period_end < latest.period_start),None)
        if previous is not None:
            absolute=latest.value-previous.value
            percent=(absolute/abs(previous.value)*Decimal(100)) if previous.value else None
            change={'previousValue':format(previous.value,'f'),'previousPeriod':f'{previous.period_start} / {previous.period_end}',
                    'absolute':format(absolute,'f'),'percent':float(percent) if percent is not None else None}
        series.append({'name':latest.name,'unit':latest.unit,'latestValue':format(latest.value,'f'),
                       'latestPeriod':f'{latest.period_start} / {latest.period_end}','observations':len(ordered),
                       'latestChange':change})
    series.sort(key=lambda item:item['name'].lower())
    return {'series':series,
            'notice':'Las variaciones usan únicamente periodos no superpuestos con el mismo nombre y unidad; no convierten indicadores en caja.'}


def _monte_carlo(candidates: list[Candidate], opening_balance: Decimal | None, threshold: Decimal | None, simulations: int,
                 default_collection_probability: Decimal | None) -> dict[str, Any]:
    if opening_balance is None or threshold is None:
        return {
            "available": False,
            "reason": "Indica saldo inicial y umbral para estimar riesgo de liquidez. Sin ellos no existe una base válida para la probabilidad.",
        }
    if not candidates:
        return {"available": False, "reason": "No hay movimientos fechados que simular."}
    ordered_dates = sorted({item.date for item in candidates})
    by_date: dict[date, list[Candidate]] = defaultdict(list)
    for item in candidates:
        by_date[item.date].append(item)
    seed_material = json.dumps([
        [item.kind, item.date.isoformat(), str(item.amount), item.direction, str(_probability(item, default_collection_probability))]
        for item in candidates
    ], sort_keys=True).encode()
    rng = random.Random(int.from_bytes(hashlib.sha256(seed_material).digest()[:8], "big"))
    finals: list[Decimal] = []
    minima: list[Decimal] = []
    terminal_breaches = 0
    any_breaches = 0
    for _ in range(simulations):
        balance = opening_balance
        minimum = opening_balance
        for day in ordered_dates:
            for item in by_date[day]:
                if item.kind == "receivable" and rng.random() >= float(_probability(item, default_collection_probability)):
                    continue
                sign = Decimal(1) if item.direction == "inflow" else Decimal(-1)
                balance += sign * item.amount
            minimum = min(minimum, balance)
        finals.append(balance)
        minima.append(minimum)
        terminal_breaches += int(balance < threshold)
        any_breaches += int(minimum < threshold)

    def probability_summary(breaches: int) -> dict[str, Any]:
        n = simulations
        probability = breaches / n
        standard_error = math.sqrt(probability * (1 - probability) / n)
        z = 1.959963984540054
        denominator = 1 + z * z / n
        center = (probability + z * z / (2 * n)) / denominator
        margin = z * math.sqrt(probability * (1 - probability) / n + z * z / (4 * n * n)) / denominator
        return {
            "probability": probability,
            "monteCarloSE": standard_error,
            "wilsonLower": max(0.0, center - margin),
            "wilsonUpper": min(1.0, center + margin),
            "breaches": breaches,
        }

    return {
        "available": True,
        "simulations": simulations,
        "openingBalance": _money(opening_balance),
        "liquidityThreshold": _money(threshold),
        "defaultCollectionProbability": float(default_collection_probability) if default_collection_probability is not None else None,
        "probabilitySource": "Supuesto común indicado por el analista." if default_collection_probability is not None else "Confianza individual de cada cobro; por defecto es 1 y no fue estimada por Gemini.",
        "terminalBelowThreshold": probability_summary(terminal_breaches),
        "anyDateBelowThreshold": probability_summary(any_breaches),
        "finalBalance": {key: _money(_quantile(finals, probability)) for key, probability in (("p05", Decimal(".05")), ("median", Decimal(".5")), ("p95", Decimal(".95")))},
        "minimumBalance": {key: _money(_quantile(minima, probability)) for key, probability in (("p05", Decimal(".05")), ("median", Decimal(".5")), ("p95", Decimal(".95")))},
        "assumptions": [
            "El saldo inicial se interpreta antes del primer movimiento fechado del archivo.",
            "Cada cobro pendiente ocurre con la confianza indicada; los pagos pendientes y movimientos realizados ocurren completos.",
            "Si se indicó una probabilidad común de cobro, esta sustituye la confianza individual solo dentro de esta simulación.",
            "Los cobros se simulan de forma independiente y en su fecha declarada; no se modelan retrasos ni correlaciones.",
            "Los intervalos Wilson describen error Monte Carlo, no incertidumbre total del negocio.",
        ],
    }


def analyze_financial_document(
    candidates: list[Candidate],
    metrics: list[MetricCandidate],
    signals: list[dict[str, Any]],
    unit_count: int,
    opening_balance: Decimal | None = None,
    threshold: Decimal | None = None,
    simulations: int = 2000,
    default_collection_probability: Decimal | None = None,
) -> dict[str, Any]:
    if default_collection_probability is not None and not ZERO <= default_collection_probability <= Decimal(1):
        raise ValueError("La probabilidad común de cobro debe estar entre 0 y 1.")
    if not 100 <= simulations <= 10000:
        raise ValueError("Las simulaciones deben estar entre 100 y 10 000.")
    actual_inflows = sum((item.amount for item in candidates if item.kind == "actual" and item.direction == "inflow"), ZERO)
    actual_outflows = sum((item.amount for item in candidates if item.kind == "actual" and item.direction == "outflow"), ZERO)
    receivables = sum((item.amount for item in candidates if item.kind == "receivable"), ZERO)
    expected_receivables = sum((item.amount * _probability(item, default_collection_probability) for item in candidates if item.kind == "receivable"), ZERO)
    payables = sum((item.amount for item in candidates if item.kind == "payable"), ZERO)
    actual_net = actual_inflows - actual_outflows
    weighted_realization=float(expected_receivables/receivables) if receivables else None
    scenarios = [
        {"name": "Tensión", "receivableRealization": 0.0, "netCashChange": _money(actual_net - payables)},
        {"name": "Ponderado", "receivableRealization": weighted_realization, "netCashChange": _money(actual_net + expected_receivables - payables)},
        {"name": "Nominal", "receivableRealization": 1.0, "netCashChange": _money(actual_net + receivables - payables)},
    ]
    data_mode = "cashflow" if candidates and not metrics and not signals else "mixed" if candidates else "contextual"
    return {
        "status": "proposal_not_confirmed",
        "dataMode": data_mode,
        "quality": _quality(candidates, metrics, signals, unit_count),
        "cashSummary": {
            "actualInflows": _money(actual_inflows),
            "actualOutflows": _money(actual_outflows),
            "actualNet": _money(actual_net),
            "receivables": _money(receivables),
            "expectedReceivables": _money(expected_receivables),
            "payables": _money(payables),
            "nominalPendingNet": _money(receivables - payables),
            "grossExposure": _money(receivables + payables),
        },
        "descriptive": _descriptive(candidates),
        "metricAnalysis": _metric_analysis(metrics),
        "timeline": _timeline(candidates, default_collection_probability),
        "scenarios": scenarios,
        "probability": _monte_carlo(candidates, opening_balance, threshold, simulations, default_collection_probability),
        "counts": {"cashMovements": len(candidates), "metrics": len(metrics), "signals": len(signals), "sourceUnits": unit_count},
        "notices": [
            "Cálculos sobre la propuesta extraída, antes de confirmarla; corrige los datos y vuelve a analizar si hay errores.",
            "El cambio acumulado inicia en cero y no representa el saldo bancario.",
            "Ventas, utilidad, EBITDA, activos y otros indicadores no se convierten ni se suman como caja.",
            "Los escenarios son sensibilidades condicionadas a los datos y supuestos declarados, no garantías.",
        ],
        "toolTrace": ["document_evidence_extraction", "cash_flow_classification", "descriptive_statistics", "counterparty_concentration", "scenario_sensitivity"] + (["metric_period_comparison"] if metrics else []) + (["monte_carlo_liquidity", "wilson_interval"] if opening_balance is not None and threshold is not None and candidates else []),
    }
