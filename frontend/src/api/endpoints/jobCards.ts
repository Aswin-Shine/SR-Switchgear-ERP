import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, request } from "../client";
import { queryKeys } from "../queryKeys";
import type { Attachment, JobCardDetail, JobCardSummary, Note, Paginated } from "../types";

/** apps/sales/api.py::job_cards (GET) reads exactly these query params — "mine=1" is a
 * boolean flag (the current user), not an arbitrary owner id; there is no such thing. */
export type JobCardFilters = {
  /** "1" to scope to the signed-in user's own cards — idx_job_cards_open. */
  mine?: string;
  /** Comma-separated status codes, e.g. `open,quoted`. Values come from /enums. */
  status?: string;
  client_id?: string;
  q?: string;
  page?: string;
};

/** apps/sales/api.py::job_cards (POST) pops client_id for the client lookup, then passes
 * the rest straight to services.create_job_card, whose _JOB_CARD_FIELDS accepts exactly
 * these — no "contact_id" (it's client_contact), no "title" or "source" (it's
 * enquiry_source) at all. Lines are NOT created with the card: add_job_line is a
 * separate POST per line to job-cards/{id}/lines after this one returns. */
export interface NewJobCardInput {
  client_id: string;
  client_contact?: string | null;
  enquiry_source?: string | null;
  enquiry_date?: string;
  required_by?: string | null;
  /** Optional: the server seeds it from the client when omitted. */
  dispatch_policy?: string | null;
  requirements?: Record<string, string>;
}

export interface NewJobLineInput {
  product_category_id: string;
  description: string;
  quantity?: number;
  required_by?: string | null;
  specs?: Record<string, string>;
}

export function useJobCards(filters: JobCardFilters) {
  return useQuery({
    queryKey: queryKeys.jobCards(filters),
    queryFn: ({ signal }) =>
      api.get<Paginated<JobCardSummary>>("/job-cards", { ...filters }, signal),
  });
}

export function useJobCard(id: string) {
  return useQuery({
    queryKey: queryKeys.jobCard(id),
    queryFn: ({ signal }) => api.get<JobCardDetail>(`/job-cards/${id}`, undefined, signal),
  });
}

/** apps/sales/api.py::job_cards (POST) returns the plain serialize_job_card shape, not a
 * JobCardDetail — a freshly created card has no lines yet, and none are created with it
 * (see NewJobCardInput's note: lines are separate POSTs, one per line). */
export function useCreateJobCard() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: NewJobCardInput) => api.post<JobCardSummary>("/job-cards", input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["job-cards"] });
      void queryClient.invalidateQueries({ queryKey: ["board"] });
      void queryClient.invalidateQueries({ queryKey: queryKeys.dashboard });
    },
  });
}

/** apps/sales/api.py::job_card_detail (PATCH) also returns the plain shape. */
export function useUpdateJobCard(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (patch: Partial<NewJobCardInput>) =>
      api.patch<JobCardSummary>(`/job-cards/${id}`, patch),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.jobCard(id) });
      void queryClient.invalidateQueries({ queryKey: ["job-cards"] });
    },
  });
}

export function useJobCardNotes(id: string) {
  return useQuery({
    queryKey: queryKeys.jobCardNotes(id),
    queryFn: async ({ signal }) => {
      const body = await api.get<{ items: Note[] }>(`/job-cards/${id}/notes`, undefined, signal);
      return body.items;
    },
  });
}

export function useAddNote(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: string) => api.post<Note>(`/job-cards/${id}/notes`, { body }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.jobCardNotes(id) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.jobCard(id) });
    },
  });
}

export function useJobCardAttachments(id: string) {
  return useQuery({
    queryKey: queryKeys.jobCardAttachments(id),
    queryFn: async ({ signal }) => {
      const body = await api.get<{ items: Attachment[] }>(
        `/job-cards/${id}/attachments`,
        undefined,
        signal,
      );
      return body.items;
    },
  });
}

export function useUploadAttachment(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.set("file", file);
      return api.upload<Attachment>(`/job-cards/${id}/attachments`, form);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.jobCardAttachments(id) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.jobCard(id) });
    },
  });
}

export function useRemoveAttachment(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (attachmentId: string) =>
      api.delete<void>(`/job-cards/${id}/attachments/${attachmentId}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.jobCardAttachments(id) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.jobCard(id) });
    },
  });
}

/** Attachment bytes are never proxied through the SPA; the server redirects to storage. */
export function attachmentUrl(attachmentId: string): string {
  return `/api/v1/attachments/${attachmentId}/download`;
}

export function fetchJobCard(id: string, signal?: AbortSignal) {
  return request<JobCardDetail>(`/job-cards/${id}`, { signal });
}
