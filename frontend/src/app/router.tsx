import { EmptyState } from "@/components/EmptyState";
import { BoardPage } from "@/features/board/BoardPage";
import { ClientDetailPage } from "@/features/clients/ClientDetailPage";
import { ClientListPage } from "@/features/clients/ClientListPage";
import { DashboardPage } from "@/features/dashboard/DashboardPage";
import { JobCardDetailPage } from "@/features/job-cards/JobCardDetailPage";
import { JobCardListPage } from "@/features/job-cards/JobCardListPage";
import { NewJobCardPage } from "@/features/job-cards/NewJobCardPage";
import { JobLinePage } from "@/features/job-lines/JobLinePage";
import { Link, createBrowserRouter } from "react-router";
import { AppShell } from "./shell/AppShell";

/**
 * Django serves /app/<anything> with the same template, so the SPA owns everything under
 * that prefix. /login/, /admin/ and /print/ are Django's and are ordinary links.
 */
export const routes = [
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: "board", element: <BoardPage /> },
      { path: "job-cards", element: <JobCardListPage /> },
      { path: "job-cards/new", element: <NewJobCardPage /> },
      { path: "job-cards/:id", element: <JobCardDetailPage /> },
      { path: "job-lines/:id", element: <JobLinePage /> },
      { path: "clients", element: <ClientListPage /> },
      { path: "clients/:id", element: <ClientDetailPage /> },
      { path: "*", element: <NotFound /> },
    ],
  },
];

export const router = createBrowserRouter(routes, { basename: "/app" });

function NotFound() {
  return (
    <EmptyState
      title="That page does not exist"
      detail="The link may be out of date."
      action={
        <Link className="btn" to="/">
          Back to dashboard
        </Link>
      }
    />
  );
}
