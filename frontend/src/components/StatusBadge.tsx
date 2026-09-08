import { useEnumChoices } from "@/api/endpoints/reference";
import { cx } from "@/lib/cx";
import { humanizeCode } from "@/lib/format";

/** job_lifecycle_status is one of the two domains this codebase already treats as a
 * sanctioned exception to "never compare a status against a literal" (it's pinned by a
 * DB CHECK constraint — see JobCardDetailPage.tsx's cardIsDead). The same outcome was
 * previously red on the print job card, neutral grey here, and an unrelated hashed hue
 * on StageChip — three disagreeing signals for one fact. This is the narrow, named
 * exception that fixes it for the one domain that actually carries a severe outcome;
 * it does not extend to other domains (quotation_status, job_line_status, ...), which
 * stay plain badges. */
const LIFECYCLE_TONE: Record<string, "success" | "danger"> = {
  won: "success",
  lost: "danger",
  cancelled: "danger",
};

/**
 * Renders a status using the label the server supplied for that domain. The client holds
 * no status vocabulary of its own: `domain` names a CHECK-constrained set from /enums, and
 * an unknown value falls back to a humanised form of the code rather than to a blank.
 */
export function StatusBadge({ domain, value }: { domain: string; value: string | null }) {
  const choices = useEnumChoices(domain);
  if (!value) return null;
  const label = choices.find((choice) => choice.value === value)?.label ?? humanizeCode(value);
  const tone = domain === "job_lifecycle_status" ? LIFECYCLE_TONE[value] : undefined;
  return <span className={cx("badge", tone && `badge--${tone}`)}>{label}</span>;
}
