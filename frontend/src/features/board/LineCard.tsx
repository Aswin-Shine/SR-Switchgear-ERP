import type { JobLineSummary, StageRef } from "@/api/types";
import { DueDate } from "@/components/DateText";
import { StatusBadge } from "@/components/StatusBadge";
import { formatQuantity } from "@/lib/format";
import { Link } from "react-router";
import { LineActions } from "../job-lines/LineActions";
import { strings } from "./strings";

/** One job line on the board. Dense on purpose: this column replaces a spreadsheet row.
 * currentStage comes from the enclosing column, not the line itself — a board line
 * carries no current_stage of its own (see api/types.ts::JobLineSummary). Likewise the
 * board payload has no per-line stage-entry timestamp and no client id, only its legal
 * name — so there's no "time in stage" indicator here and the client name isn't a link. */
export function LineCard({ line, currentStage }: { line: JobLineSummary; currentStage: StageRef }) {
  return (
    <article className="line-card">
      <div className="line-card__top">
        <Link className="line-card__no" to={`/job-lines/${line.id}`}>
          {line.job_card.job_no}-{line.line_no}
        </Link>
      </div>

      <p className="line-card__desc">{line.description}</p>

      <div className="line-card__meta">
        <span className="truncate">{line.job_card.client}</span>
      </div>

      <div className="line-card__meta">
        <span>{formatQuantity(String(line.quantity))}</span>
        <span aria-hidden="true">·</span>
        <DueDate value={line.required_by} />
      </div>

      {line.quotation ? (
        <div className="line-card__meta">
          <span className="muted">{strings.quotationRevision(line.quotation.revision_no)}</span>
          <StatusBadge domain="quotation_status" value={line.quotation.status} />
        </div>
      ) : null}

      <div className="line-card__foot">
        <LineActions line={line} currentStage={currentStage} />
      </div>
    </article>
  );
}
