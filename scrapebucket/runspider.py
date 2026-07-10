"""
Entry point for running Scrapy spiders against the AIM dealer database.

Usage::

    python runspider.py --spider <domain>   # run one spider  (e.g. ``autojini``)
    python runspider.py --spider all        # run every active spider in parallel
    python runspider.py -s autojini -j 3    # at most 3 dealer sites at once
    python runspider.py -s rehash -j 1 --site-delay 120  # sequential + cooldown

Bootstrap order (order matters):
  1. Install the asyncio Twisted reactor — must happen before any other Twisted import.
  2. Bootstrap Django ORM via ``ensure_django()`` so models are available at import time
     in middlewares and pipelines.
  3. Import Scrapy/project modules that depend on the above.
"""

import argparse
import logging
import sys
from functools import partial
from typing import Any, Protocol, cast

# ---------------------------------------------------------------------------
# 1. Reactor — install before *any* ``twisted.internet`` import elsewhere.
#    Playwright and other async spiders require the asyncio-backed reactor.
# ---------------------------------------------------------------------------
from twisted.internet import asyncioreactor

if 'twisted.internet.reactor' not in sys.modules:
    asyncioreactor.install()

# ---------------------------------------------------------------------------
# 2. Django ORM bootstrap (idempotent; no-op if already called by settings.py).
#    Locates manage.py, patches sys.path, sets DJANGO_SETTINGS_MODULE, and
#    calls django.setup().
# ---------------------------------------------------------------------------
from scrapebucket.django_setup import ensure_django

ensure_django()

# ---------------------------------------------------------------------------
# 3. Application imports — safe now that Twisted reactor and Django are ready.
# ---------------------------------------------------------------------------
from project.models import Scrape, TargetSite, TargetSiteQuerySet
from scrapebucket.urls_crawl import match_spiders
from scrapy.crawler import CrawlerRunner
from scrapy.utils.log import configure_logging
from scrapy.utils.project import get_project_settings
from twisted.internet import defer, reactor, task

configure_logging()
logger = logging.getLogger(__name__)
settings = get_project_settings()
runner = CrawlerRunner(settings)


class _TwistedReactor(Protocol):
    running: bool

    def stop(self) -> None: ...

    def run(self) -> None: ...


_twisted_reactor = cast(_TwistedReactor, reactor)


def _runnable_target_sites(spider_name: str):
    """TargetSite rows that ``match_spiders`` would schedule for a single-spider run."""
    # Must stay in sync with ``get_urls`` in urls_crawl (``.runnable()`` queryset).
    return cast(TargetSiteQuerySet, TargetSite.objects).runnable().filter(
        spider=spider_name
    )


def _safe_reactor_stop() -> None:
    # ``@defer.inlineCallbacks`` may finish synchronously when there is nothing to
    # ``yield``; calling ``reactor.stop()`` before ``reactor.run()`` raises
    # ``ReactorNotRunning``.
    if _twisted_reactor.running:
        _twisted_reactor.stop()


def _collect_jobs(spider_arg: str) -> list[tuple[Any, str, str]]:
    """
    Build ``[(spider_class, site_url, site_id), ...]`` for the requested run.

    Single-spider mode clears existing scrapes per site before scheduling.
    ``--spider all`` wipes every ``Scrape`` row once up front.
    """
    arg_l = spider_arg.lower()
    jobs: list[tuple[Any, str, str]] = []

    if arg_l == 'all':
        Scrape.objects.all().delete()
        for spider, url, domain, _status in match_spiders(TargetSite, settings):
            jobs.append((spider, url, domain))
        return jobs

    for spider, url, domain, _status in match_spiders(TargetSite, settings):
        if spider.name.lower() != arg_l:
            continue
        ts = TargetSite.objects.filter(site_id__exact=domain).first()
        if ts is not None:
            Scrape.objects.filter(target_site=ts).delete()
        jobs.append((spider, url, domain))

    return jobs


