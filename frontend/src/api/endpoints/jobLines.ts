import { type QueryClient, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../client";
import { AFFECTED_BY_TRANSITION, queryKeys } from "../queryKeys";
import type { JobLine, JobLineDetail, TransitionResult } from "../types";
import type { NewJobLineInput } from "./jobCards";

export function useJobLine(id: string) {
  return useQuery({
    queryKey: queryKeys.jobLine(id),
    queryFn: ({ signal }) => api.get<JobLineDetail>(`/job-lines/${id}`, undefined, signal),
  });
}

/** apps/sales/api.py::job_card_lines (POST) — returns the plain JobLine shape,
 * not a JobLineDetail (no current-stage-as-full-Stage, no history). */
export function useAddJobLine(jobCardId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: NewJobLineInput) =>
      api.post<JobLine>(`/job-cards/${jobCardId}/lines`, input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.jobCard(jobCardId) });
      void queryClient.invalidateQueries({ queryKey: ["board"] });
    },
  });
}

/** apps/sales/api_urls.py routes PATCH to job-lines/{id}/edit, not job-lines/{id} —
 * that bare path is job_line_detail (GET only). apps/sales/api.py::job_line_update
 * returns the plain JobLine shape too. Takes jobCardId explicitly since the plain
 * JobLine shape carries no job_card_id to invalidate by. */
export function useUpdateJobLine(id: string, jobCardId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (patch: Partial<NewJobLineInput>) =>
      api.patch<JobLine>(`/job-lines/${id}/edit`, patch),
    onSuccess: (line) => {
      queryClient.setQueryData(queryKeys.jobLine(id), line);
      void queryClient.invalidateQueries({ queryKey: queryKeys.jobCard(jobCardId) });
      void queryClient.invalidateQueries({ queryKey: ["board"] });
    },
  });
}

export interface TransitionInput {
  action_code: string;
  note?: string;
}

function invalidateAfterTransition(queryClient: QueryClient): void {
  for (const key of AFFECTED_BY_TRANSITION) {
    void queryClient.invalidateQueries({ queryKey: [key] });
  }
}

/**
 * The transition. Deliberately not optimistic: the move is authority-checked server-side
 * and can legitimately fail, so the UI waits and then applies the line the server returns.
 *
 * A 409 means another user moved this line first — apply_transition()'s row lock doing its
 * job. We refetch rather than retry; retrying would replay an action against a stage the
 * line has already left. The caller shows the message.
 */
export function useApplyTransition(lineId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: TransitionInput) =>
      api.post<TransitionResult>(`/job-lines/${lineId}/transitions`, input),
    onSuccess: () => {
      // The transition response is its own narrow shape (see TransitionResult),
      // not a full JobLineDetail — refetch rather than cache it as one.
      void queryClient.invalidateQueries({ queryKey: queryKeys.jobLine(lineId) });
      invalidateAfterTransition(queryClient);
    },
    onError: () => {
      // Whatever went wrong, our copy of this line is now suspect.
      invalidateAfterTransition(queryClient);
    },
  });
}
