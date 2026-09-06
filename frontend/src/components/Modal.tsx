import { cx } from "@/lib/cx";
import { type ReactNode, useEffect, useId, useRef } from "react";
import { Button } from "./Button";

export interface ModalProps {
  open: boolean;
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  /** Extra class on the <dialog> itself; Drawer uses it to change the geometry. */
  className?: string;
  variant?: "dialog" | "drawer";
}

/**
 * Built on <dialog>, so focus trapping, Escape, inertness of the page behind and the
 * backdrop are the platform's job rather than ours. Only actions that need confirmation
 * get one of these — the rest of the UI stays inline.
 */
export function Modal({
  open,
  title,
  onClose,
  children,
  footer,
  className,
  variant = "dialog",
}: ModalProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    if (open && !element.open) element.showModal();
    if (!open && element.open) element.close();
  }, [open]);

  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const handleClose = () => onClose();
    element.addEventListener("close", handleClose);
    return () => element.removeEventListener("close", handleClose);
  }, [onClose]);

  const content = (
    <>
      <div className="dialog__head">
        <h2 className="dialog__title" id={titleId}>
          {title}
        </h2>
        <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close">
          ✕
        </Button>
      </div>
      <div className={variant === "drawer" ? "drawer__body" : "dialog__body"}>{children}</div>
      {footer ? <div className="dialog__foot">{footer}</div> : null}
    </>
  );

  return (
    <dialog
      ref={ref}
      className={cx(variant === "drawer" ? "drawer" : "dialog", className)}
      aria-labelledby={titleId}
    >
      {variant === "drawer" ? <div className="drawer__inner">{content}</div> : content}
    </dialog>
  );
}
