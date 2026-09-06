import { formatMoney } from "@/lib/format";

/**
 * Amounts arrive as decimal strings and are formatted, never computed on. en-IN grouping
 * gives ₹1,23,45,678.90 with no work of ours.
 */
export function Money({ value }: { value: string | null | undefined }) {
  return <span className="numeric">{formatMoney(value)}</span>;
}
