import type { ActionOption, JobLineSummary, StageRef } from "@/api/types";
import { Button } from "@/components/Button";
import { humanizeCode } from "@/lib/format";
import { useState } from "react";
import { TransitionDialog } from "./TransitionDialog";
import { strings } from "./strings";

/**
 * A line's moves, rendered from `available_actions`. No switch on stage codes, no colour
 * map, no "if the user is a manager" — the server already answered all of that.
 *
 * No drag-and-drop: on a permissioned state machine most drop targets are a lie, the
 * refusal arrives after the gesture, and a wrong drop writes an audit row that cannot be
 * deleted. Explicit buttons are also the accessible option.
 */
export function LineActions({
  line,
  currentStage,
  size = "sm",
  showEmpty = false,
}: {
  line: JobLineSummary;
  /** See TransitionDialogProps.currentStage — not on JobLineSummary itself. */
  currentStage: StageRef;
  size?: "sm" | "md";
  showEmpty?: boolean;
}) {
  const [pending, setPending] = useState<ActionOption | null>(null);

  if (line.available_actions.length === 0) {
    return showEmpty ? <span className="faint">{strings.noActions}</span> : null;
  }

  return (
    <>
      <div className="row">
        {line.available_actions.map((action) => (
          <Button
            key={action.action_code}
            size={size}
            variant={
              // Cancel (an administrative override) gets the alarming treatment; Lose
              // and Won (routine, if final, commercial outcomes) don't — both are
              // "terminal", but only one is a kill switch.
              action.to_stage?.cascades_job_card_status === "cancelled"
                ? "danger"
                : action.to_stage
                  ? "default"
                  : "ghost"
            }
            disabled={!action.available}
            disabledReason={
              action.blocked_by ? strings.blockedReason(action.blocked_by) : undefined
            }
            onClick={() => setPending(action)}
          >
            {humanizeCode(action.action_code)}
          </Button>
        ))}
      </div>

      {pending ? (
        <TransitionDialog
          key={pending.action_code}
          line={line}
          currentStage={currentStage}
          action={pending}
          onClose={() => setPending(null)}
        />
      ) : null}
    </>
  );
}
