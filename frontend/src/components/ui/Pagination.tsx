import { Button } from './Button'
import './Pagination.css'

interface PaginationProps {
  total: number
  limit: number
  offset: number
  onChange: (offset: number) => void
  noun?: string
}

/** "Showing 21–40 of 57 patients" with previous/next. Offsets come straight from the API page parameters. */
export function Pagination({ total, limit, offset, onChange, noun = 'records' }: PaginationProps) {
  if (total === 0) return null
  const first = offset + 1
  const last = Math.min(offset + limit, total)
  const page = Math.floor(offset / limit) + 1
  const pages = Math.max(1, Math.ceil(total / limit))
  return (
    <nav className="pagination" aria-label="Pagination">
      <p className="pagination__summary tabular" aria-live="polite">
        Showing <strong>{first}–{last}</strong> of <strong>{total}</strong> {noun}
      </p>
      <div className="pagination__controls">
        <span className="pagination__page tabular">Page {page} of {pages}</span>
        <Button size="sm" icon="chevronLeft" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}
          aria-label="Previous page">Previous</Button>
        <Button size="sm" iconRight="chevronRight" disabled={last >= total} onClick={() => onChange(offset + limit)}
          aria-label="Next page">Next</Button>
      </div>
    </nav>
  )
}
