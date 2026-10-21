"""Official download sources for files in the project's public assets repo."""

from urllib.parse import urlsplit


PUBLIC_ASSET_HEADERS = {
    "Accept": "application/vnd.github.raw+json",
    "User-Agent": "AITeachMe/PublicAssets",
}
_RAW_ASSETS_PREFIX = "https://raw.githubusercontent.com/aiteachme/assets/main/"


def public_asset_urls(url: str) -> tuple[str, ...]:
    """Try raw GitHub first, then the same file through GitHub's Contents API."""

    if not url.startswith(_RAW_ASSETS_PREFIX):
        return (url,)
    path = urlsplit(url).path.removeprefix("/aiteachme/assets/main/")
    return (url, f"https://api.github.com/repos/aiteachme/assets/contents/{path}?ref=main")
