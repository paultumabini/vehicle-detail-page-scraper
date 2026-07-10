"""eProcess search results: Playwright for listing + VDP pages."""

from urllib.parse import urlparse

from scrapy.linkextractors import LinkExtractor
from scrapy.loader import ItemLoader

from .base_spider import ScrapebucketPlaywrightSpider
from ..items import ScrapebucketItem


class DealereprocessSpider(ScrapebucketPlaywrightSpider):
    """
    Entry URL embeds a default postal/geo filter (``cy=``) for the search hub.

    Replace or parameterize that segment if you crawl dealers outside the baked-in market.
    """

    name = 'dealereprocess'
    domain_name = ''

    def start_requests(self):
        self.domain_name = '.'.join(urlparse(self.url).netloc.split('.')[-2:])

        yield self.playwright_request(
            f'{self.url}search/toronto-on/?cy=m4a_1j8',
        )

    def parse(self, response):
        unit_urls = LinkExtractor(
            restrict_xpaths='//h2[@class="vehicle_title"]/a'
        ).extract_links(response)
        for link in unit_urls:
            if not link.url:
                continue
            yield self.playwright_request(link.url, callback=self.parse_data)

        next_page_urls = LinkExtractor(
            restrict_xpaths='//a[@class="thm-inverse_text_color"]'
        ).extract_links(response)
        for next_page in next_page_urls:
            if not next_page.url:
                continue
            yield self.playwright_request(next_page.url, callback=self.parse)

    def parse_data(self, response):
        images_urls = response.xpath(
            '//img[contains(@class,"preview_vehicle_image_item")]/@data-src'
        ).getall()

        loader = ItemLoader(
            item=ScrapebucketItem(), selector=response, response=response
        )
        loader.add_value('vehicle_url', response.url)
        loader.add_xpath(
            'stock_number',
            '//td[contains(text(),"Stock #")]/following-sibling::td/text()',
        )
        loader.add_xpath(
            'vin',
            '//td[contains(text(),"VIN")]/following-sibling::td/text()',
        )
        loader.add_value('image_urls', images_urls)
        loader.add_value('images_count', len(images_urls))
        loader.add_value('domain', self.domain_name)

        yield loader.load_item()
