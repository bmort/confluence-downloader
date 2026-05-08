from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from confluence_downloader.client import ConfluenceClient
from confluence_downloader.errors import ConfluenceApiError, PageLookupError, PdfExportError
from confluence_downloader.models import Page


def make_client(handler) -> ConfluenceClient:
    return ConfluenceClient(
        "https://confluence.example.test/confluence",
        "pat-token",
        transport=httpx.MockTransport(handler),
    )


def test_resolve_page_by_title_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer pat-token"
        assert request.url.path == "/confluence/rest/api/content"
        assert request.url.params["spaceKey"] == "DOC"
        assert request.url.params["title"] == "Root"
        assert request.url.params["expand"] == "version"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "123",
                        "title": "Root",
                        "_links": {"webui": "/display/DOC/Root"},
                        "version": {"number": 7, "when": "2026-05-01T08:30:00.000Z"},
                    }
                ]
            },
        )

    with make_client(handler) as client:
        assert client.resolve_page_by_title("DOC", "Root") == Page(
            id="123",
            title="Root",
            url="https://confluence.example.test/confluence/display/DOC/Root",
            version=7,
            version_when="2026-05-01T08:30:00.000Z",
        )


def test_resolve_page_by_title_no_match() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": []})

    with make_client(handler) as client:
        with pytest.raises(PageLookupError):
            client.resolve_page_by_title("DOC", "Missing")


def test_resolve_page_by_title_duplicate_match() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"results": [{"id": "1", "title": "Dup"}, {"id": "2", "title": "Dup"}]},
        )

    with make_client(handler) as client:
        with pytest.raises(PageLookupError):
            client.resolve_page_by_title("DOC", "Dup")


def test_resolve_page_by_title_raises_on_auth_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Unauthorized"})

    with make_client(handler) as client:
        with pytest.raises(ConfluenceApiError, match="HTTP 401"):
            client.resolve_page_by_title("DOC", "Root")


def test_get_json_retries_http_429_with_retry_after() -> None:
    calls = 0
    sleeps = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0.5"})
        return httpx.Response(200, json={"results": [{"id": "123", "title": "Root"}]})

    with ConfluenceClient(
        "https://confluence.example.test/confluence",
        "pat-token",
        transport=httpx.MockTransport(handler),
        max_retries=2,
        retry_backoff=10.0,
        sleep=sleeps.append,
    ) as client:
        assert client.resolve_page_by_title("DOC", "Root").id == "123"

    assert calls == 2
    assert sleeps == [0.5]


def test_get_json_uses_exponential_backoff_when_retry_after_missing() -> None:
    calls = 0
    sleeps = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(429)
        return httpx.Response(200, json={"results": [{"id": "123", "title": "Root"}]})

    with ConfluenceClient(
        "https://confluence.example.test/confluence",
        "pat-token",
        transport=httpx.MockTransport(handler),
        max_retries=3,
        retry_backoff=0.25,
        sleep=sleeps.append,
    ) as client:
        assert client.resolve_page_by_title("DOC", "Root").id == "123"

    assert calls == 3
    assert sleeps == [0.25, 0.5]


def test_list_child_pages_handles_pagination() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        start = request.url.params["start"]
        assert request.url.params["expand"] == "version"
        if start == "0":
            return httpx.Response(
                200,
                json={
                    "results": [{"id": "2", "title": "Child A"}],
                    "start": 0,
                    "limit": 1,
                    "size": 1,
                },
            )
        return httpx.Response(
            200,
            json={
                "results": [{"id": "3", "title": "Child B"}],
                "start": 1,
                "limit": 1,
                "size": 0,
            },
        )

    with make_client(handler) as client:
        assert client.list_child_pages("1", page_size=1) == [
            Page(id="2", title="Child A", url="https://confluence.example.test/confluence/pages/viewpage.action?pageId=2"),
            Page(id="3", title="Child B", url="https://confluence.example.test/confluence/pages/viewpage.action?pageId=3"),
        ]


