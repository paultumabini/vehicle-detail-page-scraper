"""
Tests for AimApiData helpers, render_api_data sync logic, and the
sync_accounts management command.

- ParseInt / ParseBool: pure-function unit tests (no DB).
- RenderApiData: DB integration tests — create vs update, field mapping,
  is_new_account flag, and graceful handling of bad input.
- SyncAimDealersCommand: management command wiring — credentials check,
  --dry-run, and successful end-to-end invocation (API call mocked).
"""

from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

from project.api.aimapi import AimApiData
from project.models import Account, AccountSyncState


# ---------------------------------------------------------------------------
# _parse_int
# ---------------------------------------------------------------------------


class ParseIntTests(SimpleTestCase):
    def test_string_number(self):
        self.assertEqual(AimApiData._parse_int('27505'), 27505)

    def test_real_int(self):
        self.assertEqual(AimApiData._parse_int(80), 80)

    def test_zero_string(self):
        self.assertEqual(AimApiData._parse_int('0'), 0)

    def test_none_returns_none(self):
        self.assertIsNone(AimApiData._parse_int(None))

    def test_non_numeric_string_returns_none(self):
        self.assertIsNone(AimApiData._parse_int('abc'))

    def test_empty_string_returns_none(self):
        self.assertIsNone(AimApiData._parse_int(''))


# ---------------------------------------------------------------------------
# _parse_bool
# ---------------------------------------------------------------------------


class ParseBoolTests(SimpleTestCase):
    def test_string_one_is_true(self):
        self.assertIs(AimApiData._parse_bool('1'), True)

    def test_string_zero_is_false(self):
        self.assertIs(AimApiData._parse_bool('0'), False)

    def test_int_one_is_true(self):
        self.assertIs(AimApiData._parse_bool(1), True)

    def test_int_zero_is_false(self):
        self.assertIs(AimApiData._parse_bool(0), False)

    def test_none_returns_none(self):
        self.assertIsNone(AimApiData._parse_bool(None))

    def test_non_numeric_string_returns_none(self):
        self.assertIsNone(AimApiData._parse_bool('yes'))


# ---------------------------------------------------------------------------
# render_api_data — DB integration
# ---------------------------------------------------------------------------

_SAMPLE_ROW = {
    'id': '27505',
    'account': 'ACTIVE',
    'company_name': 'Grant Miller Motors Ltd.',
    'city': 'Vegreville',
    'province': 'AB',
    'new_active_stats': '80',
    'used_active_stats': '18',
    'new_rebated': '70',
    'lease_count': '0',
    'auto_lease_on': '1',
    'facebook_feed': '1',
    'av_360': '1',
}


class RenderApiDataCreateTests(TestCase):
    """Dealer does not exist locally — should be created."""

    def setUp(self):
        AimApiData.render_api_data([_SAMPLE_ROW])
        self.dealer = Account.objects.get(account_id=27505)

    def test_dealer_is_created(self):
        self.assertEqual(Account.objects.filter(account_id=27505).count(), 1)

    def test_aim_last_synced_at_set_on_sync(self):
        """aim_last_synced_at distinguishes AIM-fed rows from manual admin adds."""
        self.assertIsNotNone(self.dealer.aim_last_synced_at)

    def test_is_new_account_flagged_true(self):
        self.assertTrue(self.dealer.is_new_account)

    def test_account_status_set(self):
        self.assertEqual(self.dealer.account_status, 'ACTIVE')

    def test_company_name_mapped_to_account_name(self):
        self.assertEqual(self.dealer.account_name, 'Grant Miller Motors Ltd.')

    def test_city_and_province_set(self):
        self.assertEqual(self.dealer.city, 'Vegreville')
        self.assertEqual(self.dealer.province, 'AB')

    def test_integer_stats_stored_as_int(self):
        self.assertEqual(self.dealer.new_active_stats, 80)
        self.assertEqual(self.dealer.used_active_stats, 18)
        self.assertEqual(self.dealer.new_rebated, 70)
        self.assertEqual(self.dealer.lease_count, 0)

    def test_boolean_flags_stored_as_bool(self):
        self.assertIs(self.dealer.auto_lease_on, True)
        self.assertIs(self.dealer.facebook_feed, True)
        self.assertIs(self.dealer.av_360, True)


class RenderApiDataSummaryStateTests(TestCase):
    def test_sync_stores_summary_state_for_accounts_page(self):
        AimApiData.render_api_data([_SAMPLE_ROW])
        state = AccountSyncState.singleton()
        self.assertIsNotNone(state.synced_at)
        self.assertEqual(state.accounts_created, 1)


