"""Csek Creative vehicle templates: wp-pagenavi + thumb src upscaled for gallery URLs."""

from urllib.parse import urlparse

import scrapy
from scrapy.linkextractors import LinkExtractor
from scrapy.loader import ItemLoader
from scrapy.spiders import CrawlSpider, Rule

from ..items import ScrapebucketItem


class CsekcreativeSpider(CrawlSpider):
    name = 'csekcreative'
    domain_name = ''

    custom_settings = {
        'DOWNLOADER_MIDDLEWARES': {
            'scrapebucket.middlewares.ScrapebucketDownloaderMiddleware': 543
        },
    }

    def start_requests(self):
        self.domain_name = '.'.join(urlparse(self.url).netloc.split('.')[-2:])
        yield scrapy.Request(url=f'{self.url}vehicles/')

    link_extractor1 = LinkExtractor(restrict_xpaths='//article/a')
    link_extractor2 = LinkExtractor(
        restrict_xpaths='//div[@class="wp-pagenavi clearfix"]/span/following::span[3]/a'
    )

    rules = (
        Rule(
            link_extractor1,
            callback='parse_item',
            follow=True,
            process_request='meta_processor',
        ),
        Rule(
            link_extractor2,
            follow=True,
            process_request='meta_processor',
        ),
    )

    def meta_processor(self, request, response):
        request.meta['page'] = response.url
        return request

    def parse_item(self, response):
        loader = ItemLoader(item=ScrapebucketItem(), selector=response)
        page = response.meta['page']
        # ``self.url`` is passed in by the crawl job (trailing slash expected).
        base_url = self.url[:-1]
        images = []
        for image in [
            img.replace('w146', 'w1000')
            for img in response.xpath('//a[contains(@class,"thumb")]/img/@src').getall()
        ]:
            # CDN path must contain the wide variant token or we skip (avoid broken hrefs).
            if 'w1000' in image:
                images.append(image)

        images_urls = [f'{base_url}{url}' for url in images]

        loader.add_value('vehicle_url', response.url)
        loader.add_xpath('year', '//span[@id="prop-year"]/text()')
        loader.add_xpath('make', '//span[@id="prop-make"]/text()')
        loader.add_xpath('model', '//span[@id="prop-model"]/text()')
        loader.add_xpath('trim', '//span[@id="prop-trim"]/text()')
        loader.add_xpath('unit', '//h2[@class="title"]/text()')
        loader.add_xpath('stock_number', '//span[@id="prop-stock"]/text()')
        loader.add_xpath('vin', '//span[@id="prop-vin"]/text()')
        loader.add_xpath('price', '//span[@class ="price-sm"]/text()')
        loader.add_xpath(
            'discount',
            '(//b[contains(text(),"Discount")]/following::span/text())[1]',
        )
        loader.add_xpath(
            'selling_price',
            '(//b[contains(text(),"Sale Price")]/following::span/text())[1]',
        )
        loader.add_value('image_urls', images_urls)
        loader.add_value('images_count', len(images_urls))
        loader.add_value('page', page)
        loader.add_value('domain', self.domain_name)

        yield loader.load_item()
