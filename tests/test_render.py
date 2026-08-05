import re
from pathlib import Path

from confluence_downloader.models import Page
from confluence_downloader.render import (
    WIDE_TABLE_CLASS,
    _inject_source_metadata,
    _inline_images,
    _prepare_pdf_html,
    _prepare_web_html,
    _tag_wide_tables,
)


def _table(columns: int, cell: str = "<p>x</p>") -> str:
    row = "".join(f"<td>{cell}</td>" for _ in range(columns))
    return f"<table><tbody><tr>{row}</tr></tbody></table>"


NESTED_LIST_CELL = "<ul><li>a<ul><li>b</li></ul></li></ul>"


def test_prepare_pdf_html_unhides_aura_tab_panels() -> None:
    html = (
        "<html><head></head><body>"
        '<div hidden="" aria-hidden="true" data-aura-tab-title="Discussion topics" '
        'data-macro-name="aura-tab"><p>Panel content</p></div>'
        "</body></html>"
    )

    prepared = _prepare_pdf_html(html)

    assert 'data-macro-name="aura-tab"' in prepared
    aura_panel = re.search(r'<div[^>]+data-macro-name="aura-tab"[^>]*>', prepared)
    assert aura_panel
    assert "hidden" not in aura_panel.group(0)
    assert "aria-hidden" not in aura_panel.group(0)
    assert 'content: attr(data-aura-tab-title)' in prepared


def test_prepare_pdf_html_unhides_export_view_aura_tab_panels() -> None:
    html = (
        "<html><head></head><body>"
        '<div hidden="" aria-hidden="true" data-aura-tab-title="Discussion topics">'
        "<p>Panel content</p></div>"
        "</body></html>"
    )

    prepared = _prepare_pdf_html(html)

    aura_panel = re.search(r'<div[^>]+data-aura-tab-title="Discussion topics"[^>]*>', prepared)
    assert aura_panel
    assert "hidden" not in aura_panel.group(0)
    assert "aria-hidden" not in aura_panel.group(0)


def test_prepare_pdf_html_routes_wide_tables_to_landscape_pages() -> None:
    html = f"<html><head></head><body>{_table(5)}</body></html>"

    prepared = _prepare_pdf_html(html)

    assert f'class="{WIDE_TABLE_CLASS}"' in prepared
    assert "@page landscape-table" in prepared
    assert "size: A4 landscape" in prepared


def test_tag_wide_tables_leaves_narrow_tables_alone() -> None:
    html = f"<html><head></head><body>{_table(3)}</body></html>"

    assert WIDE_TABLE_CLASS not in _tag_wide_tables(html)


def test_tag_wide_tables_counts_colspan() -> None:
    html = (
        "<html><body><table><tr>"
        '<td colspan="3">a</td><td>b</td>'
        "</tr></table></body></html>"
    )

    assert WIDE_TABLE_CLASS in _tag_wide_tables(html)


def test_tag_wide_tables_flags_three_columns_with_nested_lists() -> None:
    html = f"<html><body>{_table(3, NESTED_LIST_CELL)}</body></html>"

    assert WIDE_TABLE_CLASS in _tag_wide_tables(html)


def test_tag_wide_tables_ignores_nested_tables() -> None:
    inner = _table(5)
    html = f"<html><body><table><tr><td>{inner}</td></tr></table></body></html>"

    tagged = _tag_wide_tables(html)

    assert WIDE_TABLE_CLASS not in tagged


def test_inline_images_embeds_same_host_images_as_data_uris() -> None:
    html = '<html><body><img src="/download/thumb.png" srcset="/x 2x"></body></html>'

    def fetcher(url: str) -> dict:
        assert url == "https://confluence.example.test/download/thumb.png"
        return {"string": b"pngbytes", "mime_type": "image/png"}

    inlined = _inline_images(
        html, base_url="https://confluence.example.test", asset_fetcher=fetcher
    )

    assert 'src="data:image/png;base64,cG5nYnl0ZXM="' in inlined
    assert "srcset" not in inlined


