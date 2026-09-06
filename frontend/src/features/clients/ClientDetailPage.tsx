import { useClient } from "@/api/endpoints/clients";
import { useJobCards } from "@/api/endpoints/jobCards";
import type { ClientDetail, Contact } from "@/api/types";
import { DueDate } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { PageHead } from "@/components/PageHead";
import { QueryState } from "@/components/QueryState";
import { StatusBadge } from "@/components/StatusBadge";
import { Table } from "@/components/Table";
import { humanizeCode } from "@/lib/format";
import { Link, useParams } from "react-router";
import { strings as jobStrings } from "../job-cards/strings";
import { strings } from "./strings";

export function ClientDetailPage() {
  const { id = "" } = useParams();
  const client = useClient(id);

  return (
    <QueryState query={client} skeletonRows={6}>
      {(data) => (
        <div className="stack">
          <PageHead
            title={data.legal_name}
            subtitle={
              <>
                <span className="mono">{data.client_code}</span>
                {data.billing_city ? ` · ${data.billing_city}` : ""}
                {data.is_active ? "" : ` · ${strings.inactive}`}
              </>
            }
          />

          <div className="grid-2">
            <Profile client={data} />
            <Contacts contacts={data.contacts} />
          </div>

          <JobHistory clientId={data.id} />
        </div>
      )}
    </QueryState>
  );
}

function Profile({ client }: { client: ClientDetail }) {
  const address = [client.billing_city, client.billing_state].filter(Boolean).join(", ");

  return (
    <section className="panel">
      <div className="panel__head">
        <h2 className="panel__title">{strings.detailProfile}</h2>
      </div>
      <div className="panel__body">
        <dl className="kv">
          <dt className="kv__key">{strings.address}</dt>
          <dd className="kv__value">{address || "—"}</dd>

          <dt className="kv__key">{strings.gstin}</dt>
          <dd className="kv__value mono">{client.gstin ?? "—"}</dd>

          <dt className="kv__key">{strings.defaultDispatch}</dt>
          <dd className="kv__value">{humanizeCode(client.default_dispatch_policy)}</dd>
        </dl>
      </div>
    </section>
  );
}

/** Read-only: apps/sales has no contact-update endpoint (checked api_urls.py and
 * services.py) — a contact can only be created, including its is_primary flag at
 * creation time, never changed afterward. No "designation" field exists either. */
function Contacts({ contacts }: { contacts: Contact[] }) {
  return (
    <section className="panel">
      <div className="panel__head">
        <h2 className="panel__title">{strings.detailContacts}</h2>
        <span className="panel__count">{contacts.length}</span>
      </div>
      <Table
        caption={strings.detailContacts}
        rows={contacts}
        rowKey={(row) => row.id}
        empty={<EmptyState title={strings.contactsEmpty} />}
        columns={[
          {
            key: "name",
            header: strings.contactName,
            render: (row) => (
              <span className="row">
                {row.contact_name}
                {row.is_primary ? (
                  <span className="badge badge--accent">{strings.contactPrimary}</span>
                ) : null}
              </span>
            ),
          },
          { key: "phone", header: strings.contactPhone, render: (row) => row.phone ?? "—" },
          {
            key: "email",
            header: strings.contactEmail,
            render: (row) => (row.email ? <a href={`mailto:${row.email}`}>{row.email}</a> : "—"),
          },
        ]}
      />
    </section>
  );
}

function JobHistory({ clientId }: { clientId: string }) {
  const cards = useJobCards({ client_id: clientId });

  return (
    <section className="panel">
      <div className="panel__head">
        <h2 className="panel__title">{strings.detailJobs}</h2>
        <span className="panel__count">{cards.data?.total ?? 0}</span>
      </div>
      <QueryState query={cards} skeletonRows={4}>
        {(page) => (
          <Table
            caption={strings.detailJobs}
            rows={page.items}
            rowKey={(row) => row.id}
            empty={<EmptyState title={strings.jobsEmpty} />}
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
                key: "status",
                header: jobStrings.colStatus,
                render: (row) => (
                  <StatusBadge domain="job_lifecycle_status" value={row.lifecycle_status} />
                ),
              },
              {
                key: "required_by",
                header: jobStrings.colRequiredBy,
                render: (row) => <DueDate value={row.required_by} />,
              },
            ]}
          />
        )}
      </QueryState>
    </section>
  );
}
