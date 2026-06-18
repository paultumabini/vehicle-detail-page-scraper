"""Tests for Target Sites list (SiteListView) and last-run template filter.

Table layout (8 columns): Entry#, Status dot, Site Name, Provider,
Items Scraped, Last Run, Exported icon, Actions. Site URL / Owner / Create Date
are intentionally absent from the list template.
"""

from datetime import datetime
from types import SimpleNamespace

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from project.models import Account, Project, Scrape, SpiderLog, TargetSite
from project.templatetags.custom_filters import target_site_last_run


def _make_target_site(**overrides):
    """Minimal TargetSite factory — boolean scrape fields default to False."""
    defaults = {
        'site_id': 'example-dealer.com',
        'status': 'Active',
        'entry_code': 'AVAIM-001',
        'condition': False,
        'unit': False,
        'year': False,
        'make': False,
        'model': False,
        'trim': False,
        'stock_number': False,
        'vin': False,
        'vehicle_url': False,
        'msrp': False,
        'price': False,
        'selling_price': False,
        'rebate': False,
        'discount': False,
        'images': False,
        'images_count': False,
    }
    defaults.update(overrides)
    return TargetSite.objects.create(**defaults)


class TargetSiteLastRunFilterTests(TestCase):
    """Last Run shows latest log/scrape time, not live crawl state (no "running…")."""

    def test_pending_without_history_returns_em_dash(self):
        site = SimpleNamespace(status='Pending')
        self.assertEqual(target_site_last_run(site), '—')

    def test_inactive_without_history_returns_em_dash(self):
        site = SimpleNamespace(status='Inactive')
        self.assertEqual(target_site_last_run(site), '—')

    def test_pending_with_history_shows_timestamp(self):
        day = datetime(2026, 6, 13, 14, 30, 0)
        site = SimpleNamespace(
            status='Pending',
            latest_log_created=day,
            latest_scrape_checked=None,
        )
        self.assertEqual(target_site_last_run(site), '2026-06-13 14:30:00')

    def test_naive_matching_dates_formats_without_localtime(self):
        day = datetime(2026, 6, 13, 14, 30, 0)
        site = SimpleNamespace(
            status='Active',
            latest_log_created=day,
            latest_scrape_checked=day,
        )
        self.assertEqual(target_site_last_run(site), '2026-06-13 14:30:00')

    def test_aware_matching_dates_converts_to_local(self):
        utc = timezone.make_aware(datetime(2026, 6, 13, 18, 30, 0), timezone.UTC)
        site = SimpleNamespace(
            status='Active',
            latest_log_created=utc,
            latest_scrape_checked=utc,
        )
        result = target_site_last_run(site)
        self.assertRegex(result, r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$')

    def test_mismatched_dates_shows_most_recent(self):
        # Previously showed "running…" when log/scrape fell on different days.
        site = SimpleNamespace(
            status='Active',
            latest_log_created=datetime(2026, 6, 12, 10, 0, 0),
            latest_scrape_checked=datetime(2026, 6, 13, 10, 0, 0),
        )
        self.assertEqual(target_site_last_run(site), '2026-06-13 10:00:00')

    def test_log_only_shows_log_timestamp(self):
        site = SimpleNamespace(
            status='Active',
            latest_log_created=datetime(2026, 6, 12, 10, 0, 0),
            latest_scrape_checked=None,
        )
        self.assertEqual(target_site_last_run(site), '2026-06-12 10:00:00')

    def test_no_history_returns_em_dash(self):
        site = SimpleNamespace(
            status='Active',
            latest_log_created=None,
            latest_scrape_checked=None,
        )
        self.assertEqual(target_site_last_run(site), '—')


class SiteListViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='site_tester', password='test-pass'
        )
        self.project = Project.objects.create(
            name='av-aim', color='brand', sort_order=0
        )
        self.account = Account.objects.create(
            account_id=88001,
            account_name='Target Site Dealer',
            account_status='ACTIVE',
        )
        self.site = _make_target_site(
            project=self.project,
            site_name=self.account,
            site_url='https://example-dealer.com',
            web_provider='DealerOn',
            exported_feed='VDP_URLS_example-dealer.com.csv',
        )
        run_time = datetime(2026, 6, 13, 12, 0, 0)
        Scrape.objects.create(
            target_site=self.site, stock_number='STK1', last_checked=run_time
        )
        SpiderLog.objects.create(
            target_site=self.site,
            spider_name='test_spider',
            items_scraped='42',
        )

    def test_anonymous_user_redirected_to_login(self):
        response = self.client.get(
            reverse('site-list', kwargs={'project_name': 'av-aim'}),
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.url)

    def test_authenticated_user_sees_target_sites_table(self):
        """Smoke-test lean column set: dots, scrape stats, exported icon; no removed columns."""
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('site-list', kwargs={'project_name': 'av-aim'}),
        )

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('dealers-list-table', content)
        self.assertIn('Target Site Dealer', content)
        self.assertIn('scrape-status-dot--active', content)
        self.assertIn('42', content)
        self.assertIn('vdp-exported-yes', content)
        self.assertNotIn('<th>Site URL</th>', content)
        self.assertNotIn('<th>Owner</th>', content)
        self.assertNotIn('<th>Create Date</th>', content)
        self.assertNotIn('ValueError', content)

    def test_site_detail_shows_account_id(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                'site-detail',
                kwargs={'project_name': 'av-aim', 'pk': self.site.site_id},
            ),
        )

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('Account ID', content)
        self.assertIn(f'>{self.account.account_id}<', content)
        self.assertIn(self.site.site_id, content)
