"""
Nabthat dealer API: paginated JSON list plus per-VIN detail requests for image hrefs.

The list endpoint does not always embed full image URLs; we call ``/api/v1/vehicles/{vin}``
for each row (N+1 HTTP calls) so pipelines get a consistent ``image_urls`` shape.
"""

from urllib.parse import urlparse

import requests
import scrapy
from scrapy.loader import ItemLoader

from .base_spider import ScrapebucketSpider
from ..items import ScrapebucketItem
from ..spider_helpers.response_json import loads_response_body


class NabthatSpider(ScrapebucketSpider):
    name = 'nabthat'
    domain_name = ''

    custom_settings = {
        'DOWNLOADER_MIDDLEWARES': {
            'scrapebucket.middlewares.ScrapebucketDownloaderMiddleware': 543
        },
    }

    def start_requests(self):
        self.domain_name = '.'.join(urlparse(self.url).netloc.split('.')[-2:])

        # Seed both new and used pipelines; ``parse`` merges pagination for both orderings.
        yield scrapy.Request(
            url=f'{self.url}api/v1/vehicles?category=new&order=in_stock_date_desc&page=1',
            callback=self.parse,
        )
        yield scrapy.Request(
            url=f'{self.url}api/v1/vehicles?category=used&order=price_asc&page=1',
            callback=self.parse,
        )

    def get_image_urls(self, vin):
        if not vin:
            return []
        try:
            response = requests.get(
                url=f'{self.url}/api/v1/vehicles/{vin}',
                timeout=30,
            )
            response.raise_for_status()
        except requests.RequestException:
            return []

        data = loads_response_body(
            response.content,
            url=response.url,
            label=f'{self.name}.vehicle_detail',
        )
        if not data:
            return []

        vehicle = data.get('vehicle') or {}
        return vehicle.get('images') or []

    def parse(self, response):
        resp = loads_response_body(
            response.body, url=response.url, label=self.name
        )
        if not resp:
            return

        units = resp.get('models') or []

        for unit in units:
            raw_images = self.get_image_urls(unit.get('vin'))
            images = [
                url.get('href')
                for url in raw_images
                if isinstance(url, dict) and url.get('href')
            ]

            loader = ItemLoader(item=ScrapebucketItem())
            loader.add_value('vin', unit.get('vin'))
            loader.add_value('vehicle_url', unit.get('vehicle_url'))
            loader.add_value('category', unit.get('category'))
            loader.add_value('year', unit.get('year'))
            loader.add_value('make', unit.get('make'))
            loader.add_value('model', unit.get('model'))
            loader.add_value('trim', unit.get('trim'))
            loader.add_value('stock_number', unit.get('stock'))

            pricing = unit.get('pricing') or {}
            loader.add_value('msrp', pricing.get('msrp'))
            loader.add_value('price', pricing.get('price'))
            loader.add_value('selling_price', pricing.get('selling_price'))

            loader.add_value('image_urls', images)
            loader.add_value('images_count', len(images))
            loader.add_value('domain', self.domain_name)

            yield loader.load_item()

        meta = resp.get('meta') or {}
        has_next = meta.get('nextPage')
        if has_next:
            # Advance both category streams together so neither stalls on page 1.
            yield scrapy.Request(
                url=f'{self.url}/api/v1/vehicles?category=new&order=in_stock_date_desc&page={has_next}',
                callback=self.parse,
            )
            yield scrapy.Request(
                url=f'{self.url}/api/v1/vehicles?category=used&order=price_asc&page={has_next}',
                callback=self.parse,
            )
