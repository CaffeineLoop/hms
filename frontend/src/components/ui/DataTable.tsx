/**
 * Data table for clinical/operational lists.
 * - Columns declare a `priority`: 'secondary' columns hide below 1100px, 'tertiary' below 1280px, so the
 *   identifying and clinically important columns ('primary') always remain readable on laptops/tablets.
 * - The container scrolls horizontally instead of squashing; the first column stays pinned.
 * - Rows can be clickable (keyboard-activatable) for drill-down.
 */
import type { KeyboardEvent, ReactNode } from 'react'
import { LoadingState } from './States'
import './DataTable.css'

export interface Column<T> {
  key: string
  header: ReactNode
  render: (row: T) => ReactNode
  align?: 'left' | 'right' | 'center'
  width?: number | string
  priority?: 'primary' | 'secondary' | 'tertiary'
  numeric?: boolean
}

interface DataTableProps<T> {
  columns: Column<T>[]
  rows: T[] | undefined
  rowKey: (row: T) => string
  caption: string
  loading?: boolean
  empty?: ReactNode
  onRowClick?: (row: T) => void
  rowLabel?: (row: T) => string
  density?: 'comfortable' | 'compact'
}

export function DataTable<T>({ columns, rows, rowKey, caption, loading, empty, onRowClick, rowLabel,
  density = 'comfortable' }: DataTableProps<T>) {
  if (loading && !rows) return <LoadingState rows={5} label={`Loading ${caption.toLowerCase()}`} />
  if (rows && rows.length === 0 && empty) return <>{empty}</>

  function onKeyDown(event: KeyboardEvent<HTMLTableRowElement>, row: T) {
    if (onRowClick && (event.key === 'Enter' || event.key === ' ')) {
      event.preventDefault()
      onRowClick(row)
    }
  }

  return (
    <div className={`table-wrap table-wrap--${density}`}>
      <table className="table">
        <caption className="visually-hidden">{caption}</caption>
        <thead>
          <tr>
            {columns.map((col) => (
              <th key={col.key} scope="col" style={{ width: col.width, textAlign: col.align }}
                className={`col--${col.priority ?? 'primary'}`}>
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows?.map((row) => (
            <tr key={rowKey(row)} className={onRowClick ? 'is-clickable' : undefined}
              tabIndex={onRowClick ? 0 : undefined} aria-label={onRowClick && rowLabel ? rowLabel(row) : undefined}
              onClick={onRowClick ? () => onRowClick(row) : undefined} onKeyDown={(e) => onKeyDown(e, row)}>
              {columns.map((col) => (
                <td key={col.key} style={{ textAlign: col.align }}
                  className={[`col--${col.priority ?? 'primary'}`, col.numeric ? 'tabular' : ''].join(' ')}>
                  {col.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
