"use client";
export function DocumentAttachments({ items, onRetry, onRemove }) {
  if (!items.length) return null;
  return (
    <div className="document-attachments" aria-live="polite">
      {items.map((item) => (
        <div
          className={
            "document-chip " + (item.status === "failed" ? "failed" : "")
          }
          key={item.id}
        >
          <span className="document-symbol">
            {item.name.split(".").pop()?.toUpperCase().slice(0, 5)}
          </span>
          <div>
            <strong>{item.name}</strong>
            <small>
              {item.status === "uploading"
                ? `Uploading ${Math.round((100 * (item.received || 0)) / item.size)}%`
                : item.status === "ready"
                  ? `${(item.size / 1048576).toFixed(1)} MB · Ready`
                  : item.status === "failed"
                    ? item.error || item.info?.error || "Upload failed"
                    : "Preparing file…"}
            </small>
            {item.status === "uploading" && (
              <progress max={item.size} value={item.received || 0} />
            )}
          </div>
          {item.status === "failed" && (
            <button type="button" onClick={() => onRetry(item)}>
              Retry
            </button>
          )}
          <button
            type="button"
            aria-label={"Remove " + item.name}
            onClick={() => onRemove(item)}
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
