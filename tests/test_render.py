import re

from confluence_downloader.models import Page
from confluence_downloader.render import _inject_source_metadata, _prepare_confluence_html


def test_prepare_confluence_html_unhides_aura_tab_panels() -> None:
    html = (
        "<html><head></head><body>"
        '<div hidden="" aria-hidden="true" data-aura-tab-title="Discussion topics" '
        'data-macro-name="aura-tab"><p>Panel content</p></div>'
        "</body></html>"
    )

    prepared = _prepare_confluence_html(html)

    assert 'data-macro-name="aura-tab"' in prepared
    aura_panel = re.search(r'<div[^>]+data-macro-name="aura-tab"[^>]*>', prepared)
    assert aura_panel
    assert "hidden" not in aura_panel.group(0)
    assert "aria-hidden" not in aura_panel.group(0)
    assert 'content: attr(data-aura-tab-title)' in prepared


def test_prepare_confluence_html_unhides_export_view_aura_tab_panels() -> None:
    html = (
        "<html><head></head><body>"
        '<div hidden="" aria-hidden="true" data-aura-tab-title="Discussion topics">'
        "<p>Panel content</p></div>"
        "</body></html>"
    )

    prepared = _prepare_confluence_html(html)

    aura_panel = re.search(r'<div[^>]+data-aura-tab-title="Discussion topics"[^>]*>', prepared)
    assert aura_panel
    assert "hidden" not in aura_panel.group(0)
    assert "aria-hidden" not in aura_panel.group(0)


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
