from urllib.parse import urlparse

import scrapy
from scrapy.loader import ItemLoader
from scrapy.selector import Selector

from .base_spider import ScrapebucketSpider
from ..items import ScrapebucketItem
from ..spider_helpers.response_json import loads_response_body


class EdealerSpider(ScrapebucketSpider):
    """Scrape eDealer inventory listings.

    Supports three listing modes, detected per site from the first response:
    - Legacy AJAX: POST ``/{new,used}/`` returns JSON with ``vehicleCellHTML``.
    - v4 paginated: ``body[data-pagination="paginated"]`` with page-next links.
    - v4 infinite: ``body[data-pagination="infinite"]`` loads pages via admin-ajax.

    v4 listing HTML is fetched via ``wp-admin/admin-ajax.php`` (``vlp_dynamic_query``).
    Cloudflare challenges direct GETs to ``/inventory/*`` but leaves admin-ajax open.
    """

    name = 'edealer'
    domain_name = ''

    _USER_AGENT = (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
    )

    def _ajax_headers(self, referer):
        return {
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.5',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'Origin': f'{self.url}',
            'Referer': referer,
            'User-Agent': self._USER_AGENT,
            'X-Requested-With': 'XMLHttpRequest',
        }

    def start_requests(self):
        self.domain_name = '.'.join(urlparse(self.url).netloc.split('.')[-2:]).replace(
            '-', ''
        )

        # eDealer v4: load listing HTML via admin-ajax (bypasses Cloudflare on /inventory/*).
        for path in ('inventory/new/', 'inventory/used/'):
            referer = f'{self.url.rstrip("/")}/{path}'
            yield self._admin_ajax_request(
                listing_path=path,
                page=1,
                listing_ctx={
                    'listing_path': path,
                    'category': self._listing_category_from_path(path),
                    'referer': referer,
                    'seen_ids': (),
                    'page': 1,
                },
            )

        headers = self._ajax_headers(f'{self.url}new/')

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

    def _admin_ajax_request(self, listing_path, page, listing_ctx):
        ajax_url = f'{self.url.rstrip("/")}/wp-admin/admin-ajax.php'
        if page > 1:
            ajax_url = f'{ajax_url}?page={page}'
        return scrapy.FormRequest(
            url=ajax_url,
            method='POST',
            headers=self._ajax_headers(listing_ctx['referer']),
            formdata={
                'action': 'vlp_dynamic_query',
                'current_path': listing_path,
            },
            callback=self.parse,
            meta=self._listing_meta(
                listing_ctx,
                v4_ajax=True,
                v4_page=page,
            ),
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

        if response.meta.get('v4_ajax'):
            yield from self._parse_inventory_html(response)
            return

        # v4 listing HTML from direct GET (non-Cloudflare sites); skip legacy POST noise.
        if response.meta.get('legacy_ajax') or 'inventory/' not in response.url:
            return

        yield from self._parse_inventory_html(response)

    def _parse_inventory_html(self, response):
        # v4 cards expose VIN/slug on the listing row; VDP is /inventory/{slug}/.
        listing_ctx = self._listing_context(response)
        seen_ids = set(listing_ctx['seen_ids'])
        items_this_page = 0

        for card in response.css('[data-inventoryitemid]'):
            item_id = card.attrib.get('data-inventoryitemid')
            slug = card.attrib.get('data-slug')
            vin = card.attrib.get('data-vin')
            if not item_id or not slug or not vin or item_id in seen_ids:
                continue
            seen_ids.add(item_id)

            item_category = (
                card.attrib.get('data-state-of-vehicle')
                or card.attrib.get('data-conditionName')
                or listing_ctx['category']
            )

            loader = ItemLoader(ScrapebucketItem())
            loader.add_value('category', item_category)
            loader.add_value('year', card.attrib.get('data-year'))
            loader.add_value('make', card.attrib.get('data-make'))
            loader.add_value('model', card.attrib.get('data-model'))
            loader.add_value('trim', card.attrib.get('data-trim'))
            loader.add_value('stock_number', card.attrib.get('data-stocknumber'))
            loader.add_value('vin', vin)
            loader.add_value('vehicle_url', response.urljoin(f'/inventory/{slug}/'))
            loader.add_value('price', card.attrib.get('data-price'))
            loader.add_value('domain', self.domain_name)
            items_this_page += 1
            yield loader.load_item()

        listing_ctx['seen_ids'] = tuple(seen_ids)
        yield from self._follow_v4_pagination(response, listing_ctx, items_this_page)

    def _listing_context(self, response):
        listing_path = response.meta.get('listing_path')
        if not listing_path and 'inventory/' in response.url:
            listing_path = urlparse(response.url).path
            if not listing_path.endswith('/'):
                listing_path = f'{listing_path}/'

        referer = response.meta.get('listing_referer')
        if not referer and listing_path:
            referer = f'{self.url.rstrip("/")}{listing_path}'

        return {
            'listing_path': listing_path,
            'category': response.meta.get('category') or self._listing_category(response),
            'referer': referer,
            'seen_ids': response.meta.get('seen_ids') or (),
            'page': response.meta.get('v4_page', 1),
        }

    def _listing_meta(self, listing_ctx, **extra):
        meta = {
            'listing_path': listing_ctx['listing_path'],
            'category': listing_ctx['category'],
            'listing_referer': listing_ctx['referer'],
            'seen_ids': listing_ctx['seen_ids'],
        }
        meta.update(extra)
        return meta

    def _follow_v4_pagination(self, response, listing_ctx, items_this_page):
        if not items_this_page:
            return

        listing_path = listing_ctx['listing_path']
        if not listing_path:
            return

        # admin-ajax ?page=N works for both infinite-scroll and paginated v4 sites.
        if response.meta.get('v4_ajax'):
            yield self._admin_ajax_request(
                listing_path=listing_path,
                page=listing_ctx['page'] + 1,
                listing_ctx=listing_ctx,
            )
            return

        # Non-Cloudflare sites may still serve full HTML pages with link pagination.
        next_href = response.css('nav.pagination-base li.page-next a::attr(href)').get()
        if next_href:
            yield scrapy.Request(
                response.urljoin(next_href),
                callback=self.parse,
                headers={
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                    'User-Agent': self._USER_AGENT,
                    'Referer': response.url,
                },
                meta=self._listing_meta(listing_ctx),
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
            yield scrapy.FormRequest(
                url=f'{self.url}{has_next_page}',
                method='POST',
                headers=self._ajax_headers(f'{self.url}{has_next_page}'),
                formdata={
                    'ajax': 'true',
                    'refresh': 'true',
                },
                callback=self.parse,
                meta={'legacy_ajax': True},
            )

    @staticmethod
    def _listing_category_from_path(path):
        path = path.lower()
        if 'used' in path:
            return 'used'
        if 'new' in path:
            return 'new'
        return ''

    @staticmethod
    def _listing_category(response):
        url = response.url.lower()
        listing_path = (response.meta.get('listing_path') or '').lower()
        for candidate in (listing_path, url):
            if '/used' in candidate or 'inventory/used' in candidate:
                return 'used'
            if '/new' in candidate or 'inventory/new' in candidate:
                return 'new'
        return ''
