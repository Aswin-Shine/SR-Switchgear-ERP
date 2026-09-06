import { ApiError } from "@/api/client";
import { QueryClient } from "@tanstack/react-query";

/**
 * There is no realtime push (see "Not building"). Refetch on window focus plus an explicit
 * refresh is the freshness story: a user who alt-tabs back to the board sees the board as
 * it is, and nobody pays for a socket per seat.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      refetchOnWindowFocus: true,
      retry(failureCount, error) {
        // 4xx is an answer, not a hiccup: a 403 will still be a 403 on the third try.
        if (error instanceof ApiError && error.status < 500) return false;
        return failureCount < 2;
      },
    },
    mutations: {
      retry: false,
    },
  },
});
