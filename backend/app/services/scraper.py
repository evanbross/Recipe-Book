"""
Scraper service: fetches a web page and extracts readable text content
to pass to the Claude vision service for recipe extraction.
"""
import httpx
from bs4 import BeautifulSoup


_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

_REMOVE_TAGS = {"script", "style", "nav", "footer", "header", "aside", "form", "iframe"}


def fetch_page_text(url: str, timeout: int = 15) -> str:
    """
    Fetch a web page and return its cleaned text content.
    Strips navigation, scripts, and boilerplate; focuses on article/main body.
    """
    with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=timeout) as client:
        response = client.get(url)
        response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    # Remove noise elements
    for tag in soup.find_all(_REMOVE_TAGS):
        tag.decompose()

    # Try to isolate the main content area
    main = (
        soup.find("main")
        or soup.find("article")
        or soup.find(class_=lambda c: c and "recipe" in c.lower())
        or soup.find("body")
    )

    text = main.get_text(separator="\n", strip=True) if main else soup.get_text(separator="\n", strip=True)

    # Collapse excessive blank lines
    lines = [line for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def fetch_page_image(url: str, timeout: int = 15) -> tuple[bytes, str]:
    """
    Download an image URL directly. Returns (bytes, media_type).
    Used when the user provides a direct image URL rather than a page URL.
    """
    with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=timeout) as client:
        response = client.get(url)
        response.raise_for_status()

    content_type = response.headers.get("content-type", "image/jpeg").split(";")[0].strip()
    return response.content, content_type
