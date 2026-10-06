import argparse
import base64
import datetime as dt
import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import fitz
import pdfplumber
import requests
from PIL import Image
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    from . import cache
    from .security import assert_safe_url
except ImportError:  # running as a plain script rather than a package module
    import cache
    from security import assert_safe_url

MODULE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = MODULE_DIR.parent
load_dotenv(MODULE_DIR / ".env")
load_dotenv(PROJECT_ROOT / ".env")

ALLOWED_OCR_MODES = {"off", "auto", "force"}
ALLOWED_OCR_BACKENDS = {"gcv", "trocr"}

MAX_DOWNLOAD_MB = int(os.getenv("MAX_DOWNLOAD_MB", "50"))
MAX_REDIRECTS = 5

# A scanned page often carries a few stray characters in its text layer, which
# made the old "is it empty" test skip OCR and hand back junk. Anything under
# this many characters is treated as no usable text.
AUTO_OCR_MIN_CHARS = int(os.getenv("AUTO_OCR_MIN_CHARS", "16"))


class InvalidPdfError(ValueError):
    """Raised when a file is not a PDF we can parse. Maps to HTTP 400."""


@dataclass(frozen=True)
class ExtractionOptions:
    include_text: bool = True
    include_tables: bool = True
    include_images: bool = True
    include_image_bytes: bool = True  # False returns image metadata without the base64
    include_metadata: bool = True  # document info, outline and links
    ocr_mode: str = "off"  # off | auto | force
    ocr_backend: str = "gcv"  # gcv | trocr
    ocr_zoom: float = 2.0
    page_start: Optional[int] = None  # 1-based inclusive
    page_end: Optional[int] = None  # 1-based inclusive

    def __post_init__(self) -> None:
        if self.ocr_mode not in ALLOWED_OCR_MODES:
            raise ValueError(f"Invalid ocr_mode '{self.ocr_mode}'. Use one of: {sorted(ALLOWED_OCR_MODES)}")
        if self.ocr_backend not in ALLOWED_OCR_BACKENDS:
            raise ValueError(f"Invalid ocr_backend '{self.ocr_backend}'. Use one of: {sorted(ALLOWED_OCR_BACKENDS)}")
        if self.ocr_zoom <= 0:
            raise ValueError("ocr_zoom must be > 0")
        if self.page_start is not None and self.page_start < 1:
            raise ValueError("page_start must be >= 1")
        if self.page_end is not None and self.page_end < 1:
            raise ValueError("page_end must be >= 1")
        if self.page_start is not None and self.page_end is not None and self.page_start > self.page_end:
            raise ValueError("page_start cannot be greater than page_end")


def _build_retrying_session(max_retries: int = 3) -> requests.Session:
    retry = Retry(
        total=max_retries,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def _resolve_pages(total_pages: int, page_start: Optional[int], page_end: Optional[int]) -> list[int]:
    start = page_start or 1
    end = page_end or total_pages
    if start > total_pages:
        raise ValueError(f"page_start ({start}) exceeds total pages ({total_pages})")
    end = min(end, total_pages)
    if start > end:
        raise ValueError(f"Invalid page range: {start}-{end}")
    return list(range(start, end + 1))


def download_pdf(
    pdf_url: str,
    destination: Path,
    timeout: int = 60,
    max_bytes: Optional[int] = None,
) -> Path:
    limit = max_bytes if max_bytes is not None else MAX_DOWNLOAD_MB * 1024 * 1024
    session = _build_retrying_session()

    # Follow redirects by hand so each hop is checked; otherwise a public URL
    # could bounce the fetch to an internal one.
    url = pdf_url
    resp = None
    for _ in range(MAX_REDIRECTS):
        assert_safe_url(url)
        resp = session.get(url, stream=True, timeout=timeout, allow_redirects=False)
        if resp.is_redirect or resp.is_permanent_redirect:
            location = resp.headers.get("location")
            resp.close()
            if not location:
                raise ValueError("Redirect response had no Location header.")
            url = urljoin(url, location)
            continue
        break
    else:
        raise ValueError(f"Too many redirects (over {MAX_REDIRECTS}) starting at {pdf_url}")

    with resp:
        resp.raise_for_status()

        declared = resp.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > limit:
            raise ValueError(f"PDF is {int(declared)} bytes, over the {MAX_DOWNLOAD_MB}MB download limit.")

        destination.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with destination.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                written += len(chunk)
                if written > limit:
                    raise ValueError(f"PDF exceeds the {MAX_DOWNLOAD_MB}MB download limit.")
                f.write(chunk)

    if written == 0:
        raise ValueError("Downloaded file was empty.")
    return destination


def _open_fitz(pdf_path: Path) -> fitz.Document:
    try:
        return fitz.open(pdf_path)
    except Exception as exc:
        raise InvalidPdfError(f"Could not read PDF: {exc}") from exc


def _open_pdfplumber(pdf_path: Path):
    try:
        return pdfplumber.open(pdf_path)
    except Exception as exc:
        raise InvalidPdfError(f"Could not read PDF: {exc}") from exc


# Lazy-loaded globals for TrOCR
_TROCR_PROCESSOR = None
_TROCR_MODEL = None


def _load_trocr():
    global _TROCR_PROCESSOR, _TROCR_MODEL
    if _TROCR_PROCESSOR is None or _TROCR_MODEL is None:
        from transformers import TrOCRProcessor, VisionEncoderDecoderModel

        _TROCR_PROCESSOR = TrOCRProcessor.from_pretrained("microsoft/trocr-base-handwritten")
        _TROCR_MODEL = VisionEncoderDecoderModel.from_pretrained("microsoft/trocr-base-handwritten")
    return _TROCR_PROCESSOR, _TROCR_MODEL


def _page_to_image(page: fitz.Page, zoom: float = 2.0) -> Image.Image:
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)


