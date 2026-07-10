"""Dealer Inspire: sitemap table → Playwright VDPs for bot-heavy pages."""

from urllib.parse import urlparse

from scrapy.linkextractors import LinkExtractor
from scrapy.loader import ItemLoader

from .base_spider import PLAYWRIGHT_SPIDER_SETTINGS, ScrapebucketPlaywrightSpider
from ..items import ScrapebucketItem


class DealerinspireSpider(ScrapebucketPlaywrightSpider):
    """
    Starts from the inventory sitemap (tabular links), then loads each VDP in a real browser.

    VDP markup varies (classic vs. alternate price/stock blocks); we try both and merge
    gallery sources (lazy ``data-src`` plus immediate ``src``).
    """

    name = 'dealerinspire'
    domain_name = ''

    custom_settings = {
        **PLAYWRIGHT_SPIDER_SETTINGS,
        'SPIDER_MIDDLEWARES': {'scrapebucket.middlewares.JobStatLogsMiddleware': 543},
    }

    def start_requests(self):
        self.domain_name = '.'.join(urlparse(self.url).netloc.split('.')[-2:])

        yield self.playwright_request(
            f'{self.url}dealer-inspire-inventory/inventory_sitemap/',
        )

    def parse(self, response):
        unit_urls = LinkExtractor(restrict_xpaths='//td/a').extract_links(response)
        for link in unit_urls:
            if not link.url:
                continue
            yield self.playwright_request(link.url, callback=self.parse_data)

    def parse_data(self, response):
        category = 'used' if 'used' in response.url else 'new'

        # Swiper-based gallery: collect both attributes; lazy load often fills data-src later.
        images = [
            response.xpath(
                '//div[@class="swiper-container vdp-gallery-modal__main swiper-container-horizontal"]/div[@class="swiper-wrapper"]/div[contains(@class,"swiper-slide")]/img/@src'
            ).getall(),
            response.xpath(
                '//div[@class="swiper-container vdp-gallery-modal__main swiper-container-horizontal"]/div[@class="swiper-wrapper"]/div[contains(@class,"swiper-slide")]/img/@data-src'
            ).getall(),
        ]

        as_unit = response.xpath(
            '//div[@class="vdp-title__vehicle-info"]/h1/text()'
        ).get()
        price = (
            response.xpath('//span[@class="price"]/text()').get()
            or response.xpath('//span[@class="pricing-item__price "]/text()').get()
        )

        # Primary VIN/stock block vs. fallback spans (theme A/B).
        stock_number1 = response.xpath(
            '//ul[@class="vdp-title__vin-stock"]/li[2]/span/../text()[2]'
        ).get()
        vin1 = response.xpath(
            '//ul[@class="vdp-title__vin-stock"]/li[1]/..//span[@id="vin"]/text()'
        ).get()
        stock_number2 = response.xpath(
            '(//span[@class="vinstock-number"]/text())[1]'
        ).get()
        vin2 = response.xpath('(//span[@class="vinstock-number"]/text())[2]').get()

        stock_number = stock_number1 or stock_number2
        vin = vin1 or vin2

        loader = ItemLoader(
            item=ScrapebucketItem(), selector=response, response=response
        )
        loader.add_value('stock_number', stock_number)
        loader.add_value('vin', vin)
        loader.add_value('vehicle_url', response.url)
        loader.add_value('domain', self.domain_name)
        loader.add_value('category', category)
        loader.add_value('unit', as_unit)
        loader.add_value('price', price)
        src_imgs = images[0] if images else []
        data_imgs = images[1] if len(images) > 1 else []
        merged = [*(src_imgs or []), *(data_imgs or [])]
        # Pipe-separated for pipelines that expect a single string field.
        loader.add_value('image_urls', '|'.join(merged))
        loader.add_value('images_count', len(merged))

        yield loader.load_item()
