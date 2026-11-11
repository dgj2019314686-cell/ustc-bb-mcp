import hashlib
import json
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest

from ustc_bb_mcp.downloads import Downloader, safe_filename
from ustc_bb_mcp.errors import BBError
from ustc_bb_mcp.models import CourseFile

BASE = "https://www.bb.ustc.edu.cn"


def file(name="课件.pdf", *, file_id="file-1", url=None):
    return CourseFile(id=file_id, course_id="_101_1", name=name,
                      url=url or BASE + "/bbcswebdav/lecture.pdf",
                      source_url=BASE + "/content?course_id=_101_1")


def payload_files(root):
    return [p for p in root.rglob("*") if p.is_file() and p.name != ".bb-downloads.json"]


@pytest.mark.parametrize("original, expected", [
    ("中文课件.pdf", "中文课件.pdf"),
    ("实验:说明?.pdf", "实验_说明_.pdf"),
    ("CON", "_CON"),
    ("aux.txt", "_aux.txt"),
    ("LPT9.pdf", "_LPT9.pdf"),
    (" .. ", "file.bin"),
    ("../../报告.pdf", "_.._报告.pdf"),
    ("folder\\report.pdf", "folder_report.pdf"),
])
def test_windows_safe_names_preserve_chinese(original, expected):
    assert safe_filename(original) == expected


async def test_rfc5987_chinese_filename_is_sanitized_and_stored_atomically(session_factory, tmp_path):
    filename = "实验:说明?.pdf"

    def handle(request):
        return httpx.Response(200, content=b"%PDF fixture", headers={
            "content-type": "application/pdf",
            "content-disposition": "attachment; filename*=UTF-8''" + quote(filename),
        })

    result = await Downloader(session_factory(handle), tmp_path).download(file(), "数学:基础")
    target = Path(result["path"])
    assert target.name == "实验_说明_.pdf"
    assert target.read_bytes() == b"%PDF fixture"
    assert target.parent.name == "数学_基础 (_101_1)"
    assert result["sha256"] == hashlib.sha256(b"%PDF fixture").hexdigest()
    assert not list(tmp_path.rglob("*.part"))


async def test_http_200_login_page_is_not_saved_as_attachment(session_factory, tmp_path):
    session = session_factory(lambda request: httpx.Response(
        200, text='<html><form id="login"><input type="password"></form></html>',
        headers={"content-type": "text/html"},
    ))
    with pytest.raises(BBError) as error:
        await Downloader(session, tmp_path).download(file(), "数据结构")
    assert error.value.code == "authentication_required"
    assert not payload_files(tmp_path)
    assert not list(tmp_path.rglob(".bb-downloads.json"))
    assert not list(tmp_path.rglob("*.part"))


async def test_http_200_access_denied_html_is_not_saved_as_pdf(session_factory, tmp_path):
    session = session_factory(lambda request: httpx.Response(
        200, text='<h1>Access denied</h1><div class="error">Resource unavailable</div>',
        headers={"content-type": "text/html"},
    ))
    with pytest.raises(BBError):
        await Downloader(session, tmp_path).download(file(), "课程")
    assert not payload_files(tmp_path)
    assert not list(tmp_path.rglob("*.part"))


async def test_same_size_different_content_and_name_are_both_saved(session_factory, tmp_path):
    def handle(request):
        body = b"A" * 2048 if request.url.path.endswith("a.pdf") else b"B" * 2048
        return httpx.Response(200, content=body, headers={
            "content-type": "application/pdf", "content-disposition": 'attachment; filename="same.pdf"',
        })

    downloader = Downloader(session_factory(handle), tmp_path)
    first = await downloader.download(file(file_id="a", url=BASE + "/a.pdf"), "课程")
    second = await downloader.download(file(file_id="b", url=BASE + "/b.pdf"), "课程")
    assert not first["skipped"] and not second["skipped"]
    assert first["path"] != second["path"]
    assert first["sha256"] != second["sha256"]
    assert len(payload_files(tmp_path)) == 2


async def test_same_content_different_sources_is_reused_with_both_sources_indexed(session_factory, tmp_path):
    body = b"Identical file content"
    session = session_factory(lambda request: httpx.Response(200, content=body))
    downloader = Downloader(session, tmp_path)
    first = await downloader.download(file("first.pdf", file_id="a", url=BASE + "/first.pdf"), "课程")
    second = await downloader.download(file("second.pdf", file_id="b", url=BASE + "/second.pdf"), "课程")
    assert second["skipped"]
    assert second["path"] == first["path"]
    assert len(payload_files(tmp_path)) == 1
    index = json.loads(next(tmp_path.rglob(".bb-downloads.json")).read_text("utf-8"))
    assert set(index) == {"a", "b"}
    assert index["a"]["source"] != index["b"]["source"]
    assert not list(tmp_path.rglob("*.part"))


