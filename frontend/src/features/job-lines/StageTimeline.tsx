import type { StageRef, TransitionEvent } from "@/api/types";
import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { StageChip } from "@/components/StageChip";
import { humanizeCode } from "@/lib/format";
import { strings } from "./strings";

/** History entries carry only a stage *code*, not a full StageRef (see
 * api/types.ts::TransitionEvent) — StageChip needs an object, so this fills in a
 * humanized name from the code. Its `id` is never read by StageChip. */
function stageRefFromCode(code: string): StageRef {
  return { id: code, code, name: humanizeCode(code) };
}

/** The audit trail as the user sees it: newest first, every move attributable. */
export function StageTimeline({ transitions }: { transitions: TransitionEvent[] }) {
  if (transitions.length === 0) {
    return <EmptyState title={strings.timelineEmpty} />;
  }

  const ordered = [...transitions].sort(
    (a, b) => new Date(b.performed_at).getTime() - new Date(a.performed_at).getTime(),
  );

  return (
    <ol className="timeline">
      {ordered.map((event) => (
        <li className="timeline__item" key={event.id}>
          <span className="timeline__dot" aria-hidden="true" />
          <div className="timeline__body">
            <div className="row">
              <strong>{humanizeCode(event.action_code)}</strong>
              {event.from_stage ? <StageChip stage={stageRefFromCode(event.from_stage)} /> : null}
              {event.from_stage ? <span aria-hidden="true">→</span> : null}
              <StageChip stage={stageRefFromCode(event.to_stage)} />
            </div>
            <p className="timeline__meta">
              {event.performed_by} · <DateText value={event.performed_at} withTime />
            </p>
            {event.note ? <p className="timeline__note">{event.note}</p> : null}
          </div>
        </li>
      ))}
    </ol>
  );
}
