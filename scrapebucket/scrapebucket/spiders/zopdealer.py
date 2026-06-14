"""Zop Dealer (Typesense) inventory: API keys are embedded on each dealer's SRP."""

import json
import re
from urllib.parse import urljoin, urlparse

import scrapy
from scrapy.loader import ItemLoader

from ..items import ScrapebucketItem
from ..spider_helpers.response_json import loads_response_body

_PER_PAGE = 50
_TYPESENSE_FIELD = re.compile(
    r'"(?P<key>COLLECTION|API_KEY|TYPESENSE_HOST)"\s*:\s*"(?P<value>[^"]+)"'
)


class ZopDealerSpider(scrapy.Spider):
    """
    Zop dealers expose Typesense ``COLLECTION``, ``API_KEY``, and ``TYPESENSE_HOST``
    in ``globalZDProperties()`` on ``/inventory/``. VDP paths are in ``page_url``.
    """

    name = 'zopdealer'
    domain_name = ''

    custom_settings = {
        'DOWNLOADER_MIDDLEWARES': {
            'scrapebucket.middlewares.ScrapebucketDownloaderMiddleware': 543,
        },
    }

    def start_requests(self):
        self.domain_name = '.'.join(urlparse(self.url).netloc.split('.')[-2:])
        yield scrapy.Request(
            url=urljoin(self.url, '/inventory/'),
            callback=self.parse_config,
            dont_filter=True,
        )

    def parse_config(self, response):
        config = {}
        for match in _TYPESENSE_FIELD.finditer(response.text):
            config[match.group('key')] = match.group('value')

        missing = [key for key in ('COLLECTION', 'API_KEY', 'TYPESENSE_HOST') if not config.get(key)]
        if missing:
            self.logger.warning(
                'zopdealer: missing Typesense fields %s on %s',
                missing,
                response.url,
            )
            return

        api_url = (
            f"https://{config['TYPESENSE_HOST']}/multi_search"
            f"?x-typesense-api-key={config['API_KEY']}"
        )
        yield scrapy.Request(
            url=api_url,
            method='POST',
            headers={'Content-Type': 'application/json'},
            body=json.dumps(self._search_body(config['COLLECTION'], page=1, per_page=1)),
            callback=self.parse_probe,
            meta={
                'api_url': api_url,
                'collection': config['COLLECTION'],
                'base_url': response.urljoin('/'),
            },
        )

    def parse_probe(self, response):
        payload = loads_response_body(response.body, url=response.url, label=self.name)
        if not payload:
            return

        results = payload.get('results') or []
        if not results:
            return

        out_of = results[0].get('out_of') or 0
        if not out_of:
            self.logger.warning('zopdealer: empty inventory for %s', self.url)
            return

        # Typesense returns at most ~250 hits per request; Zop SRP uses one bulk fetch.
        per_page = min(out_of, 250)
        yield from self._search_request(
            api_url=response.meta['api_url'],
            collection=response.meta['collection'],
            page=1,
            per_page=per_page,
            base_url=response.meta['base_url'],
        )

    def _search_body(self, collection, page, per_page=_PER_PAGE):
        return {
            'searches': [
                {
                    'collection': collection,
                    'q': '*',
                    'query_by': 'make,model,year_search,trim,vin,stock_no,exterior_color',
                    'num_typos': 0,
                    'sort_by': 'status_rank:asc,created_at:desc',
                    'filter_by': '',
                    'page': str(page),
                    'per_page': str(per_page),
                }
            ]
        }

    def _search_request(self, api_url, collection, page, per_page, base_url):
        yield scrapy.Request(
            url=api_url,
            method='POST',
            headers={'Content-Type': 'application/json'},
            body=json.dumps(self._search_body(collection, page, per_page)),
            callback=self.parse_inventory,
            meta={
                'api_url': api_url,
                'collection': collection,
                'page': page,
                'per_page': per_page,
                'base_url': base_url,
            },
        )

    def parse_inventory(self, response):
        payload = loads_response_body(response.body, url=response.url, label=self.name)
        if not payload:
            return

        results = payload.get('results') or []
        if not results:
            self.logger.warning('zopdealer: no results in response')
            return

        batch = results[0]
        hits = batch.get('hits') or []
        base_url = response.meta['base_url']

        for hit in hits:
            doc = hit.get('document') or {}
            vin = (doc.get('vin') or '').strip()
            page_url = (doc.get('page_url') or '').strip()
            if not page_url or not vin or vin.upper() == 'UNKNOWN':
                continue

            loader = ItemLoader(item=ScrapebucketItem())
            loader.add_value('year', doc.get('year'))
            loader.add_value('make', doc.get('make'))
            loader.add_value('model', doc.get('model'))
            loader.add_value('trim', doc.get('trim'))
            loader.add_value('stock_number', doc.get('stock_no'))
            loader.add_value('vin', vin)
            loader.add_value('vehicle_url', urljoin(base_url, page_url.lstrip('/')))
            loader.add_value('price', doc.get('selling_price') or doc.get('special_price'))
            loader.add_value('category', doc.get('vehicle_type') or doc.get('status'))
            loader.add_value('domain', self.domain_name)
            yield loader.load_item()
