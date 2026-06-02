"""
Persist scraped items to Django ``Scrape`` rows and optional post-crawl exports.

- ``ScrapebucketPipeline`` — per-item DB writes during the crawl.
- ``VdpUrlFtpExportPipeline`` — batch CSV upload to FTP in ``close_spider``.

Django ORM is bootstrapped via ``ensure_django()`` (idempotent; a no-op when
``settings.py`` has already called it).
"""

from __future__ import annotations

import csv
import io
import logging
import os
from ftplib import FTP, error_perm

from django.db import close_old_connections
from itemadapter import ItemAdapter

from scrapebucket.django_setup import ensure_django

# Safety net: no-op when settings.py has already bootstrapped Django; ensures
# the ORM is available if this module is ever imported in isolation.
ensure_django()

logger = logging.getLogger(__name__)

from project.models import Scrape, TargetSite  # noqa: E402 — must follow ensure_django()

# ---------------------------------------------------------------------------
# Shared site resolution (used by DB + FTP pipelines)
# ---------------------------------------------------------------------------
# Both pipelines map a hostname to TargetSite.site_id the same way so writes
# and FTP export stay aligned. Previously VdpUrls lived in middlewares.py and
# used an exact site_id match; lookup is now iexact everywhere in this module.

# AIM FTP export column layout (must match downstream consumers).
_VDP_URLS_CSV_COLUMNS = ('VIN', 'VDP URLS')


def _registrable_site_id(domain: str) -> str | None:
    """
    Map a hostname or domain string to ``TargetSite.site_id``.

    ``site_id`` stores only the first label (e.g. ``"example"`` from ``"example.com"``).
    Returns ``None`` when the input is empty.
    """
    label = (domain or '').strip().split('.')[0]
    return label or None


def _lookup_target_site(site_id: str) -> TargetSite | None:
    """
    Case-insensitive ``TargetSite`` lookup.

    Spiders/items may use different casing than the DB row; iexact avoids
    silent skips on save or FTP export.
    """
    return TargetSite.objects.filter(site_id__iexact=site_id).first()


class ScrapebucketPipeline:
    """
    Default pipeline: resolve item domain → ``TargetSite``, then insert a ``Scrape``.

    ``domain`` is expected to be the full registered domain (e.g. ``"example.com"``).
    The leading label (``"example"``) is matched case-insensitively against
    ``TargetSite.site_id``.  Items without a domain or with no matching site are
    skipped without raising.
    """

    def process_item(self, item, spider):
        try:
            adapter = ItemAdapter(item)

            domain = adapter.get('domain')
            if not domain:
                logger.debug(
                    'ScrapebucketPipeline: item has no domain field; skip DB write'
                )
                return item

            # Same normalization as VdpUrlFtpExportPipeline (spider.domain_name).
            site_id = _registrable_site_id(domain)
            if site_id is None:
                logger.debug(
                    'ScrapebucketPipeline: empty domain after normalize; skip DB write'
                )
                return item

            target = _lookup_target_site(site_id)
            if target is None:
                logger.warning(
                    'ScrapebucketPipeline: no TargetSite for site_id=%r; skip',
                    site_id,
                )
                return item

            try:
                Scrape(
                    target_site_id=target.pk,
                    spider=spider.name,
                    category=adapter.get('category'),
                    unit=adapter.get('unit'),
                    year=adapter.get('year'),
                    make=adapter.get('make'),
                    model=adapter.get('model'),
                    trim=adapter.get('trim'),
                    stock_number=adapter.get('stock_number'),
                    vin=adapter.get('vin'),
                    vehicle_url=adapter.get('vehicle_url'),
                    msrp=adapter.get('msrp'),
                    price=adapter.get('price'),
                    selling_price=adapter.get('selling_price'),
                    rebate=adapter.get('rebate'),
                    image_urls=adapter.get('image_urls'),
                    images_count=adapter.get('images_count'),
                    page=adapter.get('page'),
                ).save()
            except Exception as exc:
                logger.exception('ScrapebucketPipeline: save failed: %s', exc)

            return item
        finally:
            # Scrapy item processing uses a thread pool; without this, each thread
            # keeps a PostgreSQL connection until the process exits.
            close_old_connections()


