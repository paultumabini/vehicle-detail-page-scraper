from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse

from webscraping.constants import DEFAULT_PROJECT_LIST_SLUG

# Sidebar dot palette — keys map to .sidebar-project-dot--* in main.css.
PROJECT_COLOR_CHOICES = (
    ('brand', 'Purple'),
    ('sky', 'Blue'),
    ('amber', 'Amber'),
    ('emerald', 'Green'),
    ('rose', 'Rose'),
)

# Slug -> nav label overrides (name stays as URL segment, e.g. av-aim).
PROJECT_DISPLAY_LABELS = {
    'av-aim': 'AV AIM',
    'vdp-urls': 'VDP URLs',
}


class Project(models.Model):
    """
    Groups TargetSite scrape configs. Each project appears as a nested link
    under the Target Sites sidebar section (not the Accounts registry).
    """

    name = models.CharField(max_length=50, null=True)
    # Color tag shown beside the project name in the sidebar.
    color = models.CharField(
        max_length=20,
        choices=PROJECT_COLOR_CHOICES,
        default='brand',
    )
    # Lower values appear first in the Target Sites nav list.
    sort_order = models.PositiveSmallIntegerField(default=0)
    date_created = models.DateTimeField(auto_now_add=True, null=True)
    # author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    class Meta:
        ordering = ['sort_order', 'name']

    def __str__(self):
        return str(self.name)

    @property
    def display_label(self):
        """Human-readable sidebar/page title; slug is unchanged for URLs."""
        if not self.name:
            return ''
        if self.name in PROJECT_DISPLAY_LABELS:
            return PROJECT_DISPLAY_LABELS[self.name]
        return self.name.replace('-', ' ').title()


class Webprovider(models.Model):
    name = models.CharField(max_length=50, null=True)

    def __str__(self):
        return f'{self.name}' or ''


