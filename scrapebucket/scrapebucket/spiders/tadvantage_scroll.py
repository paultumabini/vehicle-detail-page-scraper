import logging
import math
import time
from urllib.parse import urlparse

import scrapy
from fake_useragent import UserAgent
from scrapebucket.items_helper import remove_non_numeric
from scrapy.loader import ItemLoader
from scrapy.selector import Selector
from scrapy.utils.project import get_project_settings
from scrapy_playwright.page import PageMethod

from ..items import ScrapebucketItem

logger = logging.getLogger(__name__)


class TadvantageScrollSpider(scrapy.Spider):
    name = 'tadvantage_scroll'
    domain_name = ''

    # if sys.modules.get("twisted.internet.reactor", False):
    #     del sys.modules["twisted.internet.reactor"]
    #     scrapy.utils.reactor.install_reactor('twisted.internet.asyncioreactor.AsyncioSelectorReactor')

    custom_settings = {
        'DOWNLOADER_MIDDLEWARES': {'scrapebucket.middlewares.ScrapebucketDownloaderMiddleware': 543},
        # VDP FTP export is enabled globally via VdpUrlFtpExportPipeline in settings.
        'SPIDER_MIDDLEWARES': {
            'scrapebucket.middlewares.JobStatLogsMiddleware': 300,
        },
        'TWISTED_REACTOR': 'twisted.internet.asyncioreactor.AsyncioSelectorReactor',
        'DOWNLOAD_HANDLERS': {
            'http': 'scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler',
            'https': 'scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler',
        },
        'PLAYWRIGHT_LAUNCH_OPTIONS': {
            'headless': True,
            # 'timeout': 20 * 1000,  # 20 seconds,
        },
    }

    def start_requests(self):
        self.domain_name = '.'.join(urlparse(self.url).netloc.split('.')[-2:])

        yield scrapy.Request(
            url=f'{self.url}/vehicles/',
            headers={
                "User-Agent": f"{UserAgent().chrome}",
            },
            meta={
                "playwright": True,
                "playwright_include_page": True,
                "playwright_page_methods": [
                    PageMethod("wait_for_selector", "div.grid-view:last-child"),
                    PageMethod("evaluate", "window.scrollBy(0,document.body.scrollHeight)"),
                ],
            },
            errback=self.close_page,
        )

    async def parse(self, response):
        page = response.meta["playwright_page"]
        total_units = response.xpath(
            '//h5[@convertus-data-id="srp__vehicles-found"]/text()'
        ).get()
        units_per_page = 15
        try:
            num_of_pages = math.ceil(
                int(remove_non_numeric(total_units)) / units_per_page
            )
        except (TypeError, ValueError):
            logger.warning(
                '%s: could not parse vehicle count from %r',
                self.name,
                total_units,
            )
            num_of_pages = 1

        for _ in range(1, num_of_pages):
            # url_count = 15 * i
            # await page.evaluate("window.scrollBy(0,document.body.scrollHeight)")
            # await page.wait_for_selector(f"div.grid-view:nth-child({url_count})")

            await page.evaluate(
                """
                var scrollInterval = setInterval(function () {
                    var scrollingElement = (document.scrollingElement || document.body);
                    scrollingElement.scrollTop = scrollingElement.scrollHeight;
                }, 500);

                """
            )
            prev_height = None
            while True:
                cur_height = await page.evaluate('(window.innerHeight + window.scrollY)')
                if not prev_height:
                    prev_height = cur_height
                    time.sleep(1)
                elif prev_height == cur_height:
                    await page.evaluate('clearInterval(scrollInterval)')
                    break
                else:
                    prev_height = cur_height
                    time.sleep(1)

        html = await page.content()
        await page.close()

        target_elems = Selector(text=html).xpath('//div[@convertus-data-id="srp__vehicle-card"]')

        for num, elem in enumerate(target_elems):
            loader = ItemLoader(ScrapebucketItem(), selector=elem)
            loader.add_xpath('stock_number', './/@data-vehicle-stock')
            loader.add_xpath('vin', './/@data-vehicle-vin')
            loader.add_xpath('vehicle_url', '..//div[contains(@class,"vehicle-card__image")]/a/@href')
            loader.add_value('domain', self.domain_name)

            yield loader.load_item()

        # if pagination is enabled
        pagination = response.xpath('//div[@class="pagination__numbers"]/span/text()')

        if pagination:
            try:
                total_pages = int(remove_non_numeric(pagination.get())) + 1
            except (TypeError, ValueError):
                total_pages = 0
            for page in range(2, total_pages):
                yield scrapy.Request(
                    url=f'{self.url}/vehicles/?view=grid&pg={page}',
                    headers={
                        "User-Agent": f"{UserAgent().chrome}",
                    },
                    meta={
                        "playwright": True,
                        "playwright_include_page": True,
                        "playwright_page_methods": [
                            PageMethod("wait_for_selector", "div.grid-view:last-child"),
                            PageMethod("evaluate", "window.scrollBy(0,document.body.scrollHeight)"),
                        ],
                    },
                    callback=self.parse,
                    errback=self.close_page,
                )

    async def close_page(self, error):
        page = error.request.meta['playwright_page']
        await page.close()
