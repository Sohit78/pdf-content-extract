"use client";

import { IconCheck } from "@/components/icons";
import { ExtractionOptions, OcrBackend, OcrMode } from "@/lib/types";

interface Props {
  options: ExtractionOptions;
  onChange: (next: ExtractionOptions) => void;
}

function parseOptionalInt(value: string): number | "" {
  if (!value.trim()) return "";
  const parsed = Number.parseInt(value, 10);
  return Number.isNaN(parsed) ? "" : parsed;
}

const SCOPE: Array<{ key: keyof ExtractionOptions; label: string; note: string }> = [
  { key: "include_text", label: "Text", note: "per page" },
  { key: "include_tables", label: "Tables", note: "rows" },
  { key: "include_images", label: "Images", note: "deduped" },
  { key: "include_metadata", label: "Document info", note: "free" },
];

export function OptionsPanel({ options, onChange }: Props) {
  const ocrOn = options.ocr_mode !== "off";

  return (
    <section className="card">
      <div className="card-head">
        <h2>Options</h2>
      </div>

      <div className="card-body">
        <div className="option-section">
          <div className="option-section-head">
            <h3>Output</h3>
          </div>
          <div className="toggle-list">
            {SCOPE.map(({ key, label, note }) => (
              <div key={key}>
                <label className="toggle">
                  <input
                    type="checkbox"
                    checked={Boolean(options[key])}
                    onChange={(e) => onChange({ ...options, [key]: e.target.checked })}
                  />
                  <span className="toggle-box" aria-hidden="true">
                    <IconCheck />
                  </span>
                  <span className="toggle-text">{label}</span>
                  <span className="toggle-note">{note}</span>
                </label>

                {/* Image bytes dominate the payload, so give them their own switch. */}
                {key === "include_images" && options.include_images ? (
                  <label className="toggle toggle-nested">
                    <input
                      type="checkbox"
                      checked={options.include_image_bytes}
                      onChange={(e) =>
                        onChange({ ...options, include_image_bytes: e.target.checked })
                      }
                    />
                    <span className="toggle-box" aria-hidden="true">
                      <IconCheck />
                    </span>
                    <span className="toggle-text">Image data</span>
                    <span className="toggle-note">base64</span>
                  </label>
                ) : null}
              </div>
            ))}
          </div>
          {options.include_images && !options.include_image_bytes ? (
            <p className="hint">
              Returning the image inventory only — sizes and hashes, no pixels. Much smaller
              responses.
            </p>
          ) : null}
        </div>

        <div className="option-section">
          <div className="option-section-head">
            <h3>OCR</h3>
          </div>

          <label className="field">
            <span>Mode</span>
            <select
              value={options.ocr_mode}
              onChange={(e) => onChange({ ...options, ocr_mode: e.target.value as OcrMode })}
            >
              <option value="off">Off — use the embedded text layer</option>
              <option value="auto">Auto — only for pages with no text</option>
              <option value="force">Force — OCR every page</option>
            </select>
          </label>

          {/* Backend and zoom only matter once OCR can actually run. */}
          {ocrOn ? (
            <div className="field-grid two">
              <label className="field">
                <span>Engine</span>
                <select
                  value={options.ocr_backend}
                  onChange={(e) =>
                    onChange({ ...options, ocr_backend: e.target.value as OcrBackend })
                  }
                >
                  <option value="gcv">Google Vision</option>
                  <option value="trocr">TrOCR</option>
                </select>
              </label>

              <label className="field">
                <span>Zoom</span>
                <input
                  type="number"
                  min={1}
                  max={4}
                  step={0.1}
                  value={options.ocr_zoom}
                  onChange={(e) => onChange({ ...options, ocr_zoom: Number(e.target.value) || 2 })}
                />
              </label>
            </div>
          ) : (
            <p className="hint">Engine and zoom unlock when OCR is set to auto or force.</p>
          )}
        </div>

        <div className="option-section">
          <div className="option-section-head">
            <h3>Page range</h3>
          </div>
          <div className="field-grid two">
            <label className="field">
              <span>From</span>
              <input
                type="number"
                min={1}
                placeholder="1"
                value={options.page_start}
                onChange={(e) =>
                  onChange({ ...options, page_start: parseOptionalInt(e.target.value) })
                }
              />
            </label>
            <label className="field">
              <span>To</span>
              <input
                type="number"
                min={1}
                placeholder="last"
                value={options.page_end}
                onChange={(e) =>
                  onChange({ ...options, page_end: parseOptionalInt(e.target.value) })
                }
              />
            </label>
          </div>
          <p className="hint">Leave blank to process the whole document.</p>
        </div>
      </div>
    </section>
  );
}
