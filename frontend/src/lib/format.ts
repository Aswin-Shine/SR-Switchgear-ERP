/**
 * Formatting. Every number the user reads passes through here.
 *
 * Money arrives as a decimal string and stays a string: Intl.NumberFormat accepts a
 * string argument and formats it without ever going through a float, which is the
 * whole point of guardrail 4. The client does no arithmetic on amounts — if a total
 * is needed, the server sends it.
 */

const LOCALE = "en-IN";
export const TIME_ZONE = "Asia/Kolkata";

const moneyFormat = new Intl.NumberFormat(LOCALE, {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const numberFormat = new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 3 });

const dateFormat = new Intl.DateTimeFormat("en-GB", {
  timeZone: TIME_ZONE,
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
});

const dateTimeFormat = new Intl.DateTimeFormat("en-GB", {
  timeZone: TIME_ZONE,
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

export const EMPTY_MARK = "—";

/**
 * Intl.NumberFormat has accepted decimal strings since the Intl.NumberFormat v3 proposal
 * landed; the lib.d.ts signature still says number, hence this one narrow re-type rather
 * than a cast at each call site.
 */
const formatDecimalString = moneyFormat.format as (value: string | number | bigint) => string;

/** `"1234567.5"` → `"₹12,34,567.50"`. en-IN groups lakhs and crores with no help. */
export function formatMoney(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return EMPTY_MARK;
  try {
    return formatDecimalString(value);
  } catch {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? moneyFormat.format(parsed) : String(value);
  }
}

export function formatQuantity(value: string | null | undefined, uom?: string | null): string {
  if (value === null || value === undefined || value === "") return EMPTY_MARK;
  const parsed = Number(value);
  const shown = Number.isFinite(parsed) ? numberFormat.format(parsed) : String(value);
  return uom ? `${shown} ${uom}` : shown;
}

/** `"2026-03-14"` or an ISO timestamp → `"14/03/2026"`, rendered in Asia/Kolkata. */
export function formatDate(value: string | null | undefined): string {
  const date = toDate(value);
  return date ? dateFormat.format(date) : EMPTY_MARK;
}

export function formatDateTime(value: string | null | undefined): string {
  const date = toDate(value);
  return date ? dateTimeFormat.format(date) : EMPTY_MARK;
}

function toDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  // A bare YYYY-MM-DD parses as UTC midnight, which in IST is the same calendar day.
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** Whole days between `value` and now, floored. Negative when `value` is in the future. */
export function daysSince(value: string | null | undefined, now: Date = new Date()): number | null {
  const date = toDate(value);
  if (!date) return null;
  return Math.floor((now.getTime() - date.getTime()) / 86_400_000);
}

/** Age in a column: "today", "3d", "21d". Compact because it sits on a dense card. */
export function formatAge(value: string | null | undefined, now: Date = new Date()): string {
  const days = daysSince(value, now);
  if (days === null) return EMPTY_MARK;
  if (days <= 0) return "today";
  return `${days}d`;
}

/** Days remaining until a required-by date; negative means overdue. */
export function daysUntil(value: string | null | undefined, now: Date = new Date()): number | null {
  const days = daysSince(value, now);
  return days === null ? null : -days;
}

const STAGE_HUE_BUCKETS = 12;

/**
 * Stage colour is derived from the stage code, so a stage an administrator adds
 * tomorrow gets a stable, distinct colour with no code change and no colour column.
 * Returns a class name because a style attribute would force 'unsafe-inline' into
 * the CSP; the buckets are declared in styles/components.css.
 */
export function stageHueClass(code: string): string {
  let hash = 0;
  for (let i = 0; i < code.length; i += 1) {
    hash = (hash * 31 + code.charCodeAt(i)) % 100_003;
  }
  return `stage-chip--h${hash % STAGE_HUE_BUCKETS}`;
}

/** Title-cases a server enum value when no label was supplied: "in_progress" → "In progress". */
export function humanizeCode(code: string): string {
  const spaced = code.replace(/[_-]+/g, " ").trim();
  return spaced ? spaced.charAt(0).toUpperCase() + spaced.slice(1) : code;
}

export function pluralize(count: number, singular: string, plural = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : plural}`;
}

/**
 * Live comma-grouping for an amount *input*, Indian system (lakhs, crores).
 * formatMoney/Intl.NumberFormat can't be reused here: it needs a complete
 * number and silently drops a trailing "." or in-progress decimal, which
 * makes it unusable while someone is still typing. This only ever touches
 * punctuation (comma placement) — the digits themselves are untouched, so
 * the value stays the same decimal string end to end.
 */
export function formatAmountInput(raw: string): string {
  const [intPart, decPart] = raw.split(".");
  const digits = intPart ?? "";
  const grouped =
    digits.length <= 3
      ? digits
      : `${digits.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ",")},${digits.slice(-3)}`;
  return decPart !== undefined ? `${grouped}.${decPart}` : grouped;
}

/** Strips an amount input down to digits and a single decimal point, max 2 decimal places. */
export function sanitizeAmountInput(raw: string): string {
  const cleaned = raw.replace(/[^\d.]/g, "");
  const firstDot = cleaned.indexOf(".");
  if (firstDot === -1) return cleaned;
  const intPart = cleaned.slice(0, firstDot);
  const decPart = cleaned
    .slice(firstDot + 1)
    .replace(/\./g, "")
    .slice(0, 2);
  return `${intPart}.${decPart}`;
}
