import { useJobLine } from "@/api/endpoints/jobLines";
import { DueDate } from "@/components/DateText";
import { PageHead } from "@/components/PageHead";
import { QueryState } from "@/components/QueryState";
import { StageChip } from "@/components/StageChip";
import { StatusBadge } from "@/components/StatusBadge";
import { formatQuantity } from "@/lib/format";
import { Fragment } from "react";
import { Link, useParams } from "react-router";
import { LineActions } from "./LineActions";
import { StageTimeline } from "./StageTimeline";
import { strings } from "./strings";

export function JobLinePage() {
  const { id = "" } = useParams();
  const line = useJobLine(id);

  return (
    <QueryState query={line} skeletonRows={6}>
      {(data) => (
        <div className="stack">
          <PageHead
            title={strings.lineOf(data.job_card.job_no, data.line_no)}
            subtitle={data.description}
            actions={
              <LineActions line={data} currentStage={data.current_stage} size="md" showEmpty />
            }
          />

          <div className="grid-2">
            <section className="panel">
              <div className="panel__head">
                <h2 className="panel__title">Line</h2>
                <StageChip stage={data.current_stage} />
                <StatusBadge domain="job_line_status" value={data.line_status} />
              </div>
              <div className="panel__body">
                <dl className="kv">
                  <dt className="kv__key">Job card</dt>
                  <dd className="kv__value">
                    <Link to={`/job-cards/${data.job_card.id}`}>{data.job_card.job_no}</Link>
                  </dd>

                  <dt className="kv__key">Client</dt>
                  <dd className="kv__value">{data.job_card.client}</dd>

                  <dt className="kv__key">Category</dt>
                  <dd className="kv__value">{data.product_category.name}</dd>

                  <dt className="kv__key">Quantity</dt>
                  <dd className="kv__value">{formatQuantity(String(data.quantity))}</dd>

                  <dt className="kv__key">Required by</dt>
                  <dd className="kv__value">
                    <DueDate value={data.required_by} />
                  </dd>
                </dl>
              </div>
            </section>

            <section className="panel">
              <div className="panel__head">
                <h2 className="panel__title">{strings.specsTitle}</h2>
              </div>
              <div className="panel__body">
                <Specifications specs={data.specs} />
              </div>
            </section>
          </div>

          <section className="panel">
            <div className="panel__head">
              <h2 className="panel__title">{strings.timelineTitle}</h2>
              <span className="panel__count">{data.history.length}</span>
            </div>
            <div className="panel__body">
              <StageTimeline transitions={data.history} />
            </div>
          </section>
        </div>
      )}
    </QueryState>
  );
}

function Specifications({ specs }: { specs: Record<string, string> }) {
  const entries = Object.entries(specs);
  if (entries.length === 0) return <p className="faint">{strings.specsEmpty}</p>;
  return (
    <dl className="kv">
      {entries.map(([key, value]) => (
        <Fragment key={key}>
          <dt className="kv__key">{key}</dt>
          <dd className="kv__value">{value}</dd>
        </Fragment>
      ))}
    </dl>
  );
}
