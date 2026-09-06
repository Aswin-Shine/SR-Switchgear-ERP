import { useClients } from "@/api/endpoints/clients";
import { EmptyState } from "@/components/EmptyState";
import { Field } from "@/components/Field";
import { PageHead } from "@/components/PageHead";
import { QueryState } from "@/components/QueryState";
import { Table } from "@/components/Table";
import { useId } from "react";
import { Link, useSearchParams } from "react-router";
import { strings } from "./strings";

export function ClientListPage() {
  const [params, setParams] = useSearchParams();
  const ids = { q: useId(), active: useId() };

  const filters = {
    q: params.get("q") ?? undefined,
    is_active: params.get("is_active") ?? "true",
  };
  const clients = useClients(filters);

  function setFilter(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  }

  return (
    <div className="stack">
      <PageHead title={strings.listTitle} subtitle={strings.listSubtitle} />

      <div className="panel">
        <div className="filters">
          <Field label={strings.search} htmlFor={ids.q}>
            <input
              id={ids.q}
              className="input"
              type="search"
              defaultValue={filters.q ?? ""}
              placeholder={strings.searchPlaceholder}
              onChange={(event) => setFilter("q", event.target.value)}
            />
          </Field>

          <Field label={strings.colStatus} htmlFor={ids.active}>
            <label className="row" htmlFor={ids.active}>
              <input
                id={ids.active}
                type="checkbox"
                checked={filters.is_active === "true"}
                onChange={(event) => setFilter("is_active", event.target.checked ? "true" : "")}
              />
              <span>{strings.activeOnly}</span>
            </label>
          </Field>
        </div>

        <QueryState query={clients} skeletonRows={8}>
          {(page) => (
            <Table
              caption={strings.listTitle}
              rows={page.items}
              rowKey={(row) => row.id}
              empty={<EmptyState title={strings.empty} />}
              columns={[
                {
                  key: "code",
                  header: strings.colCode,
                  render: (row) => (
                    <Link className="table__row-link mono" to={`/clients/${row.id}`}>
                      {row.client_code}
                    </Link>
                  ),
                },
                {
                  key: "name",
                  header: strings.colName,
                  wrap: true,
                  render: (row) => row.legal_name,
                },
                { key: "city", header: strings.colCity, render: (row) => row.billing_city ?? "—" },
                {
                  key: "state",
                  header: strings.colState,
                  render: (row) => row.billing_state ?? "—",
                },
                {
                  key: "gstin",
                  header: strings.colGstin,
                  render: (row) => <span className="mono">{row.gstin ?? "—"}</span>,
                },
                {
                  key: "status",
                  header: strings.colStatus,
                  render: (row) => (
                    <span className={row.is_active ? "badge badge--success" : "badge"}>
                      {row.is_active ? strings.active : strings.inactive}
                    </span>
                  ),
                },
              ]}
            />
          )}
        </QueryState>
      </div>
    </div>
  );
}
