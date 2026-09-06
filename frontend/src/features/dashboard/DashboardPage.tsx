import { useDashboard } from "@/api/endpoints/dashboard";
import type { Dashboard } from "@/api/types";
import { useSession } from "@/auth/SessionProvider";
import { ACTION, RESOURCE } from "@/auth/permissions";
import { DueDate } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { PageHead } from "@/components/PageHead";
import { QueryState } from "@/components/QueryState";
import { StageChip } from "@/components/StageChip";
import { StatusBadge } from "@/components/StatusBadge";
import { Table } from "@/components/Table";
import { Link } from "react-router";
import { strings as jobStrings } from "../job-cards/strings";
import { LineActions } from "../job-lines/LineActions";
import { StageTimeline } from "../job-lines/StageTimeline";
import { strings } from "./strings";

export function DashboardPage() {
  const { me, can } = useSession();
  const dashboard = useDashboard();
  const firstName = me.full_name.split(" ")[0] ?? "";

  return (
    <div className="stack">
      <PageHead
        title={strings.title(firstName)}
        subtitle={strings.subtitle}
        actions={
          <>
            {can(RESOURCE.jobLine, ACTION.view) ? (
              <Link className="btn" to="/board">
                {strings.openBoard}
              </Link>
            ) : null}
            {can(RESOURCE.jobCard, ACTION.create) ? (
              <Link className="btn btn--primary" to="/job-cards/new">
                {strings.newEnquiry}
              </Link>
            ) : null}
          </>
        }
      />

      <QueryState query={dashboard} skeletonRows={6}>
        {(data) => (
          <>
            <Stats data={data} />

            <section className="panel">
              <div className="panel__head">
                <h2 className="panel__title">{strings.awaitingTitle}</h2>
                <span className="panel__count">{data.lines_awaiting_me.length}</span>
              </div>
              <Table
                caption={strings.awaitingTitle}
                rows={data.lines_awaiting_me}
                rowKey={(row) => row.id}
                empty={<EmptyState title={strings.awaitingEmpty} />}
                columns={[
                  {
                    key: "line",
                    header: jobStrings.colJobNo,
                    render: (row) => (
                      <Link className="table__row-link mono" to={`/job-lines/${row.id}`}>
                        {row.job_card.job_no}-{row.line_no}
                      </Link>
                    ),
                  },
                  {
                    key: "client",
                    header: jobStrings.colClient,
                    render: (row) => row.job_card.client,
                  },
                  {
                    key: "description",
                    header: jobStrings.colDescription,
                    wrap: true,
                    render: (row) => row.description,
                  },
                  {
                    key: "stage",
                    header: jobStrings.colStage,
                    render: (row) => <StageChip stage={row.current_stage} />,
                  },
                  {
                    key: "required_by",
                    header: jobStrings.colRequiredBy,
                    render: (row) => <DueDate value={row.required_by} />,
                  },
                  {
                    key: "actions",
                    header: jobStrings.colActions,
                    render: (row) => <LineActions line={row} currentStage={row.current_stage} />,
                  },
                ]}
              />
            </section>

            <section className="panel">
              <div className="panel__head">
                <h2 className="panel__title">{strings.cardsTitle}</h2>
                <span className="panel__count">{data.my_open_job_cards.length}</span>
              </div>
              <Table
                caption={strings.cardsTitle}
                rows={data.my_open_job_cards}
                rowKey={(row) => row.id}
                empty={<EmptyState title={strings.cardsEmpty} />}
                columns={[
                  {
                    key: "job_no",
                    header: jobStrings.colJobNo,
                    render: (row) => (
                      <Link className="table__row-link mono" to={`/job-cards/${row.id}`}>
                        {row.job_no}
                      </Link>
                    ),
                  },
                  {
                    key: "client",
                    header: jobStrings.colClient,
                    render: (row) => row.client.legal_name,
                  },
                  {
                    key: "status",
                    header: jobStrings.colStatus,
                    render: (row) => (
                      <StatusBadge domain="job_lifecycle_status" value={row.lifecycle_status} />
                    ),
                  },
                  {
                    key: "lines",
                    header: jobStrings.colLines,
                    align: "right",
                    render: (row) => `${row.open_line_count}/${row.line_count}`,
                  },
                ]}
              />
            </section>

            <section className="panel">
              <div className="panel__head">
                <h2 className="panel__title">{strings.activityTitle}</h2>
              </div>
              <div className="panel__body">
                {data.recent_activity.length === 0 ? (
                  <EmptyState title={strings.activityEmpty} />
                ) : (
                  <StageTimeline transitions={data.recent_activity} />
                )}
              </div>
            </section>
          </>
        )}
      </QueryState>
    </div>
  );
}

function Stats({ data }: { data: Dashboard }) {
  const stats = [
    { label: strings.statCards, value: data.my_open_job_cards.length },
    { label: strings.statLines, value: data.lines_awaiting_me.length },
  ];

  return (
    <div className="stat-row">
      {stats.map((stat) => (
        <div className="stat" key={stat.label}>
          <p className="stat__label">{stat.label}</p>
          <p className="stat__value">{stat.value}</p>
        </div>
      ))}
    </div>
  );
}
