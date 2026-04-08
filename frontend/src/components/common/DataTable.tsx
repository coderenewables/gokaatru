import type { ReactNode } from "react";

import { EmptyState } from "./EmptyState";

export type DataTableColumn<T> = {
  key: string;
  header: string;
  cell: (row: T, index: number) => ReactNode;
  className?: string;
};

type DataTableProps<T> = {
  columns: DataTableColumn<T>[];
  rows: T[];
  getRowKey: (row: T, index: number) => string;
  emptyTitle: string;
  emptyDetail: string;
  onRowClick?: (row: T, index: number) => void;
};

export function DataTable<T>({ columns, rows, getRowKey, emptyTitle, emptyDetail, onRowClick }: DataTableProps<T>) {
  if (rows.length === 0) {
    return <EmptyState title={emptyTitle} detail={emptyDetail} />;
  }

  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key}>{column.header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr
              key={getRowKey(row, index)}
              className={onRowClick ? "data-table-row-interactive" : undefined}
              onClick={onRowClick ? () => onRowClick(row, index) : undefined}
            >
              {columns.map((column) => (
                <td key={column.key} className={column.className}>
                  {column.cell(row, index)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}