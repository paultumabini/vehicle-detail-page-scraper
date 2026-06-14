"""Tests for TargetSite entry code helpers and generation."""

from types import SimpleNamespace

from django.test import TestCase

from project.models import Account, Project, TargetSite
from project.utils import (
    ScrapeEntryCode,
    entry_code_prefix,
    format_entry_code,
    parse_entry_code_number,
)


class EntryCodeHelperTests(TestCase):
    def test_entry_code_prefix_strips_non_letters(self):
        self.assertEqual(entry_code_prefix('av-aim'), 'AVAIM')
        self.assertEqual(entry_code_prefix('vdp-urls'), 'VDPUR')

    def test_parse_entry_code_number(self):
        self.assertEqual(parse_entry_code_number('AVAIM-001'), 1)
        self.assertEqual(parse_entry_code_number('AVAIM-244'), 244)
        self.assertEqual(parse_entry_code_number('AVAIM-245'), 245)
        self.assertIsNone(parse_entry_code_number(''))
        self.assertIsNone(parse_entry_code_number('AIM001'))

    def test_format_entry_code(self):
        self.assertEqual(format_entry_code('av-aim', 1), 'AVAIM-001')
        self.assertEqual(format_entry_code('av-aim', 244), 'AVAIM-244')
        self.assertEqual(format_entry_code('av-aim', 245), 'AVAIM-245')


class ScrapeEntryCodeGenerationTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name='av-aim', color='brand', sort_order=0)
        self.account = Account.objects.create(
            account_id=99001,
            account_name='Entry Code Dealer',
            account_status='ACTIVE',
        )
        self.generator = ScrapeEntryCode()

    def _target_site_form(self, project=None):
        return SimpleNamespace(instance=SimpleNamespace(project=project or self.project))

    def _create_site(self, entry_code, site_id):
        return TargetSite.objects.create(
            project=self.project,
            site_id=site_id,
            site_name=self.account,
            entry_code=entry_code,
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

    def test_first_entry_code_for_project(self):
        code = self.generator.get_scrape_entry_code(self._target_site_form())
        self.assertEqual(code, 'AVAIM-001')

    def test_next_entry_code_increments_from_highest_existing(self):
        self._create_site('AVAIM-001', 'dealer-a.com')
        self._create_site('AVAIM-244', 'dealer-b.com')
        self._create_site('AVAIM-245', 'dealer-c.com')

        code = self.generator.get_scrape_entry_code(self._target_site_form())
        self.assertEqual(code, 'AVAIM-246')
