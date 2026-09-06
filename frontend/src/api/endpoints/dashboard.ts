import { useQuery } from "@tanstack/react-query";
import { api } from "../client";
import { queryKeys } from "../queryKeys";
import type { Dashboard } from "../types";

/**
 * One endpoint rather than four, because "lines where I have an available action" is the
 * available_actions query run in bulk — a server-side join, not a loop over the board.
 */
export function useDashboard() {
  return useQuery({
    queryKey: queryKeys.dashboard,
    queryFn: ({ signal }) => api.get<Dashboard>("/dashboard", undefined, signal),
  });
}