class RenderApiDataUpdateTests(TestCase):
    """Dealer already exists locally — should be updated, not flagged new."""

    def setUp(self):
        Account.objects.create(
            account_id=27505,
            account_status='INACTIVE',
            account_name='Old Name',
            city='Old City',
            province='ON',
            is_new_account=False,
        )
        AimApiData.render_api_data([_SAMPLE_ROW])
        self.dealer = Account.objects.get(account_id=27505)

    def test_only_one_record_exists(self):
        self.assertEqual(Account.objects.filter(account_id=27505).count(), 1)

    def test_is_new_account_stays_false(self):
        self.assertFalse(self.dealer.is_new_account)

    def test_account_status_updated(self):
        self.assertEqual(self.dealer.account_status, 'ACTIVE')

    def test_account_name_updated(self):
        self.assertEqual(self.dealer.account_name, 'Grant Miller Motors Ltd.')

    def test_city_updated(self):
        self.assertEqual(self.dealer.city, 'Vegreville')


class RenderApiDataEdgeCaseTests(TestCase):
    """Graceful handling of missing / malformed rows."""

    def test_empty_list_creates_nothing(self):
        AimApiData.render_api_data([])
        self.assertEqual(Account.objects.count(), 0)

    def test_none_input_creates_nothing(self):
        AimApiData.render_api_data(None)
        self.assertEqual(Account.objects.count(), 0)

    def test_row_missing_id_is_skipped(self):
        AimApiData.render_api_data(
            [{'account': 'ACTIVE', 'company_name': 'No ID Corp'}]
        )
        self.assertEqual(Account.objects.count(), 0)

    def test_row_with_non_numeric_id_is_skipped(self):
        bad_row = {**_SAMPLE_ROW, 'id': 'not-a-number'}
        AimApiData.render_api_data([bad_row])
        self.assertEqual(Account.objects.count(), 0)

    def test_valid_and_invalid_rows_mixed(self):
        bad_row = {**_SAMPLE_ROW, 'id': None}
        AimApiData.render_api_data([_SAMPLE_ROW, bad_row])
        self.assertEqual(Account.objects.count(), 1)

    def test_missing_account_falls_back_to_empty_string(self):
        row = {**_SAMPLE_ROW, 'account': None}
        AimApiData.render_api_data([row])
        dealer = Account.objects.get(account_id=27505)
        self.assertEqual(dealer.account_status, '')

    def test_create_inactive_account_not_flagged_new(self):
        row = {**_SAMPLE_ROW, 'id': '27506', 'account': 'INACTIVE'}
        AimApiData.render_api_data([row])
        dealer = Account.objects.get(account_id=27506)
        self.assertFalse(dealer.is_new_account)

    def test_create_deleted_account_not_flagged_new(self):
        row = {**_SAMPLE_ROW, 'id': '27507', 'account': 'DELETED'}
        AimApiData.render_api_data([row])
        dealer = Account.objects.get(account_id=27507)
        self.assertFalse(dealer.is_new_account)

    def test_update_to_inactive_clears_is_new_account(self):
        Account.objects.create(
            account_id=27508,
            account_status='ACTIVE',
            account_name='Was New',
            is_new_account=True,
        )
        row = {**_SAMPLE_ROW, 'id': '27508', 'account': 'INACTIVE'}
        AimApiData.render_api_data([row])
        dealer = Account.objects.get(account_id=27508)
        self.assertEqual(dealer.account_status, 'INACTIVE')
        self.assertFalse(dealer.is_new_account)

    def test_sync_clears_stale_new_flag_on_inactive_accounts(self):
        Account.objects.create(
            account_id=27509,
            account_status='INACTIVE',
            account_name='Stale New',
            is_new_account=True,
        )
        AimApiData.render_api_data([])
        self.assertFalse(
            Account.objects.get(account_id=27509).is_new_account
        )


# ---------------------------------------------------------------------------
# sync_accounts management command
# ---------------------------------------------------------------------------


class SyncAccountsCommandTests(TestCase):
    """Tests for the sync_accounts management command wiring."""

    def test_raises_if_credentials_missing(self):
        with patch.dict('os.environ', {}, clear=True):
            with self.assertRaises(CommandError) as ctx:
                call_command('sync_accounts')
        self.assertIn('AVAIM_EMAIL', str(ctx.exception))

    def test_raises_if_api_returns_nothing(self):
        env = {'AVAIM_EMAIL': 'test@example.com', 'AVAIM_PASS': 'secret'}
        with patch.dict('os.environ', env):
            with patch.object(AimApiData, 'access_aim_api', return_value=None):
                with self.assertRaises(CommandError) as ctx:
                    call_command('sync_accounts')
        self.assertIn('No data returned', str(ctx.exception))

    def test_dry_run_does_not_write_to_db(self):
        env = {'AVAIM_EMAIL': 'test@example.com', 'AVAIM_PASS': 'secret'}
        with patch.dict('os.environ', env):
            with patch.object(AimApiData, 'access_aim_api', return_value=[_SAMPLE_ROW]):
                call_command('sync_accounts', dry_run=True)
        self.assertEqual(Account.objects.count(), 0)

    def test_successful_sync_creates_dealer(self):
        env = {'AVAIM_EMAIL': 'test@example.com', 'AVAIM_PASS': 'secret'}
        with patch.dict('os.environ', env):
            with patch.object(AimApiData, 'access_aim_api', return_value=[_SAMPLE_ROW]):
                call_command('sync_accounts')
        self.assertEqual(Account.objects.filter(account_id=27505).count(), 1)
