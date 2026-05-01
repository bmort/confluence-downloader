from __future__ import annotations

from pathlib import Path
import os
import sys
from typing import Callable

from .models import Page

UrlFetcher = Callable[[str], dict]


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
    document = _wrap_confluence_html(page, html)
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
    a {{ color: #0052cc; text-decoration: none; }}
    table {{
      border-collapse: collapse;
      margin: 0.8em 0 1em;
      width: 100%;
    }}
    th, td {{
      border: 1px solid #c1c7d0;
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
