import { cx } from "@/lib/cx";
import { type ReactNode, createContext, useCallback, useContext, useMemo, useState } from "react";

export type ToastTone = "success" | "error" | "info";

export interface Toast {
  id: number;
  tone: ToastTone;
  title: string;
  detail?: string;
}

interface ToastContextValue {
  push: (toast: Omit<Toast, "id">) => void;
  dismiss: (id: number) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const DISMISS_AFTER_MS = 6000;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const push = useCallback(
    (toast: Omit<Toast, "id">) => {
      const id = Date.now() + Math.random();
      setToasts((current) => [...current, { ...toast, id }]);
      // Errors stay until dismissed; a 403 or a 409 is worth reading twice.
      if (toast.tone !== "error") {
        window.setTimeout(() => dismiss(id), DISMISS_AFTER_MS);
      }
    },
    [dismiss],
  );

  const value = useMemo(() => ({ push, dismiss }), [push, dismiss]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      {/* <output> carries role=status implicitly, so a screen reader announces a
          transition result without the focus moving anywhere. */}
      <output className="toasts">
        {toasts.map((toast) => (
          <div key={toast.id} className={cx("toast", `toast--${toast.tone}`)}>
            <div className="toast__body">
              <div className="toast__title">{toast.title}</div>
              {toast.detail ? <div className="toast__detail">{toast.detail}</div> : null}
            </div>
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              onClick={() => dismiss(toast.id)}
              aria-label="Dismiss notification"
            >
              ✕
            </button>
          </div>
        ))}
      </output>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used inside <ToastProvider>");
  return context;
}
