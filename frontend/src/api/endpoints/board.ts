import { useQuery } from "@tanstack/react-query";
import { api } from "../client";
import { queryKeys } from "../queryKeys";
import type { Board } from "../types";

/** apps/pipeline/api.py::board only ever reads owner_user_id (a real user id) — client,
 * category and q are not read server-side at all, so they're kept here for the filter
 * bar's own state but never sent to the API. */
export type BoardFilters = {
  owner_user_id?: string;
  client?: string;
  category?: string;
  q?: string;
};

/**
 * The whole board in one request: stages plus lines keyed by current stage. One request
 * rather than one per column, because a column count is not worth a round trip.
 */
export function useBoard(filters: BoardFilters) {
  return useQuery({
    queryKey: queryKeys.board(filters),
    queryFn: ({ signal }) =>
      api.get<Board>("/board", { owner_user_id: filters.owner_user_id }, signal),
  });
}
