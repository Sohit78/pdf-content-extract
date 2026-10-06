"""Shrink PDFs under a size ceiling before they are handed to storage."""

import io
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import fitz
from PIL import Image

DEFAULT_TARGET_BYTES = 5 * 1024 * 1024

# Embedded-image passes, gentlest first: (longest edge in px, JPEG quality).
IMAGE_PASSES = ((2200, 85), (1700, 75), (1300, 65), (1000, 55), (800, 45))

# Re-encoding anything smaller than this rarely pays for the quality loss.
MIN_IMAGE_BYTES = 16 * 1024


@dataclass(frozen=True)
class CompressionResult:
    path: Path
    original_bytes: int
    final_bytes: int
    strategy: str
    fits_target: bool


def human_size(num_bytes: int) -> str:
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.0f}KB"
    return f"{num_bytes / (1024 * 1024):.2f}MB"


def _save_optimized(doc: fitz.Document, dest: Path) -> None:
    doc.save(
        str(dest),
        garbage=4,
        clean=True,
        deflate=True,
        deflate_images=True,
        deflate_fonts=True,
        use_objstms=1,
    )


def _collect_images(doc: fitz.Document) -> dict[int, int]:
    # xref -> page index holding it. replace_image() needs a page to call on, but
    # swaps the object everywhere it is referenced, so one page per xref is enough.
    targets: dict[int, int] = {}
    seen: set[int] = set()

    for page_index in range(doc.page_count):
        for image in doc[page_index].get_images(full=True):
            xref, smask = image[0], image[1]
            if xref in seen:
                continue
            seen.add(xref)
            # An smask carries the alpha channel; a JPEG rewrite would drop it.
            if smask:
                continue
            try:
                raw = doc.extract_image(xref).get("image") or b""
            except Exception:
                continue
            if len(raw) >= MIN_IMAGE_BYTES:
                targets[xref] = page_index

    return targets


def _shrink_image_bytes(raw: bytes, max_edge: int, quality: int) -> Optional[bytes]:
    try:
        with Image.open(io.BytesIO(raw)) as img:
            img.load()
            if img.mode in {"RGBA", "LA"} or (img.mode == "P" and "transparency" in img.info):
                return None
            frame = img.convert("RGB") if img.mode != "RGB" else img

            longest = max(frame.size)
            if longest > max_edge:
                scale = max_edge / longest
                frame = frame.resize(
                    (max(1, round(frame.width * scale)), max(1, round(frame.height * scale))),
                    Image.LANCZOS,
                )

            buf = io.BytesIO()
            frame.save(buf, format="JPEG", quality=quality, optimize=True, progressive=True)
            return buf.getvalue()
    except Exception:
        return None


def _recompress_images(doc: fitz.Document, targets: dict[int, int], max_edge: int, quality: int) -> int:
    replaced = 0

    for xref, page_index in targets.items():
        try:
            raw = doc.extract_image(xref).get("image") or b""
        except Exception:
            continue
        if not raw:
            continue

        shrunk = _shrink_image_bytes(raw, max_edge, quality)
        if shrunk is None or len(shrunk) >= len(raw):
            continue

        try:
            doc[page_index].replace_image(xref, stream=shrunk)
            replaced += 1
        except Exception:
            continue

    return replaced


def compress_pdf(
    source: Path,
    dest: Path,
    target_bytes: int = DEFAULT_TARGET_BYTES,
    strict: bool = True,
) -> CompressionResult:
    """Write a copy of `source` at `dest`, as close to `target_bytes` as possible.

    Tries lossless object cleanup first, then progressively harder downsampling and
    JPEG re-encoding of embedded images. Raises ValueError when `strict` and the
    target is still out of reach.
    """
    source = Path(source)
    dest = Path(dest)

    if target_bytes <= 0:
        raise ValueError("target_bytes must be > 0")
    if not source.is_file():
        raise ValueError(f"No such PDF: {source}")

    original_bytes = source.stat().st_size
    dest.parent.mkdir(parents=True, exist_ok=True)

    if original_bytes <= target_bytes:
        if source.resolve() != dest.resolve():
            dest.write_bytes(source.read_bytes())
        return CompressionResult(dest, original_bytes, original_bytes, "already-under-target", True)

    with fitz.open(source) as doc:
        # Collect before saving: garbage collection renumbers xrefs on the way out.
        targets = _collect_images(doc)
        _save_optimized(doc, dest)

    best_bytes = dest.stat().st_size
    best_strategy = "lossless"

    if best_bytes > target_bytes and targets:
        staging = dest.with_name(dest.name + ".compress-tmp")
        try:
            for max_edge, quality in IMAGE_PASSES:
                with fitz.open(source) as doc:
                    if not _recompress_images(doc, targets, max_edge, quality):
                        continue
                    _save_optimized(doc, staging)

                candidate_bytes = staging.stat().st_size
                if candidate_bytes < best_bytes:
                    os.replace(staging, dest)
                    best_bytes = candidate_bytes
                    best_strategy = f"images@{max_edge}px/q{quality}"

                if best_bytes <= target_bytes:
                    break
        finally:
            staging.unlink(missing_ok=True)

    fits_target = best_bytes <= target_bytes
    if strict and not fits_target:
        raise ValueError(
            f"Could not compress {source.name} under {human_size(target_bytes)}: "
            f"best effort was {human_size(best_bytes)} (from {human_size(original_bytes)})."
        )

    return CompressionResult(dest, original_bytes, best_bytes, best_strategy, fits_target)
