import { ApiError } from "@/api/client";
import { useApplyTransition } from "@/api/endpoints/jobLines";
import type { ActionOption, JobLineSummary, StageRef } from "@/api/types";
import { Button } from "@/components/Button";
import { Dialog } from "@/components/Dialog";
import { Field } from "@/components/Field";
import { errorMessage } from "@/components/QueryState";
import { StageChip } from "@/components/StageChip";
import { useToast } from "@/components/Toast";
import { humanizeCode } from "@/lib/format";
import { useId, useState } from "react";
import { strings } from "./strings";

export interface TransitionDialogProps {
  line: JobLineSummary;
  /** A board JobLineSummary carries no current_stage — the column it's grouped under
   * already says it — so the caller supplies it explicitly (a Dashboard row's own
   * current_stage field, or the Board column's stage). */
  currentStage: StageRef;
  /** The action the user picked, straight from the line's `available_actions`. */
  action: ActionOption;
  onClose: () => void;
}

/**
 * The move, confirmed.
 *
 * Three things this deliberately does not do:
 *   - it does not compute the destination stage (the server put it on the action),
 *   - it does not update optimistically (the move is authority-checked and can fail),
 *   - it does not retry a 409. A 409 means the line already moved; replaying the action
 *     would apply it to a stage the line has left. We say so and let the refetch land.
 */
export function TransitionDialog({ line, currentStage, action, onClose }: TransitionDialogProps) {
  const [note, setNote] = useState("");
  const noteId = useId();
  const mutation = useApplyTransition(line.id);
  const { push } = useToast();

  const noteMissing = action.requires_note && note.trim().length === 0;

  function submit() {
    if (noteMissing || mutation.isPending) return;
    const trimmed = note.trim();
    mutation.mutate(
      { action_code: action.action_code, ...(trimmed ? { note: trimmed } : {}) },
      {
        onSuccess: (updated) => {
          push({
            tone: "success",
            title: humanizeCode(action.action_code),
            detail: strings.moved(
              strings.lineOf(line.job_card.job_no, line.line_no),
              updated.current_stage.name,
            ),
          });
          onClose();
        },
        onError: (error) => {
          if (error instanceof ApiError && error.isStale) {
            push({ tone: "error", title: strings.staleTitle, detail: strings.staleDetail });
            onClose();
            return;
          }
          push({
            tone: "error",
            title: strings.failedTitle,
            detail: errorMessage(error),
          });
        },
      },
    );
  }

  return (
    <Dialog
      open
      title={strings.moveTitle(humanizeCode(action.action_code))}
      onClose={mutation.isPending ? () => undefined : onClose}
      footer={
        <>
          <Button onClick={onClose} disabled={mutation.isPending}>
            {strings.cancel}
          </Button>
          <Button
            variant={
              action.to_stage?.cascades_job_card_status === "cancelled" ? "danger" : "primary"
            }
            onClick={submit}
            disabled={noteMissing}
            loading={mutation.isPending}
          >
            {mutation.isPending ? strings.submitting : strings.confirm}
          </Button>
        </>
      }
    >
      <p className="muted">
        {strings.lineOf(line.job_card.job_no, line.line_no)} · {line.description}
      </p>

      <div className="row">
        <span className="muted">{strings.moveFrom}</span>
        <StageChip stage={currentStage} />
        {action.to_stage ? (
          <>
            <span aria-hidden="true">→</span>
            <span className="muted">{strings.moveTo}</span>
            <StageChip stage={action.to_stage} />
          </>
        ) : null}
      </div>

      <Field
        label={strings.noteLabel}
        htmlFor={noteId}
        required={action.requires_note}
        hint={action.requires_note ? strings.noteRequiredHint : strings.noteOptionalHint}
      >
        <textarea
          id={noteId}
          className="textarea"
          value={note}
          required={action.requires_note}
          aria-describedby={`${noteId}-hint`}
          placeholder={strings.notePlaceholder}
          onChange={(event) => setNote(event.target.value)}
        />
      </Field>
    </Dialog>
  );
}
