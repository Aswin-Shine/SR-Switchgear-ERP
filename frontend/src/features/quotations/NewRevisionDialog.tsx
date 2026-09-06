import { useUploadRevision } from "@/api/endpoints/quotations";
import type { JobLine } from "@/api/types";
import { Button } from "@/components/Button";
import { Dialog } from "@/components/Dialog";
import { Field } from "@/components/Field";
import { errorMessage } from "@/components/QueryState";
import { useToast } from "@/components/Toast";
import { formatAmountInput, sanitizeAmountInput } from "@/lib/format";
import { useId, useLayoutEffect, useRef, useState } from "react";
import { strings } from "./strings";

/**
 * Counts non-comma characters up to `caret` in a formatted string. Used to carry the
 * caret across a reformat: commas shift position as digits are added/removed, but the
 * count of "real" characters (digits, the decimal point) before the caret does not.
 */
function significantCharsBefore(value: string, caret: number): number {
  let count = 0;
  for (let i = 0; i < caret && i < value.length; i += 1) {
    if (value[i] !== ",") count += 1;
  }
  return count;
}

/** Inverse of significantCharsBefore: where in `formatted` does that many significant chars land. */
function caretForSignificantCount(formatted: string, target: number): number {
  let seen = 0;
  for (let i = 0; i < formatted.length; i += 1) {
    if (seen === target) return i;
    if (formatted[i] !== ",") seen += 1;
  }
  return formatted.length;
}

/**
 * Uploading a revision is one request: PDF, amount, and validity. The server creates
 * revision N+1 and supersedes N — the client neither numbers revisions nor decides what
 * "supersede" means. apps/sales/api.py::job_card_quotations (POST) never reads a
 * covered-lines field at all, so there's nothing here to select.
 */
export function NewRevisionDialog({
  jobCardId,
  lines: _lines,
  onClose,
}: {
  jobCardId: string;
  lines: JobLine[];
  onClose: () => void;
}) {
  const ids = { file: useId(), amount: useId(), valid: useId() };
  const [file, setFile] = useState<File | null>(null);
  const [amount, setAmount] = useState("");
  const [validTill, setValidTill] = useState("");
  const [touched, setTouched] = useState(false);
  const upload = useUploadRevision(jobCardId);
  const { push } = useToast();

  const amountInputRef = useRef<HTMLInputElement>(null);
  const pendingCaret = useRef<number | null>(null);
  const displayAmount = formatAmountInput(amount);

  useLayoutEffect(() => {
    if (pendingCaret.current === null || !amountInputRef.current) return;
    amountInputRef.current.setSelectionRange(pendingCaret.current, pendingCaret.current);
    pendingCaret.current = null;
  }, [displayAmount]);

  function handleAmountChange(event: React.ChangeEvent<HTMLInputElement>) {
    const caret = event.target.selectionStart ?? event.target.value.length;
    const significantBefore = significantCharsBefore(event.target.value, caret);
    const cleaned = sanitizeAmountInput(event.target.value);
    pendingCaret.current = caretForSignificantCount(formatAmountInput(cleaned), significantBefore);
    setAmount(cleaned);
  }

  const errors = {
    file: file ? null : strings.fileRequired,
    amount: amount.trim() ? null : strings.amountRequired,
  };
  const valid = !errors.file && !errors.amount;

  function submit() {
    setTouched(true);
    if (!valid || !file) return;
    upload.mutate(
      { pdf: file, quoted_amount: amount.trim(), valid_till: validTill },
      {
        onSuccess: (quotation) => {
          push({ tone: "success", title: strings.uploaded(quotation.revision_no) });
          onClose();
        },
        onError: (error) =>
          push({ tone: "error", title: strings.uploadFailed, detail: errorMessage(error) }),
      },
    );
  }

  return (
    <Dialog
      open
      title={strings.newRevisionTitle}
      onClose={upload.isPending ? () => undefined : onClose}
      footer={
        <>
          <Button onClick={onClose} disabled={upload.isPending}>
            {strings.cancel}
          </Button>
          <Button variant="primary" onClick={submit} loading={upload.isPending}>
            {upload.isPending ? strings.submitting : strings.submit}
          </Button>
        </>
      }
    >
      <p className="muted">{strings.supersedeNote}</p>

      <Field
        label={strings.file}
        htmlFor={ids.file}
        required
        hint={strings.fileHint}
        error={touched ? errors.file : null}
      >
        <input
          id={ids.file}
          className="input"
          type="file"
          accept="application/pdf"
          aria-invalid={touched && Boolean(errors.file)}
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
        />
      </Field>

      <Field
        label={strings.amountLabel}
        htmlFor={ids.amount}
        required
        hint={strings.amountHint}
        error={touched ? errors.amount : null}
      >
        {/* Kept as text: the amount is a decimal string end to end, never a float.
            Displayed with Indian (lakh/crore) comma grouping while typing; `amount`
            itself stays the clean, comma-free string that's actually submitted. */}
        <input
          ref={amountInputRef}
          id={ids.amount}
          className="input numeric"
          type="text"
          inputMode="decimal"
          value={displayAmount}
          aria-invalid={touched && Boolean(errors.amount)}
          onChange={handleAmountChange}
        />
      </Field>

      <Field label={strings.validTillLabel} htmlFor={ids.valid}>
        <input
          id={ids.valid}
          className="input"
          type="date"
          value={validTill}
          onChange={(event) => setValidTill(event.target.value)}
        />
      </Field>
    </Dialog>
  );
}
