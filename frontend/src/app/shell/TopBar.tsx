import { csrfToken } from "@/api/client";
import { useSession } from "@/auth/SessionProvider";
import { Button } from "@/components/Button";
import { useIsFetching, useQueryClient } from "@tanstack/react-query";

/**
 * Refresh is explicit because nothing pushes. Queries also refetch when the window regains
 * focus, so this button is for the case where the user is watching one screen and knows
 * something has changed elsewhere.
 */
export function TopBar() {
  const { me } = useSession();
  const queryClient = useQueryClient();
  const fetching = useIsFetching() > 0;

  const roles = me.roles.map((role) => role.name).join(", ");
  const token = csrfToken();

  return (
    <header className="topbar">
      <span className="muted">{me.department}</span>
      <span className="topbar__spacer" />

      <Button
        size="sm"
        variant="ghost"
        loading={fetching}
        onClick={() => void queryClient.invalidateQueries()}
      >
        Refresh
      </Button>

      <div className="topbar__user">
        <span className="topbar__user-name">{me.full_name}</span>
        <span className="topbar__user-roles">{roles || "No role assigned"}</span>
      </div>

      {/* Django owns the session, so signing out is a Django POST, not a fetch. */}
      <form method="post" action="/logout/">
        {token ? <input type="hidden" name="csrfmiddlewaretoken" value={token} /> : null}
        <Button type="submit" size="sm" variant="ghost">
          Sign out
        </Button>
      </form>
    </header>
  );
}
