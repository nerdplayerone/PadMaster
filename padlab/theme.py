"""Shared look for the app window and the report.

All scroll bars use SCROLLBAR_CSS. Do not style scroll bars anywhere else.
"""

SCROLLBAR_CSS = (
    "::-webkit-scrollbar{width:6px;height:6px}"
    "::-webkit-scrollbar-track,::-webkit-scrollbar-corner{background:transparent}"
    "::-webkit-scrollbar-thumb{background:#2a2a2f;border-radius:3px}"
    "::-webkit-scrollbar-thumb:hover{background:#4a4a52}"
    "::-webkit-scrollbar-button{display:none;width:0;height:0}"
    "html{scrollbar-color:#2a2a2f transparent;scrollbar-width:thin}"
)

# Marker in app.html that gui.py replaces with SCROLLBAR_CSS.
SCROLLBAR_MARKER = "/*PADLAB_SCROLLBAR_CSS*/"


def with_scrollbars(html: str) -> str:
    """Add the shared scroll bar style to a page (also to reports made by older versions)."""
    tag = f"<style>{SCROLLBAR_CSS}</style>"
    if "</head>" in html:
        return html.replace("</head>", tag + "</head>", 1)
    return tag + html
