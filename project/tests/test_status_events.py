"""Tests for TargetSiteStatusEvent logging, backfill, and UI helpers."""

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from project.models import Account, Project, TargetSite, TargetSiteStatusEvent
from project.templatetags.custom_filters import (
    status_event_source_label,
    target_site_status_tooltip,
)


def _make_account(**overrides):
    defaults = {
        'account_id': 27510,
        'account_status': 'ACTIVE',
        'account_name': 'Status Event Dealer',
    }
    defaults.update(overrides)
    return Account.objects.create(**defaults)


def _make_target_site(account, **overrides):
    defaults = {
        'site_id': 'status-event.example.com',
        'status': 'Active',
        'entry_code': 'AVAIM-900',
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
        'site_name': account,
    }
    defaults.update(overrides)
    return TargetSite.objects.create(**defaults)


class TargetSiteStatusEventModelTests(TestCase):
    def setUp(self):
        self.account = _make_account()
        self.site = _make_target_site(self.account)

    def test_manual_status_change_creates_event(self):
        user = User.objects.create_user(username='editor', password='pass')
        self.site.updated_by = user
        self.site.status = 'Inactive'
        self.site.save()

        event = self.site.status_events.get()
        self.assertEqual(event.from_status, 'Active')
        self.assertEqual(event.to_status, 'Inactive')
        self.assertEqual(event.source, 'manual')
        self.assertEqual(event.actor, user)

    def test_account_sync_creates_event(self):
        self.account.account_status = 'DELETED'
        self.account.save()

        event = self.site.status_events.get()
        self.assertEqual(event.from_status, 'Active')
        self.assertEqual(event.to_status, 'Inactive')
        self.assertEqual(event.source, 'account_sync')
        self.assertEqual(event.detail, 'AIM account → DELETED')
        self.assertIsNone(event.actor)

    def test_account_reactivate_creates_event(self):
        self.account.account_status = 'INACTIVE'
        self.account.save()
        self.site.status_events.all().delete()

        self.account.account_status = 'ACTIVE'
        self.account.save()

        event = self.site.status_events.get()
        self.assertEqual(event.to_status, 'Active')
        self.assertEqual(event.source, 'account_reactivate')

    def test_already_inactive_site_skips_account_sync_event(self):
        self.site.status = 'Inactive'
        self.site.save(update_fields=['status'])
        TargetSiteStatusEvent.objects.all().delete()

        self.account.account_status = 'DELETED'
        self.account.save()

        self.assertEqual(self.site.status_events.count(), 0)

    def test_no_event_when_status_unchanged(self):
        self.site.web_provider = 'edealer'
        self.site.save(update_fields=['web_provider'])
        self.assertEqual(self.site.status_events.count(), 0)


class StatusEventTemplateFilterTests(TestCase):
    def test_status_event_source_label(self):
        self.assertEqual(status_event_source_label('account_sync'), 'AIM sync')

    def test_inactive_tooltip_uses_latest_event(self):
        account = _make_account(account_id=27511, account_name='Tooltip Dealer')
        site = _make_target_site(account, site_id='tooltip.example.com')
        site.status = 'Inactive'
        site.latest_status_event_source = 'account_sync'
        site.latest_status_event_detail = 'AIM account → DELETED'
        self.assertIn('AIM sync', target_site_status_tooltip(site))


class SiteListRecentDeactivationsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='viewer', password='pass')
        self.project = Project.objects.create(name='av-aim', color='brand', sort_order=0)
        self.account = _make_account()
        self.site = _make_target_site(self.account, project=self.project)

    def test_recent_deactivations_panel_on_list_page(self):
        self.account.account_status = 'DELETED'
        self.account.save()

        self.client.force_login(self.user)
        response = self.client.get(
            reverse('site-list', kwargs={'project_name': self.project.name})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Recent deactivations')
        self.assertContains(response, self.site.entry_code)
        self.assertContains(response, 'AIM sync')

    def test_detail_page_shows_status_history(self):
        self.account.account_status = 'INACTIVE'
        self.account.save()

        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                'site-detail',
                kwargs={
                    'project_name': self.project.name,
                    'pk': self.site.pk,
                },
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Status history')
        self.assertContains(response, 'Active → Inactive')


class _MigrationApps:
    """Pass real models into RunPython backfill during tests (migration module name is numeric)."""

    def get_model(self, app_label, model_name):
        from django.apps import apps

        return apps.get_model(app_label, model_name)


class BackfillMigrationLogicTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name='av-aim', color='brand', sort_order=0)

    def _run_backfill(self):
        import importlib

        module = importlib.import_module(
            'project.migrations.0016_backfill_target_site_status_events'
        )
        module.backfill_target_site_status_events(_MigrationApps(), None)

    def test_deleted_account_site_gets_account_sync_backfill(self):
        account = _make_account(account_id=27600, account_status='DELETED')
        site = _make_target_site(
            account,
            project=self.project,
            site_id='backfill-deleted.example.com',
            status='Inactive',
        )
        self.assertEqual(site.status_events.count(), 0)

        self._run_backfill()

        event = site.status_events.get()
        self.assertEqual(event.source, 'account_sync')
        self.assertIn('DELETED', event.detail)
        self.assertEqual(event.to_status, 'Inactive')

    def test_manual_inactive_on_active_account_gets_manual_backfill(self):
        account = _make_account(account_id=27601, account_status='ACTIVE')
        site = _make_target_site(
            account,
            project=self.project,
            site_id='backfill-manual.example.com',
            status='Inactive',
        )

        self._run_backfill()

        event = site.status_events.get()
        self.assertEqual(event.source, 'manual')
        self.assertIn('manually', event.detail)

    def test_backfill_skips_sites_with_existing_events(self):
        account = _make_account(account_id=27602, account_status='DELETED')
        site = _make_target_site(
            account,
            project=self.project,
            site_id='backfill-skip.example.com',
            status='Inactive',
        )
        TargetSiteStatusEvent.objects.create(
            target_site=site,
            from_status='Active',
            to_status='Inactive',
            source='account_sync',
            detail='Already logged',
        )

        self._run_backfill()

        self.assertEqual(site.status_events.count(), 1)
