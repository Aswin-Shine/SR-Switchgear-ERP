"""Authentication with account lockout.

The lockout state lives in ``failed_login_count`` and ``locked_until``, which
the schema already provides. No rate-limiting dependency is added
(BACKEND_PLAN.md section 7).
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth.backends import ModelBackend
from django.utils import timezone

from apps.identity.models import UserAccount


class LockoutModelBackend(ModelBackend):
    """``ModelBackend`` plus the counter the schema asks for.

    Three behaviours worth stating:

    * A locked account is refused even when the password is right. Otherwise
      the lock would only slow an attacker down by the time it takes to guess.
    * A *successful* login clears the counter. Lockout should punish a run of
      failures, not accumulate across months of ordinary typos.
    * An unknown username still runs the password hasher, via
      ``set_password``'s constant-time sibling in the parent class, so the
      response time does not reveal which usernames exist.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(UserAccount.USERNAME_FIELD)
        if username is None or password is None:
            return None

        try:
            user = UserAccount.objects.get(username=username)
        except UserAccount.DoesNotExist:
            # Same work as the success path, so timing does not leak existence.
            UserAccount().set_password(password)
            return None

        if self._is_locked(user):
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            self._on_success(user)
            return user

        self._on_failure(user)
        return None

    def user_can_authenticate(self, user) -> bool:
        """Active, and not soft-deleted.

        ``ModelBackend`` checks only ``is_active``; ``deleted_at`` is ours and
        it must not be possible to log in to a deleted account.
        """
        return bool(user.is_active) and user.deleted_at is None

    # --- lockout state ------------------------------------------------------

    @staticmethod
    def _is_locked(user: UserAccount) -> bool:
        return user.locked_until is not None and user.locked_until > timezone.now()

    @staticmethod
    def _on_success(user: UserAccount) -> None:
        user.failed_login_count = 0
        user.locked_until = None
        user.last_login = timezone.now()
        user.save(update_fields=["failed_login_count", "locked_until", "last_login"])

    @staticmethod
    def _on_failure(user: UserAccount) -> None:
        user.failed_login_count = (user.failed_login_count or 0) + 1
        fields = ["failed_login_count"]

        if user.failed_login_count >= settings.LOGIN_MAX_FAILURES:
            user.locked_until = timezone.now() + timezone.timedelta(
                minutes=settings.LOGIN_LOCKOUT_MINUTES
            )
            fields.append("locked_until")

        user.save(update_fields=fields)
