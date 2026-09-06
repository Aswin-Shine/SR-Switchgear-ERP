"""Two users press the same button at the same moment.

These use ``django_db(transaction=True)`` and real threads. A plain ``TestCase``
wraps everything in one uncommitted transaction, so both "connections" would be
the same connection: the race could not happen and the test would pass without
proving anything.

The guarantee under test: exactly one insert wins, the pointer moves exactly
once, and the loser gets a clean ``StaleTransition`` rather than a corrupted
pointer, a second history row, or a deadlock.

That last one is why these tests earn their keep. ``apply_transition()`` is
still the sole arbiter of staleness, but the engine takes the job line's row
lock *before* inserting, because the FK on ``job_line_id`` grabs ``FOR KEY
SHARE`` on the parent row first and the trigger's ``FOR UPDATE`` would then be
a lock upgrade — which two concurrent writers cannot both complete. Before that
fix these tests failed with ``deadlock detected`` in five runs out of six.
"""

import threading

import pytest
from django.db import connections

from apps.core.exceptions import StaleTransition
from apps.identity import constants
from apps.identity.models import Role, UserRole
from apps.pipeline.models import JobLineTransition, Stage
from apps.pipeline.services import perform_transition
from apps.sales.models import JobLine
from tests.factories import (
    ClientFactory,
    DepartmentFactory,
    DesignationFactory,
    EmployeeFactory,
    JobCardFactory,
    JobLineFactory,
    ProductCategoryFactory,
    UserAccountFactory,
)


def _run_concurrently(target, count: int):
    """Run ``target(index)`` in ``count`` threads, collecting outcomes.

    Each thread closes its own connection afterwards; leaking them makes the
    test database undroppable at teardown.
    """
    results: list = [None] * count
    barrier = threading.Barrier(count)

    def wrapper(index: int):
        try:
            barrier.wait(timeout=10)
            results[index] = ("ok", target(index))
        except Exception as exc:
            results[index] = ("error", exc)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=wrapper, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    return results


@pytest.mark.concurrency
@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("reference_data")
def test_two_simultaneous_transitions_produce_exactly_one_success():
    department = DepartmentFactory(code="CONCDEPT")
    designation = DesignationFactory(code="CONCDESIG")
    sales_role = Role.objects.get(code=constants.ROLE_SALES)

    users = []
    for index in range(2):
        employee = EmployeeFactory(
            employee_code=f"HR-CONC-{index:05d}",
            department=department,
            designation=designation,
        )
        user = UserAccountFactory(username=f"racer{index}", employee=employee)
        UserRole.objects.create(user=user, role=sales_role)
        users.append(user)

    enquiry = Stage.objects.get(code="ENQUIRY")
    line = JobLineFactory(
        job_card=JobCardFactory(
            owner_user=users[0], client=ClientFactory(client_code="CONCCLIENT")
        ),
        current_stage=enquiry,
        product_category=ProductCategoryFactory(code="CONCCAT"),
    )

    def attempt(index: int):
        # Each thread reads the line on its own connection, as two separate
        # requests would.
        fresh = JobLine.objects.get(pk=line.pk)
        return perform_transition(users[index], fresh, "quote")

    results = _run_concurrently(attempt, 2)

    successes = [r for kind, r in results if kind == "ok"]
    failures = [r for kind, r in results if kind == "error"]

    assert len(successes) == 1, f"expected exactly one winner, got {results}"
    assert len(failures) == 1
    assert isinstance(failures[0], StaleTransition), failures[0]

    # And the state is coherent: one history row, pointer moved once.
    assert JobLineTransition.objects.filter(job_line=line).count() == 1
    line.refresh_from_db()
    assert line.current_stage_id == Stage.objects.get(code="QUOTATION").id


@pytest.mark.concurrency
@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("reference_data")
def test_five_simultaneous_transitions_still_produce_exactly_one_success():
    """Two threads can pass by luck of scheduling. Five is harder to fluke."""
    department = DepartmentFactory(code="CONC5DEPT")
    designation = DesignationFactory(code="CONC5DESIG")
    sales_role = Role.objects.get(code=constants.ROLE_SALES)

    users = []
    for index in range(5):
        employee = EmployeeFactory(
            employee_code=f"HR-C5-{index:05d}",
            department=department,
            designation=designation,
        )
        user = UserAccountFactory(username=f"crowd{index}", employee=employee)
        UserRole.objects.create(user=user, role=sales_role)
        users.append(user)

    line = JobLineFactory(
        job_card=JobCardFactory(
            owner_user=users[0], client=ClientFactory(client_code="CONC5CLIENT")
        ),
        current_stage=Stage.objects.get(code="ENQUIRY"),
        product_category=ProductCategoryFactory(code="CONC5CAT"),
    )

    def attempt(index: int):
        fresh = JobLine.objects.get(pk=line.pk)
        return perform_transition(users[index], fresh, "quote")

    results = _run_concurrently(attempt, 5)

    successes = [r for kind, r in results if kind == "ok"]
    assert len(successes) == 1, f"expected exactly one winner, got {results}"
    assert JobLineTransition.objects.filter(job_line=line).count() == 1


@pytest.mark.concurrency
@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("reference_data")
def test_different_lines_do_not_block_each_other():
    """The lock is per job line. Two people advancing two different lines must
    both succeed — otherwise the board would serialise the whole factory."""
    department = DepartmentFactory(code="INDEPDEPT")
    designation = DesignationFactory(code="INDEPDESIG")
    employee = EmployeeFactory(
        employee_code="HR-INDEP-1", department=department, designation=designation
    )
    user = UserAccountFactory(username="independent", employee=employee)
    UserRole.objects.create(user=user, role=Role.objects.get(code=constants.ROLE_SALES))

    enquiry = Stage.objects.get(code="ENQUIRY")
    card = JobCardFactory(owner_user=user, client=ClientFactory(client_code="INDEPCLIENT"))
    category = ProductCategoryFactory(code="INDEPCAT")
    lines = [
        JobLineFactory(job_card=card, line_no=n + 1, current_stage=enquiry,
                       product_category=category)
        for n in range(2)
    ]

    def attempt(index: int):
        fresh = JobLine.objects.get(pk=lines[index].pk)
        return perform_transition(user, fresh, "quote")

    results = _run_concurrently(attempt, 2)

    assert all(kind == "ok" for kind, _ in results), results
    quotation = Stage.objects.get(code="QUOTATION")
    for line in lines:
        line.refresh_from_db()
        assert line.current_stage_id == quotation.id
