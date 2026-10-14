"use client";
import { useState, useEffect } from "react";
export function Pagination({
  total = 0,
  offset = 0,
  limit = 25,
  onPage,
  onLimit,
  busy = false,
  label = "records",
}) {
  const pages = Math.max(1, Math.ceil(total / limit)),
    page = Math.floor(offset / limit) + 1;
  const [jump, setJump] = useState(String(page));
  useEffect(() => setJump(String(page)), [page]);
  const numbers = [
    ...new Set([
      1,
      ...Array.from({ length: 5 }, (_, i) => page - 2 + i).filter(
        (n) => n > 0 && n <= pages,
      ),
      pages,
    ]),
  ].sort((a, b) => a - b);
  return (
    <nav
      className="data-pagination pagination"
      aria-label={`${label} pagination`}
    >
      <span>
        {total
          ? `${offset + 1}–${Math.min(offset + limit, total)} of ${total.toLocaleString()}`
          : "0"}{" "}
        {label}
      </span>
      {onLimit && (
        <label>
          Rows per page
          <select
            aria-label={`${label} rows per page`}
            value={limit}
            disabled={busy}
            onChange={(e) => onLimit(Number(e.target.value))}
          >
            {[10, 25, 50, 100].map((n) => (
              <option key={n}>{n}</option>
            ))}
          </select>
        </label>
      )}
      <div className="page-buttons pagination-controls">
        <button
          className="button small"
          aria-label={`First ${label} page`}
          disabled={busy || page <= 1}
          onClick={() => onPage(0)}
        >
          «
        </button>
        <button
          className="button small"
          aria-label={`Previous ${label} page`}
          disabled={busy || page <= 1}
          onClick={() => onPage(Math.max(0, offset - limit))}
        >
          Previous
        </button>
        {numbers.map((n, i) => (
          <span key={n}>
            {i > 0 && n - numbers[i - 1] > 1 && (
              <span className="page-gap">…</span>
            )}
            <button
              className={"button small " + (n === page ? "page-current" : "")}
              aria-label={`${label} page ${n}`}
              aria-current={n === page ? "page" : undefined}
              disabled={busy}
              onClick={() => onPage((n - 1) * limit)}
            >
              {n}
            </button>
          </span>
        ))}
        <button
          className="button small"
          aria-label={`Next ${label} page`}
          disabled={busy || page >= pages}
          onClick={() => onPage(offset + limit)}
        >
          Next
        </button>
        <button
          className="button small"
          aria-label={`Last ${label} page`}
          disabled={busy || page >= pages}
          onClick={() => onPage((pages - 1) * limit)}
        >
          »
        </button>
      </div>
      <form
        className="page-jump"
        onSubmit={(e) => {
          e.preventDefault();
          const value = Number(jump);
          if (Number.isInteger(value) && value >= 1 && value <= pages)
            onPage((value - 1) * limit);
        }}
      >
        <label>
          Go to page
          <input
            aria-label={`${label} go to page`}
            type="number"
            min="1"
            max={pages}
            value={jump}
            disabled={busy}
            onChange={(e) => setJump(e.target.value)}
          />
        </label>
        <button className="button small" disabled={busy}>
          Go
        </button>
      </form>
    </nav>
  );
}
