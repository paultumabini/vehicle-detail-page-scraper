from urllib.parse import urlparse

from scrapy import Selector
from scrapy.loader import ItemLoader
from scrapy_playwright.page import PageMethod

from .base_spider import ScrapebucketPlaywrightSpider
from ..items import ScrapebucketItem
from ..spider_helpers.response_json import loads_response_body


class FlexdealerSpider(ScrapebucketPlaywrightSpider):
    name = 'flexdealer'

    def start_requests(self):
        self.domain_name = '.'.join(urlparse(self.url).netloc.split('.')[-2:])

        for inventory in ['new-hyundai-inventory', 'used-inventory']:
            yield self.playwright_request(
                f'{self.url}{inventory}',
                callback=self.parse,
                page_methods=[
                    PageMethod(
                        'wait_for_function',
                        'document.querySelector("script")?.textContent?.includes("var vehicles")',
                    ),
                ],
            )

    def parse(self, response):
        res = Selector(text=response.text)
        raw = res.xpath('//script[contains(.,"var vehicles")]/text()').get()
        if not raw:
            return

        json_txt = raw.replace('var vehicles = ', '').replace(';', '').strip()
        json_dict = loads_response_body(
            json_txt.encode('utf-8'),
            url=response.url,
            label=self.name,
        )
        if not isinstance(json_dict, list):
            return

        base = self.url[:-1] if self.url.endswith('/') else self.url

        for dic in json_dict:
            url = dic.get('url')
            vin = dic.get('vin')
            stock = dic.get('stock')
            if not url:
                continue

            yield self.playwright_request(
                f'{base}{url}',
                callback=self.parse_data,
                meta={'vin': vin, 'stock': stock},
            )

    def parse_data(self, response):
        vin = response.request.meta['vin']

        images_txt = response.xpath(
            '//a[@data-stateventlabel="VDP Photos Image"]/@data-cargo'
        ).get()
        img_urls = (
            Selector(text=images_txt).xpath('//@src').getall() if images_txt else []
        )

        loader = ItemLoader(item=ScrapebucketItem(), selector=response)
        loader.add_value('vehicle_url', response.url)
        loader.add_value('vin', vin)
        loader.add_value('domain', self.domain_name)

        yield loader.load_item()
