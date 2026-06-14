from django.test import SimpleTestCase

from project.models import TargetSite
from project.spider_provider import (
    spider_for_web_provider,
    sync_target_site_web_provider,
)


class SpiderProviderTests(SimpleTestCase):
    def test_omni_maps_to_omni_auto(self):
        self.assertEqual(spider_for_web_provider('omni'), 'omni_auto')
        self.assertEqual(spider_for_web_provider('Omni'), 'omni_auto')

    def test_direct_provider_uses_same_spider_name(self):
        self.assertEqual(spider_for_web_provider('edealer'), 'edealer')

    def test_unknown_provider_returns_none(self):
        self.assertIsNone(spider_for_web_provider('not-a-real-platform'))

    def test_sync_preserves_spider_when_provider_unchanged(self):
        site = TargetSite(site_id='example', web_provider='omni', spider='omni_auto')
        sync_target_site_web_provider(site, 'omni')
        self.assertEqual(site.spider, 'omni_auto')

    def test_sync_sets_spider_when_provider_changes(self):
        site = TargetSite(site_id='example', web_provider='d2cmedia', spider='nabthat')
        sync_target_site_web_provider(site, 'edealer')
        self.assertEqual(site.web_provider, 'edealer')
        self.assertEqual(site.spider, 'edealer')

    def test_sync_sets_mapped_spider_for_new_site(self):
        site = TargetSite(site_id='example', web_provider='omni', spider=None)
        sync_target_site_web_provider(site, 'omni')
        self.assertEqual(site.spider, 'omni_auto')
