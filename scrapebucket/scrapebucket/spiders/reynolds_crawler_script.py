from urllib.parse import urlparse

import scrapy
from fake_useragent import UserAgent
from scrapy.linkextractors import LinkExtractor
from scrapy.loader import ItemLoader
from scrapy.selector import Selector
from scrapy.spiders import CrawlSpider, Rule
from scrapy_playwright.page import PageMethod

from ..items import ScrapebucketItem


class ReynoldsCrawlerScript(CrawlSpider):
    name = 'reynolds_crawler_script'
    domain_name = ''

    # if sys.modules.get("twisted.internet.reactor", False):
    #     del sys.modules["twisted.internet.reactor"]
    #     scrapy.utils.reactor.install_reactor('twisted.internet.asyncioreactor.AsyncioSelectorReactor')

    custom_settings = {
        'DOWNLOADER_MIDDLEWARES': {
            'scrapebucket.middlewares.ScrapebucketDownloaderMiddleware': 543
        },
        # 'SPIDER_MIDDLEWARES': {
        #     'scrapebucket.middlewares.JobStatLogsMiddleware': 300,
        #     'scrapebucket.pipelines.VdpUrlFtpExportPipeline': 400,
        # },
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
            url=f'{self.url}/NewFordInventory',
            headers={
                "User-Agent": f"{UserAgent().chrome}",
            },
            errback=self.close_page,
        )

        # vehicle urls

    extractor1 = LinkExtractor(restrict_xpaths='//a[@class="vehicleTitleLink"]')
    # pagination urls
    extractor2 = LinkExtractor(restrict_xpaths='//a[contains(@class, "pageItem next")]')

    rules = (
        Rule(
            extractor1,
            callback='parse_item',
            process_request='set_playwright_true',
            follow=True,
        ),
        Rule(extractor2, follow=True, process_request='set_playwright_true'),
    )

    def set_playwright_true(self, request, spiders):
        request.meta["playwright"] = True
        request.meta["playwright_include_page"] = True
        request.meta["playwright_page_methods"] = [
            PageMethod("wait_for_selector", "//a[@class='vehicleTitleLink']")
        ]
        return request

    async def parse_item(self, response):
        page = response.meta["playwright_page"]
        vdp_urls = response.xpath('//a[@class="vehicleTitleLink"]/@href').getall()

        for url in vdp_urls:
            yield {'vehicle_url': url}

        html = await page.content()
        await page.close()

        # target_elems = Selector(text=html).xpath('//div[@convertus-data-id="srp__vehicle-card"]')

    #     for num, elem in enumerate(target_elems):
    #         loader = ItemLoader(ScrapebucketItem(), selector=elem)
    #         loader.add_xpath('stock_number', './/@data-vehicle-stock')
    #         loader.add_xpath('vin', './/@data-vehicle-vin')
    #         loader.add_xpath('vehicle_url', '..//div[contains(@class,"vehicle-card__image")]/a/@href')
    #         loader.add_value('domain', self.domain_name)

    #         yield loader.load_item()

    #     # if pagination is enabled
    #     pagination = response.xpath('//div[@class="pagination__numbers"]/span/text()')

    #     if pagination:
    #         total_pages = int(remove_non_numeric(pagination.get())) + 1
    #         for page in range(2, total_pages):
    #             yield scrapy.Request(
    #                 url=f'{self.url}/vehicles/?view=grid&pg={page}',
    #                 headers={
    #                     "User-Agent": f"{UserAgent().chrome}",
    #                 },
    #                 meta={
    #                     "playwright": True,
    #                     "playwright_include_page": True,
    #                     "playwright_page_methods": [
    #                         PageMethod("wait_for_selector", "div.grid-view:last-child"),
    #                         PageMethod("evaluate", "window.scrollBy(0,document.body.scrollHeight)"),
    #                     ],
    #                 },
    #                 callback=self.parse,
    #                 errback=self.close_page,
    #             )

    async def close_page(self, error):
        page = error.request.meta['playwright_page']
        await page.close()
