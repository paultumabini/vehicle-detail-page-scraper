"""
AIM Admin API client — fetches dealer data and syncs it into ``Account``.

This module is a pure library; it has no ``__main__`` entry point.
To run the sync, use the management command:

    python manage.py sync_accounts

Environment:

- ``AVAIM_EMAIL`` / ``AVAIM_PASS`` — API credentials (required).
"""

from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = (10, 60)


class AimApiData:
    """Thin client for the AIM Admin API; syncs dealer rows into ``Account``."""

    _login_url = 'https://aim-admin.com/ncso_api/auth'
    _status_url = 'https://aim-admin.com/aim_system_api/get_data_for_dealers_page/'

    def __init__(self, email: str | None, password: str | None):
        self._email = email
        self._password = password

    @property
    def email(self) -> str | None:
        return self._email

    @email.setter
    def email(self, value: str | None) -> None:
        self._email = value

    @property
    def password(self) -> str | None:
        return self._password

    @password.setter
    def password(self, value: str | None) -> None:
        self._password = value

    @classmethod
    def from_get_credentials(
        cls, email: str | None, password: str | None
    ) -> AimApiData:
        return cls(email, password)

    @classmethod
    def access_aim_api(cls, **kwargs) -> list | None:
        email, password = kwargs.get('_email'), kwargs.get('_password')
        if not email or not password:
            logger.error('AVAIM_EMAIL and AVAIM_PASS must be set.')
            return None

        form_data = {
            'email': email,
            'password': password,
            'last_logged_version': 'aim_admin',
            'extra_info': {
                'login_type': 0,
                'os': 'Windows',
                'device': 'chrome 107.0.0.0',
            },
        }

        login_res = requests.post(
            cls._login_url, json=form_data, timeout=_REQUEST_TIMEOUT
        )
        login_res.raise_for_status()
        login_payload = login_res.json()
        if not isinstance(login_payload, list) or len(login_payload) < 2:
            logger.error('Unexpected login response shape from AIM API.')
            return None

        session_id = login_payload[1].get('session_id')
        if not session_id:
            logger.error('No session_id in AIM login response.')
            return None

        status_res = requests.get(
            f'{cls._status_url}{session_id}',
            timeout=_REQUEST_TIMEOUT,
        )
        status_res.raise_for_status()
        status_payload = status_res.json()
        if not isinstance(status_payload, list) or len(status_payload) < 2:
            logger.error('Unexpected status response shape from AIM API.')
            return None

        return status_payload[1].get('data')

    @staticmethod
    def _parse_int(value: Any) -> int | None:
        """Convert a string or numeric value to int; return None on failure."""
        if value is None:
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _parse_bool(value: Any) -> bool | None:
        """Convert a string/int flag (``'0'``/``'1'``) to bool; return None on failure."""
        if value is None:
            return None
        try:
            return bool(int(value))
        except (ValueError, TypeError):
            return None

    @classmethod
    def _clear_new_on_inactive_deleted(cls) -> int:
        """Drop stale New badges — inactive/deleted dealers cannot be reviewed as new."""
        from project.models import Account

        return Account.objects.filter(
            account_status__in=('INACTIVE', 'DELETED'),
            is_new_account=True,
        ).update(is_new_account=False)

    @classmethod
    def render_api_data(cls, aimdata: list | None) -> None:
        from django.utils import timezone

        from project.models import Account

        if not aimdata:
            logger.warning('No dealer rows from AIM API; skipping DB update.')
            cleared_new = cls._clear_new_on_inactive_deleted()
            if cleared_new:
                logger.info(
                    'Cleared is_new_account on %s inactive/deleted account(s).',
                    cleared_new,
                )
            return

        updated = 0
        created_count = 0
        skipped = 0

        for dealer in aimdata:
            ext_id = cls._parse_int(dealer.get('id'))
            if ext_id is None:
                skipped += 1
                continue

            account_status = dealer.get('account') or ''
            field_values = {
                'account_status': account_status,
                'account_name': dealer.get('company_name'),
                'city': dealer.get('city'),
                'province': dealer.get('province'),
                'new_active_stats': cls._parse_int(dealer.get('new_active_stats')),
                'used_active_stats': cls._parse_int(dealer.get('used_active_stats')),
                'new_rebated': cls._parse_int(dealer.get('new_rebated')),
                'lease_count': cls._parse_int(dealer.get('lease_count')),
                'auto_lease_on': cls._parse_bool(dealer.get('auto_lease_on')),
                'facebook_feed': cls._parse_bool(dealer.get('facebook_feed')),
                'av_360': cls._parse_bool(dealer.get('av_360')),
            }
            if account_status in ('INACTIVE', 'DELETED'):
                field_values['is_new_account'] = False

            synced_at = timezone.now()
            # Only AIM sync sets this — account_form.html uses it vs date_modified.
            field_values['aim_last_synced_at'] = synced_at

            _, created = Account.objects.update_or_create(
                account_id=ext_id,
                defaults=field_values,
                create_defaults={
                    **field_values,
                    'is_new_account': account_status not in ('INACTIVE', 'DELETED'),
                },
            )

            if created:
                created_count += 1
            else:
                updated += 1

        cleared_new = cls._clear_new_on_inactive_deleted()

        from project.models import AccountSyncState

        AccountSyncState.record_sync(
            synced_at=timezone.now(),
            accounts_created=created_count,
        )

        logger.info(
            'AIM sync finished: %s created (new), %s updated, %s skipped (total local: %s).',
            created_count,
            updated,
            skipped,
            Account.objects.count(),
        )
        if cleared_new:
            logger.info(
                'Cleared is_new_account on %s inactive/deleted account(s).',
                cleared_new,
            )
