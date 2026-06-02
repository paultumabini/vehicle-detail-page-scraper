import logging
import math
from urllib.parse import urlparse

import scrapy
from scrapy.loader import ItemLoader

from ..items import ScrapebucketItem
from ..spider_helpers.response_json import loads_response_body
from ..spider_helpers.url_qs import (
    get_company_id,
    keep_top_lvl_domain,
    parse_trader_url,
)

logger = logging.getLogger(__name__)


class TadvantageOrigSpider(scrapy.Spider):
    name = 'tadvantage_orig'
    domain_name = ''
    page = 1
    handle_httpstatus_list = [403]

    custom_settings = {
        'DOWNLOADER_MIDDLEWARES': {
            'scrapebucket.middlewares.ScrapebucketDownloaderMiddleware': 543
        },
        'DOWNLOAD_DELAY': 2,
        'RANDOMIZE_DOWNLOAD_DELAY': True,
        'COOKIES_ENABLED': True,
    }

    def _dealer_origin(self) -> str:
        return self.url.rstrip('/')

    def _proxy_headers(self) -> dict:
        origin = self._dealer_origin()
        return {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            ),
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'X-Requested-With': 'XMLHttpRequest',
            'Referer': f'{origin}/vehicles/',
            'Origin': origin,
        }

    def _proxy_request(self, page: int) -> scrapy.Request:
        return scrapy.Request(
            url=parse_trader_url(self.url, self.company_id, page, 15),
            callback=self.parse,
            headers=self._proxy_headers(),
            dont_filter=True,
        )

    def _log_http_block(self, response) -> None:
        """Explain 403s — usually Cloudflare on the dealer site, not spider headers."""
        server = (response.headers.get(b'Server') or b'').decode('latin-1', 'replace')
        body = (response.text or '')[:2000].lower()
        cf_ray = (response.headers.get(b'CF-RAY') or b'').decode('latin-1', 'replace')

        if (
            'cloudflare' in server.lower()
            or 'cloudflare' in body
            or cf_ray
        ):
            logger.error(
                '%s: HTTP 403 from Cloudflare on dealer WP proxy (%s). '
                'Your egress IP is blocked on the dealer site before Convertus is '
                'contacted — Support VPN or an allowlisted server IP is required; '
                'header tweaks will not fix this.',
                self.name,
                response.url,
            )
            return

        if 'awselb' in server.lower():
            logger.error(
                '%s: HTTP 403 from Convertus AWS WAF (%s). '
                'Use Support VPN or get the scraper egress IP allowlisted on '
                'vms.prod.convertus.rocks.',
                self.name,
                response.url,
            )
            return

        logger.error(
            '%s: HTTP %s blocked (%s). Server=%r — likely geo/IP restriction; '
            'try Support VPN or prod EC2 with allowlisted egress.',
            self.name,
            response.status,
            response.url,
            server,
        )

    def start_requests(self):
        # kitchener.tabangimotors.com --> kitchenertabangimotors.com
        self.domain_name = keep_top_lvl_domain(urlparse(self.url).netloc).replace(
            'www', ''
        )

        dn = self.domain_name.split('.')[0]

        self.company_id = get_company_id(dn)
        if not self.company_id:
            logger.error(
                '%s: no feed_id for site_id=%r (url=%s)',
                self.name,
                dn,
                self.url,
            )
            return

        logger.info(
            '%s: starting dealer=%s company_id=%s via WP proxy',
            self.name,
            self.domain_name,
            self.company_id,
        )
        yield self._proxy_request(self.page)

    def parse(self, response):
        if response.status != 200:
            self._log_http_block(response)
            return

        json_res = loads_response_body(
            response.body, url=response.url, label=self.name
        )
        if not json_res:
            logger.warning(
                '%s: non-JSON or empty body (status=%s) url=%s',
                self.name,
                response.status,
                response.url,
            )
            return

        parsed_data = json_res.get('results') or []
        if not parsed_data:
            logger.warning('tadvantage_orig: empty results for %s', response.url)
            return

        logger.info(
            '%s: page %s yielded %s vehicles',
            self.name,
            self.page,
            len(parsed_data),
        )

        for result in parsed_data:
            loader = ItemLoader(ScrapebucketItem())

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
            loader.add_value('vehicle_url', new_vdp_url.replace(' ', '%20'))
            loader.add_value('price', result.get('asking_price'))
            loader.add_value('domain', self.domain_name)
            yield loader.load_item()

        summary = json_res.get('summary') or {}
        pages = summary.get('total_vehicles')
        if not pages:
            return

        page_limit = math.ceil(pages / 15)

        if self.page < page_limit:
            self.page += 1
            yield self._proxy_request(self.page)
