import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../client";
import { queryKeys } from "../queryKeys";
import type { Quotation } from "../types";

/** The revision chain for a card, newest revision first. apps/sales/api.py::
 * job_card_quotations (GET) returns {"items": [...]}, not {"results": [...]}. */
export function useQuotations(jobCardId: string) {
  return useQuery({
    queryKey: queryKeys.jobCardQuotations(jobCardId),
    queryFn: async ({ signal }) => {
      const body = await api.get<{ items: Quotation[] }>(
        `/job-cards/${jobCardId}/quotations`,
        undefined,
        signal,
      );
      return [...body.items].sort((a, b) => b.revision_no - a.revision_no);
    },
  });
}

/** apps/sales/api.py::job_card_quotations (POST) only reads quoted_amount, pdf, and
 * valid_till from the multipart body — it has never accepted covered_line_ids or a
 * field named "file"/"amount". Field names below match what the server actually reads. */
export interface NewRevisionInput {
  pdf: File;
  quoted_amount: string;
  valid_till: string;
}

/**
 * Uploading a revision creates N+1 and supersedes N — the server does both, in one
 * transaction.
 */
export function useUploadRevision(jobCardId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: NewRevisionInput) => {
      const form = new FormData();
      form.set("pdf", input.pdf);
      form.set("quoted_amount", input.quoted_amount);
      form.set("valid_till", input.valid_till);
      return api.upload<Quotation>(`/job-cards/${jobCardId}/quotations`, form);
    },
    onSuccess: () => invalidateCard(queryClient, jobCardId),
  });
}

function invalidateCard(queryClient: ReturnType<typeof useQueryClient>, jobCardId: string): void {
  void queryClient.invalidateQueries({ queryKey: queryKeys.jobCardQuotations(jobCardId) });
  void queryClient.invalidateQueries({ queryKey: queryKeys.jobCard(jobCardId) });
  void queryClient.invalidateQueries({ queryKey: ["board"] });
  void queryClient.invalidateQueries({ queryKey: queryKeys.dashboard });
}

/**
 * A plain link: the endpoint 302s to a time-limited storage URL. The bytes never pass
 * through Django, and never through this app.
 */
export function quotationPdfUrl(quotationId: string): string {
  return `/api/v1/quotations/${quotationId}/pdf`;
}
