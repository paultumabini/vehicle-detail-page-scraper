"""
Scrapy downloader/spider middlewares and Selenium/Chrome driver integration.

Classes
-------
ScrapebucketSpiderMiddleware     — thin pass-through spider middleware (boilerplate)
ScrapebucketDownloaderMiddleware — thin pass-through downloader middleware (boilerplate)
SeleniumStealthMiddleware        — scrapy-selenium with selenium-stealth applied
UndetectedChromeDriver           — scrapy-selenium wrapper using undetected-chromedriver
JobStatLogsMiddleware            — persists crawl stats to ``SpiderLog`` on spider close

Django ORM is bootstrapped via ``ensure_django()`` (idempotent; a no-op when
``settings.py`` has already called it).
"""

from __future__ import annotations

import logging
from importlib import import_module

import pytz
import undetected_chromedriver as uc
from django.db import close_old_connections
from scrapy import signals
from scrapy_selenium.middlewares import SeleniumMiddleware
from selenium_stealth import stealth

from scrapebucket.django_setup import ensure_django

# Safety net: no-op when settings.py has already bootstrapped Django; ensures
# the ORM is available if this module is ever imported in isolation.
ensure_django()

logger = logging.getLogger(__name__)

from project.models import SpiderLog, TargetSite  # noqa: E402 — must follow ensure_django()


# ---------------------------------------------------------------------------
# Boilerplate middlewares (no custom logic; extend these as needed)
# ---------------------------------------------------------------------------

class ScrapebucketSpiderMiddleware:
    """
    Default spider middleware — currently a transparent pass-through.

    All ``process_spider_*`` methods delegate straight to Scrapy's defaults.
    Add custom item/request mutation or error handling here.
    """

    @classmethod
    def from_crawler(cls, crawler):
        o = cls()
        crawler.signals.connect(o.spider_opened, signal=signals.spider_opened)
        return o

    def process_spider_input(self, response, spider):
        return None

    def process_spider_output(self, response, result, spider):
        for i in result:
            yield i

    def process_spider_exception(self, response, exception, spider):
        pass

    def process_start_requests(self, start_requests, spider):
        for r in start_requests:
            yield r

    def spider_opened(self, spider):
        spider.logger.info('Spider opened: %s' % spider.name)


class ScrapebucketDownloaderMiddleware:
    """
    Default downloader middleware — currently a transparent pass-through.

    All ``process_*`` methods delegate straight to Scrapy's defaults.
    Add request signing, proxy rotation, or retry logic here.
    """

    @classmethod
    def from_crawler(cls, crawler):
        o = cls()
        crawler.signals.connect(o.spider_opened, signal=signals.spider_opened)
        return o

    def process_request(self, request, spider):
        return None

    def process_response(self, request, response, spider):
        return response

    def process_exception(self, request, exception, spider):
        pass

    def spider_opened(self, spider):
        spider.logger.info('Spider opened: %s' % spider.name)


# ---------------------------------------------------------------------------
# Chrome / Selenium driver middlewares
# ---------------------------------------------------------------------------

class SeleniumStealthMiddleware(SeleniumMiddleware):
    """
    scrapy-selenium downloader middleware with ``selenium-stealth`` applied.

    Builds the WebDriver via dynamic import (matching scrapy-selenium's own
    pattern) so the driver name stays configurable via ``SELENIUM_DRIVER_NAME``.
    Stealth patches navigator properties that headless Chrome normally exposes to
    bot-detection scripts.
    """

    def __init__(
        self,
        driver_name,
        driver_executable_path,
        driver_arguments,
        browser_executable_path,
    ):
        webdriver_base_path = f'selenium.webdriver.{driver_name}'

        # Dynamically load the WebDriver and Options classes for the configured browser.
        driver_klass = getattr(
            import_module(f'{webdriver_base_path}.webdriver'), 'WebDriver'
        )
        driver_options_klass = getattr(
            import_module(f'{webdriver_base_path}.options'), 'Options'
        )

        driver_options = driver_options_klass()

        if browser_executable_path:
            driver_options.binary_location = browser_executable_path
        for argument in driver_arguments:
            driver_options.add_argument(argument)

        # Anti-detection flags — must be set before the driver process starts.
        driver_options.add_argument('--headless')
        driver_options.add_argument('--disable-blink-features=AutomationControlled')
        driver_options.add_argument('--disable-dev-shm-usage')
        driver_options.add_argument('--no-sandbox')
        driver_options.add_argument('--disable-gpu')
        driver_options.add_argument('--incognito')

        self.driver = driver_klass(
            executable_path=driver_executable_path,
            **{f'{driver_name}_options': driver_options},
        )

        # Patch JS navigator properties so the browser appears as a normal user agent.
        stealth(
            self.driver,
            languages=['en-US', 'en'],
            vendor='Google Inc.',
            platform='Win32',
            webgl_vendor='Intel Inc.',
            renderer='Intel Iris OpenGL Engine',
            fix_hairline=True,
        )


