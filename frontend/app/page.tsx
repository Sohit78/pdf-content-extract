"use client";

import { DragEvent, FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { OptionsPanel } from "@/components/OptionsPanel";
import { ResultPanel } from "@/components/ResultPanel";
import { SnippetPanel } from "@/components/SnippetPanel";
import { IconFile, IconLink, IconPlay, IconUpload, IconX } from "@/components/icons";
import { ExtractionOptions, ExtractionResponse } from "@/lib/types";

// Same-origin route handlers. They hold the backend URL and API key server-side,
// so neither is shipped to the browser.
const EXTRACT_URL_ENDPOINT = "/api/extract/url";
const EXTRACT_FILE_ENDPOINT = "/api/extract/file";

const DEFAULT_OPTIONS: ExtractionOptions = {
  include_text: true,
  include_tables: true,
  include_images: true,
  include_image_bytes: true,
  include_metadata: true,
  ocr_mode: "off",
  ocr_backend: "gcv",
  ocr_zoom: 2,
  page_start: "",
  page_end: "",
};

type Mode = "url" | "file";

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

async function readResponse(response: Response): Promise<ExtractionResponse> {
  const raw = await response.text();
  let data: unknown = null;
  try {
    data = raw ? JSON.parse(raw) : null;
  } catch {
    data = null;
  }

  if (!response.ok) {
    const detail = (data as { detail?: unknown } | null)?.detail;
    throw new Error(
      typeof detail === "string" ? detail : raw.slice(0, 300) || `Extraction failed (${response.status}).`,
    );
  }
  return data as ExtractionResponse;
}

function buildSanitizedOptions(options: ExtractionOptions) {
  return {
    ...options,
    page_start: options.page_start === "" ? null : options.page_start,
    page_end: options.page_end === "" ? null : options.page_end,
  };
}

export default function HomePage() {
  const [mode, setMode] = useState<Mode>("url");
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [options, setOptions] = useState<ExtractionOptions>(DEFAULT_OPTIONS);
  const [result, setResult] = useState<ExtractionResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canRun = useMemo(
    () => (mode === "url" ? url.trim().length > 0 : file !== null),
    [mode, url, file],
  );

  const runUrlExtraction = async () => {
    const response = await fetch(EXTRACT_URL_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        pdf_url: url.trim(),
        options: buildSanitizedOptions(options),
      }),
    });
    return readResponse(response);
  };

  const runFileExtraction = async () => {
    if (!file) throw new Error("Choose a PDF first.");
    const formData = new FormData();
    formData.append("file", file);
    formData.append("include_text", String(options.include_text));
    formData.append("include_tables", String(options.include_tables));
    formData.append("include_images", String(options.include_images));
    formData.append("include_image_bytes", String(options.include_image_bytes));
    formData.append("include_metadata", String(options.include_metadata));
    formData.append("ocr_mode", options.ocr_mode);
    formData.append("ocr_backend", options.ocr_backend);
    formData.append("ocr_zoom", String(options.ocr_zoom));
    if (options.page_start !== "") formData.append("page_start", String(options.page_start));
    if (options.page_end !== "") formData.append("page_end", String(options.page_end));

    const response = await fetch(EXTRACT_FILE_ENDPOINT, { method: "POST", body: formData });
    return readResponse(response);
  };

  const run = useCallback(async () => {
    if (busy || !canRun) return;
    setBusy(true);
    setError(null);
    try {
      const payload = mode === "url" ? await runUrlExtraction() : await runFileExtraction();
      setResult(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
    // runUrlExtraction / runFileExtraction close over the live state above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [busy, canRun, mode, url, file, options]);

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    void run();
  };

  // Cmd/Ctrl+Enter runs from anywhere on the page.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
        event.preventDefault();
        void run();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [run]);

  const onDrop = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    setDragging(false);
    const dropped = event.dataTransfer.files?.[0];
    if (dropped) {
      setFile(dropped);
      setError(null);
    }
  };

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            Q
          </span>
          <div>
            <p className="brand-name">Quarry</p>
            <p className="brand-sub">PDF extraction workspace</p>
          </div>
        </div>
        <div className="topbar-meta">
          <span className="status-pill">
            <span className="status-dot" aria-hidden="true" />
            {busy ? "Running" : "Ready"}
          </span>
          <code className="endpoint-chip">/api/extract</code>
        </div>
      </header>

      <main className="workspace">
        <div className="rail">
          <section className="card">
            <div className="card-head">
              <h2>Source</h2>
            </div>
            <form className="card-body" onSubmit={onSubmit}>
              <div className="segmented" role="group" aria-label="Source type">
                <button type="button" aria-pressed={mode === "url"} onClick={() => setMode("url")}>
                  <IconLink />
                  URL
                </button>
                <button type="button" aria-pressed={mode === "file"} onClick={() => setMode("file")}>
                  <IconUpload />
                  Upload
                </button>
              </div>

              {mode === "url" ? (
                <label className="field">
                  <span>PDF address</span>
                  <input
                    type="url"
                    placeholder="https://example.com/report.pdf"
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    autoComplete="off"
                    spellCheck={false}
                  />
                  <span className="hint">Must be a publicly reachable http(s) link.</span>
                </label>
              ) : file ? (
                <div className="file-chip">
                  <IconFile />
                  <div className="file-chip-meta">
                    <p className="file-chip-name" title={file.name}>
                      {file.name}
                    </p>
                    <p className="file-chip-size">{formatBytes(file.size)}</p>
                  </div>
                  <button
                    type="button"
                    className="btn btn-icon"
                    onClick={() => setFile(null)}
                    aria-label={`Remove ${file.name}`}
                  >
                    <IconX />
                  </button>
                </div>
              ) : (
                <label
                  className={`dropzone${dragging ? " is-dragging" : ""}`}
                  onDragOver={(e) => {
                    e.preventDefault();
                    setDragging(true);
                  }}
                  onDragLeave={() => setDragging(false)}
                  onDrop={onDrop}
                >
                  <IconUpload />
                  <span className="dropzone-title">Drop a PDF here</span>
                  <span className="hint">or click to browse</span>
                  <input
                    type="file"
                    accept="application/pdf"
                    onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                  />
                </label>
              )}

              <div className="run-block">
                <button className="btn btn-primary" type="submit" disabled={busy || !canRun}>
                  <IconPlay />
                  {busy ? "Extracting…" : "Run extraction"}
                </button>
                <p className="kbd-hint">
                  <kbd>{"⌘"}</kbd> / <kbd>Ctrl</kbd> + <kbd>Enter</kbd> to run
                </p>
              </div>
            </form>
          </section>

          <OptionsPanel options={options} onChange={setOptions} />

          <SnippetPanel
            mode={mode}
            url={url}
            fileName={file?.name ?? null}
            options={options}
          />
        </div>

        <ResultPanel result={result} busy={busy} error={error} />
      </main>
    </div>
  );
}
