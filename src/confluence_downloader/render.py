from __future__ import annotations

from pathlib import Path
import os
import re
import sys
from typing import Callable
from urllib.parse import urljoin

from .models import Page

UrlFetcher = Callable[[str], dict]


def write_confluence_html(
    *,
    page: Page,
    html: str,
    destination: Path,
    base_url: str,
) -> None:
    """Write a standalone HTML copy of a Confluence page."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if _is_full_html_document(html):
        document = _inject_base_href(html, base_url)
        document = _inject_source_metadata(document, page)
    else:
        document = _wrap_confluence_html_page(page, html, base_url)
    document = _rewrite_root_relative_urls(document, base_url)
    document = _prepare_confluence_html(document)
    destination.write_text(document, encoding="utf-8")


def render_html_pdf(
    *,
    page: Page,
    html: str,
    destination: Path,
    base_url: str,
    url_fetcher: UrlFetcher | None = None,
) -> None:
    """Render Confluence export_view HTML to a formatted, searchable PDF."""
    _ensure_homebrew_library_path()
    from weasyprint import HTML

    destination.parent.mkdir(parents=True, exist_ok=True)
    if _is_full_html_document(html):
        document = _inject_source_metadata(html, page)
    else:
        document = _wrap_confluence_html(page, html)
    document = _prepare_confluence_html(document)
    HTML(string=document, base_url=base_url, url_fetcher=url_fetcher).write_pdf(destination)


def render_combined_html_pdf(
    *,
    title: str,
    sections: list[tuple[Page, str]],
    destination: Path,
    base_url: str,
    url_fetcher: UrlFetcher | None = None,
) -> None:
    """Render multiple Confluence export_view documents into one formatted PDF."""
    _ensure_homebrew_library_path()
    from weasyprint import HTML

    destination.parent.mkdir(parents=True, exist_ok=True)
    document = _prepare_confluence_html(_wrap_combined_confluence_html(title, sections))
    HTML(string=document, base_url=base_url, url_fetcher=url_fetcher).write_pdf(destination)


def is_pdf_file(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(5) == b"%PDF-"
    except OSError:
        return False


def _wrap_confluence_html(page: Page, body_html: str) -> str:
    title = _escape_html(page.title)
    source = _escape_html(page.url)
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <style>
    @page {{
      size: A4;
      margin: 18mm 16mm;
    }}
    body {{
      color: #172b4d;
      font-family: Arial, Helvetica, sans-serif;
      font-size: 10.5pt;
      line-height: 1.45;
    }}
    h1, h2, h3, h4, h5, h6 {{
      color: #172b4d;
      line-height: 1.2;
      margin: 1.2em 0 0.45em;
    }}
    h1 {{
      border-bottom: 1px solid #dfe1e6;
      font-size: 22pt;
      padding-bottom: 8px;
    }}
    h2 {{ font-size: 17pt; }}
    h3 {{ font-size: 14pt; }}
    p {{ margin: 0 0 0.75em; }}
    a {{ color: #0052cc; overflow-wrap: anywhere; text-decoration: none; }}
    table {{
      border-collapse: collapse;
      margin: 0.8em 0 1em;
      table-layout: fixed;
      width: 100%;
    }}
    th, td {{
      border: 1px solid #c1c7d0;
      overflow-wrap: anywhere;
      padding: 5px 7px;
      vertical-align: top;
    }}
    th {{
      background: #f4f5f7;
      font-weight: 700;
    }}
    img, svg {{
      height: auto;
      max-width: 100%;
    }}
    pre, code {{
      background: #f4f5f7;
      border-radius: 3px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 9pt;
    }}
    pre {{
      overflow-wrap: break-word;
      padding: 8px;
      white-space: pre-wrap;
    }}
    blockquote {{
      border-left: 3px solid #c1c7d0;
      color: #44546f;
      margin-left: 0;
      padding-left: 12px;
    }}
    .metadata {{
      color: #626f86;
      font-size: 8.5pt;
      margin-bottom: 16px;
    }}
    .confluence-information-macro,
    .confluence-warning-macro,
    .confluence-note-macro,
    .confluence-tip-macro {{
      border: 1px solid #c1c7d0;
      border-radius: 4px;
      margin: 0.8em 0;
      padding: 8px 10px;
    }}
  </style>
</head>
<body>
  <h1>{title}</h1>
  <div class="metadata">Source: {source}</div>
  {body_html}
</body>
</html>
"""