def _ocr_image_trocr(img: Image.Image) -> str:
    processor, model = _load_trocr()
    pixel_values = processor(images=img, return_tensors="pt").pixel_values
    generated_ids = model.generate(pixel_values)
    text = processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
    return text.strip()


def _ocr_image_gcv(img: Image.Image) -> str:
    # Import lazily to avoid requiring vision unless backend=gcv
    from google.cloud import vision
    import io

    client = vision.ImageAnnotatorClient()
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    content = buf.getvalue()
    gimg = vision.Image(content=content)

    response = client.document_text_detection(image=gimg)
    if response.error.message:
        raise RuntimeError(f"Google Vision OCR error: {response.error.message}")

    full = response.full_text_annotation
    text = full.text if full and full.text else ""
    return (text or "").strip()


def _ocr_page(
    fitz_doc: fitz.Document,
    page_num: int,
    options: ExtractionOptions,
    digest: Optional[str],
    ocr_stats: dict,
) -> str:
    """OCR one page, reusing a cached result when the same page was read before.

    Keyed on the document digest and page number rather than the request, so
    narrowing or widening a page range never re-pays for a page already read.
    """
    key = (
        cache.make_key("ocr-v1", digest, page_num, options.ocr_backend, options.ocr_zoom)
        if digest
        else None
    )
    if key:
        hit = cache.get(key)
        if isinstance(hit, str):
            ocr_stats["cached"] += 1
            return hit

    page_img = _page_to_image(fitz_doc[page_num - 1], zoom=options.ocr_zoom)
    text = (
        _ocr_image_gcv(page_img)
        if options.ocr_backend == "gcv"
        else _ocr_image_trocr(page_img)
    )
    ocr_stats["performed"] += 1
    if key:
        cache.put(key, text)
    return text


def _extract_text_and_tables(
    pdf_path: Path,
    options: ExtractionOptions,
    digest: Optional[str] = None,
    ocr_stats: Optional[dict] = None,
) -> tuple[list[dict], list[dict], int, list[int]]:
    text_results: list[dict] = []
    table_results: list[dict] = []
    ocr_stats = ocr_stats if ocr_stats is not None else {"performed": 0, "cached": 0}

    with _open_pdfplumber(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        selected_pages = _resolve_pages(total_pages, options.page_start, options.page_end)
        fitz_doc = (
            _open_fitz(pdf_path)
            if options.include_text and options.ocr_mode in {"auto", "force"}
            else None
        )

        try:
            for page_num in selected_pages:
                page = pdf.pages[page_num - 1]

                if options.include_text:
                    extracted = page.extract_text() or ""
                    need_ocr = options.ocr_mode == "force" or (
                        options.ocr_mode == "auto"
                        and len(extracted.strip()) < AUTO_OCR_MIN_CHARS
                    )
                    if need_ocr and fitz_doc is not None:
                        extracted = _ocr_page(
                            fitz_doc, page_num, options, digest, ocr_stats
                        )
                    text_results.append({"page": page_num, "content": extracted})

                if options.include_tables:
                    extracted_tables = page.extract_tables() or []
                    for table_idx, table_rows in enumerate(extracted_tables, start=1):
                        table_results.append(
                            {"page": page_num, "table_index": table_idx, "rows": table_rows}
                        )
        finally:
            if fitz_doc is not None:
                fitz_doc.close()

    return text_results, table_results, total_pages, selected_pages


def _guess_mime_type(ext: str) -> str:
    mime_map = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "bmp": "image/bmp",
        "tif": "image/tiff",
        "tiff": "image/tiff",
        "webp": "image/webp",
    }
    return mime_map.get(ext.lower(), "application/octet-stream")


