"""apps.sales.views._format_inr: Indian digit grouping for a printed page.

No Django DB needed — pure string formatting.
"""

from decimal import Decimal

from apps.sales.views import EMPTY_MARK, _format_inr


def test_none_is_the_empty_mark():
    assert _format_inr(None) == EMPTY_MARK


def test_a_small_amount_needs_no_grouping():
    assert _format_inr(Decimal("500")) == "₹500.00"


def test_lakhs_and_crores_group_in_pairs_not_threes():
    assert _format_inr(Decimal("1234567.5")) == "₹12,34,567.50"


def test_zero():
    assert _format_inr(Decimal("0")) == "₹0.00"


def test_a_negative_amount_keeps_its_sign():
    assert _format_inr(Decimal("-1234.5")) == "-₹1,234.50"
