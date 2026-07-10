"""Leadbox (lbx-egypt): join ``inventory.xml`` URLs with inventory JSON VINs by vehicle ID."""

import re
from urllib.parse import urlparse

import scrapy
from fake_useragent import UserAgent
from scrapy.loader import ItemLoader

from .base_spider import ScrapebucketSpider
from ..items import ScrapebucketItem
from ..spider_helpers.response_json import loads_response_body

_VDP_ID_RE = re.compile(r'-(\d+)(?:/)?$')


class LeadboxSpider(ScrapebucketSpider):
    """
    Leadbox-powered dealer sites expose:
    - VDP URLs in ``/inventory.xml``
    - VIN/stock metadata in ``/wp-content/uploads/data/inventory.json``

    Both payloads share the same numeric vehicle ID (URL suffix), which lets us
    emit stable VIN + VDP rows without browser automation.
    """

    name = 'leadbox'
    domain_name = ''

    custom_settings = {
        'DOWNLOADER_MIDDLEWARES': {
            'scrapebucket.middlewares.ScrapebucketDownloaderMiddleware': 543,
        },
    }

    def start_requests(self):
        self.domain_name = '.'.join(urlparse(self.url).netloc.split('.')[-2:])
        yield scrapy.Request(
            url=f'{self.url.rstrip("/")}/inventory.xml',
            callback=self.parse_sitemap,
            headers={
                'User-Agent': UserAgent().chrome,
            },
        )

    def parse_sitemap(self, response):
        vdp_by_id = {}
        for url in response.xpath('//*[local-name()="url"]/*[local-name()="loc"]/text()').getall():
            match = _VDP_ID_RE.search(url)
            if not match:
                continue
            vdp_by_id[int(match.group(1))] = url

        if not vdp_by_id:
            self.logger.warning('%s: no VDP links found in inventory.xml', self.name)
            return

        json_url = f'{self.url.rstrip("/")}/wp-content/uploads/data/inventory.json'
        yield scrapy.Request(
            url=json_url,
            callback=self.parse_inventory_json,
            cb_kwargs={'vdp_by_id': vdp_by_id},
            headers={
                'User-Agent': UserAgent().chrome,
            },
        )

    def parse_inventory_json(self, response, vdp_by_id):
        payload = loads_response_body(response.body, url=response.url, label=self.name)
        if not payload:
            return

        vehicles = payload.get('vehicles') or []
        for vehicle in vehicles:
            vehicle_id = vehicle.get('id')
            if vehicle_id is None:
                continue

            try:
                vehicle_id = int(vehicle_id)
            except (TypeError, ValueError):
                continue

            vdp_url = vdp_by_id.get(vehicle_id)
            if not vdp_url:
                continue

            loader = ItemLoader(item=ScrapebucketItem())
            loader.add_value('category', vehicle.get('condition'))
            loader.add_value('year', vehicle.get('year'))
            loader.add_value('make', vehicle.get('make'))
            loader.add_value('model', vehicle.get('model'))
            loader.add_value('trim', vehicle.get('trim'))
            loader.add_value('stock_number', vehicle.get('stocknumber'))
            loader.add_value('vin', vehicle.get('vin'))
            loader.add_value('vehicle_url', vdp_url)
            loader.add_value('domain', self.domain_name)
            yield loader.load_item()
