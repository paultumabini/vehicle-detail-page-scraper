from urllib.parse import urlparse

import scrapy
from scrapy.linkextractors import LinkExtractor
from scrapy.loader import ItemLoader

from .base_spider import ScrapebucketSpider
from ..items import ScrapebucketItem
from ..spider_helpers.response_json import loads_response_body


class GloveboxSpider(ScrapebucketSpider):
    name = 'glovebox'
    domain_name = ''

    custom_settings = {
        'DOWNLOADER_MIDDLEWARES': {
            'scrapebucket.middlewares.ScrapebucketDownloaderMiddleware': 543
        },
    }

    def start_requests(self):
        self.domain_name = '.'.join(urlparse(self.url).netloc.split('.')[-2:])

        yield scrapy.FormRequest(
            url=f'{self.url}api/listing',
            method='POST',
            formdata={
                'blockid': '84',
                'pageid': '21',
            },
        )

    def parse(self, response):
        res_json = loads_response_body(
            response.body, url=response.url, label=self.name
        )
        if not res_json:
            return

        pages = res_json.get('last_page')
        if not pages:
            return

        for page in range(1, int(pages) + 1):
            yield scrapy.Request(
                url=f'{self.url}inventory/all?type=&make=&model=&order=asc&page={page}',
                callback=self.vdp_urls,
            )

    def vdp_urls(self, response):
        unit_urls = LinkExtractor(
            restrict_xpaths='//p[contains(@class,"vehicle-title")]/a[@itemprop="url"]'
        ).extract_links(response)

        for vdp_url in unit_urls:
            yield scrapy.Request(url=vdp_url.url, callback=self.parse_items)

    def parse_items(self, response):

        loader = ItemLoader(item=ScrapebucketItem(), selector=response)

        loader.add_xpath(
            'category',
            '//p[@class="overview-label" and contains(text(),"Type")]/following-sibling::p/text()',
        )
        loader.add_xpath(
            'year',
            'normalize-space(//p[@class="overview-label" and contains(text(),"Year")]/following-sibling::p/text())',
        )
        loader.add_xpath(
            'make',
            'normalize-space(//p[@class="overview-label" and contains(text(),"Make")]/following-sibling::p/text())',
        )
        loader.add_xpath(
            'model',
            'normalize-space(//p[@class="overview-label" and contains(text(),"Model")]/following-sibling::p/text())',
        )
        loader.add_xpath(
            'trim',
            'normalize-space(//p[@class="overview-label" and contains(text(),"Trim")]/following-sibling::p/text())',
        )
        loader.add_xpath(
            'stock_number',
            '//p[@class="overview-label" and contains(text(),"Stock Number")]/following-sibling::p/text()',
        )
        loader.add_xpath(
            'vin',
            '//p[@class="overview-label" and contains(text(),"VIN")]/following-sibling::p/text()',
        )
        loader.add_value('vehicle_url', response.request.url)
        loader.add_value('domain', self.domain_name)

        yield loader.load_item()
