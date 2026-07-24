"""
Scrapy downloader/spider middlewares.

Classes
-------
ScrapebucketSpiderMiddleware     — thin pass-through spider middleware (boilerplate)
ScrapebucketDownloaderMiddleware — thin pass-through downloader middleware (boilerplate)
RateLimitRetryMiddleware         — delayed retries for HTTP 429 (honours Retry-After)
JobStatLogsMiddleware            — persists crawl stats to ``SpiderLog`` on spider close

Django ORM is bootstrapped via ``ensure_django()`` (idempotent; a no-op when
``settings.py`` has already called it).
"""

from __future__ import annotations

import logging

import pytz
from django.db import close_old_connections
from scrapy import signals
from scrapy.http import Request, Response
from scrapy.utils.defer import deferred_to_future
from twisted.internet import reactor, task

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
    Retry HTTP 429 after a real wall-clock delay (Twisted ``deferLater``).

    Scrapy's ``RetryMiddleware`` requeues immediately; ``download_delay`` in
    ``request.meta`` does not slow those retries.  This middleware handles 429
    exclusively and should run with 429 removed from ``RETRY_HTTP_CODES``.

    Start/inventory requests may set ``meta['rate_limit_start'] = True`` for a
    lower retry budget (fail fast when the egress IP is already blocked).
    """

    def __init__(self, crawler, default_delay: int, max_retries: int, start_max_retries: int):
        self.crawler = crawler
        self.default_delay = default_delay
        self.max_retries = max_retries
        self.start_max_retries = start_max_retries

    @classmethod
    def from_crawler(cls, crawler):
        settings = crawler.settings
        return cls(
            crawler,
            default_delay=settings.getint('RATE_LIMIT_RETRY_DELAY', 60),
            max_retries=settings.getint('RATE_LIMIT_MAX_RETRIES', 2),
            start_max_retries=settings.getint('RATE_LIMIT_START_MAX_RETRIES', 1),
        )

    def _retry_delay(self, response: Response) -> float:
        raw = (response.headers.get(b'Retry-After') or b'').decode('latin-1', 'replace').strip()
        if raw.isdigit():
            return max(float(raw), float(self.default_delay))
        return float(self.default_delay)

    def _max_for_request(self, request: Request) -> int:
        if request.meta.get('rate_limit_start'):
            return self.start_max_retries
        return self.max_retries

    async def process_response(self, request, response, spider):
        if response.status != 429:
            return response

        attempt = int(request.meta.get('rate_limit_retry_times', 0))
        max_retries = self._max_for_request(request)
        if attempt >= max_retries:
            logger.error(
                '%s: giving up on HTTP 429 for %s after %d attempt(s)',
                spider.name,
                request.url,
                attempt + 1,
            )
            return response

        delay = self._retry_delay(response)
        retry_request = request.copy()
        retry_request.meta['rate_limit_retry_times'] = attempt + 1
        retry_request.dont_filter = True

        logger.warning(
            '%s: HTTP 429 on %s; retry in %ds (attempt %d/%d)',
            spider.name,
            request.url,
            int(delay),
            attempt + 1,
            max_retries,
        )

        if self.crawler.stats:
            self.crawler.stats.inc_value('rate_limit_retry/count')

        await deferred_to_future(task.deferLater(reactor, delay, lambda: None))
        return retry_request


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
