"""Login throttling, driven by the columns the schema already provides."""

import pytest
from django.contrib.auth import authenticate
from django.test import override_settings
from django.utils import timezone

from tests.factories import UserAccountFactory

PASSWORD = "a-perfectly-good-password"


@pytest.mark.django_db
def test_correct_password_authenticates():
    user = UserAccountFactory(password=PASSWORD)
    assert authenticate(username=user.username, password=PASSWORD) == user


@pytest.mark.django_db
def test_username_is_case_insensitive_at_login():
    user = UserAccountFactory(username="Kavitha", password=PASSWORD)
    assert authenticate(username="kavitha", password=PASSWORD) == user


@override_settings(LOGIN_MAX_FAILURES=3, LOGIN_LOCKOUT_MINUTES=15)
@pytest.mark.django_db
def test_n_failures_lock_the_account():
    user = UserAccountFactory(password=PASSWORD)

    for expected_count in (1, 2):
        assert authenticate(username=user.username, password="wrong") is None
        user.refresh_from_db()
        assert user.failed_login_count == expected_count
        assert user.locked_until is None

    assert authenticate(username=user.username, password="wrong") is None
    user.refresh_from_db()
    assert user.failed_login_count == 3
    assert user.locked_until is not None and user.locked_until > timezone.now()


@override_settings(LOGIN_MAX_FAILURES=3, LOGIN_LOCKOUT_MINUTES=15)
@pytest.mark.django_db
def test_a_locked_account_is_refused_even_with_the_right_password():
    """Otherwise the lock only costs an attacker the time to finish guessing."""
    user = UserAccountFactory(password=PASSWORD)
    for _ in range(3):
        authenticate(username=user.username, password="wrong")

    assert authenticate(username=user.username, password=PASSWORD) is None


@override_settings(LOGIN_MAX_FAILURES=3, LOGIN_LOCKOUT_MINUTES=15)
@pytest.mark.django_db
def test_a_successful_login_clears_the_counter():
    """Lockout should punish a run of failures, not accumulate across months
    of ordinary typos."""
    user = UserAccountFactory(password=PASSWORD)
    authenticate(username=user.username, password="wrong")
    authenticate(username=user.username, password="wrong")

    assert authenticate(username=user.username, password=PASSWORD) == user

    user.refresh_from_db()
    assert user.failed_login_count == 0
    assert user.locked_until is None
    assert user.last_login is not None


@override_settings(LOGIN_MAX_FAILURES=3, LOGIN_LOCKOUT_MINUTES=15)
@pytest.mark.django_db
def test_the_lock_expires():
    user = UserAccountFactory(password=PASSWORD)
    for _ in range(3):
        authenticate(username=user.username, password="wrong")

    user.refresh_from_db()
    user.locked_until = timezone.now() - timezone.timedelta(seconds=1)
    user.save(update_fields=["locked_until"])

    assert authenticate(username=user.username, password=PASSWORD) == user


@pytest.mark.django_db
def test_an_inactive_account_cannot_authenticate():
    user = UserAccountFactory(password=PASSWORD, is_active=False)
    assert authenticate(username=user.username, password=PASSWORD) is None


@pytest.mark.django_db
def test_a_soft_deleted_account_cannot_authenticate():
    """ModelBackend checks only is_active; deleted_at is ours to enforce."""
    user = UserAccountFactory(password=PASSWORD)
    user.deleted_at = timezone.now()
    user.save(update_fields=["deleted_at"])

    assert authenticate(username=user.username, password=PASSWORD) is None


@pytest.mark.django_db
def test_unknown_username_returns_none_without_raising():
    assert authenticate(username="nobody-by-that-name", password=PASSWORD) is None
