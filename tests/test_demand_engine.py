from datetime import date
from decimal import Decimal

from app.engine.demand_engine import estimate_shortage_adjusted_demand


def test_demand_without_shortages_keeps_user_baseline():
    result=estimate_shortage_adjusted_demand('2.5',[],as_of=date(2026,9,12),working_weekdays=range(5))
    assert result['baseDailyDemand']=='2.500'
    assert result['recommendedDailyDemand']=='2.500'
    assert result['shortageReports']==0


def test_recent_shortage_increases_estimate_and_fluctuation_range():
    result=estimate_shortage_adjusted_demand('1',[{'occurred_on':'2026-09-11','missing_units':'8'}],
        as_of=date(2026,9,12),working_weekdays=range(5))
    assert Decimal(result['estimatedDailyDemand'])>Decimal('1')
    assert Decimal(result['recommendedDailyDemand'])>=Decimal(result['estimatedDailyDemand'])
    assert Decimal(result['fluctuationHigh'])>Decimal(result['fluctuationLow'])
    assert result['shortageReports']==1


def test_non_working_report_does_not_create_expected_sales():
    result=estimate_shortage_adjusted_demand('1',[{'occurred_on':'2026-09-12','missing_units':'20'}],
        as_of=date(2026,9,12),working_weekdays=range(5))
    assert result['recommendedDailyDemand']=='1.000'
