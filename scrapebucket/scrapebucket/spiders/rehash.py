"""Spider for Shopify themes using Re-hash style navigation and Ajaxinate pagination."""

import json
import logging
from urllib.parse import urlparse

import scrapy
from scrapy import signals
from scrapy.linkextractors import LinkExtractor
from scrapy.loader import ItemLoader
from scrapy.spiders import Rule
from .base_spider import ScrapebucketCrawlSpider

from ..items import ScrapebucketItem

logger = logging.getLogger(__name__)


class RehashSpider(ScrapebucketCrawlSpider):
    """
    Crawls listing + paginated pages, then VDPs.

    Vehicle links are taken from the Ajaxinate collection grid (not the site footer,
    which re-exposes every product on each page and triggers Cloudflare/Shopify throttling).
    Pagination follows ``ajaxinate`` load-more URLs.

    VDP fields are parsed from ``application/ld+json`` ``Vehicle`` blocks (same data
    family as Convertus JSON on ``tadvantage``), with XPath fallback for VIN.
    """

    name = 'rehash'
    domain_name = ''

    _VEHICLE_LD_TYPES = frozenset({'Vehicle', 'Car', 'Product'})
    _TRIM_BODY_SUFFIXES = (' SUV', ' Truck', ' Van', ' Sedan', ' Coupe', ' Pickup', ' Wagon')

    _USER_AGENT = (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    )

    custom_settings = {
        'DOWNLOADER_MIDDLEWARES': {
            'scrapebucket.middlewares.ScrapebucketDownloaderMiddleware': 543,
            'scrapebucket.middlewares.RateLimitRetryMiddleware': 551,
        },
        'CONCURRENT_REQUESTS_PER_DOMAIN': 1,
        'AUTOTHROTTLE_ENABLED': False,
        'DOWNLOAD_DELAY': 4,
        'RANDOMIZE_DOWNLOAD_DELAY': True,
        'RATE_LIMIT_RETRY_DELAY': 45,
        'RETRY_TIMES': 5,
        'COOKIES_ENABLED': True,
        'USER_AGENT': _USER_AGENT,
    }

    # Product links on the current collection page only (avoids footer fan-out).
    link_extractor_products = LinkExtractor(
        allow=r'/products/',
        # Theme uses ``section.ajaxinate-container``, not a div.
        restrict_xpaths='//*[contains(@class,"ajaxinate-container")]//a',
    )
    # "Next" / ajaxinate pagination chunks.
    link_extractor_pagination = LinkExtractor(
        restrict_xpaths='//div[contains(@class,"ajaxinate-pagination")]//a',
    )

    rules = (
        Rule(
            link_extractor_products,
            callback='parse_item',
            follow=False,
            process_request='meta_processor',
        ),
        Rule(
            link_extractor_pagination,
            follow=True,
            process_request='meta_processor',
        ),
    )

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        crawler.signals.connect(
            spider._on_response_received, signal=signals.response_received
        )
        return spider

    def _browser_headers(self, referer=None):
        headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'User-Agent': self._USER_AGENT,
        }
        if referer:
            headers['Referer'] = referer
        return headers

    def start_requests(self):
        # Last two labels of the host (e.g. example.com) for stable domain reporting.
        self.domain_name = '.'.join(urlparse(self.url).netloc.split('.')[-2:])

        yield scrapy.Request(
            url=f'{self.url}collections/all-vehicles',
            headers=self._browser_headers(),
        )

    def meta_processor(self, request, response):
        request.meta['page'] = response.url
        request.headers.setdefault(b'User-Agent', self._USER_AGENT.encode())
        request.headers.setdefault(
            b'Accept',
            b'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        )
        request.headers[b'Referer'] = response.url.encode()
        return request

    def _walk_json_ld(self, data):
        if isinstance(data, dict):
            if data.get('@type') in self._VEHICLE_LD_TYPES and data.get(
                'vehicleIdentificationNumber'
            ):
                yield data
            graph = data.get('@graph')
            if isinstance(graph, list):
                for node in graph:
                    yield from self._walk_json_ld(node)
        elif isinstance(data, list):
            for node in data:
                yield from self._walk_json_ld(node)

    def _iter_vehicle_ld(self, response):
        for raw in response.xpath(
            '//script[@type="application/ld+json"]/text()'
        ).getall():
            raw = (raw or '').strip()
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            yield from self._walk_json_ld(data)

    @staticmethod
    def _first_offer(vehicle):
        offers = vehicle.get('offers')
        if isinstance(offers, list):
            return offers[0] if offers else {}
        return offers if isinstance(offers, dict) else {}

    @staticmethod
    def _brand_name(vehicle):
        brand = vehicle.get('brand')
        if isinstance(brand, dict):
            return brand.get('name')
        return brand

    def _parse_trim(self, vehicle):
        name = (vehicle.get('name') or '').strip()
        year = str(vehicle.get('vehicleModelDate') or '').strip()
        make = (self._brand_name(vehicle) or '').strip()
        model = (vehicle.get('model') or '').strip()
        prefix = ' '.join(part for part in (year, make, model) if part)
        if prefix and name.startswith(prefix):
            trim = name[len(prefix) :].strip()
            if trim:
                for suffix in self._TRIM_BODY_SUFFIXES:
                    if suffix in trim:
                        return trim.split(suffix)[0].strip()
                return trim

        config = (vehicle.get('vehicleConfiguration') or '').strip()
        if config:
            for suffix in self._TRIM_BODY_SUFFIXES:
                if suffix in config:
                    return config.split(suffix)[0].strip()
            return config.split()[0]
        return ''

    @staticmethod
    def _primary_image(vehicle):
        images = vehicle.get('image')
        if isinstance(images, list):
            return images[0] if images else None
        return images

    def _on_response_received(self, response, request, spider):
        if spider is not self:
            return
        if response.status not in (403, 429, 503):
            return
        path = urlparse(response.url).path
        if '/products/' not in path and '/collections/' not in path:
            return
        self._log_edge_throttle(response)

    def _log_edge_throttle(self, response):
        """Log Cloudflare/Shopify edge blocks and rate limits with CF-RAY when present."""
        server = (response.headers.get(b'Server') or b'').decode('latin-1', 'replace')
        cf_ray = (response.headers.get(b'CF-RAY') or b'').decode('latin-1', 'replace')
        retry_after = (response.headers.get(b'Retry-After') or b'').decode(
            'latin-1', 'replace'
        )
        behind_cloudflare = 'cloudflare' in server.lower() or bool(cf_ray)

        msg = '%s: HTTP %s on %s (server=%r cf-ray=%r retry-after=%r). '
        args = [self.name, response.status, response.url, server, cf_ray, retry_after]

        if response.status == 429:
            msg += 'Rate limited — reduce crawl concurrency or retry later.'
        elif response.status == 503:
            msg += (
                'Service unavailable — often Cloudflare/Shopify throttling under burst load.'
                if behind_cloudflare
                else 'Service unavailable — origin or CDN overload.'
            )
        else:
            msg += (
                'Forbidden — Cloudflare may be blocking this egress IP.'
                if behind_cloudflare
                else 'Forbidden — check dealer site access from prod egress IP.'
            )

        logger.warning(msg, *args)

    def parse_item(self, response):
        if response.status != 200:
            self._log_edge_throttle(response)
            return

        loader = ItemLoader(item=ScrapebucketItem(), selector=response)
        vehicle = next(self._iter_vehicle_ld(response), None)

        if vehicle:
            offer = self._first_offer(vehicle)
            loader.add_value('category', (offer or {}).get('itemCondition'))
            loader.add_value('year', vehicle.get('vehicleModelDate'))
            loader.add_value('make', self._brand_name(vehicle))
            loader.add_value('model', vehicle.get('model'))
            loader.add_value('trim', self._parse_trim(vehicle))
            loader.add_value('stock_number', vehicle.get('sku'))
            loader.add_value(
                'vin',
                vehicle.get('vehicleIdentificationNumber') or vehicle.get('mpn'),
            )
            loader.add_value('price', (offer or {}).get('price'))
            primary_image = self._primary_image(vehicle)
            if primary_image:
                loader.add_value('image_urls', primary_image)
                loader.add_value('images_count', 1)
        else:
            loader.add_xpath('vin', '//ul/li[contains(text(),"VIN: ")]/text()')

        loader.add_value('vehicle_url', response.url)
        loader.add_value('domain', self.domain_name)

        item = loader.load_item()
        if not item.get('vin'):
            logger.debug('%s: no VIN on %s; skip item', self.name, response.url)
            return

        yield item
