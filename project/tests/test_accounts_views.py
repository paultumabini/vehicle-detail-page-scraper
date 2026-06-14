"""
Tests for Accounts list view and htmx clear-new row action (Guides 03–04).
"""

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from project.models import Account, AccountSyncState, Project, TargetSite
from project.tests.test_target_sites import _make_target_site


class AccountsViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='account_tester', password='test-pass'
        )
        self.account = Account.objects.create(
            account_id=99001,
            account_name='HTMX Test Account',
            account_status='ACTIVE',
            city='Toronto',
            province='ON',
            is_new_account=True,
        )

    def test_anonymous_user_redirected_to_login(self):
        response = self.client.get(reverse('accounts'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.url)

    def test_authenticated_user_sees_accounts_table(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('accounts'))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('accounts-table', content)
        self.assertIn('/accounts/datatable/', content)
        self.assertIn('vdp_client_table.js', content)
        self.assertIn('htmx.org', content)
        self.assertIn('X-CSRFToken', content)

    def test_accounts_page_shows_aim_sync_banner(self):
        synced_at = timezone.make_aware(
            timezone.datetime(2026, 6, 13, 20, 35, 0),
            timezone.get_default_timezone(),
        )
        AccountSyncState.record_sync(
            synced_at=synced_at,
            accounts_created=3,
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse('accounts'))

        content = response.content.decode()
        self.assertIn('AV AIM last synced:', content)
        self.assertIn('2026-06-13 16:35', content)
        self.assertIn('(EDT)', content)
        self.assertIn('New account added: 3', content)

    def test_datatable_json_returns_account_row(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('accounts-datatable'),
            {'draw': 1, 'start': 0, 'length': 10},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['recordsTotal'], 1)
        self.assertEqual(payload['recordsFiltered'], 1)
        self.assertEqual(len(payload['data']), 1)
        self.assertIn('HTMX Test Account', payload['data'][0][1])

    def test_datatable_json_new_filter_on_account_name_column(self):
        Account.objects.create(
            account_id=99004,
            account_name='Old Account',
            account_status='ACTIVE',
            is_new_account=False,
        )
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('accounts-datatable'),
            {
                'draw': 1,
                'start': 0,
                'length': 10,
                'columns[1][search][value]': 'new',
            },
        )

        payload = response.json()
        self.assertEqual(payload['recordsFiltered'], 1)
        self.assertIn('HTMX Test Account', payload['data'][0][1])
        self.assertIn('badge-new', payload['data'][0][1])

    def test_datatable_json_account_filter(self):
        Account.objects.create(
            account_id=99003,
            account_name='Inactive Account',
            account_status='INACTIVE',
        )
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('accounts-datatable'),
            {
                'draw': 1,
                'start': 0,
                'length': 10,
                'columns[3][search][value]': 'INACTIVE',
            },
        )

        payload = response.json()
        self.assertEqual(payload['recordsFiltered'], 1)
        self.assertIn('Inactive Account', payload['data'][0][1])

    def test_datatable_json_setup_filter_not_configured(self):
        # Flat ?setup= param — mirrors dashboard Need Setup → accounts deep link.
        configured = Account.objects.create(
            account_id=99005,
            account_name='Configured Dealer',
            account_status='ACTIVE',
        )
        project = Project.objects.create(name='av-aim', color='brand', sort_order=0)
        _make_target_site(
            project=project,
            site_id='configured-dealer',
            site_name=configured,
            site_url='https://configured.example/',
            web_provider='DealerOn',
        )
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('accounts-datatable'),
            {
                'draw': 1,
                'start': 0,
                'length': 10,
                'columns[3][search][value]': 'ACTIVE',
                'setup': 'not-configured',
            },
        )

        payload = response.json()
        self.assertEqual(payload['recordsFiltered'], 1)
        self.assertIn('HTMX Test Account', payload['data'][0][1])
        self.assertIn('Not set up', payload['data'][0][4])
        self.assertNotIn('Configured Dealer', str(payload['data']))

    def test_datatable_json_setup_filter_configured(self):
        # Exists-based filter — only dealers with a linked TargetSite row.
        configured = Account.objects.create(
            account_id=99006,
            account_name='Configured Dealer',
            account_status='ACTIVE',
        )
        project = Project.objects.create(name='av-aim', color='brand', sort_order=0)
        _make_target_site(
            project=project,
            site_id='configured-dealer-2',
            site_name=configured,
            site_url='https://configured.example/',
            web_provider='DealerOn',
        )
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('accounts-datatable'),
            {
                'draw': 1,
                'start': 0,
                'length': 10,
                'columns[3][search][value]': 'ACTIVE',
                'setup': 'configured',
            },
        )

        payload = response.json()
        self.assertEqual(payload['recordsFiltered'], 1)
        self.assertIn('Configured Dealer', payload['data'][0][1])
        self.assertIn('vdp-scrape-yes', payload['data'][0][4])

    def test_accounts_deep_link_setup_query_preselects_filter(self):
        # SSR half of deep link — JS syncFiltersFromUI() must match on first datatable fetch.
        self.client.force_login(self.user)
        response = self.client.get(reverse('accounts'), {'setup': 'not-configured'})

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('value="not-configured" selected', content)
        self.assertContains(response, 'Need setup')

    def test_datatable_json_staff_sees_edit_account_link(self):
        self.user.is_staff = True
        self.user.save(update_fields=['is_staff'])
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('accounts-datatable'),
            {'draw': 1, 'start': 0, 'length': 10},
        )

        actions_cell = response.json()['data'][0][9]
        self.assertIn('vdp-table-action--edit', actions_cell)
        self.assertIn('/accounts/99001/edit/', actions_cell)

    def test_datatable_json_non_staff_has_no_edit_account_link(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('accounts-datatable'),
            {'draw': 1, 'start': 0, 'length': 10},
        )

        actions_cell = response.json()['data'][0][9]
        self.assertNotIn('vdp-table-action--edit', actions_cell)
        self.assertNotIn('/accounts/99001/edit/', actions_cell)

    def test_datatable_json_without_scrape_has_no_view_target_site_link(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('accounts-datatable'),
            {'draw': 1, 'start': 0, 'length': 10},
        )

        actions_cell = response.json()['data'][0][9]
        self.assertNotIn('vdp-table-action--view', actions_cell)
        self.assertIn('vdp-table-action--add', actions_cell)

    def test_datatable_json_with_scrape_links_to_site_detail(self):
        project = Project.objects.create(name='av-aim', color='brand', sort_order=0)
        _make_target_site(
            project=project,
            site_id='taylorcadillac',
            site_name=self.account,
            site_url='https://taylorcadillac.example/',
            web_provider='DealerOn',
        )
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('accounts-datatable'),
            {'draw': 1, 'start': 0, 'length': 10},
        )

        actions_cell = response.json()['data'][0][9]
        self.assertIn('vdp-table-action--view', actions_cell)
        self.assertIn('/project/av-aim/taylorcadillac/', actions_cell)
        self.assertNotIn('vdp-table-action--add', actions_cell)


class AccountClearNewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='clear_new_tester', password='test-pass'
        )
        self.account = Account.objects.create(
            account_id=99002,
            account_name='Clear New Account',
            account_status='ACTIVE',
            is_new_account=True,
        )
        self.url = reverse(
            'account-clear-new', kwargs={'account_id': self.account.account_id}
        )

    def test_get_request_not_allowed(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)

    def test_anonymous_post_redirected_to_login(self):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.url)

    def test_post_clears_is_new_account_and_returns_row_fragment(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('<tr', content)
        self.assertIn(f'account-row-{self.account.account_id}', content)
        self.assertNotIn('badge-new', content)
        self.assertNotIn('hx-confirm', content)

        self.account.refresh_from_db()
        self.assertFalse(self.account.is_new_account)

    def test_post_for_unknown_account_returns_404(self):
        self.client.force_login(self.user)
        url = reverse('account-clear-new', kwargs={'account_id': 99999999})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)
