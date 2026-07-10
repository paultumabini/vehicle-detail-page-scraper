from urllib.parse import urlparse

import scrapy
from scrapy.loader import ItemLoader
from scrapy.selector import Selector

from .base_spider import ScrapebucketSpider
from ..items import ScrapebucketItem
from ..spider_helpers.response_json import loads_response_body


class FoxdealerSpider(ScrapebucketSpider):
    name = 'foxdealer'
    domain_name = ''

    custom_settings = {
        'DOWNLOADER_MIDDLEWARES': {
            'scrapebucket.middlewares.ScrapebucketDownloaderMiddleware': 543
        },
        'DOWNLOAD_DELAY': 1,
    }

    def start_requests(self):
        self.domain_name = '.'.join(urlparse(self.url).netloc.split('.')[-2:]).replace(
            '-', ''
        )

        for category in ['new', 'used']:
            yield scrapy.Request(
                url=f'{self.url}api/ajax_requests/?currentQuery={self.url}inventory/{category}-page-1/',
                callback=self.parse,
            )

    def parse(self, response):
        json_res = loads_response_body(
            response.body, url=response.url, label=self.name
        )
        if not json_res:
            return

        posts = json_res.get('posts') or []

        for vehicle_data in posts:
            loader = ItemLoader(item=ScrapebucketItem())

            conditions = {
                'New': vehicle_data.get('is_new'),
                'Used': vehicle_data.get('is_used'),
            }

            condition = None
            for key, value in conditions.items():
                if value:
                    condition = key

            imagelist = vehicle_data.get('imagelist') or []
            images = [
                img.get('url')
                for img in imagelist
                if isinstance(img, dict) and img.get('url')
            ]

            permalink = vehicle_data.get('permalink') or ''
            if permalink.startswith('/'):
                path = permalink[1:]
            else:
                path = permalink

            loader.add_value('category', condition)
            loader.add_value('year', vehicle_data.get('year'))
            loader.add_value('make', vehicle_data.get('make'))
            loader.add_value('model', vehicle_data.get('model'))
            loader.add_value('trim', vehicle_data.get('trim'))
            loader.add_value('stock_number', vehicle_data.get('stock'))
            loader.add_value('vin', vehicle_data.get('vin'))
            loader.add_value('vehicle_url', f'{self.url}{path}')
            loader.add_value('msrp', vehicle_data.get('msrp'))
            loader.add_value('image_urls', images)
            loader.add_value('images_count', len(images))
            loader.add_value('domain', self.domain_name)

            yield loader.load_item()

        page_links = json_res.get('page_links')
        if page_links and len(page_links) >= 2:
            categories = ['New', 'Used']
            current_query = json_res.get('current_query') or ''
            page_text = Selector(text=page_links[-2]).xpath('//a/text()').get()
            if not page_text:
                return
            total_pages = int(page_text)
            category = ''
            for cat in categories:
                if cat in current_query:
                    category = cat
                    break

            if not category:
                return

            for next_page in range(2, total_pages + 1):
                yield scrapy.Request(
                    url=f'{self.url}api/ajax_requests/?currentQuery={self.url}inventory/{category}-page-{next_page}/',
                    callback=self.parse,
                )
