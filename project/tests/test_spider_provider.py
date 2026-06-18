from django.test import SimpleTestCase

from project.models import TargetSite
from project.spider_provider import (
    spider_for_web_provider,
    sync_target_site_web_provider,
)


class SpiderProviderTests(SimpleTestCase):
    def test_omniauto_resolves_directly(self):
        self.assertEqual(spider_for_web_provider('omniauto'), 'omniauto')
        self.assertEqual(spider_for_web_provider('Omniauto'), 'omniauto')

    def test_direct_provider_uses_same_spider_name(self):
        self.assertEqual(spider_for_web_provider('edealer'), 'edealer')

    def test_unknown_provider_returns_none(self):
        self.assertIsNone(spider_for_web_provider('not-a-real-platform'))

    def test_sync_preserves_spider_when_provider_unchanged(self):
        site = TargetSite(site_id='example', web_provider='omniauto', spider='omniauto')
        sync_target_site_web_provider(site, 'omniauto')
        self.assertEqual(site.spider, 'omniauto')

    def test_sync_sets_spider_when_provider_changes(self):
        site = TargetSite(site_id='example', web_provider='d2cmedia', spider='nabthat')
        sync_target_site_web_provider(site, 'edealer')
        self.assertEqual(site.web_provider, 'edealer')
        self.assertEqual(site.spider, 'edealer')

    def test_sync_sets_spider_for_omniauto_provider(self):
        site = TargetSite(site_id='example', web_provider='omniauto', spider=None)
        sync_target_site_web_provider(site, 'omniauto')
        self.assertEqual(site.spider, 'omniauto')
