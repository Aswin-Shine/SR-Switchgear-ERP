import { useSession } from "@/auth/SessionProvider";
import { ACTION, RESOURCE } from "@/auth/permissions";
import { NavLink } from "react-router";

interface NavItem {
  to: string;
  label: string;
  visible: boolean;
  end?: boolean;
}

/**
 * Navigation is grant-driven: a user without `client.view` never sees the Clients tab.
 * That is a convenience — the endpoint behind each screen re-checks — but it keeps people
 * out of screens that would only ever show them a 403.
 */
export function Sidebar() {
  const { can } = useSession();

  const work: NavItem[] = [
    { to: "/", label: "Dashboard", visible: true, end: true },
    { to: "/board", label: "Pipeline board", visible: can(RESOURCE.jobLine, ACTION.view) },
    {
      to: "/job-cards",
      label: "Job cards",
      visible: can(RESOURCE.jobCard, ACTION.view),
      end: true,
    },
    { to: "/job-cards/new", label: "New enquiry", visible: can(RESOURCE.jobCard, ACTION.create) },
  ];

  const records: NavItem[] = [
    { to: "/clients", label: "Clients", visible: can(RESOURCE.client, ACTION.view) },
  ];

  return (
    <nav className="sidebar" aria-label="Sections">
      <div className="sidebar__brand">
        <span className="sidebar__brand-mark">SR</span>
        <span className="sidebar__brand-sub">Switchgear</span>
      </div>

      <p className="sidebar__section">Work</p>
      {work
        .filter((item) => item.visible)
        .map((item) => (
          <NavLink key={item.to} to={item.to} className="nav-link" end={item.end}>
            {item.label}
          </NavLink>
        ))}

      {records.some((item) => item.visible) ? (
        <>
          <p className="sidebar__section">Records</p>
          {records
            .filter((item) => item.visible)
            .map((item) => (
              <NavLink key={item.to} to={item.to} className="nav-link">
                {item.label}
              </NavLink>
            ))}
        </>
      ) : null}

      {can(RESOURCE.adminSite, ACTION.view) ? (
        <>
          <p className="sidebar__section">Administration</p>
          {/* HR, roles, permissions, masters and the audit log live in Django admin. */}
          <a className="nav-link" href="/admin/">
            SR Switchgear Admin ↗
          </a>
        </>
      ) : null}
    </nav>
  );
}
