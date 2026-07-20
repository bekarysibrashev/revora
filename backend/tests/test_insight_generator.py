from decimal import Decimal
from app.modules.ai.insights.generator import evaluate_metrics

def test_evaluate_metrics_emits_auditable_v1_alerts() -> None:
    items = evaluate_metrics(revenue=Decimal("100"), expenses=Decimal("150"),
        net_cash_flow=Decimal("-300"), closing_balance=Decimal("50"),
        leads_total=20, leads_won=2, appointments_total=20, no_show=5,
        marketing_spend=Decimal("100"), attributed_revenue=Decimal("50"))
    assert {item.title for item in items} == {"Клиника работает в минус", "Низкая конверсия лидов", "Много пациентов не приходят", "Реклама не окупается", "Риск кассового разрыва"}
    assert all(item.evidence for item in items)

def test_evaluate_metrics_stays_quiet_without_enough_evidence() -> None:
    assert evaluate_metrics(revenue=Decimal("100"), expenses=Decimal("50"),
        net_cash_flow=Decimal("10"), closing_balance=Decimal("100"),
        leads_total=3, leads_won=0, appointments_total=3, no_show=1,
        marketing_spend=Decimal("0"), attributed_revenue=Decimal("0")) == []
