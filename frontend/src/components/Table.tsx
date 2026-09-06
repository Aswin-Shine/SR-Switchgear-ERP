import { cx } from "@/lib/cx";
import type { ReactNode } from "react";

export interface Column<T> {
  key: string;
  header: ReactNode;
  /** Numerics are right-aligned and tabular, so columns of money line up. */
  align?: "left" | "right";
  /** Let this cell wrap instead of truncating — descriptions, not identifiers. */
  wrap?: boolean;
  render: (row: T) => ReactNode;
}

export interface TableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  /** Rendered in place of the body when there are no rows. */
  empty?: ReactNode;
  caption?: string;
}

/**
 * Rows are not clickable: the identifier cell holds a real link, so the row is reachable
 * by keyboard and openable in a new tab. A click handler on <tr> is neither.
 */
export function Table<T>({ columns, rows, rowKey, empty, caption }: TableProps<T>) {
  if (rows.length === 0 && empty) {
    return <>{empty}</>;
  }

  return (
    <div className="table-wrap">
      <table className="table">
        {caption ? <caption className="visually-hidden">{caption}</caption> : null}
        <thead>
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                className={cx(column.align === "right" && "numeric")}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={rowKey(row)}>
              {columns.map((column) => (
                <td
                  key={column.key}
                  className={cx(column.align === "right" && "numeric", column.wrap && "wrap")}
                >
                  {column.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