@defer.inlineCallbacks
def _run_jobs(
    jobs: list[tuple[Any, str, str]], concurrency: int, site_delay: int
):
    """Schedule crawls via ``CrawlerRunner``; wait for all to finish."""
    if not jobs:
        return

    if concurrency == 1:
        pause = f' ({site_delay}s pause between sites)' if site_delay else ''
        logger.info('Scheduling %d crawl(s) sequentially%s', len(jobs), pause)
        for index, (spider, url, domain) in enumerate(jobs):
            if index > 0 and site_delay > 0:
                logger.info(
                    'Pausing %ds before %s (%s)', site_delay, spider.name, domain
                )
                yield task.deferLater(_twisted_reactor, site_delay, lambda: None)
            try:
                yield runner.crawl(spider, url=url)
                logger.info('Done: %s (%s)', spider.name, domain)
            except Exception as exc:
                logger.error('Failed: %s (%s): %s', spider.name, domain, exc)
        return

    if concurrency > 0:
        if site_delay:
            logger.warning(
                '--site-delay is only applied with -j 1; ignoring %ds', site_delay
            )
        logger.info(
            'Scheduling %d crawl(s) with concurrency=%d', len(jobs), concurrency
        )
        sem = defer.DeferredSemaphore(concurrency)
        deferreds = [
            sem.run(partial(runner.crawl, spider, url=url))
            for spider, url, _domain in jobs
        ]
    else:
        if site_delay:
            logger.warning(
                '--site-delay is only applied with -j 1; ignoring %ds', site_delay
            )
        logger.info('Scheduling %d crawl(s) in parallel', len(jobs))
        deferreds = [
            runner.crawl(spider, url=url) for spider, url, _domain in jobs
        ]

    results = yield defer.DeferredList(deferreds, consumeErrors=True)

    for (spider, _url, domain), (ok, outcome) in zip(jobs, results):
        if ok:
            logger.info('Done: %s (%s)', spider.name, domain)
        else:
            logger.error('Failed: %s (%s): %s', spider.name, domain, outcome)


@defer.inlineCallbacks
def crawl(spider_arg: str, concurrency: int, site_delay: int):
    """Schedule crawls, wait for completion, then stop the reactor."""
    jobs = _collect_jobs(spider_arg)

    if not jobs:
        logger.warning(
            'No runnable TargetSite rows for spider "%s"; nothing to crawl.',
            spider_arg.lower(),
        )
        _safe_reactor_stop()
        return

    yield _run_jobs(jobs, concurrency, site_delay)
    _safe_reactor_stop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Run one or all active Scrapy spiders.'
    )
    parser.add_argument(
        '-s',
        '--spider',
        type=str,
        metavar='NAME',
        required=True,
        help='Spider domain name (e.g. "autojini") or "all" to run every active spider.',
    )
    parser.add_argument(
        '-j',
        '--concurrency',
        type=int,
        default=0,
        metavar='N',
        help=(
            'Max concurrent site crawls (0 = unlimited). '
            'Use a small value (e.g. 2–3) for Playwright spiders.'
        ),
    )
    parser.add_argument(
        '--site-delay',
        type=int,
        default=0,
        metavar='SECONDS',
        help=(
            'Pause between site crawls when -j 1 (e.g. 120 for Cloudflare/Shopify).'
        ),
    )
    args = parser.parse_args()
    spider_arg = args.spider.lower()

    # Skip Twisted/Scrapy when nothing is runnable (e.g. cron with zero active sites).
    # Uses the same ``.runnable()`` queryset as ``match_spiders``, not status alone.
    if spider_arg != 'all':
        if not _runnable_target_sites(spider_arg).exists():
            logger.info(
                'No runnable TargetSite rows for spider "%s"; skipping crawl.',
                spider_arg,
            )
            sys.exit(0)

    crawl(args.spider, args.concurrency, args.site_delay)
    # Blocks until all crawls finish and reactor.stop() is reached.
    _twisted_reactor.run()
