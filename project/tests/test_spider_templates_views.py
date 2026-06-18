"""Tests for /spider-templates/ list (dashboard KPI deep links)."""

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from project.models import Account, Project, TargetSite
from project.tests.test_target_sites import _make_target_site


class SpiderTemplatesViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='spider_list_user',
            password='test-pass',
        )
        self.account = Account.objects.create(
            account_id=77001,
            account_name='Spider List Dealer',
            account_status='ACTIVE',
        )
        self.project = Project.objects.create(name='av-aim', color='brand', sort_order=0)
        _make_target_site(
            project=self.project,
            site_id='spider-list.example.com',
            site_name=self.account,
            site_url='https://spider-list.example.com/',
            web_provider='edealer',
            spider='edealer',
            status='Active',
        )

    def test_anonymous_user_redirected_to_login(self):
        response = self.client.get(reverse('spider-templates'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.url)

    def test_default_view_is_registered(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('spider-templates'))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('All registered', content)
        self.assertIn('value="registered" selected', content)

    def test_in_use_view_lists_assigned_spider(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('spider-templates'), {'view': 'in-use'})

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('edealer', content)
        self.assertIn('Templates in use', content)

    def test_registered_view_includes_registered_spiders(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('spider-templates'), {'view': 'registered'})

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('edealer', content)
        self.assertIn('All registered', content)
        self.assertIn('In use', content)

    def test_home_kpi_links_to_spider_templates(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('home'))

        content = response.content.decode()
        self.assertIn('/spider-templates/', content)
        self.assertNotIn('/spider-templates/?view=', content)