def _wrap_confluence_html_page(page: Page, body_html: str, base_url: str) -> str:
    title = _escape_html(page.title)
    source = _escape_html(page.url)
    base = _escape_html(base_url.rstrip("/") + "/")
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <base href="{base}">
  <title>{title}</title>
  <style>
    body {{
      color: #172b4d;
      font-family: Arial, Helvetica, sans-serif;
      font-size: 14px;
      line-height: 1.4285715;
      margin: 0 auto;
      max-width: 1120px;
      padding: 24px 32px 48px;
    }}
    h1, h2, h3, h4, h5, h6 {{
      color: #172b4d;
      line-height: 1.25;
    }}
    a {{ color: #0052cc; }}
    img, svg {{
      height: auto;
      max-width: 100%;
    }}
    table {{
      border-collapse: collapse;
      margin: 0.8em 0 1em;
      width: 100%;
    }}
    th, td {{
      border: 1px solid #c1c7d0;
      padding: 7px 10px;
      vertical-align: top;
    }}
    th {{
      background: #f4f5f7;
      font-weight: 700;
    }}
    pre, code {{
      background: #f4f5f7;
      border-radius: 3px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }}
    pre {{
      overflow-x: auto;
      padding: 12px;
    }}
    .confluence-downloader-metadata {{
      color: #626f86;
      font-size: 12px;
      margin: 0 0 16px;
    }}
  </style>
</head>
<body>
  <h1>{title}</h1>
  <div class="confluence-downloader-metadata">Source: <a href="{source}">{source}</a></div>
  {body_html}
</body>
</html>
"""


def _wrap_combined_confluence_html(title: str, sections: list[tuple[Page, str]]) -> str:
    safe_title = _escape_html(title)
    rendered_sections = "\n".join(_render_section(page, body_html) for page, body_html in sections)
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>{safe_title}</title>
  <style>
    @page {{
      size: A4;
      margin: 18mm 16mm;
    }}
    body {{
      color: #172b4d;
      font-family: Arial, Helvetica, sans-serif;
      font-size: 10.5pt;
      line-height: 1.45;
    }}
    h1, h2, h3, h4, h5, h6 {{
      color: #172b4d;
      line-height: 1.2;
      margin: 1.2em 0 0.45em;
    }}
    h1 {{
      border-bottom: 1px solid #dfe1e6;
      font-size: 22pt;
      padding-bottom: 8px;
    }}
    h2 {{ font-size: 17pt; }}
    h3 {{ font-size: 14pt; }}
    p {{ margin: 0 0 0.75em; }}
    a {{ color: #0052cc; overflow-wrap: anywhere; text-decoration: none; }}
    table {{
      border-collapse: collapse;
      margin: 0.8em 0 1em;
      table-layout: fixed;
      width: 100%;
    }}
    th, td {{
      border: 1px solid #c1c7d0;
      overflow-wrap: anywhere;
      padding: 5px 7px;
      vertical-align: top;
    }}
    th {{
      background: #f4f5f7;
      font-weight: 700;
    }}
    img, svg {{
      height: auto;
      max-width: 100%;
    }}
    pre, code {{
      background: #f4f5f7;
      border-radius: 3px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 9pt;
    }}
    pre {{
      overflow-wrap: break-word;
      padding: 8px;
      white-space: pre-wrap;
    }}
    blockquote {{
      border-left: 3px solid #c1c7d0;
      color: #44546f;
      margin-left: 0;
      padding-left: 12px;
    }}
    .metadata {{
      color: #626f86;
      font-size: 8.5pt;
      margin-bottom: 16px;
    }}
    .combined-page {{
      break-before: page;
    }}
    .combined-page:first-child {{
      break-before: auto;
    }}
  </style>
</head>
<body>
  {rendered_sections}
</body>
</html>
"""


def _render_section(page: Page, body_html: str) -> str:
    title = _escape_html(page.title)
    source = _escape_html(page.url)
    body = _html_body_fragment(body_html) if _is_full_html_document(body_html) else body_html
    return f"""
<section class="combined-page">
  <h1>{title}</h1>
  <div class="metadata">Source: {source}</div>
  {body}
</section>
"""


def _prepare_confluence_html(document: str) -> str:
    """Apply print-only fixes for Confluence macros that normally depend on JavaScript."""
    document = _unhide_aura_tab_panels(document)
    return _inject_head_style(document, _confluence_print_fixes())


def _is_full_html_document(html: str) -> bool:
    stripped = html.lstrip().lower()
    return stripped.startswith("<!doctype html") or stripped.startswith("<html")


def _html_body_fragment(html: str) -> str:
    body_start = re.search(r"<body\b[^>]*>", html, flags=re.IGNORECASE)
    body_end = re.search(r"</body\s*>", html, flags=re.IGNORECASE)
    if not body_start or not body_end or body_end.start() <= body_start.end():
        return html
    return html[body_start.end() : body_end.start()]


def _inject_source_metadata(document: str, page: Page) -> str:
    source = _escape_html(page.url)
    metadata = (
        '<div class="confluence-downloader-metadata">'
        f'Source: <a href="{source}">{source}</a>'
        "</div>"
    )
    body_start = re.search(r"<body\b[^>]*>", document, flags=re.IGNORECASE)
    if body_start:
        return f"{document[: body_start.end()]}\n{metadata}\n{document[body_start.end():]}"
    return f"{metadata}\n{document}"


def _inject_base_href(document: str, base_url: str) -> str:
    if re.search(r"<base\b", document, flags=re.IGNORECASE):
        return document
    base = _escape_html(base_url.rstrip("/") + "/")
    base_tag = f'<base href="{base}">'
    head_start = re.search(r"<head\b[^>]*>", document, flags=re.IGNORECASE)
    if head_start:
        return f"{document[: head_start.end()]}\n{base_tag}\n{document[head_start.end():]}"
    return f"{base_tag}\n{document}"


def _rewrite_root_relative_urls(document: str, base_url: str) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group("name")
        quote = match.group("quote")
        value = match.group("value")
        if value.startswith("//"):
            return match.group(0)
        rewritten = urljoin(base_url.rstrip("/") + "/", value.lstrip("/"))
        return f"{name}={quote}{rewritten}{quote}"

    return re.sub(
        r"(?P<name>\b(?:href|src|action))=(?P<quote>[\"'])(?P<value>/[^\"']*)(?P=quote)",
        replace,
        document,
        flags=re.IGNORECASE,
    )


def _inject_head_style(document: str, css: str) -> str:
    style = f"<style>\n{css}\n</style>"
    head_end = re.search(r"</head\s*>", document, flags=re.IGNORECASE)
    if head_end:
        return f"{document[: head_end.start()]}{style}\n{document[head_end.start():]}"
    return f"{style}\n{document}"


def _unhide_aura_tab_panels(document: str) -> str:
    def unhide_panel(match: re.Match[str]) -> str:
        tag = match.group(0)
        if 'data-macro-name="aura-tab"' not in tag and "data-aura-tab-title=" not in tag:
            return tag
        tag = re.sub(r"\s+hidden(?:=(?:\"\"|''|[^\s>]+))?", "", tag, flags=re.IGNORECASE)
        tag = re.sub(r'\s+aria-hidden=(["\'])true\1', "", tag, flags=re.IGNORECASE)
        return tag

    return re.sub(r"<div\b[^>]*>", unhide_panel, document, flags=re.IGNORECASE)


def _confluence_print_fixes() -> str:
    return """
    .confluence-downloader-metadata {
      color: #626f86;
      font-size: 8.5pt;
      margin-bottom: 16px;
    }
    .confluence-downloader-metadata a {
      color: #0052cc;
      text-decoration: none;
    }
    .table-wrap,
    .table-wrapper {
      box-sizing: border-box;
      max-width: 100% !important;
      overflow: hidden;
    }
    .aura-tab-container,
    .aura-tab-content,
    .aura-tab-container div,
    [data-aura-tab-title],
    .content-wrapper,
    p,
    li {
      box-sizing: border-box;
      max-width: 100% !important;
      overflow-wrap: anywhere;
    }
    table.confluenceTable,
    table.aui,
    .table-wrap > table,
    .table-wrapper > table {
      table-layout: fixed !important;
      width: 100% !important;
      max-width: 100% !important;
    }
    table.confluenceTable col,
    table.aui col {
      width: auto !important;
    }
    table.confluenceTable th,
    table.confluenceTable td,
    table.aui th,
    table.aui td {
      overflow-wrap: anywhere !important;
      word-break: normal;
    }
    table.confluenceTable img,
    table.aui img {
      max-width: 100% !important;
      height: auto !important;
    }
    [data-macro-name="aura-tab"] {
      border-top: 2px solid #6554c0;
      display: block !important;
      margin-top: 1.2em;
      padding-top: 0.6em;
    }
    [data-macro-name="aura-tab"][hidden],
    [data-macro-name="aura-tab"][aria-hidden="true"] {
      display: block !important;
    }
    [data-macro-name="aura-tab"]::before {
      color: #172b4d;
      content: attr(data-aura-tab-title);
      display: block;
      font-size: 14pt;
      font-weight: 700;
      margin: 0 0 0.7em;
    }
    .aura-tab-nav-wrapper {
      display: none !important;
    }
    """


def _escape_html(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _ensure_homebrew_library_path() -> None:
    if sys.platform != "darwin":
        return
    homebrew_lib = "/opt/homebrew/lib"
    if not Path(homebrew_lib).exists():
        return
    current = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
    paths = [path for path in current.split(":") if path]
    if homebrew_lib not in paths:
        os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = ":".join([homebrew_lib, *paths])
