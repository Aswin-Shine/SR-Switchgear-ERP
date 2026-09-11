import { useMutation } from "@tanstack/react-query";
import { api } from "../client";

/**
 * apps/sales/api.py::sync_job_sheet — same full overwrite the sheets-sync sidecar runs
 * on its 5-hour timer, triggered on demand. Writes to the external Google Sheet only;
 * nothing in our own cache needs invalidating.
 */
export function useSyncJobSheet() {
  return useMutation({
    mutationFn: () => api.post<{ synced: number }>("/sync-job-sheet"),
  });
}
