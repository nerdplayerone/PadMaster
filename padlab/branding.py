"""The owner's channels. Shown in the app sidebar, the report footer and the README.

PadMaster never loads these pages itself. A click opens them in the normal web browser.
"""

CHANNELS = [
    ("@iamyourgamingnerd", "https://www.youtube.com/@iamyourgamingnerd"),
    ("@pressstartbynerd", "https://www.youtube.com/@pressstartbynerd"),
]


def is_channel_url(url: str) -> bool:
    return any(url == u for _, u in CHANNELS)
