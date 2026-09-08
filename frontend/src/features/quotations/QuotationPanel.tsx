import { quotationPdfUrl, useQuotations } from "@/api/endpoints/quotations";
import type { JobLine, Quotation } from "@/api/types";
import { useSession } from "@/auth/SessionProvider";
import { ACTION, RESOURCE } from "@/auth/permissions";
import { Button } from "@/components/Button";
import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { Money } from "@/components/Money";
import { QueryState } from "@/components/QueryState";
import { StatusBadge } from "@/components/StatusBadge";
import { cx } from "@/lib/cx";
import { useState } from "react";
import { NewRevisionDialog } from "./NewRevisionDialog";
import { strings } from "./strings";

export function QuotationPanel({
  jobCardId,
  lines,
  cardIsDead,
}: {
  jobCardId: string;
  lines: JobLine[];
  /** True once the job card is cancelled or lost — nothing productive follows from
   * quoting a dead enquiry, so the action that would encourage it is gated here
   * rather than only after a real submission bounces off the server. */
  cardIsDead: boolean;
}) {
  const quotations = useQuotations(jobCardId);
  const { can } = useSession();
  const [uploading, setUploading] = useState(false);

  return (
    <section className="panel">
      <div className="panel__head">
        <h2 className="panel__title">{strings.title}</h2>
        <span className="panel__count">{quotations.data?.length ?? 0}</span>
        {can(RESOURCE.quotation, ACTION.create) && lines.length > 0 && !cardIsDead ? (
          <Button size="sm" variant="primary" onClick={() => setUploading(true)}>
            {strings.newRevision}
          </Button>
        ) : null}
      </div>

      {cardIsDead ? (
        <div className="panel__body">
          <p className="faint">{strings.cardIsDeadNotice}</p>
        </div>
      ) : null}

      <div className="panel__body">
        <QueryState query={quotations} skeletonRows={2}>
          {(rows) =>
            rows.length === 0 ? (
              <EmptyState title={strings.empty} />
            ) : (
              <ol className="stack stack--tight">
                {rows.map((quotation) => (
                  <li key={quotation.id}>
                    <RevisionRow quotation={quotation} />
                  </li>
                ))}
              </ol>
            )
          }
        </QueryState>
      </div>

      {uploading ? (
        <NewRevisionDialog
          jobCardId={jobCardId}
          lines={lines}
          onClose={() => setUploading(false)}
        />
      ) : null}
    </section>
  );
}

function RevisionRow({ quotation }: { quotation: Quotation }) {
  return (
    <div className={cx("revision", quotation.status === "superseded" && "revision--superseded")}>
      <span className="revision__no">{strings.revision(quotation.revision_no)}</span>
      <StatusBadge domain="quotation_status" value={quotation.status} />
      <Money value={quotation.quoted_amount} />
      <span className="muted">
        {strings.validTill} <DateText value={quotation.valid_till} />
      </span>

      <span className="revision__spacer" />

      {quotation.has_pdf ? (
        <a className="btn btn--sm" href={quotationPdfUrl(quotation.id)}>
          {strings.openPdf}
        </a>
      ) : null}
    </div>
  );
}
