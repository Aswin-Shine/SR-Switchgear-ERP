import { useClients } from "@/api/endpoints/clients";
import { type JobCardFilters, useJobCards } from "@/api/endpoints/jobCards";
import { useEnumChoices } from "@/api/endpoints/reference";
import type { JobCardSummary } from "@/api/types";
import { useSession } from "@/auth/SessionProvider";
import { ACTION, RESOURCE } from "@/auth/permissions";
import { Button } from "@/components/Button";
import { DateText, DueDate } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { Field } from "@/components/Field";
import { PageHead } from "@/components/PageHead";
import { QueryState } from "@/components/QueryState";
import { Select } from "@/components/Select";
import { StatusBadge } from "@/components/StatusBadge";
import { Table } from "@/components/Table";
import { useId } from "react";
import { Link, useSearchParams } from "react-router";
import { DEFAULT_JOB_CARD_FILTERS, OWNER_ME } from "./filters";
import { strings } from "./strings";

export function JobCardListPage() {
  const [params, setParams] = useSearchParams();
  const { can } = useSession();

  // No params at all means the user just arrived: open on their own work.
  const untouched = [...params.keys()].length === 0;
  const owner = untouched ? DEFAULT_JOB_CARD_FILTERS.owner : (params.get("owner") ?? undefined);
  const status = untouched ? DEFAULT_JOB_CARD_FILTERS.status : (params.get("status") ?? undefined);
  const clientId = untouched ? undefined : (params.get("client") ?? undefined);
  const q = untouched ? undefined : (params.get("q") ?? undefined);

  // The URL keeps "owner=me" for a shareable link; the API's own filter is mine=1.
  const filters: JobCardFilters = {
    mine: owner === OWNER_ME ? "1" : undefined,
    status,
    client_id: clientId,
    q,
  };

  const cards = useJobCards(filters);

  function setFilter(key: string, value: string) {
    const next = new URLSearchParams(untouched ? { ...DEFAULT_JOB_CARD_FILTERS } : params);
    if (value) next.set(key, value);
    else next.delete(key);
    // Keep an explicit empty marker so "Everyone" survives a reload.
    if (!next.has("owner")) next.set("owner", "");
    setParams(next, { replace: true });
  }

  return (
    <div className="stack">
      <PageHead
        title={strings.listTitle}
        subtitle={strings.listSubtitle}
        actions={
          can(RESOURCE.jobCard, ACTION.create) ? (
            <Link className="btn btn--primary" to="/job-cards/new">
              {strings.newEnquiry}
            </Link>
          ) : null
        }
      />

      <div className="panel">
        <Filters owner={owner} status={status} clientId={clientId} q={q} onChange={setFilter} />
        <QueryState query={cards} skeletonRows={8}>
          {(page) => (
            <>
              <JobCardTable rows={page.items} mine={owner === OWNER_ME} />
              {page.pages > 1 ? (
                <Pager page={page} onPage={(number) => setFilter("page", String(number))} />
              ) : null}
            </>
          )}
        </QueryState>
      </div>
    </div>
  );
}

function Filters({
  owner,
  status,
  clientId,
  q,
  onChange,
}: {
  owner?: string;
  status?: string;
  clientId?: string;
  q?: string;
  onChange: (key: string, value: string) => void;
}) {
  const ids = { owner: useId(), status: useId(), client: useId(), q: useId() };
  const statuses = useEnumChoices("job_lifecycle_status");
  const clients = useClients({ is_active: "true" });

  return (
    <div className="filters">
      <Field label={strings.filterOwner} htmlFor={ids.owner}>
        <Select
          id={ids.owner}
          value={owner ?? ""}
          placeholder={strings.filterOwnerAll}
          options={[{ value: OWNER_ME, label: strings.filterOwnerMine }]}
          onChange={(event) => onChange("owner", event.target.value)}
        />
      </Field>

      <Field label={strings.filterStatus} htmlFor={ids.status}>
        <Select
          id={ids.status}
          value={status ?? ""}
          placeholder={strings.filterStatusAll}
          options={statuses}
          onChange={(event) => onChange("status", event.target.value)}
        />
      </Field>

      <Field label={strings.filterClient} htmlFor={ids.client}>
        <Select
          id={ids.client}
          value={clientId ?? ""}
          placeholder={strings.filterClientAll}
          options={(clients.data?.items ?? []).map((client) => ({
            value: client.id,
            label: client.legal_name,
          }))}
          onChange={(event) => onChange("client", event.target.value)}
        />
      </Field>

      <Field label={strings.search} htmlFor={ids.q}>
        <input
          id={ids.q}
          className="input"
          type="search"
          defaultValue={q ?? ""}
          placeholder={strings.searchPlaceholder}
          onChange={(event) => onChange("q", event.target.value)}
        />
      </Field>
    </div>
  );
}

function JobCardTable({ rows, mine }: { rows: JobCardSummary[]; mine: boolean }) {
  return (
    <Table
      caption={strings.listTitle}
      rows={rows}
      rowKey={(row) => row.id}
      empty={<EmptyState title={mine ? strings.emptyListMine : strings.emptyList} />}
      columns={[
        {
          key: "job_no",
          header: strings.colJobNo,
          render: (row) => (
            <Link className="table__row-link mono" to={`/job-cards/${row.id}`}>
              {row.job_no}
            </Link>
          ),
        },
        {
          key: "client",
          header: strings.colClient,
          render: (row) => <Link to={`/clients/${row.client.id}`}>{row.client.legal_name}</Link>,
        },
        {
          key: "status",
          header: strings.colStatus,
          render: (row) => (
            <StatusBadge domain="job_lifecycle_status" value={row.lifecycle_status} />
          ),
        },
        {
          key: "required_by",
          header: strings.colRequiredBy,
          render: (row) => <DueDate value={row.required_by} />,
        },
        { key: "owner", header: strings.colOwner, render: (row) => row.owner_user.username },
        {
          key: "enquiry_date",
          header: strings.colUpdated,
          render: (row) => <DateText value={row.enquiry_date} />,
        },
      ]}
    />
  );
}

function Pager({
  page,
  onPage,
}: {
  page: { page: number; pages: number; total: number };
  onPage: (page: number) => void;
}) {
  return (
    <div className="filters">
      <span className="muted">
        Page {page.page} of {page.pages} · {page.total} cards
      </span>
      <span className="filters__spacer" />
      <Button size="sm" disabled={page.page <= 1} onClick={() => onPage(page.page - 1)}>
        Previous
      </Button>
      <Button size="sm" disabled={page.page >= page.pages} onClick={() => onPage(page.page + 1)}>
        Next
      </Button>
    </div>
  );
}
