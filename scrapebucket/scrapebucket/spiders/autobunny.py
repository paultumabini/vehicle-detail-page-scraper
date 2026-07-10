"""Autobunny theme: used inventory grid with WordPress-style numeric pagination."""

from urllib.parse import urlparse

import scrapy
from scrapy.linkextractors import LinkExtractor
from scrapy.loader import ItemLoader

from .base_spider import ScrapebucketSpider
from ..items import ScrapebucketItem


class AutobunnySpider(ScrapebucketSpider):
    name = 'autobunny'
    domain_name = ''

    custom_settings = {
        'DOWNLOAD_DELAY': 1,
    }

    def start_requests(self):
        self.domain_name = '.'.join(urlparse(self.url).netloc.split('.')[-2:])
        yield scrapy.Request(url=f'{self.url}used-cars/?cpage=1')

    def parse(self, response):
        unit_urls = LinkExtractor(
            restrict_xpaths='//h3[@class="vehicleName"]/ancestor::node()[1]'
        ).extract_links(response)
        for link in unit_urls:
            yield scrapy.Request(
                url=f'{link.url}/',
                callback=self.parse_data,
                meta={'page': response.url},
            )

        next_links = LinkExtractor(
            restrict_xpaths='//a[@class="next page-numbers"]'
        ).extract_links(response)
        if next_links:
            yield scrapy.Request(url=next_links[0].url, callback=self.parse)

    def parse_data(self, response):
        list_url = response.request.meta['page']

        loader = ItemLoader(item=ScrapebucketItem(), selector=response)
        loader.add_value('category', response.url)
        loader.add_xpath('year', '//span[contains(text(),"Year:")]/following-sibling::span/text()')
        loader.add_xpath('make', '//span[contains(text(),"Make:")]/following-sibling::span/text()')
        loader.add_xpath('model', '//span[contains(text(),"Model:")]/following-sibling::span/text()')
        loader.add_xpath('unit', '//h2[@class="vehicleName"]/text()')
        loader.add_xpath(
            'stock_number',
            '//span[contains(text(),"Stock Number:")]/following-sibling::span/text()',
        )
        loader.add_xpath('vin', '//span[contains(text(),"VIN:")]/following-sibling::span/text()')
        loader.add_xpath('price', '//span[@class="PriceValue"]/text()')
        loader.add_value('vehicle_url', response.url)
        loader.add_xpath('image_urls', '(//ul[@class="slides"])[1]/li/descendant::img/@src')
        loader.add_value(
            'images_count',
            len(
                response.xpath(
                    '(//ul[@class="slides"])[1]/li/descendant::img/@src'
                ).getall()
            ),
        )
        loader.add_value('page', list_url)
        loader.add_value('domain', self.domain_name)

        yield loader.load_item()
