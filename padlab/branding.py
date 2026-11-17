"""The owner's channels. Shown in the app sidebar, the report footer and the README.

PadMaster never loads these pages itself. A click opens them in the normal web browser.
"""

CHANNELS = [
    ("@iamyourgamingnerd", "https://www.youtube.com/@iamyourgamingnerd"),
    ("@pressstartbynerd", "https://www.youtube.com/@pressstartbynerd"),
]


def is_channel_url(url: str) -> bool:
    return any(url == u for _, u in CHANNELS)


# "Report a bug" opens the user's email app with a draft to this address (owner decision,
# 2026-11-17). Empty: the button opens a GitHub issue draft instead.
BUG_EMAIL = ""
REPO = "nerdplayerone/PadMaster"
RELEASES_URL = f"https://github.com/{REPO}/releases"
ISSUES_URL = f"https://github.com/{REPO}/issues/new"
LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"