class UndetectedChromeDriver(SeleniumMiddleware):
    """
    scrapy-selenium wrapper using ``undetected-chromedriver``.

    ``undetected-chromedriver`` patches the Chrome binary at runtime to remove
    automation fingerprints; no manual stealth flags are required.

    Note: the constructor signature matches scrapy-selenium's ``from_crawler``
    factory but only ``options`` is used — the other arguments are intentionally
    ignored because ``uc.Chrome`` manages its own executable path.
    """

    def __init__(
        self,
        driver_name,           # unused — uc always uses Chrome
        driver_executable_path,  # unused — uc locates its own patched binary
        driver_arguments,      # unused — add via options if needed
        browser_executable_path,  # unused — uc manages the browser path
    ):
        options = uc.ChromeOptions()
        options.add_argument('--headless')
        self.driver = uc.Chrome(options=options)


# ---------------------------------------------------------------------------
# Post-crawl stats (spider_closed signal — see pipelines for FTP export)
# ---------------------------------------------------------------------------

class JobStatLogsMiddleware:
    """
    Persist Scrapy crawl statistics to ``SpiderLog`` when a spider closes.

    Reads the final stats snapshot from ``spider.crawler.stats``, looks up the
    ``TargetSite`` by ``spider.domain_name``, and writes one ``SpiderLog`` row.
    Failures are caught and logged so a stats-save error never aborts a crawl.
    """

    def __init__(self, crawler):
        self.stats = crawler.stats

    @classmethod
    def from_crawler(cls, crawler):
        o = cls(crawler)
        crawler.signals.connect(o.spider_closed, signal=signals.spider_closed)
        return o

    def spider_closed(self, spider, reason):
        try:
            stats = spider.crawler.stats.get_stats()
            bot_name = spider.crawler.settings.get('BOT_NAME')
            domain_name = spider.domain_name.split('.')[0]

            target = TargetSite.objects.filter(site_id__exact=domain_name).first()
            if target is None:
                logger.warning(
                    'JobStatLogsMiddleware: no TargetSite for site_id=%r; skip SpiderLog',
                    domain_name,
                )
                return

            try:
                SpiderLog(
                    target_site_id=target.pk,
                    spider_name=spider.name,
                    allowed_domain=domain_name,
                    items_scraped=stats.get('item_scraped_count'),
                    items_dropped=stats.get('item_dropped_count'),
                    finish_reason=stats.get('finish_reason'),
                    request_count=stats.get('downloader/request_count'),
                    status_count_200=stats.get('downloader/response_status_count/200'),
                    start_timestamp=stats.get('start_time'),
                    end_timestamp=stats.get('finish_time'),
                    elapsed_time=self.dt_interval(stats.get('elapsed_time_seconds')),
                    elapsed_time_seconds=stats.get('elapsed_time_seconds'),
                ).save()
                logger.info(
                    'Crawl finished: bot=%s spider=%s target=%s',
                    bot_name,
                    spider.name,
                    domain_name,
                )
            except Exception as exc:
                logger.exception(
                    'JobStatLogsMiddleware: failed to save SpiderLog: %s', exc
                )
        finally:
            close_old_connections()

    def convert_dt(self, dt):
        """Convert a naive UTC datetime to a US/Eastern formatted string (unused; kept for reference)."""
        return (
            pytz.utc.localize(dt)
            .astimezone(pytz.timezone('US/Eastern'))
            .strftime('%Y-%m-%d %I:%M:%S')
        )

    def dt_interval(self, s):
        """Format elapsed seconds as ``HH:MM:SS``; returns ``'00:00:00'`` for ``None``."""
        if s is None:
            return '00:00:00'
        hours, remainder = divmod(s, 3600)
        minutes, seconds = divmod(remainder, 60)
        return '{:02}:{:02}:{:02}'.format(int(hours), int(minutes), int(seconds))
