"""When may the 1C extension's privileged control run be believed?

Extension v18.6 runs the services query a second time with RLS lifted and
adopts that result for the doctor breakdowns only if it reproduces the
standard report's ИТОГО row. It says in the snapshot what it decided, but
a claim from the sending side is not evidence -- these tests pin the
independent re-derivation the backend performs from the raw numbers.

The numbers used throughout are the clinic's real 04.08-05.08.2026 figures:
the report saw 216 services for 4 104 748,35 KZT, while the ordinary query
saw 104 services for 2 130 928,00 KZT.
"""

from decimal import Decimal

import pytest

from app.modules.reports.reconciliation import (
    CONTROL_DID_NOT_RUN,
    CONTROL_MATCHES_REPORT,
    ORDINARY_ALREADY_RECONCILED,
    PARTS_DO_NOT_SUM,
    PRIVILEGED_MODE_NOT_RESTORED,
    REPORT_TOTALS_INCOMPLETE,
    evaluate_control_run,
)

REPORT = {
    "report_quantity": Decimal("216"),
    "report_revenue": Decimal("4104748.35"),
    "report_discount": Decimal("675986.65"),
    "report_before_discount": Decimal("4780735.00"),
}
RESTRICTED = {
    "ordinary_quantity": Decimal("104"),
    "ordinary_revenue": Decimal("2130928.00"),
}
FULL = {
    "control_ran": True,
    "control_quantity": Decimal("216"),
    "control_revenue": Decimal("4104748.35"),
    "control_before_discount": Decimal("4780735.00"),
}


def verdict(**overrides):
    return evaluate_control_run(**{**REPORT, **RESTRICTED, **FULL, **overrides})


def test_a_restricted_query_and_a_full_control_run_prove_the_cause() -> None:
    """The whole point: lifting RLS reproduces all three measures at once,
    so "the ordinary query was losing rows to access rights" stops being a
    guess."""
    result = verdict()

    assert result.accepted is True
    assert result.reason == CONTROL_MATCHES_REPORT
    assert result.cause_proven is True


def test_a_control_run_that_matches_only_the_revenue_is_refused() -> None:
    """A result that happens to land on the expected money while seeing the
    wrong number of services is more dangerous than an honest gap: it looks
    like a fix. Matching one measure is never enough."""
    result = verdict(control_quantity=Decimal("150"))

    assert result.accepted is False
    assert "control_quantity" in result.reason
    assert result.cause_proven is False


def test_a_control_run_that_matches_only_the_quantity_is_refused() -> None:
    result = verdict(control_revenue=Decimal("3000000.00"))

    assert result.accepted is False
    assert "control_revenue" in result.reason


def test_a_bigger_result_is_not_accepted_for_being_bigger() -> None:
    """Overshooting the report is still a mismatch. "Closer to the number we
    wanted" is not a criterion anywhere in this decision."""
    result = verdict(
        control_quantity=Decimal("400"),
        control_revenue=Decimal("9000000.00"),
        control_before_discount=Decimal("9500000.00"),
    )

    assert result.accepted is False
    assert result.cause_proven is False


def test_before_discount_must_match_too() -> None:
    result = verdict(control_before_discount=Decimal("2567150.00"))

    assert result.accepted is False
    assert "control_before_discount" in result.reason


def test_a_control_run_that_left_privileged_mode_on_is_never_trusted() -> None:
    """Refused on its numbers being perfect, because the run misbehaved.
    Reporting built on a session that stayed privileged is not worth the
    figure it produces."""
    result = verdict(control_mode_restored=False)

    assert result.accepted is False
    assert result.reason == PRIVILEGED_MODE_NOT_RESTORED


def test_a_control_run_that_could_not_start_is_reported_as_such() -> None:
    """The configuration may refuse the switch. That is a normal outcome,
    not an error, and the ordinary path keeps working."""
    result = verdict(
        control_ran=False,
        control_quantity=Decimal("0"),
        control_revenue=Decimal("0"),
        control_before_discount=Decimal("0"),
    )

    assert result.accepted is False
    assert result.reason == CONTROL_DID_NOT_RUN


def test_an_already_reconciled_ordinary_query_needs_no_privileged_run() -> None:
    """If nothing was lost there is nothing to fix, and privileged mode must
    not be used to "confirm" a result that already agrees."""
    result = verdict(
        ordinary_quantity=Decimal("216"), ordinary_revenue=Decimal("4104748.35")
    )

    assert result.accepted is False
    assert result.reason == ORDINARY_ALREADY_RECONCILED


def test_a_total_row_whose_parts_do_not_sum_is_not_used_as_a_yardstick() -> None:
    """If revenue + discount != before-discount, the ИТОГО row is not the
    "count | cost | discount | gross" shape we think it is, and we do not
    know which of its numbers to compare against."""
    result = verdict(report_discount=Decimal("1.00"))

    assert result.accepted is False
    assert result.reason == PARTS_DO_NOT_SUM
    assert result.invariants["report_parts_sum"] is False


def test_a_missing_report_total_cannot_authorise_anything() -> None:
    result = verdict(
        report_quantity=Decimal("0"),
        report_revenue=Decimal("0"),
        report_discount=Decimal("0"),
        report_before_discount=Decimal("0"),
    )

    assert result.accepted is False
    assert result.reason == REPORT_TOTALS_INCOMPLETE


def test_rounding_drift_of_a_tiyn_still_counts_as_a_match() -> None:
    result = verdict(control_revenue=Decimal("4104748.34"))

    assert result.accepted is True


def test_two_tiyns_of_drift_does_not() -> None:
    result = verdict(control_revenue=Decimal("4104748.33"))

    assert result.accepted is False


def test_a_refund_heavy_period_reconciles_the_same_way() -> None:
    """Reversals make the totals smaller but change nothing about the rule:
    all three measures still have to agree."""
    result = evaluate_control_run(
        report_quantity=Decimal("10"),
        report_revenue=Decimal("-5000.00"),
        report_discount=Decimal("1000.00"),
        report_before_discount=Decimal("-4000.00"),
        ordinary_quantity=Decimal("4"),
        ordinary_revenue=Decimal("-2000.00"),
        control_ran=True,
        control_quantity=Decimal("10"),
        control_revenue=Decimal("-5000.00"),
        control_before_discount=Decimal("-4000.00"),
    )

    assert result.accepted is True


def test_a_doubled_control_result_is_refused_as_duplication() -> None:
    """Exactly twice the report is the signature of a duplicated join, and
    is caught by the same gate rather than needing its own rule."""
    result = verdict(
        control_quantity=Decimal("432"),
        control_revenue=Decimal("8209496.70"),
        control_before_discount=Decimal("9561470.00"),
    )

    assert result.accepted is False
