"""
Scrapy downloader/spider middlewares.

Classes
-------
ScrapebucketSpiderMiddleware     — thin pass-through spider middleware (boilerplate)
ScrapebucketDownloaderMiddleware — thin pass-through downloader middleware (boilerplate)
JobStatLogsMiddleware            — persists crawl stats to ``SpiderLog`` on spider close

Django ORM is bootstrapped via ``ensure_django()`` (idempotent; a no-op when
``settings.py`` has already called it).
"""

from __future__ import annotations

import logging

import pytz
from django.db import close_old_connections
from scrapy import signals

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


class RateLimitRetryMiddleware:
    """
    Slow Scrapy retries after HTTP 429 before ``RetryMiddleware`` requeues.

    ``RATE_LIMIT_RETRY_DELAY`` (seconds) is written to ``request.meta['download_delay']``
    so Cloudflare/Shopify rate limits are not hammered with immediate retries.
    """

    def __init__(self, delay_seconds: int):
        self.delay_seconds = delay_seconds

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler.settings.getint('RATE_LIMIT_RETRY_DELAY', 60))

    def process_response(self, request, response, spider):
        if response.status == 429:
            request.meta['download_delay'] = max(
                float(request.meta.get('download_delay', 0)),
                float(self.delay_seconds),
            )
        return response


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
