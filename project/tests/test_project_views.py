"""Tests for frontend Add Project flow (ProjectCreateView)."""

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from project.models import Project


class ProjectCreateViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.url = reverse('new-project')
        self.staff = User.objects.create_user(
            username='staff_user',
            password='test-pass',
            is_staff=True,
        )
        self.regular = User.objects.create_user(
            username='regular_user',
            password='test-pass',
        )

    def test_anonymous_user_redirected_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.url)

    def test_non_staff_user_gets_forbidden(self):
        self.client.force_login(self.regular)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_staff_user_sees_form(self):
        self.client.force_login(self.staff)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('Add Project', content)
        self.assertIn('Project slug', content)
        self.assertIn('vdp-color-picker', content)
        self.assertIn('vdp-color-swatch--brand', content)

    def test_staff_can_create_project_and_redirects_to_site_list(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            self.url,
            {
                'name': 'fleet-sites',
                'color': 'emerald',
                'sort_order': '',
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('site-list', kwargs={'project_name': 'fleet-sites'}))

        project = Project.objects.get(name='fleet-sites')
        self.assertEqual(project.color, 'emerald')
        self.assertGreaterEqual(project.sort_order, 0)

    def test_duplicate_slug_rejected(self):
        Project.objects.create(name='av-aim', color='brand', sort_order=0)
        self.client.force_login(self.staff)
        response = self.client.post(
            self.url,
            {'name': 'av-aim', 'color': 'sky', 'sort_order': '5'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already exists')
