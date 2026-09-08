import { cx } from "@/lib/cx";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { useId } from "react";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "default" | "primary" | "danger" | "ghost";
  size?: "sm" | "md";
  /** Shows a spinner and blocks further clicks. Transitions are never optimistic. */
  loading?: boolean;
  block?: boolean;
  /**
   * Why a disabled button is disabled. A native `disabled` button is removed from the tab
   * order in every browser, so a `title` on one is unreachable by keyboard/AT — it silently
   * vanishes for anyone not hovering with a mouse. Passing this switches the button to
   * `aria-disabled` (stays focusable, click still no-ops) and renders the reason as a
   * disclosure shown on both `:hover` and `:focus-visible`, and always available to screen
   * readers via `aria-describedby` regardless of hover/focus state.
   */
  disabledReason?: ReactNode;
}

export function Button({
  variant = "default",
  size = "md",
  loading = false,
  block = false,
  disabled,
  disabledReason,
  className,
  children,
  onClick,
  ...rest
}: ButtonProps) {
  const reasonId = useId();
  const blocked = Boolean(disabled || loading);
  const explained = blocked && Boolean(disabledReason);

  return (
    <button
      type="button"
      className={cx(
        "btn",
        variant !== "default" && `btn--${variant}`,
        size === "sm" && "btn--sm",
        block && "btn--block",
        className,
      )}
      disabled={blocked && !explained}
      aria-disabled={explained || undefined}
      aria-describedby={explained ? reasonId : rest["aria-describedby"]}
      aria-busy={loading || undefined}
      onClick={explained ? undefined : onClick}
      {...rest}
    >
      {loading ? <span className="btn__spinner" aria-hidden="true" /> : null}
      {children}
      {explained ? (
        // aria-hidden so this text doesn't fold into the button's own accessible name
        // (it would otherwise read as "Confirm Needs a second person") — aria-describedby
        // is explicitly permitted to reference hidden content for a description, so it's
        // still announced, just not as part of the name.
        <span className="btn__reason" id={reasonId} role="tooltip" aria-hidden="true">
          {disabledReason}
        </span>
      ) : null}
    </button>
  );
}
