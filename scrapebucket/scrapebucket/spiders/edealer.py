from urllib.parse import urlparse

import scrapy
from scrapy.loader import ItemLoader
from scrapy.selector import Selector

from ..items import ScrapebucketItem
from ..spider_helpers.response_json import loads_response_body


class EdealerSpider(scrapy.Spider):
    """Scrape eDealer inventory listings (legacy AJAX API and v4 WordPress HTML)."""

    name = 'edealer'
    domain_name = ''

    # Browser UA shared by v4 GET requests; some sites 403 without it.
    _USER_AGENT = (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36'
    )

    def _browser_headers(self, referer=None):
        # v4 listing pages are server-rendered HTML; use browser-like headers.
        headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'User-Agent': self._USER_AGENT,
        }
        if referer:
            headers['Referer'] = referer
        return headers

    def start_requests(self):
        self.domain_name = '.'.join(urlparse(self.url).netloc.split('.')[-2:]).replace(
            '-', ''
        )

        # eDealer v4 (WordPress): GET /inventory/{new,used}/ — vehicles in data-* attrs.
        for path in ('inventory/new/', 'inventory/used/'):
            yield scrapy.Request(
                url=f'{self.url}{path}',
                callback=self.parse,
                headers=self._browser_headers(),
            )

        headers = {
            'Accept': '*/*',
            'Accept-Encoding': 'gzip, deflate, br',
            'Accept-Language': 'en-US,en;q=0.5',
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'Origin': f'{self.url}',
            'Referer': f'{self.url}new/',
            'Sec-Ch-ua': '"Google Chrome";v="111", "Not(A:Brand";v="8", "Chromium";v="111"',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'user-agent': self._USER_AGENT,
            'X-Requested-With': 'XMLHttpRequest',
        }

        # Legacy eDealer: POST /{new,used}/ returns JSON (vehicleCellHTML).
        # On migrated sites these 301 to /inventory/* and POST returns 404 — harmless.
        for path in ('new/', 'used/'):
            yield scrapy.FormRequest(
                url=f'{self.url}{path}',
                method='POST',
                headers=headers,
                formdata={
                    'ajax': 'true',
                    'refresh': 'true',
                },
                meta={'legacy_ajax': True},
            )

    def parse(self, response):
        # Legacy AJAX returns JSON with Content-Type text/html — detect by leading `{`/`[`.
        body = response.body.lstrip()
        if body.startswith((b'{', b'[')):
            res = loads_response_body(
                response.body, url=response.url, label=self.name
            )
            if isinstance(res, dict) and res.get('vehicles') is not None:
                yield from self._parse_ajax(response, res)
                return

        # v4 listing HTML only; skip legacy POST failures and bad redirects.
        if response.meta.get('legacy_ajax') or 'inventory/' not in response.url:
            return

        yield from self._parse_inventory_html(response)

    def _parse_inventory_html(self, response):
        # v4 cards expose VIN/slug on the listing row; VDP is /inventory/{slug}/.
        seen_ids = set()

        for card in response.css('[data-inventoryitemid]'):
            item_id = card.attrib.get('data-inventoryitemid')
            slug = card.attrib.get('data-slug')
            vin = card.attrib.get('data-vin')
            if not item_id or not slug or not vin or item_id in seen_ids:
                continue
            seen_ids.add(item_id)

            category = (
                card.attrib.get('data-state-of-vehicle')
                or card.attrib.get('data-conditionName')
                or self._listing_category(response)
            )

            loader = ItemLoader(ScrapebucketItem())
            loader.add_value('category', category)
            loader.add_value('year', card.attrib.get('data-year'))
            loader.add_value('make', card.attrib.get('data-make'))
            loader.add_value('model', card.attrib.get('data-model'))
            loader.add_value('trim', card.attrib.get('data-trim'))
            loader.add_value('stock_number', card.attrib.get('data-stocknumber'))
            loader.add_value('vin', vin)
            loader.add_value('vehicle_url', response.urljoin(f'/inventory/{slug}/'))
            loader.add_value('price', card.attrib.get('data-price'))
            loader.add_value('domain', self.domain_name)
            yield loader.load_item()

        # Follow page-next only (one page at a time) to avoid Cloudflare 403s.
        next_href = response.css('nav.pagination-base li.page-next a::attr(href)').get()
        if next_href:
            yield response.follow(
                next_href,
                callback=self.parse,
                headers=self._browser_headers(referer=response.url),
            )

    def _parse_ajax(self, response, res):
        # Original spider logic: parse vehicleCellHTML fragments from AJAX JSON.
        items = res.get('vehicles') or []

        for item in items:
            cell_html = item.get('vehicleCellHTML')
            if not cell_html:
                continue

            html = Selector(text=cell_html)

            vin1 = html.xpath('//input/@value').get()
            vin2 = html.xpath(
                '//div[@class="vehicle-information-grid"]/following-sibling::input/@value'
            ).get()

            vdp_url1 = html.xpath(
                '//div[contains(@class,"vehicle-list-cell")]/@itemid'
            ).get()
            vdp_url2 = html.xpath(
                '//p[@class="vehicle-year-make-model"]/a/@href'
            ).get()

            vin = vin1 if vin1 else vin2
            vdp_url = vdp_url1 if vdp_url1 else vdp_url2

            loader = ItemLoader(ScrapebucketItem(), selector=html)
            if vdp_url and len(vdp_url) > 1:
                loader.add_value('vehicle_url', f'{self.url}{vdp_url[1:]}')
            elif vdp_url:
                loader.add_value('vehicle_url', f'{self.url}{vdp_url}')
            loader.add_value('category', self._listing_category(response))
            loader.add_xpath('year', '//span[contains(@class,"vehicle-year")]/text()')
            loader.add_xpath('make', '//span[contains(@class,"vehicle-make")]/text()')
            loader.add_xpath('model', '//span[contains(@class,"vehicle-model")]/text()')
            loader.add_xpath('trim', '//span[contains(@class,"vehicle-trim")]/text()')
            loader.add_xpath(
                'stock_number',
                '//*[contains(@class,"vehicle-stock")]/text()',
            )
            loader.add_xpath(
                'price',
                '//*[contains(@class,"vehicle-price")]/text()'
                ' | //*[contains(@class,"internet-price")]/text()',
            )
            loader.add_value('vin', vin)
            loader.add_value('domain', self.domain_name)

            yield loader.load_item()

        has_next_page = res.get('nextURL')

        if has_next_page:
            headers = {
                'Accept': '*/*',
                'Accept-Encoding': 'gzip, deflate, br',
                'Accept-Language': 'en-US,en;q=0.5',
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'Origin': f'{self.url}',
                'Referer': f'{self.url}{has_next_page}',
                'Sec-Ch-ua': '"Google Chrome";v="111", "Not(A:Brand";v="8", "Chromium";v="111"',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Site': 'same-origin',
                'user-agent': self._USER_AGENT,
                'X-Requested-With': 'XMLHttpRequest',
            }
            yield scrapy.FormRequest(
                url=f'{self.url}{has_next_page}',
                method='POST',
                headers=headers,
                formdata={
                    'ajax': 'true',
                    'refresh': 'true',
                },
                callback=self.parse,
                meta={'legacy_ajax': True},
            )

    @staticmethod
    def _listing_category(response):
        url = response.url.lower()
        if '/used' in url or 'inventory/used' in url:
            return 'used'
        if '/new' in url or 'inventory/new' in url:
            return 'new'
        return ''
