import math
from urllib.parse import urlparse

import scrapy
from scrapy.loader import ItemLoader

from .base_spider import ScrapebucketSpider
from ..items import ScrapebucketItem
from ..spider_helpers.response_json import loads_response_body
from ..spider_helpers.url_qs import access_trader_direct_API, get_company_id


class ConvertusSpider(ScrapebucketSpider):
    name = 'convertus'
    domain_name = ''
    page = 1
    company_id: str | None = None

    custom_settings = {
        'DOWNLOADER_MIDDLEWARES': {
            'scrapebucket.middlewares.ScrapebucketDownloaderMiddleware': 543
        },
        # 'DOWNLOAD_DELAY': 3,
    }

    def start_requests(self):
        self.domain_name = '.'.join(urlparse(self.url).netloc.split('.')[-2:])
        dn = self.domain_name.split('.')[0]

        company_id = get_company_id(dn)
        if not company_id:
            return
        self.company_id = company_id

        yield scrapy.Request(
            url=f'{access_trader_direct_API(company_id, self.page, 15)}',
            callback=self.parse,
        )

    def parse(self, response):
        json_res = loads_response_body(
            response.body, url=response.url, label=self.name
        )
        if not json_res:
            return

        parsed_data = json_res.get('results') or []
        if not parsed_data:
            return

        for result in parsed_data:
            loader = ItemLoader(ScrapebucketItem())

            # images = [image.get('image_original') for image in result.get('image', {})]

            vdp_url = result.get('vdp_url')
            if not vdp_url or 'vehicles/' not in vdp_url:
                continue

            indexed = vdp_url.index('vehicles/')
            new_vdp_url = self.url + vdp_url[indexed:]

            loader.add_value('category', result.get('sale_class'))
            loader.add_value('year', result.get('year'))
            loader.add_value('make', result.get('make'))
            loader.add_value('model', result.get('model'))
            loader.add_value('trim', result.get('trim'))
            loader.add_value('stock_number', result.get('stock_number'))
            loader.add_value('vin', result.get('vin'))
            loader.add_value('vehicle_url', new_vdp_url)
            loader.add_value('price', result.get('asking_price'))
            # loader.add_value('image_urls', images)
            # loader.add_value('images_count', len(images))
            loader.add_value('domain', self.domain_name)
            yield loader.load_item()

        summary = json_res.get('summary') or {}
        pages = summary.get('total_vehicles')
        if not pages:
            return

        page_limit = math.ceil(pages / 15)

        if self.page <= page_limit:
            self.page += 1
            company_id = self.company_id
            if not company_id:
                return
            yield scrapy.Request(
                url=f'{access_trader_direct_API(company_id, self.page, 15)}',
                callback=self.parse,
            )
