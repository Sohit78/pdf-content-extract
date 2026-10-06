"use client";

import { ComponentType, KeyboardEvent, useMemo, useState } from "react";
import Image from "next/image";

import {
  IconAlert,
  IconBraces,
  IconCheck,
  IconCopy,
  IconDownload,
  IconGauge,
  IconImage,
  IconFile,
  IconTable,
  IconText,
} from "@/components/icons";
import { ExtractionResponse } from "@/lib/types";

interface Props {
  result: ExtractionResponse | null;
  busy: boolean;
  error: string | null;
}

type View = "summary" | "document" | "text" | "tables" | "images" | "json";

const TABS: Array<{ id: View; label: string; Icon: ComponentType<{ className?: string }> }> = [
  { id: "summary", label: "Summary", Icon: IconGauge },
  { id: "document", label: "Document", Icon: IconFile },
  { id: "text", label: "Text", Icon: IconText },
  { id: "tables", label: "Tables", Icon: IconTable },
  { id: "images", label: "Images", Icon: IconImage },
  { id: "json", label: "JSON", Icon: IconBraces },
];

const TEXT_PAGE_SIZE = 20;

function formatBytes(bytes?: number): string {
  if (!bytes && bytes !== 0) return "unknown";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function pageSummary(pages?: number[], fallback?: number): string {
  if (!pages || pages.length === 0) return `p${fallback ?? "?"}`;
  if (pages.length === 1) return `p${pages[0]}`;
  if (pages.length <= 3) return `p${pages.join(", ")}`;
  return `p${pages[0]}–${pages[pages.length - 1]} (${pages.length})`;
}

function toDataUrl(mimeType?: string, bytesBase64?: string): string | null {
  if (!bytesBase64) return null;
  return `data:${mimeType || "application/octet-stream"};base64,${bytesBase64}`;
}

function downloadBlob(content: string, filename: string, mimeType: string) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function escapeCsv(value: string | null | undefined): string {
  const safe = (value ?? "").replace(/"/g, '""');
  return `"${safe}"`;
}

export function ResultPanel({ result, busy, error }: Props) {
  const [view, setView] = useState<View>("summary");
  const [notice, setNotice] = useState("");
  const [textLimit, setTextLimit] = useState(TEXT_PAGE_SIZE);

  const prettyJson = useMemo(() => (result ? JSON.stringify(result, null, 2) : ""), [result]);

  const textDump = useMemo(() => {
    if (!result) return "";
    return result.text
      .map((item) => `Page ${item.page}\n${item.content || "(No text extracted)"}`)
      .join("\n\n====================\n\n");
  }, [result]);

  const tablesCsvDump = useMemo(() => {
    if (!result) return "";
    return result.tables
      .map((table) => {
        const header = `# Page ${table.page} - Table ${table.table_index}`;
        const rows = table.rows.map((row) => row.map((cell) => escapeCsv(cell)).join(",")).join("\n");
        return `${header}\n${rows}`;
      })
      .join("\n\n");
  }, [result]);

  const flashNotice = (message: string) => {
    setNotice(message);
    window.setTimeout(() => setNotice(""), 1800);
  };

  const copyToClipboard = async (value: string, message: string) => {
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      flashNotice(message);
    } catch {
      flashNotice("Clipboard blocked by the browser");
    }
  };

  const counts: Record<View, number | null> = {
    summary: null,
    document: null,
    text: result?.text.length ?? null,
    tables: result?.tables.length ?? null,
    images: result?.images.length ?? null,
    json: null,
  };

  const onTabKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const index = TABS.findIndex((tab) => tab.id === view);
    if (event.key === "ArrowRight") {
      event.preventDefault();
      setView(TABS[(index + 1) % TABS.length].id);
    } else if (event.key === "ArrowLeft") {
      event.preventDefault();
      setView(TABS[(index - 1 + TABS.length) % TABS.length].id);
    }
  };

  const actions = () => {
    if (!result) return null;
    if (view === "text") {
      return (
        <>
          <button
            className="btn"
            onClick={() => copyToClipboard(textDump, "Text copied")}
            disabled={result.text.length === 0}
          >
            <IconCopy />
            Copy text
          </button>
          <button
            className="btn"
            onClick={() => {
              downloadBlob(textDump, `quarry-text-${Date.now()}.txt`, "text/plain");
              flashNotice("Text file downloaded");
            }}
            disabled={result.text.length === 0}
          >
            <IconDownload />
            .txt
          </button>
        </>
      );
    }
    if (view === "tables") {
      return (
        <>
          <button
            className="btn"
            onClick={() => copyToClipboard(tablesCsvDump, "Tables copied")}
            disabled={result.tables.length === 0}
          >
            <IconCopy />
            Copy CSV
          </button>
          <button
            className="btn"
            onClick={() => {
              downloadBlob(tablesCsvDump, `quarry-tables-${Date.now()}.csv`, "text/csv");
              flashNotice("Tables CSV downloaded");
            }}
            disabled={result.tables.length === 0}
          >
            <IconDownload />
            .csv
          </button>
        </>
      );
    }
    if (view === "images") return null;
    return (
      <>
        <button className="btn" onClick={() => copyToClipboard(prettyJson, "JSON copied")}>
          <IconCopy />
          Copy JSON
        </button>
        <button
          className="btn"
          onClick={() => {
            downloadBlob(prettyJson, `quarry-extract-${Date.now()}.json`, "application/json");
            flashNotice("JSON downloaded");
          }}
        >
          <IconDownload />
          .json
        </button>
      </>
    );
  };

  return (
    <section className="card results">
      <div className="results-head">
        <div className="results-title">
          <h2>Yield</h2>
          {result ? (
            <p className="results-source">
              <code title={result.source_url}>{result.source_url}</code>
              <span aria-hidden="true">·</span>
              <span>{new Date(result.extracted_at).toLocaleTimeString()}</span>
              {result.meta?.cache === "hit" ? (
                <span className="badge" title="Served from the content-addressed cache">
                  cached
                </span>
              ) : null}
            </p>
          ) : (
            <p className="results-source">Nothing extracted yet</p>
          )}
        </div>
        <div className="results-actions">{actions()}</div>
      </div>

      {busy ? <div className="progress-line" aria-hidden="true" /> : null}

      <div className="tabs" role="tablist" aria-label="Extraction output" onKeyDown={onTabKeyDown}>
        {TABS.map(({ id, label, Icon }) => (
          <button
            key={id}
            role="tab"
            id={`tab-${id}`}
            aria-selected={view === id}
            aria-controls={`panel-${id}`}
            tabIndex={view === id ? 0 : -1}
            className="tab"
            onClick={() => setView(id)}
          >
            <Icon />
            {label}
            {counts[id] !== null ? <span className="tab-count">{counts[id]}</span> : null}
          </button>
        ))}
      </div>

      <div className="tab-panel" role="tabpanel" id={`panel-${view}`} aria-labelledby={`tab-${view}`}>
        {busy ? (
          <div className="skeleton-wrap" aria-live="polite" aria-busy="true">
            <span className="sr-only">Extracting, please wait.</span>
            <div className="skeleton" />
            <div className="skeleton" />
            <div className="skeleton" />
          </div>
        ) : error ? (
          <div className="alert" role="alert">
            <IconAlert />
            <div>
              <p className="alert-title">Extraction failed</p>
              <p className="alert-body">{error}</p>
            </div>
          </div>
        ) : !result ? (
          <div className="state">
            <span className="state-icon">
              <IconGauge />
            </span>
            <h3>No results yet</h3>
            <p>
              Point Quarry at a PDF and it returns the text, tables, and images as structured JSON
              you can copy or download.
            </p>
            <div className="state-steps">
              <span className="state-step">
                <b>1</b> Pick a source
              </span>
              <span className="state-step">
                <b>2</b> Set the options
              </span>
              <span className="state-step">
                <b>3</b> Run extraction
              </span>
            </div>
          </div>
        ) : view === "summary" ? (
          <>
            <div className="stat-grid">
              <div className="stat">
                <p className="stat-label">Pages read</p>
                <p className="stat-value">
                  {result.page_count}
                  <span className="unit">/ {result.total_pages}</span>
                </p>
              </div>
              <div className="stat">
                <p className="stat-label">Text blocks</p>
                <p className="stat-value">{result.text.length}</p>
              </div>
              <div className="stat">
                <p className="stat-label">Tables</p>
                <p className="stat-value">{result.tables.length}</p>
              </div>
              <div className="stat">
                <p className="stat-label">Images</p>
                <p className="stat-value">{result.images.length}</p>
              </div>
              <div className="stat">
                <p className="stat-label">Processing</p>
                <p className="stat-value">
                  {result.meta?.processing_ms ?? 0}
                  <span className="unit">ms</span>
                </p>
              </div>
            </div>
            <div className="meta-strip">
              <span>
                Extracted <strong>{new Date(result.extracted_at).toLocaleString()}</strong>
              </span>
              <span>
                Cache <strong>{result.meta?.cache ?? "—"}</strong>
              </span>
              {result.meta?.ocr && result.meta.ocr.performed + result.meta.ocr.cached > 0 ? (
                <span>
                  OCR <strong>{result.meta.ocr.performed} run</strong>,{" "}
                  <strong>{result.meta.ocr.cached} reused</strong>
                </span>
              ) : null}
              {result.meta?.selected_pages?.length ? (
                <span>
                  Pages{" "}
                  <strong>
                    {result.meta.selected_pages[0]}–
                    {result.meta.selected_pages[result.meta.selected_pages.length - 1]}
                  </strong>
                </span>
              ) : null}
            </div>
          </>
        ) : view === "document" ? (
          !result.document ? (
            <p className="muted">
              Document info was turned off for this run. Enable “Document info” and run again.
            </p>
          ) : (
            <div className="stack">
              <article className="entry">
                <div className="entry-head">
                  <span className="entry-title">Metadata</span>
                  {result.document.metadata.encrypted ? (
                    <span className="badge">encrypted</span>
                  ) : null}
                </div>
                <div className="entry-body">
                  <dl className="kv">
                    {Object.entries(result.document.metadata)
                      .filter(([key, value]) => key !== "encrypted" && value)
                      .map(([key, value]) => (
                        <div key={key}>
                          <dt>{key}</dt>
                          <dd>{String(value)}</dd>
                        </div>
                      ))}
                  </dl>
                  {Object.entries(result.document.metadata).filter(
                    ([k, v]) => k !== "encrypted" && v,
                  ).length === 0 ? (
                    <p className="muted">This PDF carries no metadata.</p>
                  ) : null}
                </div>
              </article>

              <article className="entry">
                <div className="entry-head">
                  <span className="entry-title">Outline</span>
                  <span className="toggle-note">{result.document.outline.length} entries</span>
                </div>
                <div className="entry-body">
                  {result.document.outline.length === 0 ? (
                    <p className="muted">No bookmarks in this document.</p>
                  ) : (
                    <ul className="outline">
                      {result.document.outline.map((item, i) => (
                        <li key={`toc-${i}`} style={{ paddingLeft: `${(item.level - 1) * 16}px` }}>
                          <span className="outline-title">{item.title}</span>
                          <span className="outline-page">p{item.page}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </article>

              <article className="entry">
                <div className="entry-head">
                  <span className="entry-title">Links</span>
                  <span className="toggle-note">{result.document.links.length} found</span>
                </div>
                <div className="entry-body">
                  {result.document.links.length === 0 ? (
                    <p className="muted">No links on the selected pages.</p>
                  ) : (
                    <ul className="link-list">
                      {result.document.links.slice(0, 50).map((link, i) => (
                        <li key={`link-${i}`}>
                          <span className="link-page">p{link.page}</span>
                          {link.uri ? (
                            <a href={link.uri} target="_blank" rel="noreferrer noopener">
                              {link.uri}
                            </a>
                          ) : (
                            <span>→ page {link.target_page}</span>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                  {result.document.links.length > 50 ? (
                    <p className="hint">Showing 50 of {result.document.links.length}.</p>
                  ) : null}
                </div>
              </article>
            </div>
          )
        ) : view === "text" ? (
          result.text.length === 0 ? (
            <p className="muted">No text extracted. Try OCR mode auto or force.</p>
          ) : (
            <div className="stack">
              {result.text.slice(0, textLimit).map((item) => (
                <article key={`text-${item.page}`} className="entry">
                  <div className="entry-head">
                    <span className="entry-title">Page {item.page}</span>
                    <button
                      className="btn btn-icon"
                      onClick={() => copyToClipboard(item.content, `Page ${item.page} copied`)}
                      aria-label={`Copy text from page ${item.page}`}
                    >
                      <IconCopy />
                    </button>
                  </div>
                  <div className="entry-body">
                    <pre className={`entry-text${item.content ? "" : " entry-empty"}`}>
                      {item.content || "No text on this page."}
                    </pre>
                  </div>
                </article>
              ))}
              {result.text.length > textLimit ? (
                <button
                  className="btn"
                  onClick={() => setTextLimit((n) => n + TEXT_PAGE_SIZE)}
                >
                  Show {Math.min(TEXT_PAGE_SIZE, result.text.length - textLimit)} more of{" "}
                  {result.text.length}
                </button>
              ) : null}
            </div>
          )
        ) : view === "tables" ? (
          result.tables.length === 0 ? (
            <p className="muted">No tables detected in the selected pages.</p>
          ) : (
            <div className="stack">
              {result.tables.map((table, idx) => (
                <article key={`table-${idx}`} className="entry">
                  <div className="entry-head">
                    <span className="entry-title">
                      Page {table.page} · Table {table.table_index}
                    </span>
                    <span className="toggle-note">{table.rows.length} rows</span>
                  </div>
                  <div className="entry-body">
                    <div className="table-scroll">
                      <table>
                        <tbody>
                          {table.rows.slice(0, 12).map((row, rowIdx) => (
                            <tr key={`row-${rowIdx}`}>
                              {row.slice(0, 10).map((cell, cellIdx) => (
                                <td key={`cell-${cellIdx}`}>{cell ?? ""}</td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    {table.rows.length > 12 ? (
                      <p className="hint">
                        Showing 12 of {table.rows.length} rows — download the CSV for the rest.
                      </p>
                    ) : null}
                  </div>
                </article>
              ))}
            </div>
          )
        ) : view === "images" ? (
          result.images.length === 0 ? (
            <p className="muted">No images extracted from the selected pages.</p>
          ) : (
            <div className="image-grid">
              {result.images.map((img, idx) => {
                const dataUrl = toDataUrl(img.mime_type, img.bytes_base64);
                return (
                  <article key={`img-${idx}`} className="image-card">
                    <div className="image-frame-wrap">
                      {dataUrl ? (
                        <Image
                          src={dataUrl}
                          alt={`Image ${img.image_index} extracted from page ${img.page}`}
                          width={img.width || 800}
                          height={img.height || 600}
                          unoptimized
                          className="image-frame"
                        />
                      ) : (
                        <span className="muted">Inventory only</span>
                      )}
                    </div>
                    <div className="image-meta">
                      <span title={img.pages ? `Pages ${img.pages.join(", ")}` : undefined}>
                        {pageSummary(img.pages, img.page)} · {img.width ?? "?"}×
                        {img.height ?? "?"}
                      </span>
                      <span>{formatBytes(img.size_bytes)}</span>
                    </div>
                    {dataUrl ? (
                      <div className="image-meta">
                        <span>
                          {img.ext ?? "bin"}
                          {img.occurrences && img.occurrences > 1 ? ` ×${img.occurrences}` : ""}
                        </span>
                        <button
                          className="btn btn-icon"
                          onClick={() => {
                            const a = document.createElement("a");
                            a.href = dataUrl;
                            a.download = `page-${img.page}-image-${img.image_index}.${img.ext || "bin"}`;
                            a.click();
                            flashNotice(`Image ${img.image_index} downloaded`);
                          }}
                          aria-label={`Download image ${img.image_index} from page ${img.page}`}
                        >
                          <IconDownload />
                        </button>
                      </div>
                    ) : null}
                  </article>
                );
              })}
            </div>
          )
        ) : (
          <pre className="json-view">{prettyJson}</pre>
        )}
      </div>

      {notice ? (
        <div className="toast" role="status">
          <IconCheck />
          {notice}
        </div>
      ) : null}
    </section>
  );
}
