"""Tests for New Scrape account pre-fill from ?account= deep link."""

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from project.models import Account, Webprovider
from project.utils import (
    extract_site_id_from_site_url,
    target_site_form_initial_from_account,
)


class ExtractSiteIdFromSiteUrlTests(TestCase):
    def test_strips_scheme_www_and_tld(self):
        self.assertEqual(
            extract_site_id_from_site_url('https://www.palladinomazda.ca/'),
            'palladinomazda',
        )

    def test_handles_compound_tld(self):
        self.assertEqual(
            extract_site_id_from_site_url('https://www.example.com.au/'),
            'example',
        )

    def test_returns_empty_for_blank_input(self):
        self.assertEqual(extract_site_id_from_site_url(''), '')


class TargetSiteFormInitialFromAccountTests(TestCase):
    def setUp(self):
        self.provider = Webprovider.objects.create(name='DealerOn')
        self.account = Account.objects.create(
            account_id=99001,
            account_name='Prefill Dealer',
            account_status='ACTIVE',
            site_url='https://www.prefill-dealer.ca/inventory',
            web_provider=self.provider,
            note='AIM note for operator',
        )

    def test_maps_all_available_account_fields(self):
        initial = target_site_form_initial_from_account(self.account)

        self.assertEqual(initial['site_name'], 99001)
        self.assertEqual(initial['site_url'], 'https://www.prefill-dealer.ca/inventory')
        self.assertEqual(initial['site_id'], 'prefill-dealer')
        self.assertEqual(initial['web_provider'], 'DealerOn')
        self.assertEqual(initial['note'], 'AIM note for operator')

    def test_omits_empty_optional_fields(self):
        bare = Account.objects.create(
            account_id=99002,
            account_name='Bare Dealer',
            account_status='ACTIVE',
        )
        initial = target_site_form_initial_from_account(bare)

        self.assertEqual(initial, {'site_name': 99002})


class SiteCreateViewPrefillTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='scrape_user', password='test-pass')
        self.provider = Webprovider.objects.create(name='edealer')
        self.account = Account.objects.create(
            account_id=99003,
            account_name='Deep Link Dealer',
            account_status='ACTIVE',
            site_url='https://www.deeplink.example.com/',
            web_provider=self.provider,
            note='Carry this note forward',
        )
        self.url = reverse('new-scrape')

    def test_new_scrape_prefills_account_fields_from_query_param(self):
        self.client.force_login(self.user)
        response = self.client.get(f'{self.url}?account={self.account.account_id}')

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('value="99003"', content)
        self.assertIn('https://www.deeplink.example.com/', content)
        self.assertIn('value="deeplink"', content)
        self.assertIn('value="edealer"', content)
        self.assertIn('Carry this note forward', content)
