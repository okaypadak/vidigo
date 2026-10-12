"""Genel amaçlı web sayfası keşif ve Markdown dönüştürme akışı.

Siteye özel adapter'lar yerine iki küçük motor kullanılır: ilki aynı
doküman alanındaki sayfaları keşfeder, ikincisi her sayfanın okunabilir
ana içeriğini Markdown'a dönüştürür.
"""

import asyncio
import ipaddress
import os
import re
import socket
from collections import deque
from datetime import datetime
from urllib.parse import urljoin, urlparse, urlunparse


class WebMarkdownUnavailableError(RuntimeError):
    pass


def validate_web_url(url):
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Gecerli bir http veya https URL girin.")
    hostname = parsed.hostname.lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ValueError("Yerel adresler taranamaz.")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(hostname, None)}
    except socket.gaierror as exc:
        raise ValueError("Alan adi cozumlenemedi.") from exc
    for address in addresses:
        if not ipaddress.ip_address(address).is_global:
            raise ValueError("Genel internete acik olmayan adresler taranamaz.")
    return parsed.geturl()


def _load_crawler():
    try:
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
        from crawl4ai.content_filter_strategy import PruningContentFilter
        from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator
    except ImportError as exc:
        raise WebMarkdownUnavailableError(
            "Crawl4AI kurulu degil. requirements.txt yuklendikten sonra tekrar deneyin."
        ) from exc
    return AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig, PruningContentFilter, DefaultMarkdownGenerator


def _report_progress(progress_callback, event, **fields):
    if progress_callback is None:
        return
    try:
        progress_callback(event, **fields)
    except Exception:
        pass


class PageDiscoveryEngine:
    """Bir sitenin render edilmiş bağlantılarından sınırlı bir sayfa ağacı kurar."""

    max_pages = 100
    _ignored_suffixes = re.compile(
        r"\.(?:7z|bmp|css|csv|docx?|eot|gif|ico|jpe?g|js|json|map|mp[34]|otf|pdf|png|svg|tar|ttf|webm|webp|woff2?|xls[xm]?)$",
        re.IGNORECASE,
    )

    def __init__(self, root_url, crawler, raw_config, progress_callback=None):
        self.root_url = root_url
        self.root = urlparse(root_url)
        self.crawler = crawler
        self.raw_config = raw_config
        self.progress_callback = progress_callback

    async def discover(self):
        """Genişlik-öncelikli olarak dahili HTML sayfalarını keşfeder."""
        queue = deque([self.root_url])
        seen = set()
        urls = []
        while queue and len(urls) < self.max_pages:
            url = queue.popleft()
            canonical = self._canonical(url)
            if canonical in seen:
                continue
            seen.add(canonical)
            result = await self.crawler.arun(url=url, config=self.raw_config)
            if not getattr(result, "success", False):
                continue
            urls.append(url)
            for link in self._links(url, getattr(result, "html", "") or ""):
                if self._canonical(link) not in seen:
                    queue.append(link)
        return urls

    def _links(self, base_url, html):
        links = []
        seen = set()
        for href in re.findall(r"<a\b[^>]*?\bhref\s*=\s*(['\"])(.*?)\1", html, re.IGNORECASE | re.DOTALL):
            candidate = urljoin(base_url, href[1])
            parsed = urlparse(candidate)
            if (
                parsed.scheme not in {"http", "https"}
                or parsed.hostname != self.root.hostname
                or self._ignored_suffixes.search(parsed.path)
            ):
                continue
            canonical = self._canonical(candidate)
            if canonical not in seen:
                seen.add(canonical)
                links.append(canonical)
        return links

    @staticmethod
    def _canonical(url):
        parsed = urlparse(url)
        path = parsed.path or "/"
        if path != "/":
            path = path.rstrip("/")
        return urlunparse((parsed.scheme, parsed.netloc.lower(), path, "", parsed.query, ""))


class MarkdownConversionEngine:
    """Keşfedilmiş bir URL kümesinin ana içeriğini Markdown olarak üretir."""

    def __init__(self, crawler, page_config, progress_callback=None):
        self.crawler = crawler
        self.page_config = page_config
        self.progress_callback = progress_callback

    async def convert(self, urls):
        pages = []
        total_pages = len(urls)
        for index, url in enumerate(urls, start=1):
            _report_progress(self.progress_callback, "page_started", current_page=index, total_pages=total_pages, url=url)
            result = await self.crawler.arun(url=url, config=self.page_config)
            page = _markdown_from_result(result)
            _report_progress(
                self.progress_callback, "page_finished", current_page=index, total_pages=total_pages,
                url=url, saved=bool(page), skipped=not bool(page),
            )
            if page:
                pages.append(page)
        return pages


