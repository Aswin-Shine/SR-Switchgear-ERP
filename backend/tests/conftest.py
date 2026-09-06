"""Shared pytest fixtures.

Every test runs against a real PostgreSQL 16. There is no SQLite path, even for
unit tests: the schema leans on partial indexes, JSONB, range partitioning and
plpgsql triggers, none of which SQLite would exercise (BACKEND_PLAN.md
section 9).
"""

import importlib

import pytest
from django.apps import apps as django_apps
from django.db import connection

#: The data migrations that seed reference data, in dependency order.
_SEED_MIGRATIONS = (
    "apps.identity.migrations.0002_roles_and_permission_grid",
    "apps.pipeline.migrations.0003_sales_stage_graph",
)


def seed_reference_data() -> None:
    """Run the data migrations' own seed functions against the live models.

    ``django_db(transaction=True)`` truncates every table between tests, taking
    the seeded roles, permission grid and stage graph with it. Re-seeding by
    calling the migrations directly — rather than keeping a second copy of the
    grid in the test suite — means the tests cannot drift from what actually
    ships. ``apps.get_model`` resolves against the live registry, which is what
    the seed functions use.
    """
    for module_path in _SEED_MIGRATIONS:
        importlib.import_module(module_path).seed(django_apps, None)


def pytest_collection_modifyitems(items):
    """Run the transactional tests last, as Django's own runner does.

    ``django_db(transaction=True)`` truncates every table at teardown, and
    pytest-django does not restore the data migrations' rows. Any test running
    afterwards finds no roles and no stages, and fails for a reason that has
    nothing to do with the code under test.

    Repairing it in a fixture is not possible from this file: pytest-django's
    ``_django_db_helper`` is set up before anything in ``tests/conftest.py`` and
    torn down after it, so a teardown hook here runs *before* the flush, and a
    setup hook runs inside the next test's transaction, where a re-seed would
    simply roll back. Seeding on every setup does work, but measured at about
    0.5s per test across the suite.

    Django's own test runner solves this by ordering ``TestCase`` before
    ``TransactionTestCase``. This does the same thing for the same reason, and
    keeps the ordering explicit rather than depending on collection order.
    ``pytest-randomly`` shuffles within the collection, and this hook runs
    after it, so the two do not fight.
    """
    items.sort(key=lambda item: 1 if item.get_closest_marker("concurrency") else 0)


@pytest.fixture(scope="session", autouse=True)
def _leave_the_database_seeded(django_db_setup, django_db_blocker):
    """Put the seed rows back before the session ends.

    The transactional tests run last and truncate everything on the way out,
    which leaves the *committed* state of the test database empty. With
    ``--reuse-db`` — the local default — the next run inherits that empty
    database, the safety net below fires on every single test, and the suite
    goes from ten seconds to eighty-three.

    Session teardown is late enough to run after the final flush, and outside
    any test transaction, so this write actually persists.
    """
    yield

    with django_db_blocker.unblock():
        from apps.identity.models import Role

        if not Role.objects.filter(is_system=True).exists():
            seed_reference_data()


@pytest.fixture(autouse=True)
def _reference_data_present(request):
    """Safety net if a transactional test still manages to run early.

    One EXISTS query per database test. It should never re-seed, given the
    ordering hook above — but if it ever does, a slow suite is a better outcome
    than a cascade of failures whose cause is invisible.
    """
    # `_django_db_helper` is what pytest-django actually injects, for both the
    # `db` fixture and the `django_db` marker. `django_db_setup` is NOT a valid
    # signal here: the session fixture above depends on it, which puts it in
    # every test's fixturenames including the pure-Python ones, where touching
    # the database raises.
    if not {"db", "transactional_db", "_django_db_helper"} & set(request.fixturenames):
        return

    from apps.identity.models import Role

    if not Role.objects.filter(is_system=True).exists():
        seed_reference_data()


@pytest.fixture
def db_cursor(db):
    """A raw cursor, for the handful of assertions that must bypass the ORM."""
    with connection.cursor() as cursor:
        yield cursor


@pytest.fixture
def reference_data(transactional_db):
    """A transactional test with the seeded reference data restored."""
    seed_reference_data()
    return None
