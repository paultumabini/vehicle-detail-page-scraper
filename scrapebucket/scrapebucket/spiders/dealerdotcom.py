from urllib.parse import urlparse

import scrapy
from scrapy.loader import ItemLoader

from .base_spider import ScrapebucketSpider
from ..items import ScrapebucketItem
from ..spider_helpers.response_json import loads_response_body


class DealerdotcomSpider(ScrapebucketSpider):
    name = 'dealerdotcom'
    domain_name = ''

    custom_settings = {
        'DOWNLOADER_MIDDLEWARES': {
            'scrapebucket.middlewares.ScrapebucketDownloaderMiddleware': 543
        },
        'DOWNLOAD_DELAY': 1,
    }

    def start_requests(self):
        self.domain_name = '.'.join(urlparse(self.url).netloc.split('.')[-2:]).replace(
            '-', ''
        )

        if self.domain_name.split('.')[0] == 'jimthompsonchrysler':
            yield scrapy.Request(
                url=f'{self.url}apis/widget/INVENTORY_LISTING_DEFAULT_AUTO_NEW:inventory-data-bus1/getInventory?start=0',
                callback=self.parse,
            )

            yield scrapy.Request(
                url=f'{self.url}apis/widget/SITEBUILDER_USED_INVENTORY_1:inventory-data-bus1/getInventory?start=0',
                callback=self.parse,
            )

        else:

            for inventory in ['NEW', 'USED']:
                yield scrapy.Request(
                    url=f'{self.url}apis/widget/INVENTORY_LISTING_DEFAULT_AUTO_{inventory}:inventory-data-bus1/getInventory?start=0',
                    meta={'inventory': inventory},
                    callback=self.parse,
                )

    def parse(self, response):
        json_res = loads_response_body(
            response.body, url=response.url, label=self.name
        )
        if not json_res:
            return

        page_info = json_res.get('pageInfo') or {}
        data = page_info.get('trackingData') or []
        total_units = page_info.get('totalCount')

        for vehicle_data in data:
            loader = ItemLoader(item=ScrapebucketItem())
            loader.add_value('category', vehicle_data.get('inventoryType'))
            loader.add_value('year', vehicle_data.get('modelYear'))
            loader.add_value('make', vehicle_data.get('make'))
            loader.add_value('model', vehicle_data.get('model'))
            loader.add_value('trim', vehicle_data.get('trim'))
            loader.add_value('stock_number', vehicle_data.get('stockNumber'))
            loader.add_value('vin', vehicle_data.get('vin'))

            link = vehicle_data.get('link') or ''
            if link.startswith('/'):
                path = link[1:]
            else:
                path = link
            loader.add_value('vehicle_url', f'{self.url}{path}')
            loader.add_value('msrp', vehicle_data.get('msrp'))
            loader.add_value('domain', self.domain_name)

            yield loader.load_item()

        if total_units:
            units_per_page = 18
            number_of_pages = int(total_units / units_per_page)

            for page_start in range(1, number_of_pages + 1):

                if self.domain_name.split('.')[0] == 'jimthompsonchrysler':
                    yield scrapy.Request(
                        url=f'{self.url}apis/widget/INVENTORY_LISTING_DEFAULT_AUTO_NEW:inventory-data-bus1/getInventory?start={units_per_page * page_start}',
                        callback=self.parse,
                    )

                    yield scrapy.Request(
                        url=f'{self.url}apis/widget/SITEBUILDER_USED_INVENTORY_1:inventory-data-bus1/getInventory?start={units_per_page * page_start}',
                        callback=self.parse,
                    )
                else:
                    for inventory in ['NEW', 'USED']:
                        yield scrapy.Request(
                            url=f'{self.url}apis/widget/INVENTORY_LISTING_DEFAULT_AUTO_{inventory}:inventory-data-bus1/getInventory?start={units_per_page * page_start}',
                            callback=self.parse,
                        )
