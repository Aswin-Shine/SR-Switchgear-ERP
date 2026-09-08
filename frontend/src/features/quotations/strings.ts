export const strings = {
  title: "Quotations",
  subtitle: "Revision chain, newest first.",
  empty: "No quotation has been uploaded for this card.",
  revision: (n: number) => `Rev ${n}`,
  superseded: "Superseded",
  validTill: "Valid till",
  /** A cancelled/lost card's quotations keep whatever valid-till date they were
   * issued with — often still in the future — which reads as "still actionable"
   * unless the row itself says the card that owns it is closed. */
  validTillClosed: "— card closed",
  amount: "Amount",
  covers: (count: number) => `${count} ${count === 1 ? "line" : "lines"}`,
  openPdf: "Open PDF",
  newRevision: "Upload revision",
  newRevisionTitle: "Upload quotation revision",
  file: "Quotation PDF",
  fileHint: "The PDF your quotation software produced. This system stores it, it does not make it.",
  amountLabel: "Quoted amount (₹)",
  amountHint: "Exactly as quoted, in rupees.",
  validTillLabel: "Valid till",
  /** See job-cards/strings.ts::dateConfirm for the full reasoning — a static format
   * hint risks contradicting the native picker's own locale rendering, so this shows
   * the actual selected value instead, already correctly formatted. Duplicated here
   * since each feature owns its own strings module. */
  dateConfirm: (formatted: string) => `Selected: ${formatted}`,
  coveredLines: "Lines this quotation covers",
  coveredLinesHint: "At least one. Lines not covered stay where they are.",
  supersedeNote: "Uploading creates the next revision and supersedes the current one.",
  submit: "Upload revision",
  submitting: "Uploading…",
  cancel: "Cancel",
  uploaded: (n: number) => `Revision ${n} uploaded`,
  uploadFailed: "The revision was not uploaded",
  fileRequired: "Choose the quotation PDF.",
  amountRequired: "Enter the quoted amount.",
  linesRequired: "Select at least one line.",
  cardIsDeadNotice: "This job card is closed — no new revisions can be uploaded.",
} as const;
