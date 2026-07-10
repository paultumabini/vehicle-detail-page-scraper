"""Omni Auto inventory via ``portal.omni.auto`` (JS-rendered WordPress SRP)."""

import re
from datetime import date
from urllib.parse import quote, urljoin, urlparse

import scrapy
from scrapy.http.request.form import FormdataType
from scrapy.loader import ItemLoader

from .base_spider import ScrapebucketSpider
from ..items import ScrapebucketItem
from ..spider_helpers.response_json import loads_response_body

OMNI_API = 'https://portal.omni.auto'
INVENTORY_PAGE_SIZE = 35
_SRP_PATH = '/inventory-page-new'
_VDP_PATH = re.compile(r'href="(/Inventory/[^"]+)"', re.I)


class OmniautoSpider(ScrapebucketSpider):
    """
    Omni dealers render SRP cards in the browser; inventory is loaded from
    ``portal.omni.auto`` after ``Site/WordPressAction`` resolves ``siteID``.

    VDP slugs live under ``/Inventory/{year}-{make}-{model}-{trim}-{vin}``.
    """

    name = 'omniauto'
    domain_name = ''

    custom_settings = {
        'DOWNLOADER_MIDDLEWARES': {
            'scrapebucket.middlewares.ScrapebucketDownloaderMiddleware': 543,
        },
    }

    def _dealer_origin(self):
        """Omni resolves dealers on the bare hostname; ``www`` breaks ``WordPressAction``."""
        parsed = urlparse(self.url)
        netloc = parsed.netloc
        if netloc.lower().startswith('www.'):
            netloc = netloc[4:]
        return f'{parsed.scheme}://{netloc}'

    def _api_headers(self, referer_path=_SRP_PATH):
        origin = self._dealer_origin()
        referer = urljoin(origin + '/', referer_path.lstrip('/'))
        return {
            'Origin': origin,
            'Referer': referer,
            'Accept': 'application/json, text/plain, */*',
        }

    def start_requests(self):
        self.domain_name = '.'.join(urlparse(self.url).netloc.split('.')[-2:])
        origin = self._dealer_origin()
        referer = urljoin(origin + '/', _SRP_PATH.lstrip('/'))
        params = (
            f'pathName={quote(_SRP_PATH)}'
            f'&urlParameters='
            f'&referer={quote(referer)}'
            f'&urlString={quote(referer)}'
        )
        yield scrapy.Request(
            url=f'{OMNI_API}/Site/WordPressAction?{params}',
            headers=self._api_headers(),
            callback=self.parse_site,
            dont_filter=True,
        )

    def parse_site(self, response):
        payload = loads_response_body(response.body, url=response.url, label=self.name)
        if not payload:
            return

        site_id = None
        for element in payload.get('wordPressHTMLElements') or []:
            if element.get('name') == 'siteID':
                site_id = element.get('value')
                break
        if not site_id:
            self.logger.warning(
                'omniauto: siteID not found for %s (check www vs non-www site_url)',
                self.url,
            )
            return

        yield from self._inventory_request(site_id, skip_count=0)

    def _inventory_request(self, site_id, skip_count):
        formdata: FormdataType = {
            'skip': str(skip_count),
            'take': str(INVENTORY_PAGE_SIZE),
        }
        yield scrapy.FormRequest(
            url=(
                f'{OMNI_API}/Inventory/GetAllVehiclesFiltered'
                f'?siteID={site_id}&callFromSRP=true'
            ),
            formdata=formdata,
            headers={
                **self._api_headers(),
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            callback=self.parse_inventory,
            meta={'site_id': site_id, 'skip_count': skip_count},
        )

    def parse_inventory(self, response):
        payload = loads_response_body(response.body, url=response.url, label=self.name)
        if not payload:
            return

        site_id = response.meta['site_id']
        skip_count = response.meta['skip_count']
        vehicles = payload.get('SiteInventoryCollection') or []
        base_url = self._dealer_origin() + '/'

        for vehicle in vehicles:
            vin = vehicle.get('Vin')
            vdp_path = self._vdp_path(vehicle)
            if not vin or not vdp_path:
                continue

            loader = ItemLoader(item=ScrapebucketItem())
            loader.add_value('category', self._category(vehicle))
            loader.add_value('year', vehicle.get('Year'))
            loader.add_value('make', vehicle.get('Make'))
            loader.add_value('model', vehicle.get('Model'))
            loader.add_value('trim', vehicle.get('Trim'))
            loader.add_value('stock_number', vehicle.get('StockNumber'))
            loader.add_value('vin', vin)
            loader.add_value('vehicle_url', urljoin(base_url, vdp_path.lstrip('/')))
            loader.add_value('price', vehicle.get('CalculatedPrice'))
            loader.add_value('domain', self.domain_name)
            yield loader.load_item()

        total_count = payload.get('TotalCount') or 0
        next_skip = skip_count + len(vehicles)
        if vehicles and next_skip < total_count:
            yield from self._inventory_request(site_id, skip_count=next_skip)

    @staticmethod
    def _vdp_path(vehicle):
        html = vehicle.get('GeneratedCardHTML') or ''
        match = _VDP_PATH.search(html)
        if match:
            return match.group(1)

        vin = vehicle.get('Vin')
        if vin and vin in html:
            for href in re.findall(r'href="(/Inventory/[^"]+)"', html, re.I):
                if vin in href:
                    return href
        return None

    @staticmethod
    def _category(vehicle):
        if vehicle.get('IsDemo'):
            return 'demo'
        year = vehicle.get('Year')
        if isinstance(year, int) and year >= date.today().year:
            return 'new'
        return 'used'
