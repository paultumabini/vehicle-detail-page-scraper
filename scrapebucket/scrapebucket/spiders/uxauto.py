"""UX Auto (Angular SPA) inventory via AWS API Gateway."""

import re
from urllib.parse import urlencode, urljoin, urlparse

import scrapy
from scrapy.loader import ItemLoader

from .base_spider import ScrapebucketSpider
from ..items import ScrapebucketItem
from ..spider_helpers.response_json import loads_response_body

INVENTORY_API = (
    'https://pmy3it3grc.execute-api.ca-central-1.amazonaws.com/inventory-list'
)
_MAIN_JS = re.compile(r'main\.[a-f0-9]+\.js')
# Globals init uses ``this.dealer_id=N``; older builds used Angular metadata
# ``dealer_id","N"`` (number after the key).
_DEALER_ID = re.compile(r'this\.dealer_id=(\d+)|dealer_id","(\d+)"')
_CONDITIONS = (
    ('NEW', 'new', 'new'),
    ('USED', 'used', 'used'),
    ('DEMO', 'demos', 'demo'),
)


class UxautoSpider(ScrapebucketSpider):
    """
    UX Auto dealers are Angular SPAs. ``main.*.js`` embeds ``dealer_id`` and the
    inventory list is loaded from a shared AWS endpoint:

    ``…/inventory-list/{dealer_id}/{NEW|USED|DEMO}``

    VDPs use ``/inventory/list/{new|used|demos}?stockID={stock_id}``.
    """

    name = 'uxauto'
    domain_name = ''

    custom_settings = {
        'DOWNLOADER_MIDDLEWARES': {
            'scrapebucket.middlewares.ScrapebucketDownloaderMiddleware': 543,
        },
    }

    def start_requests(self):
        self.domain_name = '.'.join(urlparse(self.url).netloc.split('.')[-2:])
        yield scrapy.Request(
            url=self.url,
            callback=self.parse_home,
            dont_filter=True,
        )

    def parse_home(self, response):
        match = _MAIN_JS.search(response.text)
        if not match:
            self.logger.warning('uxauto: main.*.js not found on %s', response.url)
            return

        yield scrapy.Request(
            url=urljoin(response.url, match.group(0)),
            callback=self.parse_config,
            meta={'base_url': response.urljoin('/')},
        )

    def parse_config(self, response):
        dealer_match = _DEALER_ID.search(response.text)
        if not dealer_match:
            self.logger.warning('uxauto: dealer_id not found in %s', response.url)
            return

        dealer_id = dealer_match.group(1) or dealer_match.group(2)
        base_url = response.meta['base_url']
        for api_condition, list_path, category in _CONDITIONS:
            yield scrapy.Request(
                url=f'{INVENTORY_API}/{dealer_id}/{api_condition}',
                callback=self.parse_inventory,
                meta={
                    'base_url': base_url,
                    'list_path': list_path,
                    'category': category,
                },
            )

    def parse_inventory(self, response):
        payload = loads_response_body(response.body, url=response.url, label=self.name)
        if not payload:
            return

        base_url = response.meta['base_url']
        list_path = response.meta['list_path']
        category = response.meta['category']
        list_base = urljoin(base_url, f'inventory/list/{list_path}')

        for vehicle in payload.get('records') or []:
            vin = (vehicle.get('vin') or '').strip()
            stock_id = (vehicle.get('stock_id') or '').strip()
            if not vin or not stock_id:
                continue

            query = urlencode({'stockID': stock_id})
            loader = ItemLoader(item=ScrapebucketItem())
            loader.add_value('category', category)
            loader.add_value('year', vehicle.get('year'))
            loader.add_value('make', vehicle.get('make'))
            loader.add_value('model', vehicle.get('model'))
            loader.add_value('trim', vehicle.get('trim'))
            loader.add_value('stock_number', stock_id)
            loader.add_value('vin', vin)
            loader.add_value('vehicle_url', f'{list_base}?{query}')
            loader.add_value('price', vehicle.get('sale_price') or vehicle.get('list_price'))
            loader.add_value('domain', self.domain_name)
            yield loader.load_item()
