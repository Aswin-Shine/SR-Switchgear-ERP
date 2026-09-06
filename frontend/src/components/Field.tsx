import { cx } from "@/lib/cx";
import type { ReactNode } from "react";

export interface FieldProps {
  label: ReactNode;
  /** Must match the control's id; the label is a real <label for>. */
  htmlFor: string;
  required?: boolean;
  hint?: ReactNode;
  /** "seeded" marks a value pre-filled from somewhere else, e.g. the client default. */
  hintTone?: "default" | "seeded";
  error?: ReactNode;
  children: ReactNode;
}

export function Field({
  label,
  htmlFor,
  required = false,
  hint,
  hintTone = "default",
  error,
  children,
}: FieldProps) {
  return (
    <div className="field">
      <label className="field__label" htmlFor={htmlFor}>
        {label}
        {required ? (
          <span className="field__required" aria-hidden="true">
            *
          </span>
        ) : null}
      </label>
      {children}
      {hint && !error ? (
        <span
          id={`${htmlFor}-hint`}
          className={cx("field__hint", hintTone === "seeded" && "field__hint--seeded")}
        >
          {hint}
        </span>
      ) : null}
      {error ? (
        <span id={`${htmlFor}-error`} className="field__error" role="alert">
          {error}
        </span>
      ) : null}
    </div>
  );
}
