from urllib.parse import urlparse

import scrapy
from scrapy.http.request.form import FormdataType
from scrapy.loader import ItemLoader

from .base_spider import ScrapebucketSpider
from ..items import ScrapebucketItem
from ..spider_helpers.response_json import loads_response_body


class WebstagerSpider(ScrapebucketSpider):
    name = 'webstager'
    domain_name = ''

    _REDIRECT_STATUSES = (301, 302, 303, 307, 308)

    custom_settings = {
        'DOWNLOADER_MIDDLEWARES': {
            'scrapebucket.middlewares.ScrapebucketDownloaderMiddleware': 543
        },
    }

    def start_requests(self):
        self.domain_name = '.'.join(urlparse(self.url).netloc.split('.')[-2:])
        inventory_probe = f'{self.url}inventory/'

        # Resolve brand-specific inventory paths (e.g. /inventory/ -> /ford/inventory/)
        # without following redirects on the POST, which would downgrade to GET + HTML.
        yield scrapy.Request(
            url=inventory_probe,
            callback=self.resolve_inventory_url,
            meta={
                'dont_redirect': True,
                'handle_httpstatus_list': list(self._REDIRECT_STATUSES),
            },
        )

    def resolve_inventory_url(self, response):
        if response.status in self._REDIRECT_STATUSES:
            location = response.headers.get('Location', b'').decode().strip()
            inventory_url = response.urljoin(location) if location else response.url
        else:
            inventory_url = response.url

        yield self._inventory_search_request(inventory_url, page=1)

    def _inventory_search_request(self, inventory_url, page):
        formdata: FormdataType = [
            ('actionList', 'search'),
            *([('p', str(page))] if page > 1 else []),
        ]

        return scrapy.FormRequest(
            url=inventory_url,
            method='POST',
            headers={'Referer': inventory_url},
            formdata=formdata,
            callback=self.parse,
            meta={'inventory_url': inventory_url},
        )

    def parse(self, response):
        res_json = loads_response_body(response.body, url=response.url, label=self.name)
        if not res_json:
            return

        inventory = res_json.get('inventory') or {}
        for result in inventory.get('results') or []:
            loader = ItemLoader(ScrapebucketItem())
            loader.add_value('category', result.get('url'))
            loader.add_value('year', result.get('year'))
            loader.add_value('make', result.get('make'))
            loader.add_value('model', result.get('model'))
            loader.add_value('trim', result.get('trim'))
            loader.add_value('unit', result.get('title'))
            loader.add_value('stock_number', result.get('stockNumber'))
            loader.add_value('vin', result.get('VIN'))
            loader.add_value('vehicle_url', result.get('url'))
            loader.add_value('msrp', result.get('msrp_price'))
            loader.add_value('price', result.get('price'))
            images = result.get('images') or []
            loader.add_value(
                'image_urls',
                [image.get('remote') for image in images if isinstance(image, dict)],
            )
            loader.add_value('images_count', len(images))
            loader.add_value('domain', self.domain_name)

            yield loader.load_item()

        current_page = inventory.get('currentPage') or 1
        total_pages = inventory.get('totalPages') or 1
        inventory_url = response.meta['inventory_url']
        if current_page < total_pages:
            yield self._inventory_search_request(inventory_url, page=current_page + 1)