class Account(models.Model):
    ACCOUNT_STATUS = (
        ('ACTIVE', 'ACTIVE'),
        ('INACTIVE', 'INACTIVE'),
        ('DELETED', 'DELETED'),
    )
    VDP_DATA_SOURCE = (
        ('SCRAPE', 'Requires scrape setup'),
        ('DIRECT_FEED', 'Direct feed'),
    )

    account_status = models.CharField(max_length=10, choices=ACCOUNT_STATUS)
    account_id = models.IntegerField(primary_key=True)
    account_name = models.CharField(max_length=200, null=True)
    site_url = models.CharField(max_length=200, null=True)
    web_provider = models.ForeignKey(
        Webprovider,
        on_delete=models.SET_NULL,
        related_name='web_provider',
        null=True,
        blank=True,
    )
    account_manager = models.CharField(max_length=50, null=True, blank=True)

    # Location
    city = models.CharField(max_length=100, null=True, blank=True)
    province = models.CharField(max_length=10, null=True, blank=True)

    # Inventory stats (from AIM API)
    new_active_stats = models.PositiveIntegerField(null=True, blank=True)
    used_active_stats = models.PositiveIntegerField(null=True, blank=True)
    new_rebated = models.PositiveIntegerField(null=True, blank=True)
    lease_count = models.PositiveIntegerField(null=True, blank=True)

    # Feature flags (from AIM API)
    auto_lease_on = models.BooleanField(null=True, blank=True)
    facebook_feed = models.BooleanField(null=True, blank=True)
    av_360 = models.BooleanField(null=True, blank=True)

    # Sync tracking
    is_new_account = models.BooleanField(
        default=False,
        help_text='Flagged True when first created via API sync. Clear once reviewed.',
    )
    aim_last_synced_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Set when account fields are written by sync_accounts / AIM Admin API.',
    )
    # Manual/admin/in-app edits use date_modified only — do not set aim_last_synced_at.

    # Inbound VDP supply (operator-managed; not AIM sync).
    #
    # DIRECT_FEED means no scrape target is needed. Two common paths:
    #   (a) direct_feed_file only — individual file supplied by an external provider
    #   (b) batch_feed_source — VDP parsed from a shared multi-dealer batch file
    #   (c) both — batch is upstream; direct_feed_file is the per-dealer file produced from it
    #
    # Distinct from TargetSite.exported_feed (scrape output via VdpUrlFtpExportPipeline).
    vdp_data_source = models.CharField(
        max_length=20,
        choices=VDP_DATA_SOURCE,
        default='SCRAPE',
        help_text=(
            'Requires scrape setup, or direct FTP feed (individual file and/or batch source).'
        ),
    )
    direct_feed_file = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text=(
            'Individual VDP feed file — from an external provider, or derived after '
            'parsing a batch feed.'
        ),
    )
    batch_feed_source = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Upstream shared batch file when this dealer's VDP is parsed from a batch feed.",
    )

    note = models.TextField(blank=True, null=True)
    date_created = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    date_modified = models.DateTimeField(auto_now=True, null=True)
    author = models.ForeignKey(
        User, on_delete=models.SET_NULL, related_name='author', null=True, blank=True
    )
    modified_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name='modified_by',
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = 'Account'
        verbose_name_plural = 'Accounts'

    def __str__(self):
        return f'{self.account_id} - {self.account_name}'

    @property
    def is_aim_synced(self):
        """True when sync_accounts has written this row; drives account_form.html labels."""
        return self.aim_last_synced_at is not None

    @property
    def needs_scrape_setup(self) -> bool:
        """Dashboard need_setup + Accounts VDP setup column (SCRAPE without TargetSite)."""
        return self.vdp_data_source == 'SCRAPE'

    @property
    def has_direct_feed(self) -> bool:
        """Excludes account from need_setup; shown as Direct feed in Accounts table."""
        return self.vdp_data_source == 'DIRECT_FEED'

    @property
    def has_direct_feed_file(self) -> bool:
        return bool((self.direct_feed_file or '').strip())

    @property
    def has_batch_feed_source(self) -> bool:
        return bool((self.batch_feed_source or '').strip())

    @property
    def direct_feed_from_provider(self) -> bool:
        """Individual file from an external provider (no batch upstream)."""
        return (
            self.has_direct_feed
            and self.has_direct_feed_file
            and not self.has_batch_feed_source
        )

    @property
    def direct_feed_from_batch(self) -> bool:
        """VDP originates from a shared batch file (with or without a derived individual file)."""
        return self.has_direct_feed and self.has_batch_feed_source

    def direct_feed_display_title(self) -> str:
        """Tooltip for Accounts table — direct feed file and/or batch source."""
        if not self.has_direct_feed:
            return ''
        parts = ['Direct feed — no scrape setup required']
        if self.has_direct_feed_file:
            parts.append(f'File: {self.direct_feed_file.strip()}')
        if self.has_batch_feed_source:
            parts.append(f'Batch: {self.batch_feed_source.strip()}')
        return ' · '.join(parts)

    def clean(self):
        """Enforce feed fields match vdp_data_source (admin + AccountUpdateForm)."""
        super().clean()
        has_individual = self.has_direct_feed_file
        has_batch = self.has_batch_feed_source

        if self.vdp_data_source == 'SCRAPE':
            if has_individual or has_batch:
                raise ValidationError(
                    'Direct feed fields must be empty when scrape setup is required.'
                )
        elif self.vdp_data_source == 'DIRECT_FEED':
            if not has_individual and not has_batch:
                raise ValidationError(
                    'Set an individual direct feed file, a batch feed source, or both.'
                )

    def _previous_account_status(self) -> str | None:
        """DB value before this save — used to detect INACTIVE/DELETED → ACTIVE transitions."""
        if self.pk is None:
            return None
        return (
            Account.objects.filter(pk=self.pk)
            .values_list('account_status', flat=True)
            .first()
        )

    def inactivate_linked_target_sites(self) -> int:
        """
        Pause configured scrape setups when this account is inactive/deleted.

        Called from ``save()`` after manual admin edits and AIM sync (``update_or_create``
        also hits ``save()``). Sites already Inactive (operator choice) are left alone.
        ``inactive_due_to_account`` marks rows we change so they can be restored if the
        account returns to ACTIVE.
        """
        if self.account_status not in ('INACTIVE', 'DELETED'):
            return 0
        sites = list(
            TargetSite.objects.filter(site_name_id=self.account_id)
            .exclude(status='Inactive')
            .values('pk', 'status')
        )
        if not sites:
            return 0
        site_ids = [row['pk'] for row in sites]
        # queryset.update() bypasses TargetSite.save — log here, not in the model hook.
        TargetSite.objects.filter(pk__in=site_ids).update(
            status='Inactive',
            inactive_due_to_account=True,
        )
        TargetSiteStatusEvent.objects.bulk_create(
            [
                TargetSiteStatusEvent(
                    target_site_id=row['pk'],
                    from_status=row['status'],
                    to_status='Inactive',
                    source='account_sync',
                    detail=f'AIM account → {self.account_status}',
                )
                for row in sites
            ]
        )
        return len(sites)

    def activate_linked_target_sites(self) -> int:
        """
        Re-enable scrape setups that were auto-paused when this account returns to ACTIVE.

        Only touches sites flagged by ``inactivate_linked_target_sites``; operator-set
        Inactive sites are unchanged.
        """
        if self.account_status != 'ACTIVE':
            return 0
        sites = list(
            TargetSite.objects.filter(
                site_name_id=self.account_id,
                inactive_due_to_account=True,
            ).values('pk', 'status')
        )
        if not sites:
            return 0
        site_ids = [row['pk'] for row in sites]
        # queryset.update() bypasses TargetSite.save — log here, not in the model hook.
        TargetSite.objects.filter(pk__in=site_ids).update(
            status='Active',
            inactive_due_to_account=False,
        )
        TargetSiteStatusEvent.objects.bulk_create(
            [
                TargetSiteStatusEvent(
                    target_site_id=row['pk'],
                    from_status=row['status'],
                    to_status='Active',
                    source='account_reactivate',
                    detail='AIM account → ACTIVE',
                )
                for row in sites
            ]
        )
        return len(sites)

    def save(self, *args, **kwargs):
        previous_status = self._previous_account_status()
        # Inactive/deleted accounts should never show the "New" badge or review action.
        if self.account_status in ('INACTIVE', 'DELETED'):
            self.is_new_account = False
        super().save(*args, **kwargs)
        # Mirror account_status onto linked TargetSite rows (see targetsite_detail.html).
        if self.account_status in ('INACTIVE', 'DELETED'):
            self.inactivate_linked_target_sites()
        elif self.account_status == 'ACTIVE' and previous_status in (
            'INACTIVE',
            'DELETED',
        ):
            self.activate_linked_target_sites()


