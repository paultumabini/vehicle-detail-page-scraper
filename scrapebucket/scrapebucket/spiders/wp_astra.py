"""Astra-based WP inventory: shallow vehicle grid with verbose meta rows for stock/VIN."""

from urllib.parse import urlparse

import scrapy
from scrapy.linkextractors import LinkExtractor
from scrapy.loader import ItemLoader
from scrapy.spiders import Rule
from .base_spider import ScrapebucketCrawlSpider

from ..items import ScrapebucketItem


class WpAstraSpider(ScrapebucketCrawlSpider):
    """
    Listing cards link from ``/vehicles``; specs on VDP use label/value pairs with brittle XPath.

    ``meta['page']`` stores the listing URL that led to this VDP (for auditing pagination).
    """

    name = 'wp_astra'
    domain_name = ''

    custom_settings = {
        'DOWNLOADER_MIDDLEWARES': {'scrapebucket.middlewares.ScrapebucketDownloaderMiddleware': 543},
    }

    def start_requests(self):
        self.domain_name = '.'.join(urlparse(self.url).netloc.split('.')[-2:])
        yield scrapy.Request(url=f'{self.url}vehicles')

    link_extractor = LinkExtractor(restrict_xpaths='//div/h2/a')

    rules = (
        Rule(
            link_extractor,
            callback='parse_item',
            follow=True,
            process_request='carry_listing_url',
        ),
    )

    def carry_listing_url(self, request, response):
        request.meta['page'] = response.url
        return request

    def parse_item(self, response):
        loader = ItemLoader(item=ScrapebucketItem(), selector=response)
        loader.add_value('vehicle_url', response.url)
        # Theme encodes "Stock Number" / "VIN" labels; following axis reaches the value cell.
        loader.add_xpath(
            'stock_number',
            '//div[contains(text()[normalize-space()],"Stock Number")]/ancestor::node()[3]/following-sibling::div/div/div/div/text()',
        )
        loader.add_xpath(
            'vin',
            '//div[contains(text()[normalize-space()],"VIN")]/ancestor::node()[3]/following-sibling::div/div/div/div/text()',
        )
        loader.add_value('domain', self.domain_name)
        yield loader.load_item()
