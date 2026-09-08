import { humanizeCode } from "@/lib/format";

/** User-facing text for job lines. One file per feature, so a Hindi pass has one place to work. */
export const strings = {
  moveTitle: (action: string, line: string) => `${action} — ${line}`,
  moveFrom: "Currently at",
  moveTo: "Moves to",
  noteLabel: "Note",
  noteRequiredHint: "This move needs a note before it can be submitted.",
  noteOptionalHint: "Optional. Anything the next person needs to know.",
  notePlaceholder: "What changed, and why",
  cancel: "Cancel",
  confirm: "Confirm move",
  submitting: "Moving…",
  moved: (line: string, stage: string) => `${line} is now at ${stage}`,
  staleTitle: "This line has already moved",
  staleDetail: "Someone else moved it while this was open. The board has been refreshed.",
  failedTitle: "The move was not applied",
  noActions: "No moves available to you here.",
  timelineTitle: "Stage history",
  timelineEmpty: "Nothing has happened to this line yet.",
  specsTitle: "Specification",
  specsEmpty: "No specification recorded.",
  lineOf: (jobNo: string, lineNo: number) => `${jobNo} · line ${lineNo}`,
  print: "Print job card",
  inStageSince: "In this stage since",
  backToCard: "Back to job card",
  /** apps/pipeline/selectors.py::_block_reason's two known codes, explained rather than
   * left as a raw code — "a greyed-out button that explains itself ... is a usable
   * interface; one that silently vanishes is not" (same file). Anything else falls back
   * to a humanised form of the code, so a future reason never renders as blank. */
  blockedReason: (code: string) =>
    code === "self_approval"
      ? "Needs a second person"
      : code === "condition"
        ? "Not available yet"
        : humanizeCode(code),
} as const;