def extract_images(pdf_path: Path, options: ExtractionOptions) -> list[dict]:
    """One record per distinct image, with every page it appears on.

    A logo or header band repeated on each page used to be returned once per
    page, base64 and all. Records are merged first on xref, then on a hash of
    the decoded bytes so copies stored under separate xrefs also collapse.
    """
    by_hash: dict[str, dict] = {}
    seen_xrefs: dict[int, str] = {}

    with _open_fitz(pdf_path) as doc:
        selected_pages = _resolve_pages(len(doc), options.page_start, options.page_end)
        for page_idx in selected_pages:
            page = doc[page_idx - 1]
            for img_idx, img in enumerate(page.get_images(full=True), start=1):
                xref = img[0]

                known = seen_xrefs.get(xref)
                if known is not None:
                    record = by_hash[known]
                    if page_idx not in record["pages"]:
                        record["pages"].append(page_idx)
                    continue

                base_image = doc.extract_image(xref)
                bytes_ = base_image["image"]
                digest = cache.bytes_digest(bytes_)
                seen_xrefs[xref] = digest

                existing = by_hash.get(digest)
                if existing is not None:
                    if page_idx not in existing["pages"]:
                        existing["pages"].append(page_idx)
                    continue

                ext = base_image.get("ext", "png")
                record = {
                    "page": page_idx,  # first page it appears on
                    "pages": [page_idx],
                    "image_index": img_idx,
                    "ext": ext,
                    "mime_type": _guess_mime_type(ext),
                    "width": base_image.get("width"),
                    "height": base_image.get("height"),
                    "size_bytes": len(bytes_),
                    "sha256": digest,
                }
                if options.include_image_bytes:
                    record["bytes_base64"] = base64.b64encode(bytes_).decode("ascii")
                by_hash[digest] = record

    results = sorted(by_hash.values(), key=lambda r: (r["page"], r["image_index"]))
    for record in results:
        record["occurrences"] = len(record["pages"])
    return results


def _pdf_date(value: Optional[str]) -> Optional[str]:
    """Turn a PDF D:YYYYMMDDHHmmSS date into something ISO-shaped."""
    if not value:
        return None
    raw = value[2:] if value.startswith("D:") else value
    digits = raw[:14]
    if len(digits) < 8 or not digits[:8].isdigit():
        return value
    stamp = f"{digits[0:4]}-{digits[4:6]}-{digits[6:8]}"
    if len(digits) >= 14 and digits[8:14].isdigit():
        stamp += f"T{digits[8:10]}:{digits[10:12]}:{digits[12:14]}"
    return stamp


def extract_document_info(pdf_path: Path, options: ExtractionOptions) -> dict:
    """Metadata, outline and links — all already parsed, none of it costs extra."""
    with _open_fitz(pdf_path) as doc:
        raw = doc.metadata or {}
        metadata = {
            "title": raw.get("title") or None,
            "author": raw.get("author") or None,
            "subject": raw.get("subject") or None,
            "keywords": raw.get("keywords") or None,
            "creator": raw.get("creator") or None,
            "producer": raw.get("producer") or None,
            "created": _pdf_date(raw.get("creationDate")),
            "modified": _pdf_date(raw.get("modDate")),
            "format": raw.get("format") or None,
            "encrypted": bool(doc.is_encrypted),
        }

        outline = [
            {"level": level, "title": title, "page": page}
            for level, title, page in (doc.get_toc() or [])
        ]

        selected_pages = _resolve_pages(len(doc), options.page_start, options.page_end)
        links: list[dict] = []
        for page_idx in selected_pages:
            page = doc[page_idx - 1]
            for link in page.get_links() or []:
                entry = {"page": page_idx, "kind": "internal" if link.get("page", -1) >= 0 else "external"}
                if link.get("uri"):
                    entry["uri"] = link["uri"]
                    entry["kind"] = "external"
                elif link.get("page", -1) >= 0:
                    entry["target_page"] = link["page"] + 1
                else:
                    continue
                links.append(entry)

        first = doc[0] if len(doc) else None
        page_size = (
            {"width": round(first.rect.width, 1), "height": round(first.rect.height, 1),
             "rotation": first.rotation}
            if first is not None
            else None
        )

    return {"metadata": metadata, "outline": outline, "links": links, "page_size": page_size}


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def build_payload(
    source_url: str,
    text: list,
    tables: list,
    images: list,
    page_count: int,
    total_pages: int,
    selected_pages: list[int],
    options: ExtractionOptions,
    processing_ms: int,
    document: Optional[dict] = None,
    ocr_stats: Optional[dict] = None,
) -> dict:
    payload = {
        "source_url": source_url,
        "extracted_at": _utc_now(),
        "page_count": page_count,
        "total_pages": total_pages,
        "text": text,
        "tables": tables,
        "images": images,
        "meta": {
            "selected_pages": selected_pages,
            "options": asdict(options),
            "processing_ms": processing_ms,
            "cache": "miss",
        },
    }
    if document is not None:
        payload["document"] = document
    if ocr_stats is not None:
        payload["meta"]["ocr"] = ocr_stats
    return payload


