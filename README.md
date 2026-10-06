# Quarry

Pull text, tables, and images out of any PDF and get structured JSON back.

- **`backend/`** — FastAPI service plus a standalone CLI. Extraction runs on
  pdfplumber (text, tables) and PyMuPDF (images, rasterisation), with optional OCR
  via Google Cloud Vision or TrOCR. See [backend/README.md](backend/README.md).
- **`frontend/`** — Next.js workspace: pick a source, set the options, read the yield.

## Quick start

```bash
# backend
cd backend
pip install -r requirements.txt
uvicorn src.api:app --reload

# frontend, in a second shell
cd frontend
npm install
npm run dev
```

The workspace comes up on <http://localhost:3000> and talks to the API through its own
server-side route handlers, so no API credentials reach the browser.

## Configuration

Copy the templates and fill them in — neither `.env` is tracked by git:

```bash
cp backend/src/.env.example backend/src/.env
cp frontend/.env.example frontend/.env
```

The security controls (`API_KEY`, `ALLOW_PRIVATE_URLS`, upload/download ceilings) are
documented in [backend/README.md](backend/README.md#security). They default to off, so
a fresh clone runs without configuration.
