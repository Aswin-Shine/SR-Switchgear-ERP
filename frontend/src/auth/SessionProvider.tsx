import { useMe } from "@/api/endpoints/reference";
import type { Me } from "@/api/types";
import { ErrorNotice, Skeleton } from "@/components/QueryState";
import { type ReactNode, createContext, useContext, useEffect, useMemo } from "react";
import { type Grants, type OwnedObject, can as evaluate, grantsFrom } from "./can";

export interface Session {
  me: Me;
  grants: Grants;
  /** Visibility only. The endpoint re-checks, and the 403 is the enforcement. */
  can: (resource: string, action: string, obj?: OwnedObject | null) => boolean;
  isSelf: (userId: string | null | undefined) => boolean;
}

const SessionContext = createContext<Session | null>(null);

const PASSWORD_CHANGE_PATH = "/password/change/";

/**
 * Holds the answer to GET /me for the session. Credentials never pass through the SPA:
 * login, the forced password change and the password change form are Django pages, so
 * lockout and throttling live in one place.
 */
export function SessionProvider({ children }: { children: ReactNode }) {
  const query = useMe();
  const me = query.data;

  const mustChangePassword = me?.must_change_password ?? false;

  useEffect(() => {
    if (!mustChangePassword) return;
    const next = `${window.location.pathname}${window.location.search}`;
    window.location.assign(`${PASSWORD_CHANGE_PATH}?next=${encodeURIComponent(next)}`);
  }, [mustChangePassword]);

  const value = useMemo<Session | null>(() => {
    if (!me) return null;
    const grants = grantsFrom(me);
    return {
      me,
      grants,
      can: (resource, action, obj) => evaluate(grants, resource, action, obj),
      isSelf: (userId) => Boolean(userId) && userId === me.id,
    };
  }, [me]);

  if (query.isPending) {
    return (
      <div className="main">
        <Skeleton rows={6} />
      </div>
    );
  }

  if (query.isError) {
    // A 401 has already sent the browser to /login/; anything else is worth showing.
    return (
      <div className="main">
        <ErrorNotice error={query.error} onRetry={() => void query.refetch()} />
      </div>
    );
  }

  if (!value || mustChangePassword) {
    return null; // navigating away to the Django password page
  }

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): Session {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useSession must be used inside <SessionProvider>");
  return session;
}

export function useCan(): Session["can"] {
  return useSession().can;
}
