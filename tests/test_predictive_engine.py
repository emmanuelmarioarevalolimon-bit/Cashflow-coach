"""Pruebas sin red, claves, SQL Server ni cuentas de usuario."""
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
import ast
import json
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import pytest
from app.engine import predictive_engine as m
from app.engine import budget_engine as original

START=date(2026,9,12)


def cfg(**kw):
    base=dict(start_date=START,history_start=START-timedelta(days=90),history_end=START-timedelta(days=1),
              history_complete=True,days=15,simulations=300,model="seasonal_mean",bootstrap_block=1,seed=17)
    base.update(kw)
    return m.ForecastConfig(**base)


def tx(i,offset,amount=100,direction="inflow",party="Cliente",category="cobros",irregular=False):
    return m.HistoricalTransaction(str(i),party,Decimal(str(amount)),direction,START+timedelta(days=offset),category,irregular)


def event(id="bill",amount=100,direction="outflow",offset=0,**kw):
    return m.PlannedEvent(id,kw.pop("counterparty","Empresa nueva"),Decimal(str(amount)),direction,START+timedelta(days=offset),**kw)


def prepared(**kw):
    return m.prepare_forecast([],cfg(**kw))


def credit(id="c",amount=200,cost=0,repay=60,**kw):
    return m.LiquidityAction(id,"draw_credit",amount=Decimal(str(amount)),financial_cost=Decimal(str(cost)),
                              effective_date=START,repayment_date=START+timedelta(days=repay),**kw)


def weekly(period=7):
    return [tx(f"r{i}",-85+i*period,100) for i in range(12 if period==7 else 6)]


