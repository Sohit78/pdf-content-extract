# Quarry — Extraction Backend

Scalable backend for extracting raw content from PDFs:
- Text
- Tables
- Images
- Optional OCR (`gcv` or `trocr`)

It supports both script usage and optimized FastAPI endpoints.

## Setup
1. Create and activate a virtual environment.
2. Install dependencies:
```bash
pip install -r requirements.txt
```
3. Configure environment variables as needed (copy `src/.env.example` to `src/.env`).

## Run as Script
```bash
python src/pipeline.py --pdf-url "https://example.com/sample.pdf" --out src/output.json
```

Useful flags:
- `--no-image-bytes` — image inventory without the base64
- `--no-metadata` — skip document info, outline and links
- `--ocr-mode off|auto|force`
- `--ocr-backend gcv|trocr`
- `--no-text`
- `--no-tables`
- `--no-images`
- `--page-start 1 --page-end 5`

## Run as API
```bash
uvicorn src.api:app --reload
```

Optional CORS override for custom frontend domains:
- `CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000`

### Health
- `GET /health`
- `GET /ready`

### Extract from URL
`POST /v1/extract/url`

Request:
```json
{
  "pdf_url": "https://example.com/sample.pdf",
  "options": {
    "include_text": true,
    "include_tables": true,
    "include_images": true,
    "include_image_bytes": true,
    "include_metadata": true,
    "ocr_mode": "auto",
    "ocr_backend": "gcv",
    "ocr_zoom": 2.0,
    "page_start": 1,
    "page_end": 10
  }
}
```

### Extract from Uploaded File
`POST /v1/extract/file` (multipart/form-data)

Form fields:
- `file` (required)
- all option fields from URL endpoint as form values

Max upload size is `50MB` (configurable in `src/api.py`).

## Response Shape
```json
{
  "source_url": "https://example.com/sample.pdf",
  "extracted_at": "2026-03-18T12:00:00.000000Z",
  "page_count": 10,
  "total_pages": 63,
  "text": [],
  "tables": [],
  "document": {
    "metadata": { "title": "...", "author": "...", "created": "2026-03-18T11:59:27", "encrypted": false },
    "outline": [{ "level": 1, "title": "Introduction", "page": 1 }],
    "links": [{ "page": 1, "kind": "external", "uri": "https://example.com" }],
    "page_size": { "width": 595.0, "height": 842.0, "rotation": 0 }
  },
  "images": [
    {
      "page": 1,
      "pages": [1, 2, 3],
      "occurrences": 3,
      "sha256": "e3b0c442...",
      "image_index": 1,
      "ext": "png",
      "mime_type": "image/png",
      "width": 1024,
      "height": 768,
      "size_bytes": 12345,
      "bytes_base64": "iVBORw0KGgoAAAANSUhEUgAA..."
    }
  ],
  "meta": {
    "selected_pages": [1, 2, 3],
    "options": {},
    "processing_ms": 1320,
    "cache": "miss",
    "ocr": { "performed": 0, "cached": 0 }
  }
}
```

## Caching

Every extraction is keyed on a SHA-256 of the PDF's own bytes plus the options, so
the same document hits the same entry regardless of filename or source. Two layers:

- **Whole payloads** — an identical request returns from disk. Measured at 335ms cold
  vs 27ms warm.
- **Individual OCR'd pages** — keyed on digest + page number + OCR settings, *not* the
  request. Narrowing or widening a page range re-reads pages already OCR'd instead of
  paying for them again. This is the layer that controls your Vision bill.

`meta.cache` is `"hit"` or `"miss"` on every response, and `meta.ocr` reports
`{performed, cached}` so you can see what a run actually cost.

Controls: `CACHE_ENABLED` (default true), `CACHE_DIR` (default `backend/.cache`),
`CACHE_MAX_MB` (default 512, least-recently-used entries are swept past that).

- `GET /v1/cache` — entry count and size on disk
- `DELETE /v1/cache` — drop everything

## Payload Size

Images are returned **once per distinct image**, with a `pages` array listing every page
it appears on. A logo repeated across a report used to be re-encoded per page; a 12-page
fixture with 36 image placements now returns 14 records.

Set `include_image_bytes: false` for an inventory — dimensions, byte size and a SHA-256
per image, no base64. Measured 92% smaller on that same fixture. `include_metadata: false`
drops the document block the same way.

## Security

Both controls are off by default, so an existing local setup keeps working unchanged.

