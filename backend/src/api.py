import logging
import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, HttpUrl
from dotenv import load_dotenv

from . import cache
from .pipeline import ALLOWED_OCR_BACKENDS, ALLOWED_OCR_MODES, ExtractionOptions, process_pdf, process_pdf_from_url
from .security import auth_enabled, private_urls_allowed, require_api_key

MODULE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = MODULE_DIR.parent
load_dotenv(MODULE_DIR / ".env")
load_dotenv(PROJECT_ROOT / ".env")

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not auth_enabled():
        logger.warning("API_KEY is not set: extraction endpoints are unauthenticated.")
    if private_urls_allowed():
        logger.warning("ALLOW_PRIVATE_URLS is on: /v1/extract/url may reach internal hosts.")
    yield


app = FastAPI(
    title="PDF Extraction API",
    version="1.0.0",
    description="Extract raw text, tables, and images from PDFs with optional OCR.",
    lifespan=lifespan,
)


def _get_cors_origins() -> list[str]:
    configured = os.getenv("CORS_ORIGINS", "").strip()
    if configured:
        return [origin.strip() for origin in configured.split(",") if origin.strip()]
    return [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ExtractionOptionsRequest(BaseModel):
    include_text: bool = True
    include_tables: bool = True
    include_images: bool = True
    include_image_bytes: bool = True
    include_metadata: bool = True
    ocr_mode: str = "off"
    ocr_backend: str = "gcv"
    ocr_zoom: float = 2.0
    page_start: Optional[int] = None
    page_end: Optional[int] = None

    model_config = ConfigDict(extra="forbid")

    def to_pipeline_options(self) -> ExtractionOptions:
        return ExtractionOptions(
            include_text=self.include_text,
            include_tables=self.include_tables,
            include_images=self.include_images,
            include_image_bytes=self.include_image_bytes,
            include_metadata=self.include_metadata,
            ocr_mode=self.ocr_mode,
            ocr_backend=self.ocr_backend,
            ocr_zoom=self.ocr_zoom,
            page_start=self.page_start,
            page_end=self.page_end,
        )


class UrlExtractionRequest(BaseModel):
    pdf_url: HttpUrl
    options: ExtractionOptionsRequest = Field(default_factory=ExtractionOptionsRequest)

    model_config = ConfigDict(extra="forbid")


class HealthResponse(BaseModel):
    status: str


MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024


@app.get("/v1/cache", dependencies=[Depends(require_api_key)])
async def cache_stats() -> dict:
    return cache.stats()


@app.delete("/v1/cache", dependencies=[Depends(require_api_key)])
async def cache_clear() -> dict:
    return {"removed": await run_in_threadpool(cache.clear)}


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/ready", response_model=HealthResponse)
async def ready() -> HealthResponse:
    return HealthResponse(status="ready")


@app.post("/v1/extract/url", dependencies=[Depends(require_api_key)])
async def extract_from_url(request: UrlExtractionRequest) -> dict:
    try:
        options = request.options.to_pipeline_options()
        payload = await run_in_threadpool(
            process_pdf_from_url,
            str(request.pdf_url),
            options,
        )
        return payload
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Extraction failed: {exc}") from exc


async def _spool_upload(file: UploadFile, destination: Path) -> int:
    # Stream to disk so an oversized upload is cut off instead of buffered whole.
    written = 0
    with destination.open("wb") as out:
        while True:
            chunk = await file.read(UPLOAD_CHUNK_BYTES)
            if not chunk:
                break
            written += len(chunk)
            if written > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413, detail=f"File exceeds max size of {MAX_UPLOAD_MB}MB."
                )
            out.write(chunk)
    return written


@app.post("/v1/extract/file", dependencies=[Depends(require_api_key)])
async def extract_from_file(
    file: UploadFile = File(...),
    include_text: bool = Form(True),
    include_tables: bool = Form(True),
    include_images: bool = Form(True),
    include_image_bytes: bool = Form(True),
    include_metadata: bool = Form(True),
    ocr_mode: str = Form("off"),
    ocr_backend: str = Form("gcv"),
    ocr_zoom: float = Form(2.0),
    page_start: Optional[int] = Form(None),
    page_end: Optional[int] = Form(None),
) -> dict:
    if file.content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
    if ocr_mode not in ALLOWED_OCR_MODES:
        raise HTTPException(status_code=400, detail=f"ocr_mode must be one of {sorted(ALLOWED_OCR_MODES)}")
    if ocr_backend not in ALLOWED_OCR_BACKENDS:
        raise HTTPException(status_code=400, detail=f"ocr_backend must be one of {sorted(ALLOWED_OCR_BACKENDS)}")

    try:
        options = ExtractionOptions(
            include_text=include_text,
            include_tables=include_tables,
            include_images=include_images,
            include_image_bytes=include_image_bytes,
            include_metadata=include_metadata,
            ocr_mode=ocr_mode,
            ocr_backend=ocr_backend,
            ocr_zoom=ocr_zoom,
            page_start=page_start,
            page_end=page_end,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Keep only the basename: an uploaded name may carry directory components.
    safe_name = Path(file.filename or "upload.pdf").name or "upload.pdf"

    with tempfile.TemporaryDirectory() as tmpdir:
        temp_pdf_path = Path(tmpdir) / safe_name
        written = await _spool_upload(file, temp_pdf_path)
        if written == 0:
            raise HTTPException(status_code=400, detail="Uploaded file was empty.")

        try:
            payload = await run_in_threadpool(
                process_pdf,
                temp_pdf_path,
                f"uploaded://{safe_name}",
                options,
            )
            return payload
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Extraction failed: {exc}") from exc
