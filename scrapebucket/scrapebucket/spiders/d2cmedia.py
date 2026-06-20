"""D2C Media inventory via the dealer AJAX search API (UsedSrp2)."""

import base64
import json
import re
from typing import Any
from urllib.parse import urljoin, urlparse

import scrapy
from scrapy.loader import ItemLoader
from scrapy.selector import Selector

from ..items import ScrapebucketItem
from ..spider_helpers.response_json import loads_response_body

_FILTER_SUFFIX = '-10x0-0-0'
_FILTER_VARIANTS = ('a1b13q', 'a1b123d19q')
_FILTER_ID = re.compile(r'id="filterid"\s+value="([^"]+)"', re.I)


class D2cmediaSpider(scrapy.Spider):
    """
    D2C UsedSrp2 dealers load inventory through::

        POST /{lang}/ajax/getSearchVehiclesFromFilterObject?wswidth=1920

    with a ``filterid`` form field (the JSON filter state from the hidden
    ``#filterid`` input).  Pagination stops when the API returns ``count=0``;
    ``fltPageId[1]`` in the filter blob is a UI cap (36), not inventory size.

    VIN, VDP URL, and listing metadata are parsed from the API ``html`` fragment
    (``carBoxInner`` / ``carImage`` cards); VDP pages are not crawled.
    """

    name = 'd2cmedia'
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
        canonical = (
            response.xpath('//link[@rel="canonical"]/@href').get() or response.url
        )
        parsed = urlparse(canonical)
        base_url = f'{parsed.scheme}://{parsed.netloc}/'
        lang = self._ajax_lang(response)
        variant = _FILTER_VARIANTS[0]
        yield scrapy.Request(
            url=f'{base_url}inventory.html?filterid={variant}0{_FILTER_SUFFIX}',
            callback=self.parse_config,
            meta={
                'base_url': base_url,
                'lang': lang,
                'variant': variant,
                'variant_idx': 0,
            },
            dont_filter=True,
        )

    def parse_config(self, response):
        basic = self._basic_filter(response)
        if not basic:
            yield from self._try_next_variant(response)
            return

        yield from self._inventory_request(
            base_url=response.meta['base_url'],
            lang=response.meta['lang'],
            basic=basic,
            page=0,
        )

    def _try_next_variant(self, response):
        idx = response.meta['variant_idx'] + 1
        if idx >= len(_FILTER_VARIANTS):
            self.logger.warning('d2cmedia: no filterid on %s', response.url)
            return

        variant = _FILTER_VARIANTS[idx]
        base_url = response.meta['base_url']
        yield scrapy.Request(
            url=f'{base_url}inventory.html?filterid={variant}0{_FILTER_SUFFIX}',
            callback=self.parse_config,
            meta={
                **response.meta,
                'variant': variant,
                'variant_idx': idx,
            },
            dont_filter=True,
        )

    def _inventory_request(self, base_url, lang, basic, page):
        proxy = dict[Any, Any](basic)
        max_page = basic['fltPageId'][1]
        proxy['fltPageId'] = [page, max_page]
        body_inner = self._filterid_body(proxy)

        yield scrapy.FormRequest(
            url=(
                f'{base_url}{lang}/ajax/getSearchVehiclesFromFilterObject?wswidth=1920'
            ),
            formdata={'filterid': body_inner},
            callback=self.parse_inventory,
            meta={
                'base_url': base_url,
                'lang': lang,
                'basic': basic,
                'page': page,
            },
            dont_filter=True,
        )

    def parse_inventory(self, response):
        payload = loads_response_body(response.body, url=response.url, label=self.name)
        if not payload:
            return

        html = payload.get('html') or ''
        count = payload.get('count') or 0
        base_url = response.meta['base_url']

        for row in Selector(text=html).css('div.carBoxInner'):
            card = row.css('div.carImage[data-vin]')
            if not card:
                continue

            vin = card.attrib.get('data-vin')
            path = row.css('div.carImage a::attr(href)').get()
            if not vin or not path:
                continue

            loader = ItemLoader(item=ScrapebucketItem())
            loader.add_value(
                'category', 'used' if '/used/' in path.lower() else 'new'
            )
            loader.add_value('year', card.attrib.get('data-year'))
            loader.add_value('make', card.attrib.get('data-make'))
            loader.add_value('model', card.attrib.get('data-model'))
            loader.add_value('trim', (row.css('span.divTrim::text').get() or '').strip())
            loader.add_value('stock_number', card.attrib.get('data-nostock'))
            loader.add_value('vin', vin)
            loader.add_value('vehicle_url', urljoin(base_url, path.lstrip('/')))
            loader.add_value(
                'price', row.css('span.dollarsigned.p-base::text').get()
            )
            loader.add_value('domain', self.domain_name)
            yield loader.load_item()

        if count > 0:
            yield from self._inventory_request(
                base_url=base_url,
                lang=response.meta['lang'],
                basic=response.meta['basic'],
                page=response.meta['page'] + 1,
            )

    @staticmethod
    def _ajax_lang(response):
        lang = (
            response.xpath('//input[@id="activesitelanguage"]/@value').get() or ''
        ).strip()
        if lang.upper().startswith('F'):
            return 'fr'
        return 'en'

    @staticmethod
    def _basic_filter(response):
        match = _FILTER_ID.search(response.text)
        if not match:
            return None
        pad = '=' * (-len(match.group(1)) % 4)
        try:
            data = json.loads(base64.b64decode(match.group(1) + pad))
        except (json.JSONDecodeError, ValueError):
            return None
        return data.get('basic')

    @staticmethod
    def _filterid_body(basic_filter):
        """Match UsedSrp2 ``FilterRequest.process`` double-JSON encoding."""
        currenturl = json.dumps(basic_filter)
        encoded = json.dumps(currenturl).replace('\\"', '"')
        return encoded[1:-1]
