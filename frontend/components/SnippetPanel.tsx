"use client";

import { useMemo, useState } from "react";

import { IconCheck, IconCopy } from "@/components/icons";
import { ExtractionOptions } from "@/lib/types";

type Lang = "curl" | "python" | "js";

interface Props {
  mode: "url" | "file";
  url: string;
  fileName: string | null;
  options: ExtractionOptions;
}

const LANGS: Array<{ id: Lang; label: string }> = [
  { id: "curl", label: "cURL" },
  { id: "python", label: "Python" },
  { id: "js", label: "JavaScript" },
];

const BASE = "$QUARRY_API";
const KEY = "$QUARRY_API_KEY";

/** Only send what differs from the server's defaults — snippets stay readable. */
const DEFAULTS: Record<string, string | number | boolean> = {
  include_text: true,
  include_tables: true,
  include_images: true,
  include_image_bytes: true,
  include_metadata: true,
  ocr_mode: "off",
  ocr_backend: "gcv",
  ocr_zoom: 2,
};

function activeOptions(options: ExtractionOptions): Array<[string, string | number | boolean]> {
  const out: Array<[string, string | number | boolean]> = [];
  for (const [key, fallback] of Object.entries(DEFAULTS)) {
    const value = options[key as keyof ExtractionOptions];
    // OCR engine and zoom are inert while OCR is off.
    if ((key === "ocr_backend" || key === "ocr_zoom") && options.ocr_mode === "off") continue;
    if (value !== fallback) out.push([key, value as string | number | boolean]);
  }
  if (options.page_start !== "") out.push(["page_start", options.page_start]);
  if (options.page_end !== "") out.push(["page_end", options.page_end]);
  return out;
}

function buildSnippet(lang: Lang, props: Props): string {
  const { mode, url, fileName, options } = props;
  const pairs = activeOptions(options);
  const target = mode === "url" ? `${BASE}/v1/extract/url` : `${BASE}/v1/extract/file`;
  const pdf = url.trim() || "https://example.com/report.pdf";
  const name = fileName || "report.pdf";

  if (lang === "curl") {
    if (mode === "url") {
      const body = JSON.stringify(
        { pdf_url: pdf, options: Object.fromEntries(pairs) },
        null,
        2,
      )
        .split("\n")
        .join("\n  ");
      return [
        `curl -X POST "${target}" \\`,
        `  -H "X-API-Key: ${KEY}" \\`,
        `  -H "Content-Type: application/json" \\`,
        `  -d '${body}'`,
      ].join("\n");
    }
    const forms = pairs.map(([k, v]) => `  -F "${k}=${v}" \\`);
    return [
      `curl -X POST "${target}" \\`,
      `  -H "X-API-Key: ${KEY}" \\`,
      `  -F "file=@${name};type=application/pdf" \\`,
      ...forms,
    ]
      .join("\n")
      .replace(/ \\$/, "");
  }

  if (lang === "python") {
    const opts = pairs.length
      ? `{\n${pairs.map(([k, v]) => `        "${k}": ${JSON.stringify(v)},`).join("\n")}\n    }`
      : "{}";
    if (mode === "url") {
      return [
        "import os, requests",
        "",
        'resp = requests.post(',
        `    f"{os.environ['QUARRY_API']}/v1/extract/url",`,
        '    headers={"X-API-Key": os.environ["QUARRY_API_KEY"]},',
        `    json={"pdf_url": ${JSON.stringify(pdf)}, "options": ${opts}},`,
        "    timeout=300,",
        ")",
        "resp.raise_for_status()",
        "payload = resp.json()",
      ].join("\n");
    }
    return [
      "import os, requests",
      "",
      `with open(${JSON.stringify(name)}, "rb") as f:`,
      "    resp = requests.post(",
      `        f"{os.environ['QUARRY_API']}/v1/extract/file",`,
      '        headers={"X-API-Key": os.environ["QUARRY_API_KEY"]},',
      `        files={"file": (${JSON.stringify(name)}, f, "application/pdf")},`,
      `        data=${opts.replace(/\n {8}/g, "\n            ").replace(/\n {4}}/, "\n        }")},`,
      "        timeout=300,",
      "    )",
      "resp.raise_for_status()",
      "payload = resp.json()",
    ].join("\n");
  }

  const optsJs = pairs.length
    ? `{\n${pairs.map(([k, v]) => `      ${k}: ${JSON.stringify(v)},`).join("\n")}\n    }`
    : "{}";
  if (mode === "url") {
    return [
      `const res = await fetch(\`\${process.env.QUARRY_API}/v1/extract/url\`, {`,
      '  method: "POST",',
      "  headers: {",
      '    "X-API-Key": process.env.QUARRY_API_KEY,',
      '    "Content-Type": "application/json",',
      "  },",
      "  body: JSON.stringify({",
      `    pdf_url: ${JSON.stringify(pdf)},`,
      `    options: ${optsJs},`,
      "  }),",
      "});",
      "const payload = await res.json();",
    ].join("\n");
  }
  return [
    "const form = new FormData();",
    'form.append("file", file, ' + JSON.stringify(name) + ");",
    ...pairs.map(([k, v]) => `form.append("${k}", ${JSON.stringify(String(v))});`),
    "",
    `const res = await fetch(\`\${process.env.QUARRY_API}/v1/extract/file\`, {`,
    '  method: "POST",',
    '  headers: { "X-API-Key": process.env.QUARRY_API_KEY },',
    "  body: form,",
    "});",
    "const payload = await res.json();",
  ].join("\n");
}

export function SnippetPanel(props: Props) {
  const [lang, setLang] = useState<Lang>("curl");
  const [copied, setCopied] = useState(false);

  const snippet = useMemo(() => buildSnippet(lang, props), [lang, props]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(snippet);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      /* clipboard blocked; the snippet is selectable anyway */
    }
  };

  return (
    <section className="card">
      <div className="card-head snippet-head">
        <h2>Call it from code</h2>
        <button className="btn btn-icon" onClick={copy} aria-label="Copy snippet">
          {copied ? <IconCheck /> : <IconCopy />}
        </button>
      </div>
      <div className="card-body snippet-body">
        <div className="segmented" role="group" aria-label="Snippet language">
          {LANGS.map(({ id, label }) => (
            <button
              key={id}
              type="button"
              aria-pressed={lang === id}
              onClick={() => setLang(id)}
            >
              {label}
            </button>
          ))}
        </div>
        <pre className="snippet">{snippet}</pre>
        <p className="hint">
          Mirrors the options above. Set <code>QUARRY_API</code> and{" "}
          <code>QUARRY_API_KEY</code> in your environment.
        </p>
      </div>
    </section>
  );
}
