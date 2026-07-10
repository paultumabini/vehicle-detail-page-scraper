from urllib.parse import urlparse

import scrapy
from fake_useragent import UserAgent
from scrapy.loader import ItemLoader
from scrapy.selector import Selector
from scrapy_playwright.page import PageMethod

from .base_spider import ScrapebucketSpider
from ..items import ScrapebucketItem

# from scrapy.utils.reactor import install_reactor
# install_reactor('twisted.internet.asyncioreactor.AsyncioSelectorReactor')


class ReynoldsSpider(ScrapebucketSpider):
    name = 'reynolds'
    domain_name = ''

    custom_settings = {
        'DOWNLOADER_MIDDLEWARES': {
            'scrapebucket.middlewares.ScrapebucketDownloaderMiddleware': 543
        },
        # 'TWISTED_REACTOR': 'twisted.internet.asyncioreactor.AsyncioSelectorReactor',
        'DOWNLOAD_HANDLERS': {
            'http': 'scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler',
            'https': 'scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler',
        },
        'PLAYWRIGHT_LAUNCH_OPTIONS': {
            'headless': True,
            'timeout': 20 * 1000,  # 20 seconds,
        },
    }

    @classmethod
    def update_settings(cls, settings):
        super().update_settings(settings)
        settings.set(
            "TWISTED_REACTOR",
            "twisted.internet.asyncioreactor.AsyncioSelectorReactor",
            priority="spider",
        )

    def start_requests(self):
        self.domain_name = '.'.join(urlparse(self.url).netloc.split('.')[-2:])

        yield scrapy.Request(
            url=f'{self.url}/NewFordInventory',
            headers={
                "User-Agent": f"{UserAgent().chrome}",
            },
            meta={
                "playwright": True,
                "playwright_include_page": True,
                "playwright_page_methods": [
                    PageMethod(
                        "wait_for_selector",
                        "//a[@class='vehicleTitleLink']",
                    ),
                ],
            },
            errback=self.close_page,
        )

        yield scrapy.Request(
            url=f'{self.url}/UsedInventory',
            headers={
                "User-Agent": f"{UserAgent().chrome}",
            },
            meta={
                "playwright": True,
                "playwright_include_page": True,
                "playwright_page_methods": [
                    PageMethod(
                        "wait_for_selector",
                        "//a[@class='vehicleTitleLink']",
                    ),
                ],
            },
            errback=self.close_page,
        )

    async def parse(self, response):
        page = response.meta["playwright_page"]
        vdp_urls = response.xpath('//a[@class="vehicleTitleLink"]/@href').getall()

        for url in vdp_urls:
            yield scrapy.Request(url=url, callback=self.parse_data)

        #  page text option via Selector class
        html_text = await page.content()
        await page.close()

        has_next_page = Selector(text=html_text).xpath(
            '//a[contains(@class, "pageItem next")]'
        )

        next_href = has_next_page.xpath('.//@href').get() if has_next_page else None
        if next_href:
            yield scrapy.Request(
                url=next_href,
                callback=self.parse,
                meta={
                    "playwright": True,
                    "playwright_include_page": True,
                    "playwright_page_methods": [
                        PageMethod(
                            "wait_for_selector",
                            "//a[@class='vehicleTitleLink']",
                        ),
                    ],
                },
                errback=self.close_page,
            )

    async def parse_data(self, response):
        loader = ItemLoader(ScrapebucketItem(), selector=response)
        loader.add_xpath('stock_number', '//span[@itemprop="sku"]/@title')
        loader.add_xpath(
            'vin', '//meta[@itemprop="vehicleIdentificationNumber"]/@content'
        )
        loader.add_value('vehicle_url', response.url)
        loader.add_value('domain', self.domain_name)

        yield loader.load_item()

    async def close_page(self, failure):
        page = failure.request.meta.get('playwright_page')
        if page is not None:
            await page.close()