class DealerinspireXmlPipeline:
    """
    Debug/experimental pipeline for Dealer Inspire XML spiders.

    Logs each item at DEBUG level; does not write to the database.
    Enable in settings via ``ITEM_PIPELINES`` when troubleshooting XML output.
    """

    def process_item(self, item, spider):
        logger.debug('DealerinspireXmlPipeline item=%s', item)
        return item


class VdpUrlFtpExportPipeline:
    """
    Export VIN/VDP URL pairs to FTP as ``VDP_URLS_{site_id}.csv`` when the crawl ends.

    Moved from ``VdpUrlsMiddleWare`` (spider middleware) — that class only hooked
    ``spider_closed`` and never processed requests. ``close_spider`` is the idiomatic
    Scrapy hook for post-crawl data export.

    Register in ``ITEM_PIPELINES`` at a higher number than ``ScrapebucketPipeline``
    (e.g. 400 vs 300) so all items are persisted before export runs.

    Required env vars: ``AIM_FTP_HOST``, ``AIM_FTP_USER``, ``AIM_FTP_PASS``.
    Optional:          ``AIM_FTP_PORT`` (defaults to ``21``).
    """

    def close_spider(self, spider):
        try:
            # Set in spider start_urls/start_requests from the crawl URL netloc.
            site_id = _registrable_site_id(getattr(spider, 'domain_name', '') or '')
            if site_id is None:
                logger.warning(
                    'VdpUrlFtpExportPipeline: spider.domain_name not set; skip FTP export'
                )
                return

            self._upload_vdp_csv(site_id)
        finally:
            # Scrapy pipelines may run in a thread pool; release DB connections.
            close_old_connections()

    def _upload_vdp_csv(self, site_id: str) -> None:
        target = _lookup_target_site(site_id)
        if target is None:
            logger.warning(
                'VdpUrlFtpExportPipeline: no TargetSite for site_id=%r; skip FTP export',
                site_id,
            )
            return

        host = os.environ.get('AIM_FTP_HOST')
        user = os.environ.get('AIM_FTP_USER')
        password = os.environ.get('AIM_FTP_PASS')
        if not all((host, user, password)):
            logger.warning(
                'VdpUrlFtpExportPipeline: AIM_FTP_* env vars not set; skip FTP export'
            )
            return

        # Reads rows written by ScrapebucketPipeline during this crawl (plus any
        # pre-existing scrapes for the site until runspider clears them).
        payload = io.BytesIO(_vdp_urls_csv_bytes(target))
        # Filename uses DB site_id so casing matches AIM's expected VDP_URLS_*.csv names.
        remote = f'VDP_URLS_{target.site_id}.csv'

        ftp = FTP()
        try:
            ftp.connect(host, int(os.environ.get('AIM_FTP_PORT', '21')))
            ftp.login(user, password)
            # STOR uploads in binary mode; payload is UTF-8-encoded CSV bytes.
            ftp.storbinary(f'STOR {remote}', payload)
            logger.info('VdpUrlFtpExportPipeline: uploaded %s', remote)
        except (OSError, error_perm) as exc:
            logger.error('VdpUrlFtpExportPipeline: FTP upload failed: %s', exc)
        finally:
            try:
                ftp.quit()
            except Exception:
                ftp.close()


def _vdp_urls_csv_bytes(target: TargetSite) -> bytes:
    """
    Serialize ``target.scrapes`` to UTF-8 CSV bytes for FTP upload.

    Kept separate from ``_upload_vdp_csv`` so CSV layout stays testable and
    mirrors the column set used by ``ftp_test.py`` smoke uploads.
    """
    csvfile = io.StringIO()
    writer = csv.DictWriter(csvfile, fieldnames=_VDP_URLS_CSV_COLUMNS)
    writer.writeheader()
    for row in target.scrapes.values():
        writer.writerow(
            {'VIN': row.get('vin'), 'VDP URLS': row.get('vehicle_url')}
        )
    return csvfile.getvalue().encode('utf-8')
