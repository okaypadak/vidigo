import asyncio
import ipaddress
import os
import re
import socket
from datetime import datetime
from urllib.parse import urlparse

from utils.web_crawl_adapters import fetch_access_plan, resolve_site_adapter


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
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ValueError("Genel internete acik olmayan adresler taranamaz.")
    return parsed.geturl()


def _load_crawler():
    try:
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
        from crawl4ai.content_filter_strategy import PruningContentFilter
        from crawl4ai.deep_crawling import BFSDeepCrawlStrategy, DomainFilter, FilterChain, URLPatternFilter
        from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator
    except ImportError as exc:
        raise WebMarkdownUnavailableError(
            "Crawl4AI kurulu degil. requirements.txt yuklendikten sonra tekrar deneyin."
        ) from exc
    return (
        AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig, PruningContentFilter,
        DefaultMarkdownGenerator, BFSDeepCrawlStrategy, DomainFilter, FilterChain, URLPatternFilter,
    )


def _crawler_run_config(url, include_children=False, target_main=True):
    (
        _, _, CacheMode, CrawlerRunConfig, PruningContentFilter, DefaultMarkdownGenerator,
        BFSDeepCrawlStrategy, DomainFilter, FilterChain, URLPatternFilter,
    ) = _load_crawler()
    deep_crawl_strategy = None
    if include_children:
        parsed = urlparse(url)
        base_path = parsed.path.rstrip("/") or "/"
        path_pattern = f"{base_path.rstrip('/')}/*" if base_path != "/" else "/*"
        deep_crawl_strategy = BFSDeepCrawlStrategy(
            max_depth=5,
            max_pages=100,
            filter_chain=FilterChain([
                DomainFilter(allowed_domains=[parsed.hostname]),
                URLPatternFilter(path_pattern),
                URLPatternFilter("*.md", reverse=True),
            ]),
        )
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
        deep_crawl_strategy=deep_crawl_strategy,
    )


def _navigation_discovery_config():
    _, _, CacheMode, CrawlerRunConfig, *_ = _load_crawler()
    # Sol menü bağlantıları ana içerik seçicisiyle kırpılmadan önce alınmalıdır.
    return CrawlerRunConfig(cache_mode=CacheMode.BYPASS)


def _report_progress(progress_callback, event, **fields):
    """İlerleme bildiriminin taramayı kesmesine izin vermez."""
    if progress_callback is None:
        return
    try:
        progress_callback(event, **fields)
    except Exception:
        pass


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
    adapter = resolve_site_adapter(url)
    if adapter and adapter.requires_interactive_collection:
        _report_progress(progress_callback, "crawl_started", url=url, include_children=include_children)
        pages = await adapter.collect_interactively(
            url, include_children, progress_callback=progress_callback
        )
        pages = [simplify_markdown(page) for page in pages if page]
        if not pages:
            raise RuntimeError(f"{adapter.name} dokuman icerigi alinamadi.")
        return "\n\n---\n\n".join(pages), len(pages)

    browser_config = BrowserConfig(headless=True)
    async with AsyncWebCrawler(config=browser_config) as crawler:
        first_result = await crawler.arun(
            url=url,
            config=_navigation_discovery_config() if include_children else _crawler_run_config(url),
        )
        access_plan = adapter.discover(url, getattr(first_result, "html", ""), include_children) if adapter else None
        if access_plan:
            _report_progress(
                progress_callback,
                "crawl_plan_ready",
                total_pages=len(access_plan.urls),
                source=access_plan.name,
            )
            native_pages = await fetch_access_plan(access_plan, progress_callback=progress_callback)
            if native_pages:
                result = native_pages
            else:
                result = []
                for index, page_url in enumerate(access_plan.urls, start=1):
                    _report_progress(
                        progress_callback,
                        "page_started",
                        current_page=index,
                        total_pages=len(access_plan.urls),
                        url=page_url,
                    )
                    result.append(await crawler.arun(url=page_url, config=_crawler_run_config(url)))
                    _report_progress(
                        progress_callback,
                        "page_finished",
                        current_page=index,
                        total_pages=len(access_plan.urls),
                        url=page_url,
                    )
        elif include_children:
            _report_progress(progress_callback, "crawl_started", url=url, include_children=True, total_pages="bilinmiyor")
            result = await crawler.arun(url=url, config=_crawler_run_config(url, include_children=True))
        else:
            _report_progress(progress_callback, "crawl_started", url=url, include_children=False, total_pages=1)
            result = first_result

    results = result if isinstance(result, list) else [result]
    pages = [item if isinstance(item, str) else _markdown_from_result(item) for item in results]
    pages = [page for page in pages if page]
    if not pages:
        # Bazı sade siteler semantic <main> kullanmaz; bu durumda içerik kaybetmemek için
        # aynı temizleme kurallarıyla body düzeyinde tekrar dene.
        async with AsyncWebCrawler(config=browser_config) as crawler:
            result = await crawler.arun(
                url=url,
                config=_crawler_run_config(url, include_children=include_children, target_main=False),
            )
        results = result if isinstance(result, list) else [result]
        pages = [_markdown_from_result(item) for item in results]
        pages = [page for page in pages if page]
    markdown = "\n\n---\n\n".join(pages)
    if not markdown:
        error = getattr(result, "error_message", None) if not isinstance(result, list) else None
        raise RuntimeError(error or "Sayfa Markdown icerigi uretmedi.")
    return markdown, len(pages)


def simplify_markdown(markdown):
    """Sayfa navigasyonu yerine okunabilir, linksiz Markdown saklar."""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", markdown or "")
    text = re.sub(r"\[([^\]]+)\]\((?:[^()]|\([^)]*\))*\)", r"\1", text)
    ignored_lines = {
        "copy for llm",
        "view as markdown",
        "was this helpful?",
        "did you find this page helpful?",
    }
    ignored_sections = {"next steps", "see also", "related links", "related resources", "ilgili baglantilar"}
    lines = []
    skipping_section_level = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading:
            level = len(heading.group(1))
            title = heading.group(2).strip().lower()
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
    return stem[:120].strip(". _") or "web-page"


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
