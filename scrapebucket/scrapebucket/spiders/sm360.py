"""SM360 inventory: vehicle JSON is embedded in page script as Jsonnet-ish ``vehicleDetails``."""

import json
import re
from urllib.parse import urlparse

import _jsonnet
import scrapy
from scrapy.linkextractors import LinkExtractor
from scrapy.loader import ItemLoader
from scrapy.spiders import Rule

from .base_spider import ScrapebucketCrawlSpider
from ..items import ScrapebucketItem


class Sm360Spider(ScrapebucketCrawlSpider):
    """
    VDP HTML contains ``vehicleDetails: ...`` inside a script blob; we slice between markers
    and evaluate via ``_jsonnet`` (not plain ``json.loads``).

    Legacy themes expose SRP links in HTML; newer Showroom v2 sites render inventory via a
    React widget, so we also seed VDP URLs from the dealer sitemap.
    """

    name = 'sm360'
    domain_name = ''

    _USER_AGENT = (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    )
    _INVENTORY_RE = re.compile(r'^/(en|fr)/(?:new|used|certified)-inventory/?$', re.I)
    _VDP_SITEMAP_RE = re.compile(r'/(?:new|used|certified)-inventory/.+-id\d+', re.I)

    custom_settings = {
        'USER_AGENT': _USER_AGENT,
        'DOWNLOADER_MIDDLEWARES': {
            'scrapebucket.middlewares.ScrapebucketDownloaderMiddleware': 543
        },
    }

    def start_requests(self):
        self.domain_name = '.'.join(urlparse(self.url).netloc.split('.')[-2:])
        yield scrapy.Request(
            url=self.url,
            callback=self.parse_home,
            dont_filter=True,
        )

    def parse_home(self, response):
        locale = self._locale_prefix(response)

        for which in ('new', 'used', 'certified'):
            yield scrapy.Request(url=response.urljoin(f'{locale}{which}-inventory'))

        yield scrapy.Request(
            url=response.urljoin(f'{locale}sitemap-xml'),
            callback=self.parse_sitemap,
            dont_filter=True,
        )

    def _locale_prefix(self, response):
        for href in response.css('a::attr(href)').getall():
            match = self._INVENTORY_RE.match(href)
            if match:
                return f'{match.group(1)}/'
        return ''

    def parse_sitemap(self, response):
        if response.status != 200:
            return

        for loc in re.findall(r'<loc>([^<]+)</loc>', response.text):
            if not self._VDP_SITEMAP_RE.search(loc):
                continue
            yield scrapy.Request(
                url=loc,
                callback=self.parse_item,
                meta={'page': response.url},
            )

    link_extractor1 = LinkExtractor(
        restrict_xpaths=[
            '//div[@class="inventory-preview-bravo-section-title"]/a',
            '//div[@class="inventory-preview-alpha-section-title"]/a',
            '//div[@class="inventory-preview-bravo__infos-wrapper"]/a',
        ]
    )
    link_extractor2 = LinkExtractor(
        restrict_xpaths='//a[starts-with(@class, "pagination__page-button")]'
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

    def _vehicle_details_snippet(self, response):
        json_txt = response.xpath(
            'normalize-space(substring-before(substring-after('
            '(//script[contains(.,"vehicleDetails:")]/text())[last()],'
            '"vehicleDetails:"),"formVehicle"))'
        ).get()
        if json_txt and len(json_txt) > 2:
            return json_txt[:-1]

        for script in response.xpath('//script[contains(., "vehicleDetails:")]/text()').getall():
            match = re.search(
                r'vehicleDetails:\s*(\{.*?\})\s*,?\s*formVehicle',
                script,
                re.S,
            )
            if match:
                return match.group(1)
        return None

    def parse_item(self, response):
        snippet = self._vehicle_details_snippet(response)
        if not snippet:
            return

        try:
            json_dict = json.loads(_jsonnet.evaluate_snippet('snippet', snippet))
        except Exception:
            # Malformed embed or Jsonnet eval failure — skip item rather than poison the crawl.
            return

        loader = ItemLoader(item=ScrapebucketItem(), selector=response)
        loader.add_value('category', json_dict.get('status'))
        loader.add_value('year', json_dict.get('year'))
        loader.add_value('make', json_dict.get('make'))
        loader.add_value('model', json_dict.get('model'))
        loader.add_value('trim', json_dict.get('trim'))
        loader.add_value('stock_number', json_dict.get('stockNumber'))
        loader.add_value('vin', json_dict.get('vin'))
        loader.add_value('vehicle_url', response.url)
        loader.add_value('msrp', json_dict.get('msrp'))
        loader.add_value('domain', self.domain_name)

        yield loader.load_item()
