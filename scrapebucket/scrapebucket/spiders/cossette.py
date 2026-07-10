from urllib.parse import urlparse

import scrapy
from scrapy.loader import ItemLoader
from scrapy.selector import Selector

from .base_spider import ScrapebucketSpider
from ..items import ScrapebucketItem
from ..spider_helpers.response_json import loads_response_body
from ..utils import request_all_urls


class CossetteSpider(ScrapebucketSpider):
    name = 'cossette'
    base_url_api = 'https://oserv3.oreganscdn.com/api/vehicle-inventory-search/?'
    domain_name = ''

    custom_settings = {
        'DOWNLOADER_MIDDLEWARES': {
            'scrapebucket.middlewares.ScrapebucketDownloaderMiddleware': 543
        },
        'DOWNLOAD_DELAY': 1,
    }

    def start_requests(self):
        self.domain_name = '.'.join(urlparse(self.url).netloc.split('.')[-2:])

        for url in request_all_urls(self.domain_name, self.base_url_api):
            yield scrapy.Request(
                url=url,
                callback=self.parse,
            )

    def parse(self, response):
        json_res = loads_response_body(
            response.body, url=response.url, label=self.name
        )
        if not json_res:
            return

        search = json_res.get('search') or {}
        results = search.get('results') or []
        if not results:
            return

        parsed_html = [
            Selector(text=html_text.get('html'))
            for html_text in results
            if html_text.get('html')
        ]

        base = self.url[:-1] if self.url.endswith('/') else self.url

        for unit in parsed_html:
            sub_url = unit.xpath(
                '//div[@class="ouvsrHeading orH"]/a/@href'
            ).get()
            if not sub_url:
                continue

            price = unit.xpath('//div [@class="ouvsrCurrentPrice"]/text()')
            p = price.get() if price else 'N/A'

            loader = ItemLoader(item=ScrapebucketItem(), selector=unit)
            loader.add_value('category', f'{base}{sub_url}')
            loader.add_xpath('year', '//span[@class="ouvsrYear"]/text()')
            loader.add_xpath('make', '//span[@class="ouvsrMake"]/text()')
            loader.add_xpath('model', '//span[@class="ouvsrModel"]/text()')
            loader.add_xpath('trim', '//span[@class="ouvsrTrimAndPackage"]/text()')
            loader.add_xpath(
                'stock_number', '//span[@class="ouvsrShortLabel"]/../text()'
            )
            loader.add_xpath(
                'vin',
                'substring-after(//ul[@class="ouvsrToolsList otToolbar"]/li[1]/a/@href, "vin=")',
            )
            loader.add_value('vehicle_url', f'{base}{sub_url}')
            loader.add_value('price', p)
            loader.add_value('domain', self.domain_name)

            yield loader.load_item()
