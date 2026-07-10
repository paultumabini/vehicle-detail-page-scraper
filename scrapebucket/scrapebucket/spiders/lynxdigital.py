"""Lynx Digital / WooCommerce vehicle archive (product attributes table for VIN)."""

from urllib.parse import urlparse

import scrapy
from scrapy.linkextractors import LinkExtractor
from scrapy.loader import ItemLoader
from scrapy.spiders import Rule
from .base_spider import ScrapebucketCrawlSpider
from scrapy.utils.project import get_project_settings

from ..items import ScrapebucketItem


class LynxdigitalSpider(ScrapebucketCrawlSpider):
    name = 'lynxdigital'
    domain_name = ''

    custom_settings = {
        'DOWNLOADER_MIDDLEWARES': {'scrapebucket.middlewares.ScrapebucketDownloaderMiddleware': 543},
    }

    def start_requests(self):
        self.domain_name = '.'.join(urlparse(self.url).netloc.split('.')[-2:])
        yield scrapy.Request(url=f'{self.url}vehicles/')

    extractor1 = LinkExtractor(
        restrict_xpaths='//h3[starts-with(@class,"product-title")]/a'
    )
    extractor2 = LinkExtractor(
        restrict_xpaths='//nav[@class="woocommerce-pagination"]/descendant::a[@class="next page-numbers"]'
    )

    rules = (
        Rule(extractor1, callback='parse_item', follow=True),
        Rule(extractor2, follow=True, process_request='set_user_agent'),
    )

    def set_user_agent(self, request, spiders):
        request.headers['User-Agent'] = get_project_settings().get('USER_AGENT')
        return request

    def parse_item(self, response):
        loader = ItemLoader(item=ScrapebucketItem(), selector=response)
        # VIN stored as a WooCommerce product attribute row (linked text in TD).
        loader.add_xpath(
            'vin',
            '//tr[@class="woocommerce-product-attributes-item woocommerce-product-attributes-item--attribute_pa_vin"]/td/p/a/text()',
        )
        loader.add_value('vehicle_url', response.url)
        loader.add_value('domain', self.domain_name)
        yield loader.load_item()
