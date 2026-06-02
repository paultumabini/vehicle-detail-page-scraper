"""Carpages / Dealersite+ style WordPress inventory (mixed microdata and table VIN rows)."""

import re
from urllib.parse import urlparse

import scrapy
from scrapy.linkextractors import LinkExtractor
from scrapy.loader import ItemLoader
from scrapy.spiders import CrawlSpider, Rule
from scrapy.utils.project import get_project_settings

from ..items import ScrapebucketItem

# SRP entry paths vary by theme generation (legacy Carpages vs NASAPI / Ford boilerplate).
INVENTORY_PATHS = (
    'vehicles/',
    'new-inventory/',
    'used-inventory/',
    'all-inventory/',
    'all-vehicles/',  # legacy; 404 on newer installs but harmless
)


class DealersiteplusSpider(CrawlSpider):
    """
    Entry paths differ by site install (``vehicles``, ``new-inventory``, ``all-inventory``).

    VDP links use ``/inventory/{slug}/{id}`` on newer themes; older themes use ``h4`` /
    ``featured-card`` markup. Pagination uses ``next page-numbers`` with ``dsp_page`` query
    args; some themes need an explicit User-Agent on follow-up requests (``set_user_agent``).
    """

    name = 'dealersiteplus'  # carpages
    domain_name = ''

    custom_settings = {
        'DOWNLOADER_MIDDLEWARES': {'scrapebucket.middlewares.ScrapebucketDownloaderMiddleware': 543},
    }

    def start_requests(self):
        self.domain_name = '.'.join(urlparse(self.url).netloc.split('.')[-2:])

        for page in INVENTORY_PATHS:
            yield scrapy.Request(url=f'{self.url}{page}')

    link_extractor1 = LinkExtractor(
        restrict_xpaths=[
            '//h4/a[contains(@title,*)]',
            '//div[@class="featured-card"]/a',
            '//div[contains(@class,"vehicle-card")]//a[contains(@href,"/inventory/")]',
            '//a[contains(@class,"vehicle__image") and contains(@href,"/inventory/")]',
            # Tailwind / microdata SRP cards (e.g. spadonileasing.com).
            '//a[@itemprop="url" and contains(@href,"/inventory/")]',
        ]
    )
    link_extractor2 = LinkExtractor(
        restrict_xpaths='//a[@class="next page-numbers"]'
    )

    rules = (
        Rule(
            link_extractor1,
            callback='parse_item',
            follow=True,
        ),
        Rule(
            link_extractor2,
            follow=True,
            process_request='set_user_agent',
        ),
    )

    def set_user_agent(self, request, spiders):
        request.headers['User-Agent'] = get_project_settings().get('USER_AGENT')
        return request

    def parse_item(self, response):
        # Microdata-first; data-vin / feature grid / table fallbacks for newer themes.
        vin = (
            response.xpath('//li[@itemprop="productID"]/span/text()').get()
            or response.xpath('//*[@data-vin]/@data-vin').get()
            or response.xpath(
                '//p[@class="feature-name" and normalize-space()="VIN"]'
                '/following-sibling::p[contains(@class,"feature-value")]/text()'
            ).get()
            or response.xpath(
                '//div[contains(@class,"details-title") and contains(., "VIN")]/text()'
            ).get()
            or response.xpath('(//td[contains(text(),"VIN:")]/../td)[2]//text()').get()
            or response.xpath('//div[contains(text(),"VIN:")]/text()').get()
            or response.xpath(
                '(//div[contains(text(),"VIN:")]/../div)[2]//text()'
            ).get()
            or response.xpath('//span[contains(., "VIN:")]/text()').get()
        )

        if vin and not re.search(r'[A-HJ-NPR-Z0-9]{17}', str(vin).upper()):
            vin = None

        loader = ItemLoader(item=ScrapebucketItem(), selector=response)
        loader.add_value('vehicle_url', response.url)
        loader.add_xpath('year', '//span[@itemprop="releaseDate"]/text()')
        loader.add_xpath('make', '//span[@itemprop="brand"]/text()')
        loader.add_xpath('model', '//span[@itemprop="model"]/text()')
        loader.add_value('vin', vin)
        loader.add_xpath('stock_number', '//li[@itemprop="sku"]/text()')
        loader.add_xpath(
            'stock_number',
            '//div[contains(@class,"details-info") and contains(., "Stock")]/text()',
        )
        loader.add_xpath(
            'stock_number',
            '//span[contains(., "Stock #")]/text()',
        )
        loader.add_value('domain', self.domain_name)

        yield loader.load_item()
