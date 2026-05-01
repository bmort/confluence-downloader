from __future__ import annotations

from pathlib import Path
import time
from typing import Any
from urllib.parse import urljoin

import httpx

from .errors import ConfluenceApiError, ConfluencePdfError, PageLookupError, PdfExportError
from .models import Page
from .render import render_combined_html_pdf, render_html_pdf
from .utils import normalize_base_url


class ConfluenceClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
        request_delay: float = 0.0,
        retry_backoff: float = 1.0,
        max_retries: int = 3,
        sleep: Any = time.sleep,
    ) -> None:
        self.base_url = normalize_base_url(base_url)
        self.request_delay = request_delay
        self.retry_backoff = retry_backoff
        self.max_retries = max_retries
        self._sleep = sleep
        self._last_request_at = 0.0
        self._client = httpx.Client(
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ConfluenceClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def resolve_page_by_title(self, space_key: str, title: str) -> Page:
        data = self._get_json(
            "/rest/api/content",
            params={
                "spaceKey": space_key,
                "type": "page",
                "title": title,
                "status": "current",
                "limit": 2,
                "expand": "version",
            },
        )
        results = data.get("results", [])
        if not results:
            raise PageLookupError(f'No current page found for title "{title}" in space {space_key}.')
        if len(results) > 1:
            raise PageLookupError(f'More than one page matched title "{title}" in space {space_key}.')
        return self._page_from_result(results[0])

    def iter_descendants(self, root: Page, *, page_size: int = 50) -> list[Page]:
        descendants: list[Page] = []
        stack = [root]

        while stack:
            parent = stack.pop()
            children = self.list_child_pages(parent.id, page_size=page_size)
            descendants.extend(children)
            stack.extend(reversed(children))

        return descendants

    def list_space_root_pages(self, space_key: str, *, page_size: int = 50) -> list[Page]:
        pages: list[Page] = []
        start = 0

        while True:
            data = self._get_json(
                f"/rest/api/space/{space_key}/content/page",
                params={
                    "depth": "root",
                    "start": start,
                    "limit": page_size,
                    "expand": "version",
                },
            )
            page_data = data.get("page", data)
            results = page_data.get("results", [])
            for result in results:
                pages.append(self._page_from_result(result))

            size = int(page_data.get("size", len(results)))
            limit = int(page_data.get("limit", page_size))
            if size == 0 or size < limit:
                break
            start += size

        return pages

    def list_child_pages(self, page_id: str, *, page_size: int = 50) -> list[Page]:
        pages: list[Page] = []
        start = 0

        while True:
            data = self._get_json(
                f"/rest/api/content/{page_id}/child/page",
                params={"start": start, "limit": page_size, "expand": "version"},
            )
            page_data = data.get("page", data)
            results = page_data.get("results", [])
            for result in results:
                pages.append(self._page_from_result(result))

            size = int(page_data.get("size", len(results)))
            limit = int(page_data.get("limit", page_size))
            if size == 0 or size < limit:
                break
            start += size

        return pages

    def download_pdf(self, page: Page, destination: Path) -> None:
        try:
            self.download_native_pdf(page.id, destination)
        except PdfExportError as exc:
            try:
                html = self.get_page_export_view(page.id)
                render_html_pdf(
                    page=page,
                    html=html,
                    destination=destination,
                    base_url=self.base_url,
                    url_fetcher=self._fetch_render_asset,
                )
                valid_fallback = destination.read_bytes().startswith(b"%PDF-")
            except (ConfluencePdfError, ImportError, OSError, ValueError) as fallback_exc:
                raise PdfExportError(
                    f"Native PDF export failed and REST fallback failed: {fallback_exc}"
                ) from fallback_exc
            if not valid_fallback:
                raise PdfExportError(
                    f"Native PDF export failed and REST fallback did not create a valid PDF: {exc}"
                ) from exc

    def download_combined_pdf(self, pages: list[Page], destination: Path) -> None:
        if not pages:
            raise PdfExportError("Cannot create a combined PDF with no pages.")
        try:
            sections = [(page, self.get_page_export_view(page.id)) for page in pages]
            render_combined_html_pdf(
                title=pages[0].title,
                sections=sections,
                destination=destination,
                base_url=self.base_url,
                url_fetcher=self._fetch_render_asset,
            )
        except (ConfluencePdfError, ImportError, OSError, ValueError) as exc:
            raise PdfExportError(f"Combined PDF export failed: {exc}") from exc
        if not destination.read_bytes().startswith(b"%PDF-"):
            raise PdfExportError("Combined PDF export did not create a valid PDF.")

    def download_native_pdf(self, page_id: str, destination: Path) -> None:
        export_url = self._url(f"/spaces/flyingpdf/pdfpageexport.action?pageId={page_id}")
        headers = {"X-Atlassian-Token": "no-check", "Accept": "*/*"}
        try:
            response = self._request("GET", export_url, headers=headers, follow_redirects=False)
        except httpx.HTTPError as exc:
            raise PdfExportError(f"Could not start PDF export for page {page_id}: {exc}") from exc

        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("location")
            if not location:
                raise PdfExportError(f"PDF export for page {page_id} redirected without a Location header.")
            download_url = urljoin(self.base_url + "/", location)
            self._stream_pdf(download_url, destination, page_id)
            return

        if response.status_code == 200 and self._looks_like_pdf(response):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(response.content)
            return

        if response.status_code == 200 and self._looks_like_html(response):
            raise PdfExportError(
                f"Native PDF export for page {page_id} returned HTML instead of PDF. "
                "This usually means the FlyingPDF UI action requires a browser session or MFA."
            )

        raise PdfExportError(
            f"PDF export for page {page_id} failed with HTTP {response.status_code}."
        )

    def get_page_export_view(self, page_id: str) -> str:
        data = self._get_json(
            f"/rest/api/content/{page_id}",
            params={"expand": "body.export_view"},
        )
        try:
            return str(data["body"]["export_view"]["value"])
        except KeyError as exc:
            raise ConfluenceApiError(
                f"Confluence response for page {page_id} did not include body.export_view."
            ) from exc

    def _stream_pdf(self, url: str, destination: Path, page_id: str) -> None:
        try:
            response = self._request("GET", url, headers={"Accept": "application/pdf"})
            if response.status_code >= 400:
                raise PdfExportError(
                    f"PDF download for page {page_id} failed with HTTP {response.status_code}."
                )
            content_type = response.headers.get("content-type", "").lower()
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary_destination = destination.with_suffix(destination.suffix + ".tmp")
            with temporary_destination.open("wb") as handle:
                for chunk in response.iter_bytes():
                    handle.write(chunk)
            response.close()
            if not self._file_looks_like_pdf(temporary_destination):
                temporary_destination.unlink(missing_ok=True)
                raise PdfExportError(
                    f"PDF download for page {page_id} returned {content_type or 'unknown content'} "
                    "instead of PDF."
                )
            temporary_destination.replace(destination)
        except httpx.HTTPError as exc:
            raise PdfExportError(f"Could not download PDF for page {page_id}: {exc}") from exc

    def _get_json(self, path: str, *, params: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self._request("GET", self._url(path), params=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            raise ConfluenceApiError(
                f"Confluence request failed with HTTP {exc.response.status_code}: {path}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ConfluenceApiError(f"Confluence request failed: {path}: {exc}") from exc
        except ValueError as exc:
            raise ConfluenceApiError(f"Confluence returned invalid JSON: {path}") from exc

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def _page_from_result(self, result: dict[str, Any]) -> Page:
        page_id = str(result["id"])
        links = result.get("_links", {})
        webui = links.get("webui")
        version = result.get("version", {})
        version_number = version.get("number")
        if not isinstance(version_number, int):
            version_number = None
        return Page(
            id=page_id,
            title=str(result["title"]),
            url=self._page_url(str(webui), page_id) if webui else self._url(f"/pages/viewpage.action?pageId={page_id}"),
            version=version_number,
            version_when=str(version.get("when", "")),
        )

    def _page_url(self, webui: str, page_id: str) -> str:
        if webui.startswith(("http://", "https://")):
            return webui
        if not webui:
            return self._url(f"/pages/viewpage.action?pageId={page_id}")
        return urljoin(self.base_url + "/", webui.lstrip("/"))

    def _fetch_render_asset(self, url: str) -> dict:
        asset_url = urljoin(self.base_url + "/", url)
        response = self._request("GET", asset_url, headers={"Accept": "*/*"})
        response.raise_for_status()
        return {
            "string": response.content,
            "mime_type": response.headers.get("content-type", "").split(";", 1)[0],
            "redirected_url": str(response.url),
        }

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        attempt = 0
        while True:
            self._apply_request_delay()
            response = self._client.request(method, url, **kwargs)
            if response.status_code != 429 or attempt >= self.max_retries:
                return response
            retry_delay = self._retry_delay(response, attempt)
            response.close()
            self._sleep(retry_delay)
            attempt += 1

    def _apply_request_delay(self) -> None:
        if self.request_delay <= 0:
            return
        now = time.monotonic()
        elapsed = now - self._last_request_at
        if elapsed < self.request_delay:
            self._sleep(self.request_delay - elapsed)
        self._last_request_at = time.monotonic()

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("retry-after")
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                pass
        return self.retry_backoff * (2**attempt)

    @staticmethod
    def _looks_like_pdf(response: httpx.Response) -> bool:
        content_type = response.headers.get("content-type", "").lower()
        return "pdf" in content_type or response.content.startswith(b"%PDF-")

    @staticmethod
    def _looks_like_html(response: httpx.Response) -> bool:
        content_type = response.headers.get("content-type", "").lower()
        return "html" in content_type or response.content.lstrip().lower().startswith(b"<!doctype html")

    @staticmethod
    def _file_looks_like_pdf(path: Path) -> bool:
        try:
            with path.open("rb") as handle:
                return handle.read(5) == b"%PDF-"
        except OSError:
            return False
