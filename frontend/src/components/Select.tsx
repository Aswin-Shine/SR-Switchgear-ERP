import type { EnumChoice } from "@/api/types";
import { cx } from "@/lib/cx";
import type { SelectHTMLAttributes } from "react";

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  /** Options come from GET /api/v1/enums or another server list — never a literal here. */
  options: EnumChoice[];
  /** Label for the empty option. Omit to require a choice. */
  placeholder?: string;
}

export function Select({ options, placeholder, className, ...rest }: SelectProps) {
  return (
    <select className={cx("select", className)} {...rest}>
      {placeholder !== undefined ? <option value="">{placeholder}</option> : null}
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}
