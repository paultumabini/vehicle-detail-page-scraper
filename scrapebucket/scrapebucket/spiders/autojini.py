import json
from urllib.parse import urlencode, urlparse

import scrapy
from scrapy.linkextractors import LinkExtractor
from scrapy.loader import ItemLoader

from .base_spider import ScrapebucketSpider
from ..items import ScrapebucketItem
from ..spider_helpers.response_json import loads_response_body


class AutojiniSpider(ScrapebucketSpider):
    name = 'autojini'

    custom_settings = {
        'DOWNLOADER_MIDDLEWARES': {
            'scrapebucket.middlewares.ScrapebucketDownloaderMiddleware': 543,
        },
        'DOWNLOAD_DELAY': 1,
    }

    def start_requests(self):
        self.domain_name = '.'.join(urlparse(self.url).netloc.split('.')[-2:])
        pages = [1, 25, 49, 73, 97, 121]

        for page in pages:
            params = {'ajExtCall': 'inventory.list', 'startRow': page}
            yield scrapy.Request(
                url=f'{self.url}cms.cfm?{urlencode(params)}',
                callback=self.parse,
            )

    def parse(self, response):
        unit_urls = LinkExtractor(
            restrict_xpaths='//div[@class="productImage"]/a[2]'
        ).extract_links(response)
        for url in unit_urls:
            yield scrapy.Request(
                url=f'{url.url}',
                callback=self.parse_api,
            )

    def parse_api(self, response):
        access_url = (
            'https://public-api.buyerbridge.io/v1/accounts/'
            '3f301d49-919f-49bd-908b-914b735cc716/products/search'
        )
        vin = response.xpath('//div/@vin').get()
        if not vin:
            return

        payload = {
            'queries': [
                {
                    'field': 'vin',
                    'value': [vin, vin, vin],
                    'match_type': 'term',
                },
            ],
        }

        headers = {
            'Accept-Encoding': 'gzip, deflate, br',
            'Content-Type': 'application/json',
            'Referer': 'https://www.drivencarscanada.ca/',
            'Origin': 'https://www.drivencarscanada.ca/',
        }

        yield scrapy.Request(
            url=access_url,
            method='POST',
            headers=headers,
            body=json.dumps(payload),
            callback=self.parse_items,
        )

    def parse_items(self, response):
        res_json = loads_response_body(
            response.body, url=response.url, label=self.name
        )
        if not res_json:
            return

        data_list = res_json.get('data') or []
        if not data_list:
            return

        data = data_list[0]
        loader = ItemLoader(item=ScrapebucketItem())

        loader.add_value('vin', data.get('vin'))
        loader.add_value('vehicle_url', data.get('vdp_url'))
        loader.add_value('domain', self.domain_name)

        yield loader.load_item()