def _raw_page_config():
    _, _, CacheMode, CrawlerRunConfig, _, _ = _load_crawler()
    return CrawlerRunConfig(cache_mode=CacheMode.BYPASS, remove_overlay_elements=True, remove_consent_popups=True)


def _markdown_page_config(target_main=True):
    _, _, CacheMode, CrawlerRunConfig, PruningContentFilter, DefaultMarkdownGenerator = _load_crawler()
    return CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        css_selector="main, article, [role='main']" if target_main else None,
        excluded_tags=["nav", "header", "footer", "aside", "form"],
        remove_overlay_elements=True,
        remove_consent_popups=True,
        exclude_all_images=True,
        markdown_generator=DefaultMarkdownGenerator(
            content_filter=PruningContentFilter(threshold=0.4, threshold_type="fixed")
        ),
    )


def _markdown_from_result(result):
    if not getattr(result, "success", False):
        return ""
    markdown_result = getattr(result, "markdown", "")
    return simplify_markdown(str(
        getattr(markdown_result, "fit_markdown", None)
        or getattr(markdown_result, "raw_markdown", markdown_result)
        or ""
    ).strip())


async def _crawl(url, include_children=False, progress_callback=None):
    AsyncWebCrawler, BrowserConfig, *_ = _load_crawler()
    browser_config = BrowserConfig(headless=True)
    async with AsyncWebCrawler(config=browser_config) as crawler:
        if include_children:
            _report_progress(progress_callback, "crawl_started", url=url, include_children=True, total_pages="bilinmiyor")
            discovery = PageDiscoveryEngine(url, crawler, _raw_page_config(), progress_callback)
            urls = await discovery.discover()
            if not urls:
                raise RuntimeError("Taranabilir bir sayfa bulunamadi.")
            _report_progress(progress_callback, "crawl_plan_ready", total_pages=len(urls), source="generic_page_discovery")
        else:
            _report_progress(progress_callback, "crawl_started", url=url, include_children=False, total_pages=1)
            urls = [url]
        pages = await MarkdownConversionEngine(crawler, _markdown_page_config(), progress_callback).convert(urls)
        if not pages:
            pages = await MarkdownConversionEngine(crawler, _markdown_page_config(target_main=False), progress_callback).convert(urls)
    if not pages:
        raise RuntimeError("Sayfa Markdown icerigi uretmedi.")
    return "\n\n---\n\n".join(pages), len(pages)


def simplify_markdown(markdown):
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", markdown or "")
    text = re.sub(r"\[([^\]]+)\]\((?:[^()]|\([^)]*\))*\)", r"\1", text)
    ignored_lines = {"copy for llm", "view as markdown", "was this helpful?", "did you find this page helpful?"}
    ignored_sections = {"next steps", "see also", "related links", "related resources", "ilgili baglantilar"}
    lines, skipping_section_level = [], None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading:
            level, title = len(heading.group(1)), heading.group(2).strip().lower()
            if title in ignored_sections:
                skipping_section_level = level
                continue
            if skipping_section_level is not None and level <= skipping_section_level:
                skipping_section_level = None
        if skipping_section_level is None and line.strip().lower() not in ignored_lines:
            lines.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def crawl_url_to_markdown(url, progress_callback=None):
    markdown, _ = _run_async(_crawl(validate_web_url(url), progress_callback=progress_callback))
    return markdown


def crawl_url_tree_to_markdown(url, progress_callback=None):
    return _run_async(_crawl(validate_web_url(url), include_children=True, progress_callback=progress_callback))


def _run_async(coroutine):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    raise RuntimeError("Crawl4AI aktif bir async olay dongusunda calistirilamaz.")


def _safe_stem(url):
    parsed = urlparse(url)
    stem = f"{parsed.hostname}{parsed.path}".strip("/") or "web-page"
    for char in '\\/:*?\"<>|':
        stem = stem.replace(char, "_")
    return stem[:120].strip(". ") or "web-page"


def save_web_markdown(url, markdown, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    stem = _safe_stem(url)
    path = os.path.join(output_dir, f"{stem}.md")
    if os.path.exists(path):
        path = os.path.join(output_dir, f"{stem}-{datetime.now():%Y%m%d-%H%M%S}.md")
    with open(path, "w", encoding="utf-8") as output:
        output.write((markdown or "").strip())
        output.write("\n")
    return path
