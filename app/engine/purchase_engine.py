"""Motor determinista de compra de mercancía conectado a una curva de caja.

El módulo no consulta bases de datos ni modelos de lenguaje. Recibe inventario
revisado por el usuario y la banda conservadora de una predicción guardada.
La recomendación respeta presupuesto, múltiplos de compra y el excedente de
caja disponible sobre el umbral en todos los días posteriores al pago.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, localcontext
from hashlib import sha256
from math import floor
from typing import Any, Iterable, Mapping, Sequence


CENT = Decimal("0.01")
# Debe coincidir con el máximo por evento aceptado por predictive_engine.
MAX_PAYMENT = Decimal("1000000000")


class PurchaseInputError(ValueError):
    """Entrada de inventario o proyección inválida."""


def _decimal(value: Any, name: str, *, minimum: Decimal = Decimal("0")) -> Decimal:
    try:
        number = Decimal(str(value))
    except Exception as exc:
        raise PurchaseInputError(f"{name} debe ser numérico.") from exc
    if not number.is_finite() or number < minimum or number > Decimal("1000000000000"):
        raise PurchaseInputError(f"{name} está fuera del intervalo permitido.")
    return number


def _money(value: Decimal) -> str:
    return str(_money_value(value))


def _money_value(value: Decimal) -> Decimal:
    """Convierte un importe calculado a la misma precisión que tendrá el pago."""
    # Los límites válidos de demanda × horizonte × costo pueden superar la
    # precisión decimal global aunque el pago finalmente quede limitado.
    with localcontext() as context:
        context.prec = 50
        return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _units(value: Decimal) -> str:
    rounded = value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    return format(rounded.normalize(), "f")


def _day(value: Any, name: str) -> date:
    try:
        return value if isinstance(value, date) else date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise PurchaseInputError(f"{name} debe ser una fecha ISO válida.") from exc


def _integer(value: Any, name: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise PurchaseInputError(f"{name} debe estar entre {low} y {high}.")
    return value


@dataclass(frozen=True)
class MerchandiseItem:
    id: str
    name: str
    supplier: str
    stock_on_hand: Decimal
    average_daily_demand: Decimal
    unit_cost: Decimal
    lead_time_days: int
    incoming_units: Decimal = Decimal("0")
    safety_stock_units: Decimal = Decimal("0")
    minimum_order_units: Decimal = Decimal("0")
    order_multiple: Decimal = Decimal("1")
    unit_price: Decimal | None = None
    payment_terms_days: int = 0

    def __post_init__(self) -> None:
        for field in ("id", "name", "supplier"):
            value = str(getattr(self, field)).strip()
            if not value:
                raise PurchaseInputError(f"Cada artículo requiere {field}.")
            object.__setattr__(self, field, value)
        if len(self.id) > 80 or len(self.name) > 160 or len(self.supplier) > 160:
            raise PurchaseInputError("El identificador, artículo o proveedor es demasiado largo.")
        for field in (
            "stock_on_hand", "average_daily_demand", "unit_cost", "incoming_units",
            "safety_stock_units", "minimum_order_units", "order_multiple",
        ):
            object.__setattr__(self, field, _decimal(getattr(self, field), field))
        if self.unit_cost <= 0 or self.order_multiple <= 0:
            raise PurchaseInputError("unit_cost y order_multiple deben ser mayores que cero.")
        if self.unit_cost * self.order_multiple < CENT:
            raise PurchaseInputError(
                "El costo de un múltiplo de compra debe ser de al menos 0.01."
            )
        if self.unit_price is not None:
            object.__setattr__(self, "unit_price", _decimal(self.unit_price, "unit_price"))
        object.__setattr__(self, "lead_time_days", _integer(self.lead_time_days, "lead_time_days", 0, 365))
        object.__setattr__(self, "payment_terms_days", _integer(self.payment_terms_days, "payment_terms_days", 0, 365))


def _ceil_multiple(value: Decimal, multiple: Decimal) -> Decimal:
    if value <= 0:
        return Decimal("0")
    return (value / multiple).to_integral_value(rounding=ROUND_CEILING) * multiple


def _floor_multiple(value: Decimal, multiple: Decimal) -> Decimal:
    if value <= 0:
        return Decimal("0")
    return (value / multiple).to_integral_value(rounding=ROUND_FLOOR) * multiple


def _projection_rows(projection: Sequence[Mapping[str, Any]], reserve: Decimal) -> list[dict[str, Any]]:
    if not projection:
        raise PurchaseInputError("La predicción no contiene una curva diaria para evaluar compras.")
    if len(projection) > 365:
        raise PurchaseInputError("La curva de compra admite como máximo 365 días.")
    rows: list[dict[str, Any]] = []
    seen: set[date] = set()
    for point in projection:
        day = _day(point.get("date"), "projection.date")
        if day in seen:
            raise PurchaseInputError("La predicción contiene fechas duplicadas.")
        seen.add(day)
        low = _decimal(point.get("qLow"), "projection.qLow", minimum=Decimal("-1000000000000"))
        threshold = _decimal(point.get("liquidityThreshold"), "projection.liquidityThreshold")
        # Conservar valores negativos permite informar un faltante que ya existe
        # en la predicción base; la asignación de compras lo limita a cero después.
        rows.append({"date": day, "headroom": low - threshold - reserve})
    rows.sort(key=lambda row: row["date"])
    if any(current["date"] != previous["date"] + timedelta(days=1)
           for previous, current in zip(rows, rows[1:])):
        raise PurchaseInputError("La predicción debe contener una curva diaria sin fechas faltantes.")
    return rows


def _event_id(item_id: str) -> str:
    digest = sha256(item_id.encode("utf-8")).hexdigest()[:14]
    return f"compra-mercancia-{digest}"


def analyze_purchases(
    items: Iterable[MerchandiseItem],
    projection: Sequence[Mapping[str, Any]],
    *,
    analysis_date: date,
    currency: str,
    coverage_days: int,
    available_budget: Any,
    reserve_buffer: Any = 0,
    working_weekdays: Iterable[int] = range(7),
    non_working_dates: Iterable[date] = (),
) -> dict[str, Any]:
    """Prioriza reposición y asigna solo la caja conservadora disponible.

    La restricción de caja es acumulativa: un pago aprobado debe caber en el
    excedente qLow - umbral - reserva de cada cierre posterior dentro del
    horizonte. Esto conecta inventario y cash flow sin afirmar una garantía.
    """
    item_list = list(items)
    if not 1 <= len(item_list) <= 30:
        raise PurchaseInputError("Incluye entre 1 y 30 artículos por análisis.")
    if len({item.id for item in item_list}) != len(item_list):
        raise PurchaseInputError("Los identificadores de artículo deben ser únicos.")
    if (not isinstance(currency, str) or len(currency) != 3 or
            not currency.isascii() or not currency.isalpha()):
        raise PurchaseInputError("currency debe ser un código ISO ASCII de tres letras.")
    currency = currency.upper()
    coverage_days = _integer(coverage_days, "coverage_days", 1, 365)
    budget = _decimal(available_budget, "available_budget")
    reserve = _decimal(reserve_buffer, "reserve_buffer")
    analysis_date = _day(analysis_date, "analysis_date")
    weekdays = frozenset(working_weekdays)
    if not weekdays or any(type(day) is not int or day < 0 or day > 6 for day in weekdays):
        raise PurchaseInputError("working_weekdays debe incluir días únicos entre 0 y 6.")
    closures = frozenset(_day(day, "non_working_dates") for day in non_working_dates)
    is_working = lambda day: day.weekday() in weekdays and day not in closures
    def next_working(day: date) -> date:
        for offset in range(367):
            candidate = day + timedelta(days=offset)
            if is_working(candidate):
                return candidate
        raise PurchaseInputError("No se encontró un día laborable dentro de un año.")
    def working_count(start: date, calendar_days: int) -> int:
        return sum(1 for offset in range(calendar_days) if is_working(start + timedelta(days=offset)))
    def days_until_working_demand(start: date, workdays_needed: int) -> int | None:
        if workdays_needed <= 0:
            return 0
        seen = 0
        for offset in range(731):
            if is_working(start + timedelta(days=offset)):
                seen += 1
                if seen >= workdays_needed:
                    return offset
        return None
    cash_rows = _projection_rows(projection, reserve)
    horizon_start, horizon_end = cash_rows[0]["date"], cash_rows[-1]["date"]
    allocated_by_day = {row["date"]: Decimal("0") for row in cash_rows}

    candidates: list[dict[str, Any]] = []
    for item in item_list:
        order_date = next_working(max(analysis_date, horizon_start))
        delivery_date = next_working(order_date + timedelta(days=item.lead_time_days))
        lead_calendar_days = (delivery_date - order_date).days
        lead_working_days = working_count(order_date, lead_calendar_days)
        coverage_working_days = working_count(delivery_date, coverage_days)
        position = item.stock_on_hand + item.incoming_units
        lead_demand = item.average_daily_demand * lead_working_days
        reorder_point = lead_demand + item.safety_stock_units
        target = item.average_daily_demand * (lead_working_days + coverage_working_days) + item.safety_stock_units
        raw_needed = max(Decimal("0"), target - position)
        required = _ceil_multiple(raw_needed, item.order_multiple)
        if required and required < item.minimum_order_units:
            required = _ceil_multiple(item.minimum_order_units, item.order_multiple)
        days_to_stockout = None
        if item.average_daily_demand > 0:
            covered_workdays = max(0, floor(item.stock_on_hand / item.average_daily_demand))
            days_to_stockout = days_until_working_demand(order_date, covered_workdays + 1)
        critical = days_to_stockout is not None and days_to_stockout <= lead_calendar_days
        shortage_ratio = Decimal("0") if reorder_point <= 0 else max(Decimal("0"), reorder_point - position) / reorder_point
        gross_margin = Decimal("0") if item.unit_price is None else max(Decimal("0"), item.unit_price - item.unit_cost)
        margin_rate = Decimal("0") if not item.unit_price else gross_margin / item.unit_price
        priority = (Decimal("1000") if critical else Decimal("0")) + shortage_ratio * 100 + margin_rate * 10
        candidates.append({
            "item": item,
            "position": position,
            "reorderPoint": reorder_point,
            "target": target,
            "required": required,
            "requiredCost": required * item.unit_cost,
            "daysToStockout": days_to_stockout,
            "critical": critical,
            "priority": priority,
            "orderDate": order_date,
            "deliveryDate": delivery_date,
            "paymentDate": order_date + timedelta(days=item.payment_terms_days),
            "grossMarginPerUnit": gross_margin,
            "leadWorkingDays": lead_working_days,
            "coverageWorkingDays": coverage_working_days,
        })

    candidates.sort(key=lambda row: (-row["priority"], row["daysToStockout"] is None,
                                     row["daysToStockout"] if row["daysToStockout"] is not None else 10**9,
                                     row["item"].id))
    remaining_budget = budget
    decisions: list[dict[str, Any]] = []
    planned_events: list[dict[str, Any]] = []
    calendar_events: list[dict[str, Any]] = []

    for row in candidates:
        item: MerchandiseItem = row["item"]
        payment_date: date = row["paymentDate"]
        required: Decimal = row["required"]
        applicable = [cash for cash in cash_rows if cash["date"] >= payment_date]
        cash_capacity = min((cash["headroom"] - allocated_by_day[cash["date"]] for cash in applicable), default=Decimal("0"))
        spend_capacity = max(Decimal("0"), min(remaining_budget, cash_capacity, MAX_PAYMENT))
        affordable_units = _floor_multiple(spend_capacity / item.unit_cost, item.order_multiple)
        # El motor de caja recibe importes a centavos. Evita aprobar con el costo
        # sin redondear una compra cuyo pago redondeado ya rebasa la holgura.
        while affordable_units > 0 and _money_value(affordable_units * item.unit_cost) > spend_capacity:
            affordable_units -= item.order_multiple
        recommended = min(required, affordable_units)
        if recommended and recommended < item.minimum_order_units:
            recommended = Decimal("0")
        recommended_cost = _money_value(recommended * item.unit_cost)
        if required == 0:
            status = "no_order"
            reason = "La posición de inventario cubre el punto objetivo."
        elif payment_date > horizon_end:
            status = "extend_horizon"
            reason = "El pago queda fuera de la predicción; amplía el horizonte antes de comprometer la compra."
            recommended = recommended_cost = Decimal("0")
        elif recommended == required:
            status = "recommended"
            reason = "Cubre el objetivo y cabe en el presupuesto conservador."
        elif recommended > 0:
            status = "partial"
            reason = "Compra parcial: el presupuesto o la caja conservadora limitan la cobertura."
        else:
            status = "deferred_cash"
            reason = "No cabe sin consumir la reserva o cruzar el umbral conservador."

        if recommended_cost > 0:
            remaining_budget -= recommended_cost
            for cash in applicable:
                allocated_by_day[cash["date"]] += recommended_cost
            event_id = _event_id(item.id)
            planned_events.append({
                "id": event_id,
                "counterparty": item.supplier,
                "amount": _money(recommended_cost),
                "direction": "outflow",
                "expected_date": payment_date.isoformat(),
                "category": "compra_mercancia",
                "currency": currency,
                "collection_probability": 1.0,
                "delay_samples": [0],
                "source": "compra_mercancia",
                "additional_to_history": True,
            })
            calendar_events.extend([
                {"id": event_id + ":order", "date": row["orderDate"].isoformat(), "type": "purchase_order",
                 "title": f"Ordenar {item.name}", "itemId": item.id, "units": _units(recommended), "amount": None},
                {"id": event_id + ":delivery", "date": row["deliveryDate"].isoformat(), "type": "purchase_delivery",
                 "title": f"Recibir {item.name}", "itemId": item.id, "units": _units(recommended), "amount": None},
                {"id": event_id + ":payment", "date": payment_date.isoformat(), "type": "purchase_payment",
                 "title": f"Pagar {item.supplier}", "itemId": item.id, "units": _units(recommended),
                 "amount": _money(recommended_cost), "direction": "outflow"},
            ])
        potential_margin = row["grossMarginPerUnit"] * recommended
        decisions.append({
            "id": item.id,
            "name": item.name,
            "supplier": item.supplier,
            "status": status,
            "reason": reason,
            "critical": row["critical"],
            "daysToStockout": row["daysToStockout"],
            "leadWorkingDays": row["leadWorkingDays"],
            "coverageWorkingDays": row["coverageWorkingDays"],
            "stockPosition": _units(row["position"]),
            "reorderPoint": _units(row["reorderPoint"]),
            "targetStock": _units(row["target"]),
            "requiredUnits": _units(required),
            "recommendedUnits": _units(recommended),
            "requiredCost": _money(row["requiredCost"]),
            "recommendedCost": _money(recommended_cost),
            "unfundedCost": _money(max(Decimal("0"), row["requiredCost"] - recommended_cost)),
            "cashCapacityAtPayment": _money(max(Decimal("0"), cash_capacity)),
            "potentialGrossMargin": _money(potential_margin),
            "orderDate": row["orderDate"].isoformat(),
            "deliveryDate": row["deliveryDate"].isoformat(),
            "paymentDate": payment_date.isoformat(),
        })

    input_order = {item.id: index for index, item in enumerate(item_list)}
    decisions.sort(key=lambda row: input_order[row["id"]])
    requested_cost = sum((Decimal(row["requiredCost"]) for row in decisions), Decimal("0"))
    recommended_cost = sum((Decimal(row["recommendedCost"]) for row in decisions), Decimal("0"))
    potential_margin = sum((Decimal(row["potentialGrossMargin"]) for row in decisions), Decimal("0"))
    headroom_values = [row["headroom"] for row in cash_rows]
    limiting_row = min(cash_rows, key=lambda row: row["headroom"])
    return {
        "version": "purchase-1.0",
        "currency": currency,
        "analysisDate": analysis_date.isoformat(),
        "horizon": {"startDate": horizon_start.isoformat(), "endDate": horizon_end.isoformat()},
        "policy": {
            "coverageDays": coverage_days,
            "availableBudget": _money(budget),
            "reserveBuffer": _money(reserve),
            "workingWeekdays": sorted(weekdays),
            "nonWorkingDates": sorted(day.isoformat() for day in closures),
            "demandRule": "La demanda diaria se aplica solo en días laborables; cierres y descansos tienen venta esperada cero.",
            "maximumPaymentAmount": _money(MAX_PAYMENT),
            "cashRule": "Cada pago debe caber en qLow - umbral - reserva durante todos los cierres posteriores.",
        },
        "cashEnvelope": {
            "minimumHeadroom": _money(min(headroom_values)),
            "maximumHeadroom": _money(max(headroom_values)),
            "limitingDate": limiting_row["date"].isoformat(),
            "unusedBudget": _money(remaining_budget),
        },
        "summary": {
            "itemCount": len(item_list),
            "criticalItems": sum(1 for row in decisions if row["critical"]),
            "orderNowItems": sum(1 for row in decisions if Decimal(row["recommendedUnits"]) > 0),
            "requestedCost": _money(requested_cost),
            "recommendedCost": _money(recommended_cost),
            "unfundedCost": _money(max(Decimal("0"), requested_cost - recommended_cost)),
            "potentialGrossMargin": _money(potential_margin),
        },
        "items": decisions,
        "plannedEvents": planned_events,
        "calendarEvents": calendar_events,
        "warnings": [
            "La demanda, el inventario, los precios y los plazos son supuestos revisados por el usuario; no se infieren del saldo bancario.",
            "Las compras se agregan como egresos incrementales. Si una compra ya está implícita en una recurrencia histórica, reconcilia o sustituye esa recurrencia para evitar contabilizarla dos veces.",
            "El cuantil conservador depende del modelo de caja y no garantiza disponibilidad futura.",
            "El margen potencial no incluye mermas, impuestos, descuentos, costos de almacenamiento ni demanda no realizada.",
        ],
    }
