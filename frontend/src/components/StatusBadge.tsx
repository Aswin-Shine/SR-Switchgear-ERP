import { useEnumChoices } from "@/api/endpoints/reference";
import { humanizeCode } from "@/lib/format";

/**
 * Renders a status using the label the server supplied for that domain. The client holds
 * no status vocabulary of its own: `domain` names a CHECK-constrained set from /enums, and
 * an unknown value falls back to a humanised form of the code rather than to a blank.
 */
export function StatusBadge({ domain, value }: { domain: string; value: string | null }) {
  const choices = useEnumChoices(domain);
  if (!value) return null;
  const label = choices.find((choice) => choice.value === value)?.label ?? humanizeCode(value);
  return <span className="badge">{label}</span>;
}