class AccountSyncState(models.Model):
    """
    Singleton (pk=1) — latest sync_accounts summary for /accounts/ page header.

    Stored in DB so manage.py sync and the web process share the same values
    (LocMem cache does not cross processes).
    """

    synced_at = models.DateTimeField(null=True, blank=True)
    accounts_created = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'Account sync state'
        verbose_name_plural = 'Account sync state'

    def __str__(self):
        return f'AIM sync at {self.synced_at}'

    @classmethod
    def singleton(cls):
        state, _ = cls.objects.get_or_create(pk=1)
        return state

    @classmethod
    def record_sync(cls, *, synced_at, accounts_created):
        cls.objects.update_or_create(
            pk=1,
            defaults={
                'synced_at': synced_at,
                'accounts_created': accounts_created,
            },
        )


class TargetSiteQuerySet(models.QuerySet):
    def runnable(self):
        """
        Sites eligible for scheduled crawls (``runspider``, ``match_spiders``).

        ``status`` is the operator-facing on/off switch. Inactive/deleted AIM
        accounts are excluded even if a TargetSite row is still Active — a guard
        when account and site status drift before ``Account.save()`` cascade runs.
        """
        return self.filter(status='Active').exclude(
            site_name__account_status__in=('INACTIVE', 'DELETED')
        )


class TargetSiteManager(models.Manager.from_queryset(TargetSiteQuerySet)):
    """Default manager; exposes ``TargetSite.objects.runnable()`` for crawl scheduling."""


