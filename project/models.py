from django.contrib.auth.models import User
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

    def save(self, *args, **kwargs):
        # Inactive/deleted accounts should never show the "New" badge or review action.
        if self.account_status in ('INACTIVE', 'DELETED'):
            self.is_new_account = False
        super().save(*args, **kwargs)
        # Keep TargetSite.status aligned with AIM account (runspider uses TargetSite.objects.runnable()).
        if self.account_status == 'DELETED':
            TargetSite.objects.filter(site_name_id=self.account_id).exclude(
                status='Inactive'
            ).update(status='Inactive')


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

        ``status`` is the operator-facing on/off switch; excluding ``DELETED`` is a
        belt-and-suspenders guard when AIM account and TargetSite status drift apart.
        """
        return self.filter(status='Active').exclude(site_name__account_status='DELETED')


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

    # def save(self, force_insert=False, force_update=False):
    #     self.entry_code = ''
    #     existing_entry_code = TargetSite.objects.all().order_by('-entry_code')
    #     if existing_entry_code.count() > 0:

    #         new_entry_code = int(existing_entry_code.count()) + 1
    #     else:
    #         new_entry_code = 1
    #     self.entry_code = f'SB-{new_entry_code}'
    #     super().save(force_insert, force_update)


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
