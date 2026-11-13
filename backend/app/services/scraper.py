"""
Scraper service: fetches a web page and extracts readable text content
to pass to the Claude vision service for recipe extraction.
"""
import json as _json
import logging
import httpx
from bs4 import BeautifulSoup, Tag
from urllib.parse import urljoin, urlparse

from app.services.url_guard import check_public_destination

logger = logging.getLogger(__name__)


_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

# ai: claude-opus-5-5 | 2026-11-13
def _reject_non_public(request: httpx.Request) -> None:
    """httpx request hook: runs before the first request and before every redirect hop."""
    check_public_destination(str(request.url))


# ai: claude-opus-5-5 | 2026-11-13
def _guarded_client(timeout: int) -> httpx.Client:
    """The only way this module makes HTTP requests: SSRF-checked on every hop.

    Raises url_guard.UnsafeURLError (a ValueError) when a URL or redirect points
    at a non-public address.
    """
    return httpx.Client(
        headers=_HEADERS,
        follow_redirects=True,
        timeout=timeout,
        event_hooks={"request": [_reject_non_public]},
    )


_REMOVE_TAGS = {"script", "style", "nav", "footer", "header", "aside", "form", "iframe"}

# Known recipe card container CSS classes (WordPress Recipe Maker, Tasty Recipes,
# Mediavine Create, generic "recipe-card"). Checked before <main>/<article> so a
# long blog-post intro doesn't push the actual recipe past the character limit.
_RECIPE_CARD_CLASSES: tuple[str, ...] = (
    "wprm-recipe-container",
    "wprm-recipe",
    "tasty-recipes",
    "tasty-recipes-entry",
    "mv-create-card",
    "recipe-card",
)


_RECIPE_TYPES = {"Recipe", "https://schema.org/Recipe", "http://schema.org/Recipe"}


def _is_recipe_node(node: object) -> bool:
    if not isinstance(node, dict):
        return False
    t = node.get("@type", "")
    if isinstance(t, list):
        return bool(_RECIPE_TYPES.intersection(t))
    return t in _RECIPE_TYPES


def extract_jsonld_recipe(soup: BeautifulSoup) -> dict | None:
    """
    Find and return the first Recipe JSON-LD block on the page, or None.
    Handles direct {"@type": "Recipe"}, {"@graph": [...]}, and bare lists.
    """
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = _json.loads(script.string or "")
        except (_json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict):
            if _is_recipe_node(data):
                return data
            for item in data.get("@graph", []):
                if _is_recipe_node(item):
                    return item
        elif isinstance(data, list):
            for item in data:
                if _is_recipe_node(item):
                    return item
    return None


def _find_recipe_element(soup: BeautifulSoup) -> Tag | None:
    """Return the most specific recipe card element available, or None."""
    # schema.org microdata attribute — works across plugin boundaries
    elem = soup.find(attrs={"itemtype": "https://schema.org/Recipe"})
    if elem:
        return elem
    for cls in _RECIPE_CARD_CLASSES:
        elem = soup.find(class_=lambda c: c and cls in c.split())
        if elem:
            return elem
    return None


# Common content container IDs used across many WordPress / CMS themes.
_CONTENT_IDS: tuple[str, ...] = (
    "content",
    "main-content",
    "primary-content",
    "page-content",
    "main",
)


def _find_main_content(soup: BeautifulSoup) -> Tag | None:
    """
    Return the element that most likely contains the page's primary content.

    Tries recipe-specific containers first, then semantic <main>, then common
    content IDs. If the page has multiple <article> elements (e.g. related-
    recipe widgets), prefers the one that contains the <h1> title or the
    largest article by text volume.
    """
    # 1. Recipe plugin containers
    elem = _find_recipe_element(soup)
    if elem:
        return elem

    # 2. Semantic main
    elem = soup.find("main")
    if elem:
        return elem

    # 3. Common content container IDs
    for cid in _CONTENT_IDS:
        elem = soup.find(id=cid)
        if elem:
            return elem

    # 4. <article> elements — handle pages with multiple articles
    articles = soup.find_all("article")
    if len(articles) == 1:
        return articles[0]
    if len(articles) > 1:
        h1 = soup.find("h1")
        if h1:
            # Prefer the article that actually contains the page heading
            for article in articles:
                if h1 in article.descendants:
                    return article
            for parent in h1.parents:
                if parent.name == "article":
                    return parent
        # Fallback: the article with the most text is probably the main content
        return max(articles, key=lambda a: len(a.get_text(separator="\n", strip=True)))

    return None


def extract_jsonld_image_url(jsonld: dict) -> str | None:
    """Extract the best image URL from a JSON-LD Recipe dict.

    Handles string, list, and ImageObject dict forms for ``image`` and
    ``thumbnailUrl`` properties.
    """
    if not jsonld:
        return None
    for key in ("image", "thumbnailUrl"):
        value = jsonld.get(key)
        if not value:
            continue
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    return item
                if isinstance(item, dict):
                    url = item.get("url") or item.get("contentUrl")
                    if isinstance(url, str):
                        return url
            continue
        if isinstance(value, dict):
            url = value.get("url") or value.get("contentUrl")
            if isinstance(url, str):
                return url
    return None


