import {
  attachmentUrl,
  useJobCardAttachments,
  useRemoveAttachment,
  useUploadAttachment,
} from "@/api/endpoints/jobCards";
import type { Attachment } from "@/api/types";
import { useSession } from "@/auth/SessionProvider";
import { ACTION, RESOURCE } from "@/auth/permissions";
import { Button } from "@/components/Button";
import { DateText } from "@/components/DateText";
import { Dialog } from "@/components/Dialog";
import { QueryState, errorMessage } from "@/components/QueryState";
import { Table } from "@/components/Table";
import { useToast } from "@/components/Toast";
import { useId, useRef, useState } from "react";
import { strings } from "./strings";

const BYTES_IN_KB = 1024;

function formatSize(bytes: number): string {
  if (bytes < BYTES_IN_KB) return `${bytes} B`;
  const kb = bytes / BYTES_IN_KB;
  if (kb < BYTES_IN_KB) return `${Math.round(kb)} KB`;
  return `${(kb / BYTES_IN_KB).toFixed(1)} MB`;
}

export function AttachmentsPanel({ jobCardId }: { jobCardId: string }) {
  const attachments = useJobCardAttachments(jobCardId);
  const upload = useUploadAttachment(jobCardId);
  const remove = useRemoveAttachment(jobCardId);
  const { can } = useSession();
  const { push } = useToast();
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [pendingRemoval, setPendingRemoval] = useState<Attachment | null>(null);
  const canRemove = can(RESOURCE.jobCard, ACTION.edit);

  function confirmRemoval() {
    if (!pendingRemoval) return;
    remove.mutate(pendingRemoval.id, {
      onSuccess: () => {
        push({
          tone: "success",
          title: strings.attachmentRemove,
          detail: strings.attachmentRemoved(pendingRemoval.filename),
        });
        setPendingRemoval(null);
      },
      onError: (error) =>
        push({ tone: "error", title: strings.attachmentRemove, detail: errorMessage(error) }),
    });
  }

  return (
    <section className="panel">
      <div className="panel__head">
        <h2 className="panel__title">{strings.detailAttachments}</h2>
        <span className="panel__count">{attachments.data?.length ?? 0}</span>
      </div>

      <div className="panel__body">
        {can(RESOURCE.document, ACTION.create) ? (
          <div className="stack stack--tight">
            <label className="field__label" htmlFor={inputId}>
              {upload.isPending ? strings.attachmentUploading : strings.attachmentAdd}
            </label>
            <input
              id={inputId}
              ref={inputRef}
              className="input"
              type="file"
              disabled={upload.isPending}
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (!file) return;
                upload.mutate(file, {
                  onSettled: () => {
                    if (inputRef.current) inputRef.current.value = "";
                  },
                  onError: (error) =>
                    push({
                      tone: "error",
                      title: strings.attachmentAdd,
                      detail: errorMessage(error),
                    }),
                });
              }}
            />
            <hr className="divider" />
          </div>
        ) : null}

        <QueryState query={attachments} skeletonRows={2}>
          {(rows) =>
            rows.length === 0 ? (
              <p className="faint">{strings.attachmentEmpty}</p>
            ) : (
              <Table
                caption={strings.detailAttachments}
                rows={rows}
                rowKey={(row) => row.id}
                columns={[
                  {
                    key: "file",
                    header: "File",
                    wrap: true,
                    // The endpoint redirects to storage; bytes never pass through Django.
                    render: (row) => <a href={attachmentUrl(row.id)}>{row.filename}</a>,
                  },
                  {
                    key: "size",
                    header: "Size",
                    align: "right",
                    render: (row) => formatSize(row.byte_size),
                  },
                  { key: "by", header: "Added by", render: (row) => row.attached_by },
                  {
                    key: "at",
                    header: "Added",
                    render: (row) => <DateText value={row.attached_at} />,
                  },
                  ...(canRemove
                    ? [
                        {
                          key: "actions",
                          header: "",
                          align: "right" as const,
                          render: (row: Attachment) => (
                            <Button
                              variant="danger"
                              size="sm"
                              onClick={() => setPendingRemoval(row)}
                            >
                              {strings.attachmentRemove}
                            </Button>
                          ),
                        },
                      ]
                    : []),
                ]}
              />
            )
          }
        </QueryState>
      </div>

      {pendingRemoval ? (
        <Dialog
          open
          title={strings.attachmentRemoveTitle}
          onClose={remove.isPending ? () => undefined : () => setPendingRemoval(null)}
          footer={
            <>
              <Button onClick={() => setPendingRemoval(null)} disabled={remove.isPending}>
                {strings.cancel}
              </Button>
              <Button variant="danger" onClick={confirmRemoval} loading={remove.isPending}>
                {remove.isPending ? strings.attachmentRemoving : strings.attachmentRemoveConfirm}
              </Button>
            </>
          }
        >
          <p>{strings.attachmentRemoveBody(pendingRemoval.filename)}</p>
        </Dialog>
      ) : null}
    </section>
  );
}