def test_inline_images_never_fetches_other_hosts() -> None:
    html = '<html><body><img src="https://elsewhere.example.test/pic.png"></body></html>'

    def fetcher(url: str) -> dict:
        raise AssertionError(f"unexpected fetch: {url}")

    inlined = _inline_images(
        html, base_url="https://confluence.example.test", asset_fetcher=fetcher
    )

    assert 'src="https://elsewhere.example.test/pic.png"' in inlined


def test_inline_images_keeps_remote_url_when_fetch_fails() -> None:
    html = '<html><body><img src="/download/thumb.png"></body></html>'

    def fetcher(url: str) -> dict:
        raise OSError("boom")

    inlined = _inline_images(
        html, base_url="https://confluence.example.test", asset_fetcher=fetcher
    )

    assert 'src="/download/thumb.png"' in inlined


def test_prepare_web_html_makes_table_wrappers_scrollable() -> None:
    html = f'<html><head></head><body><div class="table-wrap">{_table(5)}</div></body></html>'

    prepared = _prepare_web_html(html, base_url="https://confluence.example.test", asset_fetcher=None)

    assert "overflow-x: auto" in prepared
    assert WIDE_TABLE_CLASS not in prepared


def test_inject_source_metadata_adds_link_to_full_html_document() -> None:
    html = "<html><head></head><body><h1>Rendered page</h1></body></html>"
    page = Page(
        id="123",
        title="Rendered page",
        url="https://confluence.example.test/pages/viewpage.action?pageId=123",
    )

    prepared = _inject_source_metadata(html, page)

    assert '<div class="confluence-downloader-metadata">' in prepared
    assert f'href="{page.url}"' in prepared
    assert prepared.index("confluence-downloader-metadata") < prepared.index("<h1>Rendered page</h1>")


def test_write_confluence_html_rewrites_attachment_links(tmp_path) -> None:
    from confluence_downloader.render import write_confluence_html

    html = (
        '<p><a href="/download/attachments/123/meeting%20notes.txt?version=2&api=v2">'
        "notes</a></p>"
    )
    destination = tmp_path / "page.html"
    write_confluence_html(
        page=Page(id="123", title="Root", url="https://confluence.example.test/x"),
        html=html,
        destination=destination,
        base_url="https://confluence.example.test",
        attachment_targets={"meeting notes.txt": "../attachments/root-123/meeting%20notes.txt"},
    )

    saved = destination.read_text(encoding="utf-8")
    assert 'href="../attachments/root-123/meeting%20notes.txt"' in saved


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_sprint_review_fixture_flags_discussion_table_as_wide() -> None:
    html = (FIXTURE_DIR / "sprint_review_export_view.html").read_text(encoding="utf-8")

    tagged = _tag_wide_tables(html)

    assert f'class="{WIDE_TABLE_CLASS}"' in tagged


def test_sprint_review_fixture_renders_wide_tables_on_landscape_pages(tmp_path) -> None:
    # Regression for the real page whose 5-column table rendered one
    # character per line: wide tables must land on landscape pages and
    # the document must not balloon into dozens of near-empty pages.
    from pypdf import PdfReader

    from confluence_downloader.render import render_html_pdf

    html = (FIXTURE_DIR / "sprint_review_export_view.html").read_text(encoding="utf-8")
    destination = tmp_path / "fixture.pdf"

    def offline_fetcher(url: str) -> dict:
        raise OSError(f"offline test refused to fetch {url}")

    render_html_pdf(
        page=Page(id="1", title="Sprint review fixture"),
        html=html,
        destination=destination,
        base_url="https://confluence.example.test",
        url_fetcher=offline_fetcher,
    )

    reader = PdfReader(destination)
    orientations = [
        "landscape" if page.mediabox.width > page.mediabox.height else "portrait"
        for page in reader.pages
    ]
    assert "landscape" in orientations
    assert "portrait" in orientations
    assert len(orientations) <= 20
