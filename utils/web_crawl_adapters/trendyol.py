from urllib.parse import urljoin, urlparse

from .base import CrawlAccessPlan, SiteCrawlAdapter, _normalized_path

class TrendyolDocumentationAdapter(SiteCrawlAdapter):
    """Trendyol'un ReadMe tabanlı sol menüsündeki aktif doküman grubunu indirir."""

    name = "trendyol_readme"

    def matches(self, url):
        return urlparse(url).hostname == "developers.trendyol.com"

    def discover(self, url, html, include_children):
        if not include_children:
            return None
        urls = self._active_sidebar_group_urls(html, url)
        if len(urls) <= 1:
            return None
        return CrawlAccessPlan(name=self.name, urls=urls, use_native_markdown=True)

    @staticmethod
    def _active_sidebar_group_urls(html, current_url):
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        soup = BeautifulSoup(html or "", "html.parser")
        current_path = _normalized_path(current_url)
        active_link = next(
            (
                anchor for anchor in soup.find_all("a", href=True)
                if _normalized_path(urljoin(current_url, anchor["href"])) == current_path
                and "active" in (anchor.get("class") or [])
            ),
            None,
        )
        if active_link is None:
            return []

        group = active_link.find_parent("ul", class_=lambda value: value and "subpages" in value)
        if group is None:
            return []

        urls = []
        seen = set()
        current_host = urlparse(current_url).netloc.lower()
        for anchor in group.find_all("a", href=True):
            candidate = urljoin(current_url, anchor["href"]).split("#", 1)[0]
            parsed = urlparse(candidate)
            if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != current_host:
                continue
            key = candidate.rstrip("/")
            if key not in seen:
                seen.add(key)
                urls.append(candidate)
        return urls
