import { csrfToken } from "@/api/client";
import { useSyncJobSheet } from "@/api/endpoints/sheetExport";
import { useSession } from "@/auth/SessionProvider";
import { ACTION, RESOURCE } from "@/auth/permissions";
import { Button } from "@/components/Button";
import { errorMessage } from "@/components/QueryState";
import { useToast } from "@/components/Toast";
import { useTheme } from "@/lib/theme";
import { useIsFetching, useQueryClient } from "@tanstack/react-query";

// No icon library in this app (checked: no other inline SVG icon exists anywhere in
// frontend/src) — two tiny fixed icons don't earn one. currentColor picks up the ghost
// button's text color, including the accent tint from .btn--ghost[aria-pressed="true"].
function SunIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79Z" />
    </svg>
  );
}

function SyncIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M21 2v6h-6" />
      <path d="M3 12a9 9 0 0 1 15-6.7L21 8" />
      <path d="M3 22v-6h6" />
      <path d="M21 12a9 9 0 0 1-15 6.7L3 16" />
    </svg>
  );
}

/**
 * Refresh is explicit because nothing pushes. Queries also refetch when the window regains
 * focus, so this button is for the case where the user is watching one screen and knows
 * something has changed elsewhere.
 */
export function TopBar() {
  const { can, me } = useSession();
  const queryClient = useQueryClient();
  const fetching = useIsFetching() > 0;
  const [theme, toggleTheme] = useTheme();
  const { push } = useToast();
  const syncSheet = useSyncJobSheet();

  const roles = me.roles.map((role) => role.name).join(", ");
  const token = csrfToken();

  return (
    <header className="topbar">
      <span className="muted">{me.department}</span>
      <span className="topbar__spacer" />

      <Button
        size="sm"
        variant="ghost"
        aria-pressed={theme === "dark"}
        aria-label="Dark mode"
        onClick={toggleTheme}
      >
        {theme === "dark" ? <MoonIcon /> : <SunIcon />}
      </Button>

      {can(RESOURCE.sheetExport, ACTION.view) ? (
        <Button
          size="sm"
          variant="ghost"
          aria-label="Sync job sheet"
          loading={syncSheet.isPending}
          onClick={() =>
            syncSheet.mutate(undefined, {
              onSuccess: (data) =>
                push({
                  tone: "success",
                  title: "Sheet synced",
                  detail: `Synced ${data.synced} job card${data.synced === 1 ? "" : "s"}.`,
                }),
              onError: (error) =>
                push({ tone: "error", title: "Sheet sync failed", detail: errorMessage(error) }),
            })
          }
        >
          <SyncIcon />
        </Button>
      ) : null}

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
