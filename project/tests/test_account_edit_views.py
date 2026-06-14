"""Tests for in-app account edit (AccountUpdateView).

Covers staff gate, form save, target-site provider sync, and AIM vs local
read-only labels on account_form.html (is_aim_synced / aim_last_synced_at).
"""

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from project.models import Account, TargetSite, Webprovider


class AccountUpdateViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.staff = User.objects.create_user(
            username='staff_editor',
            password='test-pass',
            is_staff=True,
        )
        self.regular = User.objects.create_user(
            username='regular_editor',
            password='test-pass',
        )
        self.provider = Webprovider.objects.create(name='edealer')
        self.account = Account.objects.create(
            account_id=88001,
            account_name='Edit Test Dealer',
            account_status='ACTIVE',
            city='Toronto',
            province='ON',
            account_manager='Old Manager',
            site_url='https://old.example.com',
            web_provider=self.provider,
        )
        self.url = reverse('account-edit', kwargs={'account_id': self.account.account_id})

    def test_anonymous_user_redirected_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.url)

    def test_non_staff_user_gets_forbidden(self):
        self.client.force_login(self.regular)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_staff_user_sees_edit_form(self):
        self.client.force_login(self.staff)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('Edit Account', content)
        self.assertIn('Edit Test Dealer', content)
        self.assertIn('Account details', content)
        self.assertIn('added locally', content)
        self.assertNotIn('From AIM sync', content)
        self.assertIn('Editable fields', content)
        self.assertIn('Save account', content)

    def test_staff_sees_aim_sync_section_for_synced_account(self):
        from django.utils import timezone

        self.account.aim_last_synced_at = timezone.now()
        self.account.save(update_fields=['aim_last_synced_at'])
        self.client.force_login(self.staff)
        response = self.client.get(self.url)

        content = response.content.decode()
        self.assertIn('From AIM sync', content)
        self.assertIn('Last synced', content)
        self.assertNotIn('added locally', content)

    def test_staff_can_update_account_and_redirects_to_accounts(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            self.url,
            {
                'web_provider': self.provider.pk,
                'account_manager': 'New Manager',
                'site_url': 'https://new.example.com',
                'note': 'Updated via in-app form',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('accounts'))

        self.account.refresh_from_db()
        self.assertEqual(self.account.account_manager, 'New Manager')
        self.assertEqual(self.account.site_url, 'https://new.example.com')
        self.assertEqual(self.account.note, 'Updated via in-app form')
        self.assertEqual(self.account.modified_by, self.staff)

    def test_update_syncs_linked_target_site_web_provider(self):
        TargetSite.objects.create(
            site_id='edit-test.example.com',
            site_name=self.account,
            site_url='https://old.example.com',
            web_provider='legacy',
            spider='legacy',
            condition=False,
            unit=False,
            year=False,
            make=False,
            model=False,
            trim=False,
            stock_number=False,
            vin=False,
            vehicle_url=False,
            msrp=False,
            price=False,
            selling_price=False,
            rebate=False,
            discount=False,
            images=False,
            images_count=False,
        )
        new_provider = Webprovider.objects.create(name='omni')

        self.client.force_login(self.staff)
        self.client.post(
            self.url,
            {
                'web_provider': new_provider.pk,
                'account_manager': '',
                'site_url': '',
                'note': '',
            },
        )

        site = TargetSite.objects.get(site_id='edit-test.example.com')
        self.assertEqual(site.web_provider, 'omni')
        self.assertEqual(site.spider, 'omni_auto')

    def test_unknown_account_returns_404(self):
        self.client.force_login(self.staff)
        url = reverse('account-edit', kwargs={'account_id': 99999999})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)