class TargetSite(models.Model):
    objects = TargetSiteManager()

    STATUS_CHOICES = (
        ('Active', 'Active'),
        ('Inactive', 'Inactive'),
        ('Pending', 'Pending'),
        ('Failed', 'Failed'),
        ('Paused', 'Paused'),
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='Pending')
    # Set by Account.inactivate_linked_target_sites; cleared on reactivation or manual edit.
    inactive_due_to_account = models.BooleanField(
        default=False,
        help_text=(
            'True when status was auto-set to Inactive because the linked account '
            'is inactive/deleted; cleared when the account returns to ACTIVE.'
        ),
    )
    entry_code = models.CharField(
        max_length=20, blank=True, default='', verbose_name='entry#'
    )
    project = models.ForeignKey(
        Project, on_delete=models.SET_NULL, related_name='projects', null=True
    )
    site_id = models.CharField(
        max_length=50, primary_key=True, verbose_name='site id (domain)'
    )  # domain_name input
    site_name = models.ForeignKey(Account, on_delete=models.CASCADE, null=True)
    site_url = models.CharField(max_length=200, blank=True, null=True)
    web_provider = models.CharField(max_length=50, blank=True, null=True)
    feed_id = models.CharField(
        max_length=50, blank=True, null=True, verbose_name='feed#'
    )
    exported_feed = models.CharField(max_length=100, blank=True, null=True)
    spider = models.CharField(max_length=50, null=True)
    author = models.ForeignKey(
        User, on_delete=models.SET_NULL, related_name='sites', null=True
    )
    updated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, related_name='updated_by', null=True
    )
    note = models.TextField(blank=True, null=True)
    condition = models.BooleanField()
    unit = models.BooleanField()
    year = models.BooleanField()
    make = models.BooleanField()
    model = models.BooleanField()
    trim = models.BooleanField()
    stock_number = models.BooleanField()
    vin = models.BooleanField()
    vehicle_url = models.BooleanField()
    msrp = models.BooleanField()
    price = models.BooleanField()
    selling_price = models.BooleanField()
    rebate = models.BooleanField()
    discount = models.BooleanField()
    images = models.BooleanField()
    images_count = models.BooleanField()
    date_created = models.DateTimeField(auto_now_add=True, null=True)
    date_updated = models.DateTimeField(auto_now=True, null=True)

    def __str__(self):
        return str(self.site_name) or ''

    def get_absolute_url(self):
        """Match ``project/<project_name>/<str:pk>/`` using the project slug, not the model instance."""
        project_name = (
            self.project.name
            if self.project_id and getattr(self.project, 'name', None)
            else DEFAULT_PROJECT_LIST_SLUG
        )
        return reverse(
            'site-detail',
            kwargs={'project_name': project_name, 'pk': self.pk},
        )

    def _previous_status(self) -> str | None:
        if self.pk is None:
            return None
        return (
            TargetSite.objects.filter(pk=self.pk)
            .values_list('status', flat=True)
            .first()
        )

    def save(self, *args, **kwargs):
        previous_status = self._previous_status()
        # Operator changed status away from Inactive — no longer account-driven.
        if self.status != 'Inactive':
            self.inactive_due_to_account = False
        super().save(*args, **kwargs)
        # Form/admin edits only — account cascade uses queryset.update() above.
        if previous_status is not None and previous_status != self.status:
            TargetSiteStatusEvent.record(
                target_site=self,
                from_status=previous_status,
                to_status=self.status,
                source='manual',
                actor=self.updated_by,
            )

    # def save(self, force_insert=False, force_update=False):
    #     self.entry_code = ''
    #     existing_entry_code = TargetSite.objects.all().order_by('-entry_code')
    #     if existing_entry_code.count() > 0:

    #         new_entry_code = int(existing_entry_code.count()) + 1
    #     else:
    #         new_entry_code = 1
    #     self.entry_code = f'SB-{new_entry_code}'
    #     super().save(force_insert, force_update)


