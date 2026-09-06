"""Two transactions asking for a job number at the same instant.

``next_number()`` increments under a row lock, so the guarantee is that no two
callers ever receive the same string. Worth testing for real rather than
trusting: a duplicated job number would be discovered weeks later, on paper, by
a client holding two different quotations bearing the same reference.
"""

import threading

import pytest
from django.db import connections

from apps.core.models import NumberSeries
from apps.core.numbering import next_number

PREFIX = "RACE-2026-"


def _issue_concurrently(count: int, prefix: str = PREFIX) -> list:
    issued: list = [None] * count
    barrier = threading.Barrier(count)

    def worker(index: int):
        try:
            barrier.wait(timeout=10)
            issued[index] = next_number(prefix)
        except Exception as exc:
            issued[index] = f"error: {exc}"
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    return issued


@pytest.mark.concurrency
@pytest.mark.django_db(transaction=True)
def test_two_simultaneous_callers_never_receive_the_same_number():
    issued = _issue_concurrently(2)

    assert all(isinstance(value, str) and not value.startswith("error") for value in issued), issued
    assert len(set(issued)) == 2, issued
    assert sorted(issued) == [f"{PREFIX}00001", f"{PREFIX}00002"]


@pytest.mark.concurrency
@pytest.mark.django_db(transaction=True)
def test_twenty_simultaneous_callers_produce_twenty_distinct_numbers():
    """No gaps and no duplicates when nothing rolls back."""
    issued = _issue_concurrently(20)

    assert len(set(issued)) == 20, sorted(issued)
    assert sorted(issued) == [f"{PREFIX}{n:05d}" for n in range(1, 21)]

    series = NumberSeries.objects.get(prefix=PREFIX)
    assert series.current == 20


@pytest.mark.concurrency
@pytest.mark.django_db(transaction=True)
def test_separate_prefixes_have_separate_counters():
    """D6 depends on this: the year lives in the prefix, so a new year is a new
    row and the counter resets without anybody remembering to reset it."""
    first = _issue_concurrently(3, "YEARA-2026-")
    second = _issue_concurrently(3, "YEARB-2027-")

    assert sorted(first) == [f"YEARA-2026-{n:05d}" for n in (1, 2, 3)]
    assert sorted(second) == [f"YEARB-2027-{n:05d}" for n in (1, 2, 3)]


@pytest.mark.concurrency
@pytest.mark.django_db(transaction=True)
def test_a_rolled_back_transaction_does_not_burn_a_number():
    """Contrary to the comment on ``next_number()``, this counter IS gapless.

    Both the schema and BACKEND_PLAN.md section 11 say a rolled-back
    transaction leaves a gap. That is true of a PostgreSQL ``SEQUENCE``, whose
    ``nextval`` is deliberately non-transactional — but ``next_number()`` is
    not a sequence. It is an ordinary ``UPDATE`` of a row in
    ``core_number_series``, and an ordinary UPDATE rolls back with its
    transaction.

    So the real behaviour is stronger than documented: numbers are gapless, at
    the cost of serialising every issuer on one row per prefix. That is a fine
    trade at this volume, and it is worth pinning, because someone reading only
    the comment might later "fix" the perceived gap problem by switching to a
    sequence and silently introduce the very gaps the comment warns about.
    """
    from django.db import transaction

    first = next_number(PREFIX)

    with pytest.raises(RuntimeError), transaction.atomic():
        next_number(PREFIX)
        raise RuntimeError("abandon this job card")

    third = next_number(PREFIX)

    assert first == f"{PREFIX}00001"
    assert third == f"{PREFIX}00002", "the abandoned number should have been reclaimed"

    series = NumberSeries.objects.get(prefix=PREFIX)
    assert series.current == 2
