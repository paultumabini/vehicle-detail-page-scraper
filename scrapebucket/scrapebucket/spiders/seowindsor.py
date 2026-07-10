from urllib.parse import urlparse

import scrapy
from scrapy.loader import ItemLoader
from scrapy.utils.project import get_project_settings

from .base_spider import ScrapebucketSpider
from ..items import ScrapebucketItem
from ..spider_helpers.response_json import loads_response_body


class SeowindsorSpider(ScrapebucketSpider):
    name = 'seowindsor'
    domain_name = ''

    custom_settings = {
        'DOWNLOAD_DELAY': 3,
    }

    def start_requests(self):
        self.domain_name = '.'.join(urlparse(self.url).netloc.split('.')[-2:])

        ua = get_project_settings().get('USER_AGENT')
        headers = {'User-Agent': ua} if ua else {}

        yield scrapy.Request(
            url='https://darrylfrith.com/mkf/api/2022/api/inventory/0/NEW',
            callback=self.parse,
            headers=headers,
        )
        yield scrapy.Request(
            url='https://darrylfrith.com/mkf/api/2022/api/inventory/0/USED',
            callback=self.parse,
            headers=headers,
        )

    def parse(self, response):
        resp = loads_response_body(
            response.body, url=response.url, label=self.name
        )
        if not resp:
            return

        units = resp.get('results') or []

        for unit in units:
            loader = ItemLoader(item=ScrapebucketItem())
            loader.add_value('category', unit.get('condition'))
            loader.add_value('year', unit.get('year'))
            loader.add_value('make', unit.get('make'))
            loader.add_value('model', unit.get('model'))
            loader.add_value('trim', unit.get('trim'))
            loader.add_value('stock_number', unit.get('stock_id'))
            loader.add_value('vin', unit.get('vin'))

            cond = unit.get('condition')
            stock_id = unit.get('stock_id')
            if cond and stock_id:
                loader.add_value(
                    'vehicle_url',
                    f'{self.url}/inventory/listings/{cond.lower()}?stockID={stock_id}',
                )

            loader.add_value('price', unit.get('retail_price'))
            loader.add_value('selling_price', unit.get('sale_price'))

            images = unit.get('images') or []
            image_urls = [
                f'https://darrylfrith.com/mkf/api/uploadedImages/{url.get("image_key")}'
                for url in images
                if isinstance(url, dict) and url.get('image_key')
            ]
            loader.add_value('image_urls', '|'.join(image_urls))
            loader.add_value('images_count', len(image_urls))
            loader.add_value('domain', self.domain_name)

            yield loader.load_item()
