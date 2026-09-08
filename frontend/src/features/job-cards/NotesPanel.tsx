import { useAddNote, useJobCardNotes } from "@/api/endpoints/jobCards";
import { useSession } from "@/auth/SessionProvider";
import { ACTION, RESOURCE } from "@/auth/permissions";
import { Button } from "@/components/Button";
import { DateText } from "@/components/DateText";
import { QueryState } from "@/components/QueryState";
import { errorMessage } from "@/components/QueryState";
import { useToast } from "@/components/Toast";
import { useId, useState } from "react";
import { strings } from "./strings";

export function NotesPanel({
  jobCardId,
  cardIsDead,
}: {
  jobCardId: string;
  /** True once the job card is cancelled or lost. Existing notes stay visible — this
   * is a communication record, not a production input — but adding new ones is gated
   * off, the same way the quotation and attachment panels are on a dead card. */
  cardIsDead: boolean;
}) {
  const notes = useJobCardNotes(jobCardId);
  const addNote = useAddNote(jobCardId);
  const { can } = useSession();
  const { push } = useToast();
  const [draft, setDraft] = useState("");
  const draftId = useId();

  function submit() {
    const body = draft.trim();
    if (!body) return;
    addNote.mutate(body, {
      onSuccess: () => setDraft(""),
      onError: (error) =>
        push({ tone: "error", title: strings.addNote, detail: errorMessage(error) }),
    });
  }

  return (
    <section className="panel">
      <div className="panel__head">
        <h2 className="panel__title">{strings.detailNotes}</h2>
        <span className="panel__count">{notes.data?.length ?? 0}</span>
      </div>

      <div className="panel__body">
        {cardIsDead ? <p className="faint">{strings.noteCardIsDeadNotice}</p> : null}

        {can(RESOURCE.jobNote, ACTION.create) && !cardIsDead ? (
          <div className="stack stack--tight">
            <label className="visually-hidden" htmlFor={draftId}>
              {strings.addNote}
            </label>
            <textarea
              id={draftId}
              className="textarea"
              value={draft}
              placeholder={strings.notePlaceholder}
              onChange={(event) => setDraft(event.target.value)}
            />
            <div className="row">
              <Button
                variant="primary"
                size="sm"
                onClick={submit}
                disabled={draft.trim().length === 0}
                loading={addNote.isPending}
              >
                {strings.addNote}
              </Button>
            </div>
            <hr className="divider" />
          </div>
        ) : null}

        <QueryState query={notes} skeletonRows={3}>
          {(rows) =>
            rows.length === 0 ? (
              <p className="faint">{strings.noteEmpty}</p>
            ) : (
              <ol>
                {rows.map((note) => (
                  <li className="note" key={note.id}>
                    <div className="note__meta">
                      <strong>{note.author}</strong>
                      <DateText value={note.created_at} withTime />
                    </div>
                    <p className="note__body">{note.body}</p>
                  </li>
                ))}
              </ol>
            )
          }
        </QueryState>
      </div>
    </section>
  );
}
