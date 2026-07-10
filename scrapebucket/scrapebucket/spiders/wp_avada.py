"""WordPress + Avada theme: Playwright discovers inventory page count, then lists + VDPs."""

from urllib.parse import urlparse

import scrapy
from scrapy.linkextractors import LinkExtractor
from scrapy.loader import ItemLoader
from scrapy_playwright.page import PageMethod

from .base_spider import PLAYWRIGHT_SPIDER_SETTINGS, ScrapebucketPlaywrightSpider
from ..items import ScrapebucketItem
from ..spider_helpers.playwright_helper import PlaywrightHelper


class WpAvadaSpider(ScrapebucketPlaywrightSpider):
    """
    Pagination is not always in the first HTML response; Playwright counts
    ``/inventory/page/N``.

    ``get_pagination_remove_text_legacy`` returns the highest page index seen on
    the listing chrome (Avada-specific parsing).
    """

    name = 'wp_avada'
    domain_name = ''

    custom_settings = {
        **PLAYWRIGHT_SPIDER_SETTINGS,
        'DOWNLOAD_DELAY': 1,
    }

    def start_requests(self):
        self.domain_name = '.'.join(urlparse(self.url).netloc.split('.')[-2:])

        wait_until_selector = 'a.inactive'
        pages = PlaywrightHelper(
            f'{self.url}inventory/',
            wait_until_selector,
            wait_until_selector,
        ).get_page_num_src('get_pagination_remove_text_legacy')

        # ``range(pages + 1)`` includes page 0/1-style first URL segment used by this theme.
        for page in range(pages + 1):
            yield self.playwright_request(
                f'{self.url}inventory/page/{page}',
                callback=self.parse,
                page_methods=[
                    PageMethod('wait_for_selector', wait_until_selector),
                ],
            )

    def parse(self, response):
        unit_urls = LinkExtractor(
            restrict_xpaths='//h1[@class="title-heading-left"]/a'
        ).extract_links(response)
        for link in unit_urls:
            yield scrapy.Request(
                url=link.url,
                callback=self.parse_data,
                meta={'page': response.url},
            )

    def parse_data(self, response):
        list_url = response.request.meta['page']

        loader = ItemLoader(item=ScrapebucketItem(), selector=response)
        loader.add_value('vehicle_url', response.url)
        loader.add_xpath(
            'stock_number', '//li[contains(text(),"Stock #: ")]/span/text()'
        )
        loader.add_xpath('vin', '//li[contains(text(),"VIN: ")]/span/text()')
        loader.add_xpath(
            'price',
            '(//span[@class="woocommerce-Price-currencySymbol"])[1]/../text()',
        )
        loader.add_xpath(
            'image_urls',
            '//a[@class="avada-product-gallery-lightbox-trigger"]/@href',
        )
        loader.add_value(
            'images_count',
            len(
                response.xpath(
                    '//a[@class="avada-product-gallery-lightbox-trigger"]/@href'
                ).getall()
            ),
        )
        loader.add_value('page', list_url)
        loader.add_value('domain', self.domain_name)

        yield loader.load_item()