async def test_same_source_is_downloaded_again_when_its_content_changes(session_factory, tmp_path):
    bodies = iter([b"Version one", b"Version two"])
    session = session_factory(lambda request: httpx.Response(200, content=next(bodies)))
    downloader = Downloader(session, tmp_path)
    first = await downloader.download(file(), "课程")
    second = await downloader.download(file(), "课程")
    assert not second["skipped"]
    assert first["path"] != second["path"]
    assert Path(first["path"]).read_bytes() == b"Version one"
    assert Path(second["path"]).read_bytes() == b"Version two"
    index = json.loads(next(tmp_path.rglob(".bb-downloads.json")).read_text("utf-8"))
    assert index["file-1"]["sha256"] == second["sha256"]
    assert len(session.requests) == 2


async def test_modified_local_copy_is_not_trusted_for_deduplication(session_factory, tmp_path):
    session = session_factory(lambda request: httpx.Response(200, content=b"Original content"))
    downloader = Downloader(session, tmp_path)
    first = await downloader.download(file(), "课程")
    Path(first["path"]).write_bytes(b"Locally modified")
    second = await downloader.download(file(), "课程")
    assert not second["skipped"]
    assert Path(second["path"]).read_bytes() == b"Original content"
    assert Path(first["path"]).read_bytes() == b"Locally modified"


class FailingStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b"first chunk" * 30000
        raise httpx.ReadError("Simulated interrupted download")


async def test_interrupted_stream_removes_partial_file_and_leaves_no_index(session_factory, tmp_path):
    session = session_factory(lambda request: httpx.Response(200, stream=FailingStream()))
    with pytest.raises(httpx.ReadError):
        await Downloader(session, tmp_path).download(file(), "课程")
    assert not payload_files(tmp_path)
    assert not list(tmp_path.rglob(".bb-downloads.json"))
    assert not list(tmp_path.rglob("*.part"))


async def test_metadata_write_failure_does_not_leave_partial_index(session_factory, tmp_path, monkeypatch):
    session = session_factory(lambda request: httpx.Response(200, content=b"downloaded content"))

    def interrupted_dump(*args, **kwargs):
        raise OSError("Simulated full disk while writing download index")

    monkeypatch.setattr("ustc_bb_mcp.downloads.json.dump", interrupted_dump)
    with pytest.raises(OSError):
        await Downloader(session, tmp_path).download(file(), "课程")
    assert not list(tmp_path.rglob("*.part"))


async def test_download_http_error_and_assignment_subdirectory(session_factory, tmp_path):
    session = session_factory(lambda request: httpx.Response(404))
    with pytest.raises(BBError) as error:
        await Downloader(session, tmp_path).download(file(), "课程", assignment=True)
    assert error.value.code == "download_failed"
    good = session_factory(lambda request: httpx.Response(200, content=b"attachment"))
    result = await Downloader(good, tmp_path).download(file(), "课程", assignment=True)
    assert Path(result["path"]).parent.name == "assignments"


async def test_source_metadata_drops_credentials_and_tickets(session_factory, tmp_path):
    secret_url = BASE + "/bbcswebdav/report.pdf?content_id=_11_1&ticket=private&token=private"
    session = session_factory(lambda request: httpx.Response(200, content=b"content"))
    result = await Downloader(session, tmp_path).download(file(url=secret_url), "课程")
    assert "private" not in result["source_url"]
    assert "content_id" in result["source_url"]
    index_text = next(tmp_path.rglob(".bb-downloads.json")).read_text("utf-8")
    assert "private" not in index_text


async def test_untrusted_index_cannot_reuse_file_outside_course_directory(session_factory, tmp_path):
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"same content")
    target_dir = tmp_path / "课程 (_101_1)"
    target_dir.mkdir()
    (target_dir / ".bb-downloads.json").write_text(json.dumps({
        "old": {"filename": "../outside.pdf", "sha256": hashlib.sha256(b"same content").hexdigest()},
    }), "utf-8")
    session = session_factory(lambda request: httpx.Response(200, content=b"same content"))
    result = await Downloader(session, tmp_path).download(file(), "课程")
    assert not result["skipped"]
    assert Path(result["path"]).parent == target_dir
    assert outside.read_bytes() == b"same content"


def test_course_directory_dots_are_not_truncated_as_a_file_extension():
    from ustc_bb_mcp.downloads import safe_filename
    course = "_123456_1 CS2502A.02.2026FA: 数据结构A"
    folder = safe_filename(course, directory=True)
    assert folder.startswith("_123456_1 ")
    assert folder.endswith("数据结构A")
    assert ":" not in folder
