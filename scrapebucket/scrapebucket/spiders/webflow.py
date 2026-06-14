"""Webflow CMS inventory (Finsweet filters): VDP slugs use ``/{locale}-listing/vin-{vin}``."""

import re
from urllib.parse import urlparse

import scrapy
from scrapy.linkextractors import LinkExtractor
from scrapy.loader import ItemLoader
from scrapy.spiders import CrawlSpider, Rule

from ..items import ScrapebucketItem

_LISTING_PATH = re.compile(r'/(?:en|fr)-listing/(?:vin-)?[A-HJ-NPR-Z0-9]{17}$', re.I)


class WebflowSpider(CrawlSpider):
    """
    Genesis-style Webflow CPO sites expose VINs in listing URLs and on the VDP.

    Inventory is rendered server-side on the homepage; Finsweet may load more in
    the browser only (not followed here).
    """

    name = 'webflow'
    domain_name = ''

    custom_settings = {
        'DOWNLOADER_MIDDLEWARES': {
            'scrapebucket.middlewares.ScrapebucketDownloaderMiddleware': 543,
        },
    }

    def start_requests(self):
        self.domain_name = '.'.join(urlparse(self.url).netloc.split('.')[-2:])
        yield scrapy.Request(url=self.url)

    listing_links = LinkExtractor(allow=_LISTING_PATH)

    rules = (
        Rule(
            listing_links,
            callback='parse_item',
            follow=False,
        ),
    )

    def parse_item(self, response):
        vin1 = response.xpath(
            '//div[contains(@class,"vehicle_vin-wrapper")]'
            '/div[contains(@class,"vehicle_vin-text")][2]/text()'
        ).get()
        vin2 = response.xpath('//input[@name="vehicleVIN"]/@value').get()
        vin3 = response.xpath('//input[@id="vehicleVIN-batd"]/@value').get()
        slug = response.url.rstrip('/').rsplit('/', 1)[-1]
        vin4 = slug[4:].upper() if slug.lower().startswith('vin-') else slug
        vin = vin1 or vin2 or vin3 or vin4

        loader = ItemLoader(item=ScrapebucketItem(), selector=response)
        loader.add_value('vin', vin)
        loader.add_value('vehicle_url', response.url)
        loader.add_value('domain', self.domain_name)

        yield loader.load_item()