def fetch_page(url: str, timeout: int = 15) -> tuple[str, str | None, str, dict | None]:
    """
    Fetch a web page and return (cleaned_text, og_image_url, final_url, jsonld_recipe).

    jsonld_recipe is a raw JSON-LD Recipe dict when the page embeds one, otherwise None.
    Callers should prefer jsonld_recipe when present — it is the most reliable source of
    recipe data and is immune to sidebar/widget contamination in the page text.

    final_url is the URL after following all redirects — differs from url when
    the original link is a tracking redirect (e.g. ActiveCampaign lt.php).
    The OG image URL is extracted from og:image / twitter:image meta tags and
    resolved to an absolute URL.
    """
    logger.info("[scraper] Fetching page: %s", url)
    with _guarded_client(timeout) as client:
        response = client.get(url)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            logger.warning("[scraper] HTTP %s for %s", response.status_code, url)
            raise
    final_url = str(response.url)

    soup = BeautifulSoup(response.text, "html.parser")

    # Extract OG image and JSON-LD before decomposing any elements.
    og_tag = soup.find("meta", attrs={"property": "og:image"}) or \
             soup.find("meta", attrs={"name": "twitter:image"})
    og_image_url: str | None = og_tag.get("content") if og_tag else None
    if og_image_url:
        og_image_url = urljoin(final_url, og_image_url)
    jsonld_recipe = extract_jsonld_recipe(soup)

    # Remove noise elements
    for tag in soup.find_all(_REMOVE_TAGS):
        tag.decompose()

    # Prefer a specific recipe card container so that long blog-post intros
    # don't crowd out the actual recipe content before the character limit.
    main = (
        _find_main_content(soup)
        or soup.find(class_=lambda c: c and "recipe" in c.lower())
        or soup.find("body")
    )

    text = main.get_text(separator="\n", strip=True) if main else soup.get_text(separator="\n", strip=True)

    lines = [line for line in text.splitlines() if line.strip()]
    return "\n".join(lines), og_image_url, final_url, jsonld_recipe


def fetch_page_text(url: str, timeout: int = 15) -> str:
    """Fetch a web page and return its cleaned text. Use fetch_page() to also get the OG image."""
    text, _, _, _ = fetch_page(url, timeout)
    return text


def fetch_page_html(url: str, timeout: int = 15) -> tuple[str, str]:
    """Fetch a web page and return (raw_html, final_url). Used for link extraction."""
    logger.info("[scraper] Fetching HTML: %s", url)
    with _guarded_client(timeout) as client:
        response = client.get(url)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            logger.warning("[scraper] HTTP %s for %s", response.status_code, url)
            raise
    return response.text, str(response.url)


def extract_links(html: str, base_url: str) -> list[dict[str, str | None]]:
    """
    Extract all anchor links from an HTML page, resolved to absolute URLs.

    Returns a list of {"url": str, "title": str | None, "same_origin": bool}
    dicts, deduplicated and sorted same-origin first.
    """
    soup = BeautifulSoup(html, "html.parser")
    base_parsed = urlparse(base_url)
    base_origin = (base_parsed.scheme, base_parsed.netloc)

    seen: set[str] = set()
    same: list[dict] = []
    other: list[dict] = []

    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        abs_url = urljoin(base_url, href)
        parsed = urlparse(abs_url)
        if parsed.scheme not in ("http", "https"):
            continue
        clean = parsed._replace(fragment="").geturl()
        if clean == base_url or clean in seen:
            continue
        seen.add(clean)

        raw_title = a.get_text(" ", strip=True) or a.get("title") or None
        if raw_title:
            title = raw_title[:200]
        else:
            slug = parsed.path.rstrip("/").rsplit("/", 1)[-1]
            title = slug.replace("-", " ").replace("_", " ").title() if slug else None
        is_same = (parsed.scheme, parsed.netloc) == base_origin
        entry = {"url": clean, "title": title, "same_origin": is_same}
        (same if is_same else other).append(entry)

    return same + other


def fetch_page_image(url: str, timeout: int = 15) -> tuple[bytes, str]:
    """
    Download an image URL directly. Returns (bytes, media_type).
    Used when the user provides a direct image URL rather than a page URL.
    """
    logger.info("[scraper] Fetching image: %s", url)
    with _guarded_client(timeout) as client:
        response = client.get(url)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            logger.warning("[scraper] HTTP %s for image %s", response.status_code, url)
            raise

    content_type = response.headers.get("content-type", "image/jpeg").split(";")[0].strip()
    logger.info("[scraper] Image downloaded: %s (%s, %d bytes)", url, content_type, len(response.content))
    return response.content, content_type
