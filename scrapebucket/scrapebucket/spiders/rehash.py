"""Spider for Shopify Re-hash dealers via the public collection products JSON API."""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse, urlunparse

from scrapy import Selector
from scrapy.loader import ItemLoader

from ..items import ScrapebucketItem
from ..spider_helpers.response_json import loads_response_body
from .base_spider import PLAYWRIGHT_SPIDER_SETTINGS, ScrapebucketPlaywrightSpider

logger = logging.getLogger(__name__)


class RehashSpider(ScrapebucketPlaywrightSpider):
    """
    Loads inventory from Shopify's legacy public JSON endpoint instead of HTML VDPs.

    ``{site}/collections/all-vehicles/products.json?limit=250&page=N`` returns
    VIN, stock, price, images, and tags in one or two requests per dealer — far
    fewer Cloudflare round-trips than crawling every product page.

    JSON is fetched via Playwright (real Chromium TLS) because Cloudflare blocks
    Scrapy's Twisted downloader on these Shopify hosts even when ``curl`` succeeds.
    """

    name = 'rehash'
    domain_name = ''
    _origin = ''

    COLLECTION_JSON_PATH = 'collections/all-vehicles/products.json'
    PAGE_LIMIT = 250

    _USER_AGENT = (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    )
    _VIN_PATTERNS = (
        re.compile(r'VIN[:\s#]*([A-HJ-NPR-Z0-9]{17})', re.I),
        re.compile(r'vin=([A-HJ-NPR-Z0-9]{17})', re.I),
    )
    _YEAR_TAG = re.compile(r'^(19|20)\d{2}$')

    custom_settings = {
        **PLAYWRIGHT_SPIDER_SETTINGS,
        'DOWNLOADER_MIDDLEWARES': {
            'scrapebucket.middlewares.ScrapebucketDownloaderMiddleware': 543,
            'scrapy.downloadermiddlewares.retry.RetryMiddleware': 550,
            'scrapebucket.middlewares.RateLimitRetryMiddleware': 555,
        },
        'CONCURRENT_REQUESTS_PER_DOMAIN': 1,
        'AUTOTHROTTLE_ENABLED': False,
        'DOWNLOAD_DELAY': 2,
        'RANDOMIZE_DOWNLOAD_DELAY': True,
        'USER_AGENT': _USER_AGENT,
        # 429 is handled by RateLimitRetryMiddleware with real delays.
        'RETRY_HTTP_CODES': [500, 502, 503, 504, 522, 524, 408],
        'RETRY_TIMES': 3,
        'RATE_LIMIT_RETRY_DELAY': 60,
        'RATE_LIMIT_MAX_RETRIES': 2,
        'RATE_LIMIT_START_MAX_RETRIES': 1,
    }

    def _canonical_origin(self) -> str:
        """Shopify on apex hosts often 429s while ``www`` succeeds from the same IP."""
        parsed = urlparse(self.url)
        host = parsed.netloc
        if host and not host.startswith('www.'):
            host = f'www.{host}'
        return urlunparse((parsed.scheme, host, '', '', '', '')).rstrip('/')

    def start_requests(self):
        self.domain_name = '.'.join(urlparse(self.url).netloc.split('.')[-2:])
        self._origin = self._canonical_origin()
        yield self._inventory_request(page=1, is_start=True)

    def _json_headers(self):
        return {
            'Accept': 'application/json,text/plain,*/*',
            'Accept-Language': 'en-US,en;q=0.5',
            'User-Agent': self._USER_AGENT,
        }

    def _inventory_request(self, page: int, *, is_start: bool = False):
        url = (
            f'{self._origin}/{self.COLLECTION_JSON_PATH}'
            f'?limit={self.PAGE_LIMIT}&page={page}'
        )
        return self.playwright_request(
            url,
            callback=self.parse_inventory,
            headers=self._json_headers(),
            meta={
                'inventory_page': page,
                'rate_limit_start': is_start,
            },
        )

    def _response_json_bytes(self, response) -> bytes:
        """Playwright wraps JSON document URLs in an HTML ``<pre>`` shell."""
        body = response.body or b''
        if body[:1] in (b'{', b'['):
            return body
        pre = Selector(text=response.text or '').xpath('//pre/text()').get()
        if pre:
            return pre.encode('utf-8')
        return body

    def parse_inventory(self, response):
        if response.status != 200:
            self._log_edge_throttle(response)
            return

        data = loads_response_body(
            self._response_json_bytes(response), url=response.url, label=self.name
        )
        if not data:
            return

        products = data.get('products') or []
        if not products:
            page = response.meta.get('inventory_page', 1)
            if page == 1:
                logger.warning(
                    '%s: empty products JSON for %s', self.name, response.url
                )
            return

        for product in products:
            item = self._product_to_item(product)
            if item is None:
                continue
            yield item

        if len(products) >= self.PAGE_LIMIT:
            yield self._inventory_request(page=response.meta['inventory_page'] + 1)

    @classmethod
    def _normalize_tags(cls, tags) -> list[str]:
        if isinstance(tags, list):
            return [str(tag).strip() for tag in tags if str(tag).strip()]
        if isinstance(tags, str):
            return [part.strip() for part in tags.split(',') if part.strip()]
        return []

    @classmethod
    def _extract_vin(cls, body_html: str | None) -> str | None:
        text = body_html or ''
        for pattern in cls._VIN_PATTERNS:
            match = pattern.search(text)
            if match:
                return match.group(1).upper()
        return None

    @classmethod
    def _category_from_tags(cls, tags: list[str]) -> str:
        upper = {tag.upper() for tag in tags}
        if 'USED' in upper or 'DEMO' in upper:
            return 'used'
        if 'NEW' in upper:
            return 'new'
        return ''

    @classmethod
    def _year_from_product(cls, title: str, tags: list[str]) -> str:
        for tag in tags:
            if cls._YEAR_TAG.match(tag):
                return tag
        match = re.match(r'^(\d{4})\b', title or '')
        return match.group(1) if match else ''

    @classmethod
    def _trim_from_title(cls, title: str, year: str, make: str, model: str) -> str:
        trim = (title or '').strip()
        prefix = ' '.join(part for part in (year, make, model) if part)
        if prefix and trim.startswith(prefix):
            trim = trim[len(prefix) :].strip()
        return trim

    @classmethod
    def _fields_from_title(cls, title: str) -> tuple[str, str, str]:
        parts = (title or '').strip().split()
        if len(parts) >= 3 and cls._YEAR_TAG.match(parts[0]):
            return parts[0], parts[1], ' '.join(parts[2:])
        if len(parts) >= 2 and cls._YEAR_TAG.match(parts[0]):
            return parts[0], parts[1], ''
        return '', '', ''

    def _product_to_item(self, product: dict):
        tags = self._normalize_tags(product.get('tags'))
        title = (product.get('title') or '').strip()
        title_year, title_make, title_model = self._fields_from_title(title)
        year = self._year_from_product(title, tags) or title_year
        make = title_make or (product.get('vendor') or '').strip()
        model = title_model or (product.get('product_type') or '').strip()
        trim = self._trim_from_title(title, year, make, model)

        variant = (product.get('variants') or [{}])[0]
        stock_number = variant.get('sku')
        price = variant.get('price')
        vin = self._extract_vin(product.get('body_html'))
        if not vin:
            logger.debug('%s: no VIN in JSON for %r; skip', self.name, title)
            return None

        handle = (product.get('handle') or '').strip()
        if not handle:
            return None

        base = self._origin or self._canonical_origin()
        vehicle_url = f'{base}/products/{handle}'

        loader = ItemLoader(item=ScrapebucketItem())
        loader.add_value('category', self._category_from_tags(tags))
        loader.add_value('year', year)
        loader.add_value('make', make)
        loader.add_value('model', model)
        loader.add_value('trim', trim)
        loader.add_value('stock_number', stock_number)
        loader.add_value('vin', vin)
        loader.add_value('vehicle_url', vehicle_url)
        loader.add_value('price', price)
        loader.add_value('domain', self.domain_name)

        images = product.get('images') or []
        if images:
            src = images[0].get('src')
            if src:
                loader.add_value('image_urls', src)
                loader.add_value('images_count', 1)

        return loader.load_item()

    def _log_edge_throttle(self, response):
        """Log Cloudflare/Shopify edge blocks with CF-RAY when present."""
        server = (response.headers.get(b'Server') or b'').decode('latin-1', 'replace')
        cf_ray = (response.headers.get(b'CF-RAY') or b'').decode('latin-1', 'replace')
        retry_after = (response.headers.get(b'Retry-After') or b'').decode(
            'latin-1', 'replace'
        )

        logger.warning(
            '%s: HTTP %s on %s (server=%r cf-ray=%r retry-after=%r)',
            self.name,
            response.status,
            response.url,
            server,
            cf_ray,
            retry_after,
        )
