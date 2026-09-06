import { useJobCard } from "@/api/endpoints/jobCards";
import type { JobCardDetail, JobLine } from "@/api/types";
import { DateText, DueDate } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { PageHead } from "@/components/PageHead";
import { QueryState } from "@/components/QueryState";
import { StageChip } from "@/components/StageChip";
import { StatusBadge } from "@/components/StatusBadge";
import { Table } from "@/components/Table";
import { formatQuantity, humanizeCode } from "@/lib/format";
import { Fragment } from "react";
import { Link, useParams } from "react-router";
import { QuotationPanel } from "../quotations/QuotationPanel";
import { AttachmentsPanel } from "./AttachmentsPanel";
import { NotesPanel } from "./NotesPanel";
import { strings } from "./strings";

export function JobCardDetailPage() {
  const { id = "" } = useParams();
  const card = useJobCard(id);

  return (
    <QueryState query={card} skeletonRows={8}>
      {(data) => (
        <div className="stack">
          <PageHead
            title={
              <span className="row">
                <span className="mono">{data.job_no}</span>
                <StatusBadge domain="job_lifecycle_status" value={data.lifecycle_status} />
              </span>
            }
            actions={
              // Print stays server-rendered: fidelity is better. Anyone who can see
              // this page already has job_card:view, which is all print needs too —
              // there's no separate "print" permission in the real grant model.
              <a className="btn" href={`/print/job-card/${data.id}`}>
                {strings.print}
              </a>
            }
          />

          <Header card={data} />

          <section className="panel">
            <div className="panel__head">
              <h2 className="panel__title">{strings.detailLines}</h2>
              <span className="panel__count">{data.lines.length}</span>
            </div>
            {/* No available_actions here — the plain per-card line shape doesn't
                carry them (see api/types.ts::JobLine). Moving a line happens from
                its own detail page, linked below, or from the board. */}
            <LinesTable lines={data.lines} />
          </section>

          <QuotationPanel jobCardId={data.id} lines={data.lines} />

          <div className="grid-2">
            <NotesPanel jobCardId={data.id} />
            <AttachmentsPanel jobCardId={data.id} />
          </div>
        </div>
      )}
    </QueryState>
  );
}

function Header({ card }: { card: JobCardDetail }) {
  const requirements = Object.entries(card.requirements ?? {});

  return (
    <div className="grid-2">
      <section className="panel">
        <div className="panel__head">
          <h2 className="panel__title">{strings.detailHeader}</h2>
        </div>
        <div className="panel__body">
          <dl className="kv">
            <dt className="kv__key">{strings.colClient}</dt>
            <dd className="kv__value">
              <Link to={`/clients/${card.client.id}`}>{card.client.legal_name}</Link>{" "}
              <span className="faint mono">{card.client.client_code}</span>
            </dd>

            <dt className="kv__key">{strings.contact}</dt>
            <dd className="kv__value">
              {card.client_contact ? (
                <>
                  {card.client_contact.contact_name}
                  {card.client_contact.phone ? (
                    <span className="muted"> · {card.client_contact.phone}</span>
                  ) : null}
                </>
              ) : (
                <span className="faint">{strings.contactNone}</span>
              )}
            </dd>

            <dt className="kv__key">{strings.enquiryDate}</dt>
            <dd className="kv__value">
              <DateText value={card.enquiry_date} />
            </dd>

            <dt className="kv__key">{strings.colRequiredBy}</dt>
            <dd className="kv__value">
              <DueDate value={card.required_by} />
            </dd>

            <dt className="kv__key">{strings.source}</dt>
            <dd className="kv__value">{humanizeCode(card.enquiry_source)}</dd>

            <dt className="kv__key">{strings.dispatchPolicy}</dt>
            <dd className="kv__value">{humanizeCode(card.dispatch_policy)}</dd>

            <dt className="kv__key">{strings.colOwner}</dt>
            <dd className="kv__value">{card.owner_user.username}</dd>
          </dl>
        </div>
      </section>

      <section className="panel">
        <div className="panel__head">
          <h2 className="panel__title">{strings.requirements}</h2>
          <span className="panel__count">{requirements.length}</span>
        </div>
        <div className="panel__body">
          {requirements.length === 0 ? (
            <p className="faint">{strings.requirementsHint}</p>
          ) : (
            <dl className="kv">
              {requirements.map(([key, value]) => (
                <Fragment key={key}>
                  <dt className="kv__key">{key}</dt>
                  <dd className="kv__value">{value}</dd>
                </Fragment>
              ))}
            </dl>
          )}
        </div>
      </section>
    </div>
  );
}

/** The split made visible: each line carries its own stage. apps/sales/api.py::
 * job_card_detail's lines use the plain JobLine shape — no available_actions here
 * (that's the board/job-line-detail shapes), so no move buttons on this table. */
function LinesTable({ lines }: { lines: JobLine[] }) {
  return (
    <Table
      caption={strings.detailLines}
      rows={lines}
      rowKey={(row) => row.id}
      empty={<EmptyState title={strings.linesEmpty} />}
      columns={[
        {
          key: "line_no",
          header: strings.colLine,
          render: (row) => (
            <Link className="table__row-link mono" to={`/job-lines/${row.id}`}>
              {row.line_no}
            </Link>
          ),
        },
        {
          key: "description",
          header: strings.colDescription,
          wrap: true,
          render: (row) => row.description,
        },
        {
          key: "category",
          header: strings.colCategory,
          render: (row) => row.product_category.name,
        },
        {
          key: "qty",
          header: strings.colQty,
          align: "right",
          render: (row) => formatQuantity(String(row.quantity)),
        },
        {
          key: "required_by",
          header: strings.colRequiredBy,
          render: (row) => <DueDate value={row.required_by} />,
        },
        {
          key: "stage",
          header: strings.colStage,
          render: (row) => <StageChip stage={row.current_stage} />,
        },
      ]}
    />
  );
}
