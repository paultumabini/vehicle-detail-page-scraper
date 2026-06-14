"""
Django management command: sync AIM API data into ``Account``.

Usage:

    python manage.py sync_accounts

    # Preview counts without writing to the DB:
    python manage.py sync_accounts --dry-run

Credentials are read from environment variables ``AVAIM_EMAIL`` and
``AVAIM_PASS``.  In production these are sourced from ``$ENVS`` before
the cron job runs.
"""

from __future__ import annotations

import os

from django.core.management.base import BaseCommand, CommandError

from project.api.aimapi import AimApiData


class Command(BaseCommand):
    help = 'Fetch account data from the AIM API and update/create Account records.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Fetch data from the API but do not write anything to the database.',
        )

    def handle(self, *args, **options):
        email = os.environ.get('AVAIM_EMAIL')
        password = os.environ.get('AVAIM_PASS')

        if not email or not password:
            raise CommandError(
                'AVAIM_EMAIL and AVAIM_PASS environment variables must be set.'
            )

        self.stdout.write('Fetching account data from AIM API...')

        credential = AimApiData.from_get_credentials(email, password)
        aimdata = AimApiData.access_aim_api(**vars(credential))

        if not aimdata:
            raise CommandError('No data returned from AIM API. Check credentials and network.')

        self.stdout.write(f'Received {len(aimdata)} account rows from API.')

        if options['dry_run']:
            self.stdout.write(
                self.style.WARNING(f'Dry run — skipping DB writes ({len(aimdata)} rows would be processed).')
            )
            return

        AimApiData.render_api_data(aimdata)

        self.stdout.write(self.style.SUCCESS('Account sync completed successfully.'))