def process_pdf(pdf_path: Path, source_url: str, options: Optional[ExtractionOptions] = None) -> dict:
    opts = options or ExtractionOptions()
    start = time.perf_counter()

    # Identify the document by its bytes, so the same PDF hits the same entry
    # whatever it was named or wherever it was fetched from.
    try:
        digest = cache.file_digest(pdf_path)
    except OSError:
        digest = None

    payload_key = cache.make_key("payload-v1", digest, asdict(opts)) if digest else None
    if payload_key:
        hit = cache.get(payload_key)
        if isinstance(hit, dict):
            hit["source_url"] = source_url
            hit["extracted_at"] = _utc_now()
            meta = hit.setdefault("meta", {})
            meta["cache"] = "hit"
            meta["processing_ms"] = int((time.perf_counter() - start) * 1000)
            return hit

    ocr_stats = {"performed": 0, "cached": 0}
    text, tables, total_pages, selected_pages = _extract_text_and_tables(
        pdf_path, opts, digest=digest, ocr_stats=ocr_stats
    )
    images = extract_images(pdf_path, options=opts) if opts.include_images else []
    document = extract_document_info(pdf_path, opts) if opts.include_metadata else None

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    payload = build_payload(
        source_url=source_url,
        text=text if opts.include_text else [],
        tables=tables if opts.include_tables else [],
        images=images,
        page_count=len(selected_pages),
        total_pages=total_pages,
        selected_pages=selected_pages,
        options=opts,
        processing_ms=elapsed_ms,
        document=document,
        ocr_stats=ocr_stats,
    )

    if payload_key:
        cache.put(payload_key, payload)
        cache.sweep()
    return payload


def process_pdf_from_url(pdf_url: str, options: Optional[ExtractionOptions] = None) -> dict:
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "input.pdf"
        download_pdf(pdf_url, pdf_path)
        return process_pdf(pdf_path=pdf_path, source_url=pdf_url, options=options)


def run(pdf_url: str, output_json: Path, options: Optional[ExtractionOptions] = None) -> Path:
    payload = process_pdf_from_url(pdf_url=pdf_url, options=options)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    with output_json.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return output_json


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract text, tables, and images from a PDF URL.")
    parser.add_argument("--pdf-url", required=True, help="Public URL of the PDF to process")
    parser.add_argument("--out", default="without_ocr.json", help="Output JSON path")
    parser.add_argument("--ocr-mode", default=os.getenv("OCR_MODE", "off"), choices=sorted(ALLOWED_OCR_MODES))
    parser.add_argument("--ocr-backend", default=os.getenv("OCR_BACKEND", "gcv"), choices=sorted(ALLOWED_OCR_BACKENDS))
    parser.add_argument("--ocr-zoom", default=float(os.getenv("OCR_ZOOM", "2.0")), type=float)
    parser.add_argument("--no-text", action="store_true", help="Disable text extraction")
    parser.add_argument("--no-tables", action="store_true", help="Disable table extraction")
    parser.add_argument("--no-images", action="store_true", help="Disable image extraction")
    parser.add_argument("--no-image-bytes", action="store_true", help="Image metadata only, no base64")
    parser.add_argument("--no-metadata", action="store_true", help="Skip document info, outline and links")
    parser.add_argument("--page-start", type=int, default=None, help="Start page (1-based, inclusive)")
    parser.add_argument("--page-end", type=int, default=None, help="End page (1-based, inclusive)")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    options = ExtractionOptions(
        include_text=not args.no_text,
        include_tables=not args.no_tables,
        include_images=not args.no_images,
        include_image_bytes=not args.no_image_bytes,
        include_metadata=not args.no_metadata,
        ocr_mode=args.ocr_mode,
        ocr_backend=args.ocr_backend,
        ocr_zoom=args.ocr_zoom,
        page_start=args.page_start,
        page_end=args.page_end,
    )
    result = run(
        pdf_url=args.pdf_url,
        output_json=Path(args.out),
        options=options,
    )
    print(f"Wrote JSON to {result.resolve()}")


if __name__ == "__main__":
    main()
