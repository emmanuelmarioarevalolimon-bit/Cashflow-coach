from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ApiModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", allow_inf_nan=False)


class EventInput(ApiModel):
    id: str = Field(min_length=1, max_length=80)
    counterparty: str = Field(min_length=1, max_length=120)
    amount: Decimal = Field(gt=0, le=Decimal("1000000000000"))
    direction: Literal["inflow", "outflow"]
    expected_date: date = Field(alias="expectedDate")
    category: str = Field(min_length=1, max_length=80)
    confidence: Decimal = Field(default=Decimal("1"), ge=0, le=1)
    recurring: bool = False


class DelayReceivableScenario(ApiModel):
    enabled: bool = True
    event_id: str = Field(alias="eventId", min_length=1)
    delay_days: int = Field(alias="delayDays", ge=0, le=365)


class AccelerateReceivableSettings(ApiModel):
    enabled: bool = True
    event_id: str = Field(alias="eventId", min_length=1)
    days_earlier: int = Field(alias="daysEarlier", ge=0, le=365)
    discount: Decimal = Field(default=Decimal("0"), ge=0)
    operational_impact: int = Field(alias="operationalImpact", default=1, ge=0, le=10)


class DeferPayableSettings(ApiModel):
    enabled: bool = True
    event_id: str = Field(alias="eventId", min_length=1)
    delay_days: int = Field(alias="delayDays", ge=0, le=365)
    financial_cost: Decimal = Field(alias="financialCost", default=Decimal("0"), ge=0)
    operational_impact: int = Field(alias="operationalImpact", default=2, ge=0, le=10)


class CreditLineSettings(ApiModel):
    enabled: bool = True
    amount: Decimal = Field(gt=0, le=Decimal("1000000000000"))
    days_from_start: int = Field(alias="daysFromStart", ge=0, le=365)
    financial_cost: Decimal = Field(alias="financialCost", ge=0)
    operational_impact: int = Field(alias="operationalImpact", default=3, ge=0, le=10)


class InterventionSettings(ApiModel):
    accelerate_receivable: AccelerateReceivableSettings | None = Field(
        default=None, alias="accelerateReceivable"
    )
    defer_payable: DeferPayableSettings | None = Field(
        default=None, alias="deferPayable"
    )
    credit_line: CreditLineSettings | None = Field(default=None, alias="creditLine")


class AnalyzeRequest(ApiModel):
    opening_balance: Decimal = Field(alias="openingBalance", ge=0)
    liquidity_threshold: Decimal = Field(alias="liquidityThreshold", ge=0)
    start_date: date = Field(alias="startDate")
    days: int = Field(default=30, ge=1, le=365)
    events: list[EventInput] = Field(min_length=1, max_length=500)
    stress_scenario: DelayReceivableScenario | None = Field(
        default=None, alias="stressScenario"
    )
    interventions: InterventionSettings
    max_actions: int = Field(alias="maxActions", default=2, ge=1, le=3)

    @model_validator(mode="after")
    def validate_event_ids(self) -> "AnalyzeRequest":
        event_ids = [event.id for event in self.events]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("Cada evento debe tener un ID único")
        if any(event.id == "generated-credit-draw" for event in self.events):
            raise ValueError("El ID generated-credit-draw está reservado para el motor")
        if self.stress_scenario and self.stress_scenario.enabled:
            selected = next((event for event in self.events if event.id == self.stress_scenario.event_id), None)
            if not selected or selected.direction != "inflow":
                raise ValueError("El cobro seleccionado para el retraso debe existir y ser una entrada")
        return self


class AssistantHistoryMessage(ApiModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class AssistantRequest(ApiModel):
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    message: str = Field(min_length=1, max_length=2000)
    analysis_input: AnalyzeRequest = Field(alias="analysisInput")
    analysis_result: dict[str, Any] = Field(default_factory=dict, alias="analysisResult")
    history: list[AssistantHistoryMessage] = Field(default_factory=list, max_length=12)
