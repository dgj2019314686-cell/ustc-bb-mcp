"""Atomic downloads, source tracking and content-based deduplication."""

import asyncio
import hashlib
import json
import os
import re
import tempfile
from email.message import Message
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .errors import BBError
from .models import CourseFile
from .parsing import is_login_page, safe_public_url


def safe_filename(name: str, *, directory: bool = False) -> str:
    name = re.sub(r'[\x00-\x1f<>:"/\\|?*]', "_", unquote(name)).strip(" .")
    name = name or "file.bin"
    stem, suffix = (name, "") if directory else os.path.splitext(name)
    if re.fullmatch(r"CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]", stem, re.I):
        stem = "_" + stem
    return stem[:150] + suffix[:20]


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class Downloader:
    def __init__(self, session, output_dir: Path):
        self.session = session
        self.root = output_dir.resolve()
        self._lock = asyncio.Lock()

    async def download(self, file: CourseFile, course_name: str, *, assignment=False) -> dict:
        async with self._lock:
            return await self._download(file, course_name, assignment=assignment)

    async def _download(self, file, course_name, *, assignment=False):
        folder = self.root / f"{safe_filename(course_name, directory=True)} ({safe_filename(file.course_id)})"
        if assignment:
            folder /= "assignments"
        folder.mkdir(parents=True, exist_ok=True)
        index_path = folder / ".bb-downloads.json"
        try:
            index = json.loads(index_path.read_text("utf-8"))
            if not isinstance(index, dict):
                index = {}
        except (OSError, ValueError):
            index = {}
        temporary = None
        try:
            async with self.session.stream(file.url) as response:
                if response.status_code != 200:
                    raise BBError("download_failed", f"下载返回 HTTP {response.status_code}。")
                disposition = Message()
                disposition["Content-Disposition"] = response.headers.get("content-disposition", "")
                filename = disposition.get_filename()
                if not filename:
                    filename = file.name or Path(urlsplit(file.url).path).name or "file"
                    if not Path(filename).suffix:
                        extensions = {
                            "application/pdf": ".pdf", "application/zip": ".zip",
                            "application/vnd.ms-powerpoint": ".ppt",
                            "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
                            "text/plain": ".txt", "text/html": ".html",
                        }
                        filename += extensions.get(response.headers.get("content-type", "").split(";")[0], ".bin")
                filename = safe_filename(filename)
                digest = hashlib.sha256()
                prefix = bytearray()
                with tempfile.NamedTemporaryFile(dir=folder, suffix=".part", delete=False) as handle:
                    temporary = Path(handle.name)
                    size = 0
                    async for chunk in response.aiter_bytes(256 * 1024):
                        if len(prefix) < 65536:
                            prefix.extend(chunk[:65536 - len(prefix)])
                        size += len(chunk)
                        digest.update(chunk)
                        handle.write(chunk)
                if is_login_page(prefix.decode("utf-8", errors="replace"), str(response.url)):
                    raise BBError("authentication_required", "附件下载返回了登录页面，请重新登录。")
                sample = bytes(prefix).lstrip().lower()
                is_html = "text/html" in response.headers.get("content-type", "").lower() or sample.startswith((b"<!doctype html", b"<html", b"<head", b"<body"))
                if is_html and Path(filename).suffix.casefold() not in {".html", ".htm"}:
                    raise BBError("unexpected_html", "附件地址返回了 HTML 页面，未将错误页面保存为课件。")
                checksum = digest.hexdigest()
            for record in index.values():
                if not isinstance(record, dict) or record.get("sha256") != checksum:
                    continue
                candidate = (folder / str(record.get("filename", ""))).resolve()
                if candidate.parent == folder.resolve() and candidate.is_file() and file_hash(candidate) == checksum:
                    target, skipped = candidate, True
                    break
            else:
                target = folder / filename
                number = 1
                while target.exists():
                    target = folder / f"{Path(filename).stem} ({number}){Path(filename).suffix}"
                    number += 1
                os.replace(temporary, target)
                temporary = None
                skipped = False
            index[file.id] = {"filename": target.name, "sha256": checksum,
                              "source": safe_public_url(file.url), "bytes": size}
            index_temp = None
            try:
                with tempfile.NamedTemporaryFile(dir=folder, suffix=".part", delete=False, mode="w", encoding="utf-8") as handle:
                    index_temp = Path(handle.name)
                    json.dump(index, handle, ensure_ascii=False, indent=2)
                    handle.flush()
                os.replace(index_temp, index_path)
            finally:
                if index_temp:
                    index_temp.unlink(missing_ok=True)
            return {"file_id": file.id, "name": file.name, "path": str(target),
                    "sha256": checksum, "bytes": size, "skipped": skipped,
                    "source_url": safe_public_url(file.url)}
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
