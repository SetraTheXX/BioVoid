"""Small compatibility page for the deprecated ``/portal`` route.

The canonical interface is the React application served at ``/``.  Keeping a
minimal local page here preserves the old diagnostic URL without loading
third-party scripts or presenting unsupported scientific wording.
"""

from __future__ import annotations

from pathlib import Path

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_PORTAL_CACHE: str | None = None
_PORTAL_MTIME: float = 0.0

_FALLBACK_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src 'self'; script-src 'none'; connect-src 'self'">
    <title>BioVoid local interface</title>
  </head>
  <body>
    <main>
      <h1>BioVoid local interface</h1>
      <p>The compatibility page is available, but its template is missing.</p>
      <p><a href="/">Open the canonical React interface</a></p>
    </main>
  </body>
</html>
"""


def render_portal_html() -> str:
    """Load the compatibility template and fail closed if it is unavailable."""
    global _PORTAL_CACHE, _PORTAL_MTIME

    template_path = _TEMPLATE_DIR / "portal.html"
    if not template_path.is_file():
        return _FALLBACK_HTML

    mtime = template_path.stat().st_mtime
    if _PORTAL_CACHE is None or mtime != _PORTAL_MTIME:
        _PORTAL_CACHE = template_path.read_text(encoding="utf-8")
        _PORTAL_MTIME = mtime
    return _PORTAL_CACHE
