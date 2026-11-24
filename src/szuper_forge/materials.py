from __future__ import annotations
import csv
from html.parser import HTMLParser
import io
from pathlib import Path
import shutil
import subprocess
import tempfile

from .common import check, digest, project, read, write

TEXT = {".txt", ".md", ".rst", ".csv", ".tsv", ".json", ".html", ".htm"}
IMAGE = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}
AUDIO = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}
SUPPORTED = TEXT | IMAGE | AUDIO | {".pdf", ".docx"}


class PlainHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        elif tag in ("p", "br", "li", "tr", "h1", "h2", "h3", "td", "div"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def html_text(source):
    parser = PlainHTML()
    parser.feed(source)
    return "".join(parser.parts).strip()


def ocr(path, language):
    check(shutil.which("tesseract"), "OCR needs tesseract or use attach-text after agent vision")
    result = subprocess.run(
        ["tesseract", str(path), "stdout", "-l", language], text=True, capture_output=True, check=True
    )
    return result.stdout.strip()


def extract_file(path, ocr_language=None):
    ext = path.suffix.lower()
    if ext in TEXT:
        content = path.read_text(encoding="utf-8-sig")  # Encoding errors are visible, never discarded.
        if ext in (".html", ".htm"):
            content = html_text(content)
        elif ext in (".csv", ".tsv"):
            content = "\n".join(
                " | ".join(r)
                for r in csv.reader(io.StringIO(content), delimiter="\t" if ext == ".tsv" else ",")
            )
        return [{"page": 1, "text": content.strip(), "method": "text"}]
    if ext == ".docx":
        from docx import Document

        doc = Document(path)
        content = [p.text for p in doc.paragraphs]
        content += [" | ".join(c.text for c in row.cells) for t in doc.tables for row in t.rows]
        return [{"page": 1, "text": "\n".join(content).strip(), "method": "docx"}]
    if ext == ".pdf":
        from pypdf import PdfReader

        pages = []
        for index, page in enumerate(PdfReader(path).pages, 1):
            content = (page.extract_text() or "").strip()
            method = "pdf-text"
            if not content and ocr_language:
                check(
                    shutil.which("pdftoppm"),
                    "Scanned PDF OCR needs pdftoppm, or attach-text after agent vision",
                )
                with tempfile.TemporaryDirectory() as tmp:
                    dest = Path(tmp) / "page"
                    subprocess.run(
                        [
                            "pdftoppm",
                            "-f",
                            str(index),
                            "-l",
                            str(index),
                            "-singlefile",
                            "-scale-to",
                            "2400",
                            "-png",
                            str(path),
                            str(dest),
                        ],
                        check=True,
                        capture_output=True,
                    )
                    content = ocr(dest.with_suffix(".png"), ocr_language)
                method = "tesseract"
            pages.append({"page": index, "text": content, "method": method if content else "needs-ocr"})
        return pages
    if ext in IMAGE and ocr_language:
        return [{"page": 1, "text": ocr(path, ocr_language), "method": "tesseract"}]
    return [{"page": 1, "text": "", "method": "needs-transcription" if ext in AUDIO else "needs-vision"}]


def extract(root, ocr_language=None):
    config = project(root)
    materials = Path(config.materials).resolve()
    check(materials.is_dir(), f"Materials directory is missing: {materials}")
    # Avoid recursively ingesting our own growing artifacts.
    check(not Path(root).resolve().is_relative_to(materials), "Project must be outside the materials folder")
    paths = sorted(
        p
        for p in materials.rglob("*")
        if p.is_file()
        and not p.is_symlink()
        and not any(s.startswith(".") for s in p.relative_to(materials).parts)
    )
    check(paths, "No visible source files found")
    check(len(paths) <= 2000, "More than 2000 source files; split the source collection")
    previous_path = Path(root) / "sources/manifest.json"
    previous = {s["id"]: s for s in read(previous_path)["sources"]} if previous_path.exists() else {}
    sources = []
    for path in paths:
        relative = path.relative_to(materials).as_posix()
        check(path.resolve().is_relative_to(materials), f"Source escapes material root: {relative}")
        check(path.stat().st_size <= 100 * 1024 * 1024, f"Source exceeds 100 MiB: {relative}")
        sha = digest(path.read_bytes())
        sid = "src-" + digest(relative.encode())[:16]
        old = previous.get(sid)
        if (
            old
            and not old.get("error")
            and old["sha256"] == sha
            and (not ocr_language or all(p["text"] for p in old["pages"]))
        ):
            sources.append(old)
            continue
        try:
            pages = (
                extract_file(path, ocr_language)
                if path.suffix.lower() in SUPPORTED
                else [{"page": 1, "text": "", "method": "unsupported-format"}]
            )
            sources.append({"id": sid, "path": relative, "sha256": sha, "pages": pages})
        except Exception as exc:
            sources.append(
                {"id": sid, "path": relative, "sha256": sha, "pages": [], "error": type(exc).__name__}
            )
    manifest = {"version": 1, "sources": sources}
    write(Path(root) / "sources/manifest.json", manifest)
    return {
        "sources": len(sources),
        "pages": sum(len(s["pages"]) for s in sources),
        "unread_pages": sum(not p["text"] for s in sources for p in s["pages"]),
        "failed_sources": [s["path"] for s in sources if s.get("error")],
    }


def attach_text(root, source_id, page_number, text_path, method):
    manifest_path = Path(root) / "sources/manifest.json"
    manifest = read(manifest_path)
    source = next((s for s in manifest["sources"] if s["id"] == source_id), None)
    check(source is not None, f"Unknown source: {source_id}")
    page = next((p for p in source["pages"] if p["page"] == page_number), None)
    check(page is not None, "Unknown page; rerun extract after fixing a failed source")
    content = Path(text_path).read_text(encoding="utf-8").strip()
    check(content, "Attached text cannot be empty")
    page.update(text=content, method=method)
    write(manifest_path, manifest)
    return {"source_id": source_id, "page": page_number, "method": method}
