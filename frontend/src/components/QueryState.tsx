import { ApiError } from "@/api/client";
import type { UseQueryResult } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Button } from "./Button";

export function Skeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="stack stack--tight" aria-hidden="true">
      {Array.from({ length: rows }, (_, index) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: placeholder rows have no identity
        <div className="skeleton" key={index} />
      ))}
    </div>
  );
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.isForbidden) {
      return "You do not have permission for this. Ask your manager if you think you should.";
    }
    return error.message;
  }
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}

export function ErrorNotice({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const details = error instanceof ApiError ? error.fieldMessages() : [];
  return (
    <div className="error-panel" role="alert">
      <strong>{errorMessage(error)}</strong>
      {details.length > 0 ? (
        <ul>
          {details.map(([field, message]) => (
            <li key={`${field}:${message}`}>
              <span className="muted">{field}:</span> {message}
            </li>
          ))}
        </ul>
      ) : null}
      {onRetry ? (
        <div>
          <Button onClick={onRetry}>Try again</Button>
        </div>
      ) : null}
    </div>
  );
}

/**
 * Loading and error handling in one place, so screens are about their own content.
 * Data is passed to the render prop rather than to context: a screen that renders is a
 * screen whose data arrived.
 */
export function QueryState<T>({
  query,
  skeletonRows,
  children,
}: {
  query: UseQueryResult<T>;
  skeletonRows?: number;
  children: (data: T) => ReactNode;
}) {
  if (query.isPending) return <Skeleton rows={skeletonRows} />;
  if (query.isError)
    return <ErrorNotice error={query.error} onRetry={() => void query.refetch()} />;
  return <>{children(query.data)}</>;
}