def test_list_space_root_pages_handles_pagination() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/confluence/rest/api/space/DOC/content/page"
        assert request.url.params["depth"] == "root"
        assert request.url.params["expand"] == "version"
        start = request.url.params["start"]
        if start == "0":
            return httpx.Response(
                200,
                json={
                    "page": {
                        "results": [{"id": "1", "title": "Root A"}],
                        "start": 0,
                        "limit": 1,
                        "size": 1,
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "page": {
                    "results": [{"id": "2", "title": "Root B"}],
                    "start": 1,
                    "limit": 1,
                    "size": 0,
                }
            },
        )

    with make_client(handler) as client:
        assert client.list_space_root_pages("DOC", page_size=1) == [
            Page(id="1", title="Root A", url="https://confluence.example.test/confluence/pages/viewpage.action?pageId=1"),
            Page(id="2", title="Root B", url="https://confluence.example.test/confluence/pages/viewpage.action?pageId=2"),
        ]


def test_iter_descendants_recurses_depth_first() -> None:
    child_map = {
        "1": [{"id": "2", "title": "Child"}],
        "2": [{"id": "3", "title": "Grandchild"}],
        "3": [],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        page_id = request.url.path.rstrip("/").split("/")[-3]
        assert request.url.params["expand"] == "version"
        results = child_map[page_id]
        return httpx.Response(200, json={"results": results, "limit": 50, "size": len(results)})

    with make_client(handler) as client:
        assert client.iter_descendants(Page(id="1", title="Root")) == [
            Page(id="2", title="Child", url="https://confluence.example.test/confluence/pages/viewpage.action?pageId=2"),
            Page(id="3", title="Grandchild", url="https://confluence.example.test/confluence/pages/viewpage.action?pageId=3"),
        ]


def test_download_pdf_follows_flyingpdf_redirect(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/pdfpageexport.action"):
            assert request.headers["x-atlassian-token"] == "no-check"
            return httpx.Response(302, headers={"location": "/confluence/download/export/page.pdf"})
        if request.url.path.endswith("/download/export/page.pdf"):
            return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF- test")
        return httpx.Response(404)

    output = tmp_path / "page.pdf"
    with make_client(handler) as client:
        client.download_pdf(Page(id="123", title="Root"), output)

    assert output.read_bytes() == b"%PDF- test"


def test_download_native_pdf_raises_on_export_error(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    with make_client(handler) as client:
        with pytest.raises(PdfExportError):
            client.download_native_pdf("123", tmp_path / "page.pdf")


def test_download_native_pdf_raises_on_redirect_download_error(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/pdfpageexport.action"):
            return httpx.Response(302, headers={"location": "/confluence/download/export/page.pdf"})
        return httpx.Response(404)

    with make_client(handler) as client:
        with pytest.raises(PdfExportError, match="HTTP 404"):
            client.download_native_pdf("123", tmp_path / "page.pdf")


def test_download_native_pdf_rejects_html_login_page(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=b"<!DOCTYPE html><h1>Verify your login via MFA</h1>",
        )

    with make_client(handler) as client:
        with pytest.raises(PdfExportError, match="returned HTML instead of PDF"):
            client.download_native_pdf("123", tmp_path / "page.pdf")


def test_download_pdf_falls_back_to_rest_export_view(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/pdfpageexport.action"):
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                content=b"<!DOCTYPE html><h1>Verify your login via MFA</h1>",
            )
        if request.url.path.endswith("/rest/api/content/123"):
            assert request.url.params["expand"] == "body.export_view"
            return httpx.Response(
                200,
                json={"body": {"export_view": {"value": "<h1>Root</h1><p>Context text</p>"}}},
            )
        return httpx.Response(404)

    output = tmp_path / "page.pdf"
    with make_client(handler) as client:
        client.download_pdf(Page(id="123", title="Root"), output)

    assert output.read_bytes().startswith(b"%PDF-")