### API key
Set `API_KEY` in `src/.env` and `/v1/extract/*` then require a matching `X-API-Key`
header (401 otherwise). `/health` and `/ready` stay open. Leave it empty and the
endpoints are unauthenticated — the server logs a warning at startup saying so.

### Outbound URL filtering
`/v1/extract/url` refuses loopback, link-local (cloud metadata), RFC1918, multicast
and reserved addresses, and re-checks **every redirect hop** so a public URL cannot
bounce the fetch somewhere internal. Set `ALLOW_PRIVATE_URLS=true` to turn this off
when you deliberately fetch PDFs from inside your own network.

### Size limits
- `MAX_UPLOAD_MB` (default 50) — uploads stream to disk and are cut off at the limit
  rather than being buffered whole, so an oversized POST cannot exhaust memory.
- `MAX_DOWNLOAD_MB` (default 50) — same ceiling for URL fetches, checked against
  `Content-Length` and again while streaming.

## Supabase Upload

`src/upload_to_supabase.py` enforces a size ceiling before anything leaves the machine.
PDFs over the limit are compressed first; the original file on disk is never touched.

```python
from pathlib import Path
from src.upload_to_supabase import supabase_upload_file

public_url = supabase_upload_file(
    supabase_url=os.environ["SUPABASE_URL"],
    service_role_key=os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    bucket=os.environ["SUPABASE_BUCKET"],
    local_file=Path("report.pdf"),
    object_path="2026-10-05/report.pdf",
)
```

Defaults to a `5MB` ceiling. Override per call:
- `max_bytes=10 * 1024 * 1024` — raise or lower the ceiling (`None` disables the check)
- `compress_pdfs=False` — reject oversized PDFs instead of shrinking them

An oversized non-PDF, or a PDF that cannot reach the target, raises `ValueError`.

### Compression Directly
`src/compression.py` is usable on its own:

```python
from src.compression import compress_pdf

result = compress_pdf(Path("big.pdf"), Path("small.pdf"), target_bytes=5 * 1024 * 1024)
print(result.final_bytes, result.strategy, result.fits_target)
```

It escalates only as far as it has to:
1. **Lossless** — object garbage collection, stream deflation, object streams. Pixels untouched.
2. **Image passes** — embedded images downsampled and re-encoded as JPEG at
   `2200px/q85`, then `1700px/q75`, `1300px/q65`, `1000px/q55`, `800px/q45`, stopping at the
   first pass under target. Each pass restarts from the original, so quality loss never compounds.

Page count, text layer, and vector content are preserved throughout; only raster images are
touched. Images carrying an alpha channel (`smask`) and images under 16KB are skipped.
Pass `strict=False` to get a best-effort result instead of a `ValueError` when the target is
unreachable — a text- or vector-heavy PDF has no images to give back.

## Notes for Scale
- Use page ranges for faster partial extraction.
- Disable unused extractors (`include_tables`, `include_images`) for lower latency.
- Keep OCR as `auto` by default to avoid unnecessary OCR overhead. In auto mode a page
  with fewer than `AUTO_OCR_MIN_CHARS` (default 16) characters counts as having no text
  layer, so scanned pages carrying a few stray characters are no longer skipped.
- Leave the cache on. It is the difference between paying for OCR once and paying every run.
- Compression rewrites every embedded image per pass; budget for it on image-heavy PDFs.
- For high throughput, run multiple Uvicorn workers and externalize queueing if needed.

## Next.js Frontend
The Quarry workspace lives in `frontend/`.

```bash
cd frontend
npm install
npm run dev
```

### How it talks to this API
The browser never calls this API directly. It posts to same-origin route handlers
(`/api/extract/url`, `/api/extract/file`) which run on the Next server and forward
the request, adding the `X-API-Key` header. That keeps the backend URL and the key
out of the client bundle, and sidesteps CORS entirely.

```
browser  ->  /api/extract/*  (Next route handler, server-side)  ->  FastAPI
                             adds X-API-Key here
```

Configure in `frontend/.env` — note **no** `NEXT_PUBLIC_` prefix, which is the point:

- `BACKEND_API_BASE_URL=http://127.0.0.1:8000`
- `API_KEY=` — must match `API_KEY` in `backend/src/.env`; leave empty if the backend is open

Anything named `NEXT_PUBLIC_*` is compiled into the JavaScript every visitor downloads,
so an API key must never use that prefix.
