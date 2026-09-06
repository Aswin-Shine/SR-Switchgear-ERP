import { cx } from "@/lib/cx";
import { EMPTY_MARK, daysUntil, formatAge, formatDate, formatDateTime } from "@/lib/format";

/** dd/mm/yyyy in Asia/Kolkata. The server sends UTC; the reader is in India. */
export function DateText({
  value,
  withTime = false,
}: {
  value: string | null | undefined;
  withTime?: boolean;
}) {
  if (!value) return <span className="faint">{EMPTY_MARK}</span>;
  return <time dateTime={value}>{withTime ? formatDateTime(value) : formatDate(value)}</time>;
}

/** A required-by date that says so when it has passed. */
export function DueDate({ value }: { value: string | null | undefined }) {
  const remaining = daysUntil(value);
  if (!value || remaining === null) return <span className="faint">{EMPTY_MARK}</span>;
  return (
    <time dateTime={value} className={cx(remaining < 0 && "badge badge--danger")}>
      {formatDate(value)}
    </time>
  );
}

/** How long a line has sat in its current stage. Stale after a fortnight. */
export function StageAge({
  since,
  staleAfterDays = 14,
}: { since: string; staleAfterDays?: number }) {
  const age = formatAge(since);
  const days = daysUntil(since);
  const stale = days !== null && -days >= staleAfterDays;
  return (
    <span
      className={cx("line-card__age", stale && "line-card__age--stale")}
      title={`In this stage since ${formatDateTime(since)}`}
    >
      {age}
    </span>
  );
}