class TargetSiteStatusEvent(models.Model):
    """
    Append-only audit log for TargetSite.status changes.

    Written from three paths:
      - TargetSite.save() → manual (frontend form / admin)
      - Account.inactivate_linked_target_sites() → account_sync (AIM sync cascade)
      - Account.activate_linked_target_sites() → account_reactivate

    Migration 0016 seeds historical rows for sites that were already Inactive;
    those use detail prefix ``Historical backfill —``.
    """

    SOURCE_CHOICES = (
        ('manual', 'Manual'),
        ('account_sync', 'Account sync'),
        ('account_reactivate', 'Account reactivated'),
        ('system', 'System'),
    )

    target_site = models.ForeignKey(
        TargetSite,
        on_delete=models.CASCADE,
        related_name='status_events',
    )
    from_status = models.CharField(max_length=10, blank=True, default='')
    to_status = models.CharField(max_length=10)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES)
    detail = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    actor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='target_site_status_events',
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Target site status event'
        verbose_name_plural = 'Target site status events'

    def __str__(self):
        return (
            f'{self.target_site_id}: {self.from_status or "—"} → {self.to_status} '
            f'({self.get_source_display()})'
        )

    @classmethod
    def record(
        cls,
        *,
        target_site,
        from_status,
        to_status,
        source,
        detail='',
        actor=None,
    ):
        # Account cascade uses bulk_create instead — this is for TargetSite.save() only.
        if from_status == to_status:
            return None
        return cls.objects.create(
            target_site=target_site,
            from_status=from_status or '',
            to_status=to_status,
            source=source,
            detail=detail,
            actor=actor,
        )


class Scrape(models.Model):
    spider = models.CharField(max_length=50, null=True, blank=True)
    category = models.CharField(max_length=50, null=True, blank=True)
    unit = models.CharField(max_length=200, null=True, blank=True)
    year = models.CharField(max_length=10, null=True, blank=True)
    make = models.CharField(max_length=50, null=True, blank=True)
    model = models.CharField(max_length=200, null=True, blank=True)
    trim = models.CharField(max_length=200, null=True, blank=True)
    stock_number = models.CharField(max_length=50, null=True, blank=True)
    vin = models.CharField(max_length=50, null=True, blank=True)
    vehicle_url = models.CharField(max_length=255, null=True, blank=True)
    msrp = models.CharField(max_length=50, null=True, blank=True)
    price = models.CharField(max_length=50, null=True, blank=True)
    selling_price = models.CharField(max_length=50, null=True, blank=True)
    rebate = models.CharField(max_length=50, null=True, blank=True)
    discount = models.CharField(max_length=50, null=True, blank=True)
    image_urls = models.TextField(null=True, blank=True)
    images_count = models.CharField(max_length=50, null=True, blank=True)
    page = models.CharField(max_length=50, null=True, blank=True)
    last_checked = models.DateTimeField(auto_now_add=True, null=True)
    target_site = models.ForeignKey(
        TargetSite, on_delete=models.CASCADE, related_name='scrapes', null=True
    )

    def __str__(self):
        return f'{self.target_site} - stk: {self.stock_number} - {self.last_checked.strftime("%Y-%m-%d %I:%M:%S %p")}'


class SpiderLog(models.Model):
    spider_name = models.CharField(max_length=50, null=True)
    allowed_domain = models.CharField(max_length=50, null=True)
    items_scraped = models.CharField(max_length=50, null=True)
    items_dropped = models.CharField(max_length=50, null=True)
    finish_reason = models.CharField(max_length=50, null=True)
    request_count = models.CharField(max_length=50, null=True)
    status_count_200 = models.CharField(max_length=50, null=True)
    start_timestamp = models.CharField(max_length=50, null=True)
    end_timestamp = models.CharField(max_length=50, null=True)
    elapsed_time = models.CharField(max_length=50, null=True)
    elapsed_time_seconds = models.CharField(max_length=50, null=True)
    date_created = models.DateTimeField(auto_now_add=True, null=True)
    target_site = models.ForeignKey(
        TargetSite, on_delete=models.CASCADE, related_name='spider_logs'
    )

    def __str__(self):
        return f'{str(self.target_site)} - {self.items_scraped} | {self.date_created.strftime("%Y-%m-%d %I:%M:%S %p")}'
