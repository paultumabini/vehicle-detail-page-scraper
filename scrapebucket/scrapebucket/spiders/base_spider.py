"""Shared spider bases for crawl-time kwargs injected by ``runner.crawl(..., url=...)``."""

from __future__ import annotations

from typing import Any, ClassVar

import scrapy
from scrapy import Request
from scrapy.spiders import CrawlSpider
from scrapy_playwright.page import PageMethod

PLAYWRIGHT_DOWNLOAD_HANDLERS = {
    'http': 'scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler',
    'https': 'scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler',
}

PLAYWRIGHT_SPIDER_SETTINGS: dict[str, Any] = {
    'DOWNLOAD_HANDLERS': PLAYWRIGHT_DOWNLOAD_HANDLERS,
    'PLAYWRIGHT_LAUNCH_OPTIONS': {
        'headless': True,
    },
}


class ScrapebucketSpider(scrapy.Spider):
    url: str


class ScrapebucketCrawlSpider(CrawlSpider):
    url: str


class ScrapebucketPlaywrightSpider(ScrapebucketSpider):
    """Scrapy spider with ``scrapy-playwright`` download handlers and asyncio reactor."""

    custom_settings: ClassVar[dict[str, Any]] = PLAYWRIGHT_SPIDER_SETTINGS

    @classmethod
    def update_settings(cls, settings):
        super().update_settings(settings)
        settings.set(
            'TWISTED_REACTOR',
            'twisted.internet.asyncioreactor.AsyncioSelectorReactor',
            priority='spider',
        )

    def playwright_request(
        self,
        url: str,
        *,
        callback=None,
        page_methods: list[PageMethod] | None = None,
        meta: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Request:
        req_meta = dict[str, Any](meta or {})
        req_meta['playwright'] = True
        if page_methods:
            req_meta['playwright_page_methods'] = page_methods
        return Request(url, callback=callback, meta=req_meta, **kwargs)
