from datetime import date
from decimal import Decimal
from typing import Literal
from pydantic import Field, model_validator
from .models import ApiModel, AnalyzeRequest

class Candidate(ApiModel):
    kind: Literal['actual','receivable','payable']
    date: date
    counterparty: str = Field(min_length=1,max_length=120)
    amount: Decimal = Field(gt=0,le=Decimal('1000000000000'),decimal_places=2)
    direction: Literal['inflow','outflow']
    currency: str = Field(pattern=r'^[A-Z]{3}$')
    category: str = Field(min_length=1,max_length=80)
    reference: str = Field(default='',max_length=120)
    confidence: Decimal = Field(default=Decimal('1'),ge=0,le=1,decimal_places=6)
    source: str = Field(min_length=1,max_length=160)
    quote: str = Field(min_length=1,max_length=1500)
    @model_validator(mode='after')
    def matching(self):
        if self.kind=='receivable' and self.direction!='inflow': raise ValueError('Una cuenta por cobrar debe ser entrada.')
        if self.kind=='payable' and self.direction!='outflow': raise ValueError('Una cuenta por pagar debe ser salida.')
        if self.kind=='actual' and self.confidence != 1: raise ValueError('Un movimiento realizado no lleva incertidumbre de cobro.')
        return self

class MetricCandidate(ApiModel):
    name: str = Field(min_length=1,max_length=120)
    period_start: date
    period_end: date
    value: Decimal = Field(ge=Decimal('-1000000000000'),le=Decimal('1000000000000'),decimal_places=4)
    unit: str = Field(min_length=1,max_length=40)
    source: str = Field(min_length=1,max_length=160)
    quote: str = Field(min_length=1,max_length=1500)
    @model_validator(mode='after')
    def period(self):
        if self.period_end < self.period_start: raise ValueError('El periodo final precede al inicial.')
        return self

class DocumentSignal(ApiModel):
    type: Literal['risk','opportunity','obligation','operational_driver','accounting_policy','assumption','anomaly','context']
    title: str = Field(min_length=1,max_length=160)
    detail: str = Field(min_length=1,max_length=1200)
    cash_flow_relevance: Literal['direct','indirect','contextual','unknown']
    direction: Literal['inflow','outflow','mixed','none']
    horizon: Literal['immediate','short_term','long_term','unspecified']
    source: str = Field(min_length=1,max_length=160)
    quote: str = Field(min_length=1,max_length=1500)

class Approval(ApiModel):
    revision: int = Field(ge=1)
    candidates: list[Candidate] = Field(default_factory=list,max_length=2000)
    metrics: list[MetricCandidate] = Field(default_factory=list,max_length=300)
    confirm: Literal[True]
    allowPossibleDuplicates: bool = False

class Consent(ApiModel):
    consentToGoogle: Literal[True]
    revision: int = Field(ge=1)
    include_external_context: bool = Field(default=False,alias='includeExternalContext')
    opening_balance: Decimal | None = Field(default=None,alias='openingBalance',ge=0,le=Decimal('1000000000000'),decimal_places=2)
    liquidity_threshold: Decimal | None = Field(default=None,alias='liquidityThreshold',ge=0,le=Decimal('1000000000000'),decimal_places=2)
    default_collection_probability: Decimal | None = Field(default=None,alias='defaultCollectionProbability',ge=0,le=1,decimal_places=6)
    simulations: int = Field(default=2000,ge=100,le=10000)
    @model_validator(mode='after')
    def probability_inputs(self):
        if (self.opening_balance is None) != (self.liquidity_threshold is None):
            raise ValueError('Saldo inicial y umbral deben indicarse juntos.')
        return self

class PlanSave(ApiModel):
    name: str = Field(min_length=1,max_length=160)
    analysisInput: AnalyzeRequest

class LedgerPlan(ApiModel):
    name: str = Field(default='Plan desde documentos',max_length=160)
    startDate: date
    openingBalance: Decimal = Field(ge=0,le=Decimal('1000000000000'),decimal_places=2)
    liquidityThreshold: Decimal = Field(ge=0,le=Decimal('1000000000000'),decimal_places=2)
    days: int = Field(default=30,ge=1,le=365)

class ReportRequest(ApiModel):
    consentToGoogle: Literal[True]
    documentIds: list[str] = Field(default_factory=list,max_length=10)
    planId: str | None = None