def test_original_public_functions_ast_unchanged():
    path=Path(m.__file__).parent
    old=ast.parse((path/"budget_engine.py").read_text())
    new=ast.parse((path/"predictive_engine.py").read_text())
    new_defs={n.name:ast.dump(n) for n in new.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
    for n in old.body:
        if isinstance(n,(ast.FunctionDef,ast.ClassDef)):
            assert ast.dump(n)==new_defs[n.name],n.name


def test_legacy_outputs_unchanged():
    args=("a","Cliente",Decimal("1000"),"inflow",START,"sales",Decimal("0.8"))
    old=original.forecast_cash_flow(100,[original.CashFlowEvent(*args)],START,5,500)
    new=m.forecast_cash_flow(100,[m.CashFlowEvent(*args)],START,5,500)
    assert original.result_to_dict(old)==m.result_to_dict(new)


@pytest.mark.parametrize("kw",[{"days":0},{"days":True},{"simulations":50},{"simulations":50000,"days":365},
                               {"history_complete":False},{"alpha":2},{"confidence":1},{"model":"magic"},
                               {"chance_method":"certain"},{"recurrence_weights":(1,1,1)},
                               {"history_end":START},{"bootstrap_block":0}])
def test_config_validation(kw):
    with pytest.raises(m.InputError): cfg(**kw)


def test_probability_strings_are_normalized():
    assert cfg(alpha="0.05").alpha==0.05


@pytest.mark.parametrize("value",["NaN","Infinity",-1,"not-money"])
def test_money_validation(value):
    with pytest.raises(m.InputError):
        m.HistoricalTransaction("invalid","Cliente",value,"inflow",START-timedelta(days=1))


def test_no_future_in_training():
    with pytest.raises(m.InputError): m.prepare_forecast([tx("a",0)],cfg())


def test_no_mixed_currency():
    with pytest.raises(m.InputError): m.prepare_forecast([replace(tx("a",-1),currency="USD")],cfg())


def test_no_duplicate_history():
    a=tx("a",-1)
    with pytest.raises(m.InputError): m.prepare_forecast([a,a],cfg())


def test_past_pending_not_silently_discarded():
    with pytest.raises(m.InputError): m.prepare_forecast([],cfg(),[event(offset=-1)])


def test_outflow_must_be_full_obligation():
    with pytest.raises(m.InputError): event(collection_probability=0.5)
    with pytest.raises(m.InputError): event(delay_samples=(7,))


def test_conflicting_coverage_flags():
    with pytest.raises(m.InputError): event(history_series_key="x",additional_to_history=True)


def test_levenshtein_and_composite():
    assert m.levenshtein_distance("kitten","sitting")==3
    a,b=tx("1",-30),tx("2",-60)
    d=m.composite_distance(a,b)
    assert d==dict(counterparty=0.0,amount=0.0,time=0.0,total=0.0)
    b=replace(b,amount=Decimal(200))
    assert m.composite_distance(a,b)["amount"]==0.5


def test_acf_matches_document_with_adjusted_flag():
    x=np.array([1,2,0,5,4,0,2.],float); z=x-x.mean()
    out=m.autocorrelation(x,3,adjusted=True)
    assert out[2]==pytest.approx(np.mean(z[:-2]*z[2:])/np.mean(z*z))
    assert m.autocorrelation(x,3)[2]==pytest.approx(np.dot(z[:-2],z[2:])/np.dot(z,z))


def test_constant_acf_does_not_invent_periods():
    assert np.array_equal(m.autocorrelation([3]*20,5),[1,0,0,0,0,0])


@pytest.mark.parametrize("period",[7,14])
def test_detect_true_period_not_harmonic(period):
    patterns,_=m.detect_recurrences(weekly(period),cfg())
    assert len(patterns)==1
    assert patterns[0].period==period and patterns[0].stable


def test_recurrence_requires_three_dates():
    patterns,rejected=m.detect_recurrences([tx("a",-14),tx("b",-7)],cfg())
    assert not patterns and rejected


def test_category_separates_equal_amounts():
    a=weekly(); b=[replace(t,id="b"+t.id,direction="outflow",category="nomina") for t in a]
    patterns,_=m.detect_recurrences(a+b,cfg())
    assert len(patterns)==2


def test_stopped_recurrence_not_automatically_extended():
    history=[tx("a",-80),tx("b",-73),tx("c",-66),tx("d",-59)]
    p=m.prepare_forecast(history,cfg())
    assert all(not pattern.stable for pattern in p.patterns)
    assert not any(e.source=="recurrencia" for e in p.events)


def test_duplicate_projection_requires_explicit_link():
    hist=weekly()
    p=m.prepare_forecast(hist,cfg())
    generated=p.events[0]
    manual=m.PlannedEvent("known","Cliente",100,"inflow",generated.expected_date,"cobros")
    with pytest.raises(m.InputError): m.prepare_forecast(hist,cfg(),[manual])
    manual=replace(manual,history_series_key=hist[0].key)
    replaced=m.prepare_forecast(hist,cfg(),[manual])
    assert len(replaced.events)==len(p.events)
    assert "known" in [e.id for e in replaced.events]
    assert generated.id not in [e.id for e in replaced.events]


def test_additional_event_must_be_declared():
    hist=weekly()
    future=event(id="extra",direction="inflow",counterparty="Cliente",category="cobros",additional_to_history=True)
    base=m.prepare_forecast(hist,cfg()); p=m.prepare_forecast(hist,cfg(),[future])
    assert len(p.events)==len(base.events)+1


def test_two_invoices_cannot_replace_same_occurrence():
    hist=weekly(); generated=m.prepare_forecast(hist,cfg()).events[0]
    a=m.PlannedEvent("a","Cliente",100,"inflow",generated.expected_date,"cobros",history_series_key=hist[0].key)
    with pytest.raises(m.InputError): m.prepare_forecast(hist,cfg(),[a,replace(a,id="b")])


def test_series_schedule_replaces_background():
    hist=[tx(f"x{i}",-90+i,100+i) for i in range(90)]
    a=m.PlannedEvent("a","Cliente",1000,"inflow",START,"cobros",history_series_key=hist[0].key)
    p=m.prepare_forecast(hist,cfg(),[a])
    assert np.all(p.background_history==0)
    assert len(p.events)==1


def test_seasonal_mean_short_history_is_explicit():
    fit=m.fit_temporal_model([1,2,3],5,method="seasonal_mean",period=7)
    assert np.all(fit.forecast==2) and fit.diagnostics["warnings"]


def test_short_stl_is_rejected():
    with pytest.raises(m.InputError): m.fit_temporal_model([1,2,3],5,method="stl",period=7)


@pytest.mark.parametrize("method",["stl","holt_winters","sarima","seasonal_mean"])
def test_all_time_models_execute_real_fits(method):
    rng=np.random.default_rng(41); t=np.arange(120)
    x=20+0.05*t+3*np.sin(t*2*np.pi/7)+rng.normal(0,0.35,120)
    fit=m.fit_temporal_model(x,14,method=method,period=7)
    assert fit.forecast.shape==(14,)
    assert np.isfinite(fit.forecast).all() and len(fit.residuals)>10
    if method=="sarima":
        assert fit.analytic_flow_interval.shape==(14,2)
        assert fit.diagnostics["converged"] and len(fit.diagnostics["search"])>=1


def test_auto_uses_temporal_holdout(monkeypatch):
    seen=[]; real=m._fit_one
    def tracked(x,h,*args,**kw):
        seen.append(len(x)); return real(x,h,*args,**kw)
    monkeypatch.setattr(m,"_fit_one",tracked)
    x=np.sin(np.arange(90)/3)+np.arange(90)*0.02
    f=m.fit_temporal_model(x,7,period=7,auto_methods=("seasonal_mean","stl"))
    assert seen[:-1]==[83,83] and seen[-1]==90
    assert f.diagnostics["autoSelection"]["trainDays"]==83


def test_backtest_cutoffs_are_ordered():
    x=20+np.sin(np.arange(90)*2*np.pi/7)
    result=m.backtest_temporal(x,horizon=7,folds=3,method="seasonal_mean")
    assert [f["trainingDays"] for f in result["folds"]]==[69,76,83]
    assert result["meanMAE"]<1e-10


def test_invalid_backtest_is_rejected():
    with pytest.raises(m.InputError): m.backtest_temporal([1,2,3])
    with pytest.raises(m.InputError): m.backtest_temporal([float("nan")]*100)


def test_bootstrap_reproducible_and_blocks():
    residual=[-2,-1,0,1,2]
    a=m.bootstrap_residuals(residual,100,9,np.random.default_rng(17),block_length=3)
    b=m.bootstrap_residuals(residual,100,9,np.random.default_rng(17),block_length=3)
    assert np.array_equal(a,b)
    for k in (0,3,6): assert np.all(np.isin(a[:,k+1]-a[:,k],[1,-4]))


def test_copula_empirical_marginals_and_dependence():
    rng=np.random.default_rng(32); z=rng.integers(0,20,50)
    cop=m.GaussianDelayCopula.fit(["a","b"],np.column_stack([z,z+rng.integers(0,2,50)]))
    data=cop.sample(4000,np.random.default_rng(4))
    assert np.corrcoef(data.T)[0,1]>0.8
    assert set(data[:,0]).issubset(set(z))
    assert np.array_equal(data,cop.sample(4000,np.random.default_rng(4)))


def test_copula_needs_real_alignment_not_missing_pairs():
    with pytest.raises(m.InputError): m.GaussianDelayCopula.fit(["a","b"],[[1,1],[2,2]])
    with pytest.raises(m.InputError): m.GaussianDelayCopula.fit(["a","b"],[[1,np.nan],[np.nan,2]]*12)


def test_constant_client_copula_is_supported():
    cop=m.GaussianDelayCopula.fit(["a","b"],[[0,i%4] for i in range(20)])
    samples=cop.sample(100,np.random.default_rng(1))
    assert np.all(samples[:,0]==0)


def test_accounting_identity_and_deterministic_no_noise():
    p=prepared(days=3); e=(event(amount=100),event(id="in",direction="inflow",amount=200,offset=2))
    paths=m.simulate_cash_flow(p,1000,e)
    assert paths.dtype==np.int64
    assert np.all(paths==[90000,90000,110000])


def test_bernoulli_receipts_are_not_fractional_cash():
    p=prepared(days=1,simulations=1000)
    e=event(direction="inflow",amount=100,collection_probability=0.5)
    paths=m.simulate_cash_flow(p,0,[e])
    assert set(paths.ravel())=={0,10000}
    assert 0.42<np.mean(paths[:,0]>0)<0.58


def test_delays_past_horizon_do_not_enter_cash():
    p=prepared(days=3)
    e=event(direction="inflow",delay_samples=(7,))
    assert np.all(m.simulate_cash_flow(p,0,[e])==0)


def test_reordering_events_does_not_change_randomness():
    p=prepared(days=5)
    a=event("a",100,"inflow",0,collection_probability=0.5,delay_samples=(0,1,2))
    b=event("b",100,"inflow",0,collection_probability=0.6,delay_samples=(0,1))
    assert np.array_equal(m.simulate_cash_flow(p,0,[a,b]),m.simulate_cash_flow(p,0,[b,a]))


def test_copula_is_used_by_simulator():
    cop=m.GaussianDelayCopula.fit(["a","b"],[[2,2]]*20)
    p=replace(prepared(days=4),copula=cop)
    e=event("a",100,"inflow",client_id="a")
    paths=m.simulate_cash_flow(p,0,[e])
    assert np.all(paths==[0,0,10000,10000])


def test_poisson_is_not_double_counted_in_background():
    hist=[tx(f"x{i}",-90+i*10,100,"outflow",irregular=True) for i in range(9)]
    p=m.prepare_forecast(hist,cfg(days=30,simulations=5000))
    assert np.all(p.background_history==0)
    assert p.irregular[0].rate_per_day==pytest.approx(0.1)
    paths=m.simulate_cash_flow(p,0)
    assert np.mean(paths[:,-1])/100==pytest.approx(-300,abs=15)


def test_terminal_safety_does_not_hide_midperiod_crisis():
    c=cfg(days=3); p=np.tile([10000,-1000,20000],(300,1))
    r=m.risk_metrics(p,100,0,c)
    assert r["pdTerminal"]["probability"]==0
    assert r["pdAnyDay"]["probability"]==1
    assert float(r["workingCapitalBuffer"]["additionalCashToThresholdQuantile"])==10


def test_var_es_conventions_are_both_explicit():
    c=cfg(days=1); paths=np.full((300,1),8000)
    r=m.risk_metrics(paths,100,50,c)
    assert r["documentConvention"]["VaR"]=="-80.00"
    assert r["documentConvention"]["ES"]=="-80.00"
    assert r["changeFromOpening"]["VaR"]=="20.00"


def test_buffer_cogs_and_runway_zero_burn():
    c=cfg(days=3,daily_cogs=20,coverage_days=10)
    r=m.risk_metrics(np.full((300,3),10000),100,0,c)
    assert r["workingCapitalBuffer"]["cogsTimesCoverage"]=="200.00"
    assert r["runway"]["days"] is None


def test_wilson_zero_events_not_zero_upper_risk():
    p=m._probability_summary(np.zeros(100,bool))
    assert p["probability"]==0 and p["wilsonUpper"]>0


def test_action_fees_and_principal_actually_debit():
    c=cfg(days=5); e=m.apply_liquidity_actions([], [credit(amount=200,cost=10,repay=2)],c)
    p=prepared(days=5); paths=m.simulate_cash_flow(p,0,e)
    assert np.all(paths==[19000,19000,-1000,-1000,-1000])


def test_credit_requires_repayment_date():
    with pytest.raises(m.InputError): m.LiquidityAction("x","draw_credit",amount=100,effective_date=START)


def test_conflicting_actions_are_rejected():
    e=event(id="x",direction="inflow",offset=3)
    a=m.LiquidityAction("a","delay_receivable",target_event_id="x",days=1)
    b=m.LiquidityAction("b","accelerate_receivable",target_event_id="x",days=1)
    with pytest.raises(m.InputError): m.apply_liquidity_actions([e],[a,b],cfg())


def test_advance_expense_moves_purchase_or_payment_earlier():
    original=event(id="purchase",direction="outflow",offset=7)
    action=m.LiquidityAction("buy-earlier","advance_expense",target_event_id="purchase",days=3)
    moved=m.apply_liquidity_actions([original],[action],cfg())
    assert moved[0].expected_date==START+timedelta(days=4)


def test_incompatible_groups_are_rejected():
    with pytest.raises(m.InputError): m.apply_liquidity_actions([],[credit(id="a",exclusive_group="one"),credit(id="b",exclusive_group="one")],cfg())


def test_credit_limit_options_not_combined_in_same_group():
    p=replace(prepared(days=3),events=(event(amount=250),))
    actions=[credit("a",amount=100,exclusive_group="line"),credit("b",amount=200,exclusive_group="line")]
    result=m.optimize_chance_constrained(p,0,0,actions)
    assert not result["feasible"] and any(s["reason"]=="mismo grupo excluyente" for s in result["skipped"])


def test_optimizer_terminal_vs_any_day():
    e=(event(id="out",amount=100),event(id="in",amount=200,direction="inflow",offset=2))
    c=cfg(days=3); p=replace(m.prepare_forecast([],c),events=e)
    a=credit(amount=150,cost=1)
    anyday=m.optimize_chance_constrained(p,0,0,[a])
    terminal=m.optimize_chance_constrained(replace(p,config=replace(c,constraint="terminal")),0,0,[a])
    assert anyday["feasible"] and anyday["selectedActions"]==["c"]
    assert terminal["feasible"] and terminal["selectedActions"]==[]
    assert anyday["outsideHorizonObligations"][0]["id"]=="repayment:c"


def test_optimizer_does_not_hide_cost_shortfall():
    p=replace(prepared(days=2),events=(event(amount=100),))
    r=m.optimize_chance_constrained(p,0,0,[credit(amount=100,cost=1)])
    assert not r["feasible"]


def test_candidate_explosion_rejected():
    p=prepared(max_candidates=2)
    with pytest.raises(m.InputError): m.optimize_chance_constrained(p,100,0,[credit("a"),credit("b")])


def test_independent_validation_can_reject_selection(monkeypatch):
    p=prepared(days=2)
    monkeypatch.setattr(m,"simulate_cash_flow",lambda *a,**k: np.full((300,2),-100))
    r=m.optimize_chance_constrained(p,100,0,[])
    assert r["selectionCheck"]["passes"]
    assert not r["validationCheck"]["passes"] and not r["feasible"]


def test_original_arrays_are_not_mutated_by_actions():
    e=event(id="x",direction="inflow",offset=2)
    a=m.LiquidityAction("a","delay_receivable",target_event_id="x",days=5)
    moved=m.apply_liquidity_actions([e],[a],cfg())
    assert e.expected_date==START+timedelta(days=2)
    assert moved[0].expected_date==START+timedelta(days=7)


def test_json_contract_rejects_unknown_keys():
    with pytest.raises(m.InputError): m.analyze_payload({"execute_sql":"DELETE ..."})
    with pytest.raises(m.InputError): m.analyze_payload([])


def test_end_to_end_reproducible_strict_json():
    c=cfg(days=5,simulations=150)
    a=m.analyze_advanced(weekly(),c,1000,0)
    b=m.analyze_advanced(weekly(),c,1000,0)
    assert a==b
    json.dumps(a,allow_nan=False)
    assert a["horizon"]["endDate"]=="2026-09-16"
    assert a["baseline"]["band"]["pointwiseMass"]==pytest.approx(0.9)


def test_amount_empirical_marginal_keeps_cash_sign():
    p=prepared(days=1,simulations=2000)
    a=event("a",100,"inflow",amount_samples=(80,100,140))
    result=m.simulate_cash_flow(p,0,[a])[:,0]
    assert set(result)=={8000,10000,14000}


def test_shift_uses_same_event_random_draws():
    p=prepared(days=5)
    a=event("a",100,"inflow",collection_probability=0.7,amount_samples=(80,100,120))
    original_paths=m.simulate_cash_flow(p,0,[a])
    changed=m.apply_liquidity_actions([a],[m.LiquidityAction("late","delay_receivable",target_event_id="a",days=2)],p.config)
    shifted=m.simulate_cash_flow(p,0,changed)
    assert np.all(shifted[:,:2]==0)
    assert np.array_equal(shifted[:,2:],original_paths[:,:3])


def test_cash_risk_improves_when_adding_opening_balance():
    p=prepared(days=4)
    e=event("risky",100,"inflow",delay_samples=(0,2,9),collection_probability=0.7)
    a=m.simulate_cash_flow(p,0,[e]); b=m.simulate_cash_flow(p,200,[e])
    assert np.array_equal(a+20000,b)
    risk_a=m.risk_metrics(a,0,80,p.config); risk_b=m.risk_metrics(b,200,80,p.config)
    assert risk_b["pdAnyDay"]["probability"]<=risk_a["pdAnyDay"]["probability"]


def test_outside_horizon_principal_not_hidden_as_erased():
    p=prepared(days=5)
    scenario=m.apply_liquidity_actions([], [credit(amount=100,repay=40)], p.config)
    debt=[e for e in scenario if e.id.startswith("repayment:")]
    assert len(debt)==1 and debt[0].expected_date==START+timedelta(days=40)


def test_fuzzy_names_detect_potential_double_counting():
    hist=weekly(); p=m.prepare_forecast(hist,cfg())
    # Variación del nombre suficientemente pequeña para solaparse con el patrón.
    e=m.PlannedEvent("new","Clientee",100,"inflow",p.events[0].expected_date,"cobros")
    with pytest.raises(m.InputError): m.prepare_forecast(hist,cfg(),[e])


def test_invalid_copula_observations_rejected():
    with pytest.raises(m.InputError): m.GaussianDelayCopula.fit(["a"],[[1.5]]*20)
    with pytest.raises(m.InputError): m.GaussianDelayCopula.fit(["a"],[[-1]]*20)


def test_empirical_constraint_option_matches_source():
    c=cfg(days=1,alpha=0.0,chance_method="empirical")
    p=prepared(days=1,alpha=0.0,chance_method="empirical")
    result=m.optimize_chance_constrained(p,10,0,[])
    assert result["feasible"] and result["validationCheck"]["criterionValue"]==0


def test_fractional_percentiles_are_not_confused_with_simultaneous_band():
    p=m.analyze_advanced([],cfg(days=2),100,0)
    band=p["baseline"]["band"]
    assert band["quantiles"][0]==pytest.approx(0.05)
    assert "simultánea" in band["note"]


def test_end_to_end_payload_with_poisson_copula_and_scenario():
    payload=m.synthetic_example_payload()
    payload["config"]["simulations"]=300
    result=m.analyze_payload(payload)
    assert len(result["recurrences"])==4
    assert result["copula"]["clients"]==["cliente principal","cliente secundario"]
    assert result["irregularProcesses"]
    assert len(result["scenario"]["projection"])==30
    assert result["scenario"]["risk"]["pdAnyDay"]["probability"]>=result["baseline"]["risk"]["pdAnyDay"]["probability"]
    assert sum(a.startswith("credito-") for a in result["optimization"]["selectedActions"])<=1
    assert any(s["reason"]=="mismo grupo excluyente" for s in result["optimization"]["skipped"])
    json.dumps(result,allow_nan=False)


def test_expected_shortfall_ties_exact_mass():
    r=m.empirical_loss_risk([0]*99+[100],0.95)
    assert r["VaR"]=="0.00" and r["ES"]=="20.00"


def test_horizon_includes_first_day_and_last_day():
    p=prepared(days=3)
    e=(event("first",10,"inflow",0),event("last",20,"inflow",2),event("beyond",1000,"inflow",3))
    assert np.all(m.simulate_cash_flow(p,0,e)==[1000,1000,3000])


def test_accelerated_receipt_discount_is_not_subtracted_twice():
    c=cfg(days=4); base=(event("invoice",100,"inflow",2),)
    a=m.LiquidityAction("discount","accelerate_receivable",target_event_id="invoice",days=1,financial_cost=10)
    result=m.apply_liquidity_actions(base,[a],c)
    p=prepared(days=4)
    paths=m.simulate_cash_flow(p,0,result)
    assert np.all(paths==[0,9000,9000,9000])


def test_fee_validation_and_repayment_direction():
    with pytest.raises(m.InputError): credit(cost=-1)
    with pytest.raises(m.InputError): credit(repay=0)


def test_api_scalar_collection_probability_is_not_legacy_confidence():
    e=event("x",100,"inflow")
    assert e.collection_probability==1.0
    assert not hasattr(e,"confidence")
