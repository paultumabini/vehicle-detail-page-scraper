import datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.models import Max, OuterRef, Subquery
from django.contrib import admin
from django.contrib.admin import DateFieldListFilter
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django.http import HttpResponseRedirect
from django.utils import timezone as dj_tz
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from unfold.admin import ModelAdmin as UnfoldModelAdmin

from .models import Account, Project, Scrape, SpiderLog, TargetSite, TargetSiteStatusEvent, Webprovider
from .spider_provider import sync_target_site_web_provider
from .utils import ScrapeEntryCode

_ACCOUNT_LABELS = {
    'ACTIVE': 'Active',
    'INACTIVE': 'Inactive',
    'DELETED': 'Deleted',
}

# Stroke trash icon — reads clearly at small sizes (filled icons collapse to a bar).
_DELETED_ICON = (
    '<svg class="account-icon account-icon--deleted" viewBox="0 0 24 24" '
    'width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.25" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">'
    '<path d="M3 6h18"/>'
    '<path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>'
    '<path d="M6 6l1 14h10l1-14"/>'
    '<line x1="10" y1="11" x2="10" y2="17"/>'
    '<line x1="14" y1="11" x2="14" y2="17"/>'
    '</svg>'
)


def _account_status_icon(account_value):
    """Active = filled dot, Inactive = hollow ring, Deleted = trash icon."""
    label = _ACCOUNT_LABELS.get(account_value, account_value or 'Unknown')

    if account_value == 'DELETED':
        return format_html(
            '<span class="account-indicator account-indicator--deleted" '
            'title="{}" aria-label="Account: {}">{}</span>',
            label,
            label,
            mark_safe(_DELETED_ICON),
        )
    if account_value == 'ACTIVE':
        return format_html(
            '<span class="account-indicator" title="{}" aria-label="Account: {}">'
            '<span class="account-dot account-dot--active"></span></span>',
            label,
            label,
        )
    if account_value == 'INACTIVE':
        return format_html(
            '<span class="account-indicator" title="{}" aria-label="Account: {}">'
            '<span class="account-dot account-dot--inactive"></span></span>',
            label,
            label,
        )
    return format_html(
        '<span class="account-indicator" title="{}" aria-label="Account: {}">'
        '<span class="account-dot account-dot--unknown"></span></span>',
        label,
        label,
    )


def _format_display_datetime(dt_value):
    display_tz = ZoneInfo(settings.DEFAULT_TIME_ZONE)
    if dj_tz.is_naive(dt_value):
        dt_value = dj_tz.make_aware(dt_value, dj_tz.UTC)
    return dt_value.astimezone(display_tz).strftime('%Y-%m-%d %I:%M:%S %p')


# Shared query-string key for dealer account sidebar filters (Account, TargetSite, SpiderLog).
ACCOUNT_FILTER_PARAM = 'dealer_account'
ACCOUNT_FILTER_ALL = (
    'all'  # explicit value so "All" does not fall back to the ACTIVE default
)
ACCOUNT_FILTER_DEFAULT = 'ACTIVE'


def make_dealer_account_filter(field_path):
    """Build a list_filter for ``Account.account_status`` or a related path (e.g. ``site_name__account_status``)."""

    class DealerAccountListFilter(admin.SimpleListFilter):
        title = 'account'
        parameter_name = ACCOUNT_FILTER_PARAM

        def lookups(self, request, model_admin):
            return Account.ACCOUNT_STATUS

        def queryset(self, request, queryset):
            value = self.value()
            if value == ACCOUNT_FILTER_ALL:
                return queryset
            if value:
                return queryset.filter(**{field_path: value})
            # Fallback when the param is missing (Mixin redirect normally sets ACTIVE first).
            return queryset.filter(**{field_path: ACCOUNT_FILTER_DEFAULT})

        def choices(self, changelist):
            # Django's built-in "All" omits the param; we use ``all`` so it is not treated as ACTIVE.
            yield {
                'selected': self.value() == ACCOUNT_FILTER_ALL,
                'query_string': changelist.get_query_string(
                    {self.parameter_name: ACCOUNT_FILTER_ALL},
                ),
                'display': 'All',
            }
            for lookup, title in self.lookup_choices:
                yield {
                    'selected': self.value() == str(lookup),
                    'query_string': changelist.get_query_string(
                        {self.parameter_name: lookup},
                    ),
                    'display': title,
                }

    return DealerAccountListFilter


# One filter class per admin model; field_path matches how each queryset reaches Account.account_status.
AccountStatusFilter = make_dealer_account_filter('account_status')
TargetSiteAccountFilter = make_dealer_account_filter('site_name__account_status')
SpiderLogAccountFilter = make_dealer_account_filter('target_site__site_name__account_status')


class DefaultActiveAccountAdminMixin:
    """Open changelist with ACTIVE selected; other filters in the query string are preserved."""

    def changelist_view(self, request, extra_context=None):
        if ACCOUNT_FILTER_PARAM not in request.GET:
            query = request.GET.copy()
            query[ACCOUNT_FILTER_PARAM] = ACCOUNT_FILTER_DEFAULT
            return HttpResponseRedirect(f'{request.path}?{query.urlencode()}')
        return super().changelist_view(request, extra_context)


class UserAdmin(UserAdmin):
    list_display = (
        'username',
        'email',
        'first_name',
        'last_name',
        'is_staff',
        'is_superuser',
    )


class AccountAdminView(DefaultActiveAccountAdminMixin, UnfoldModelAdmin):
    list_max_show_all = 500
    list_per_page = 10
    # Account filter defaults to ACTIVE; use sidebar "All" for every status.
    list_filter = [AccountStatusFilter, 'web_provider', 'account_manager']
    list_display_links = ('account_id', 'account_name')
    ordering = ('account_name',)

    list_display = (
        'show_account_status',
        'account_id',
        'account_name',
        'show_site_url',
        'web_provider',
        'account_manager',
        'date_created_fmt',
        'date_modified_fmt',
    )
    search_fields = [
        'account_status',
        'account_id',
        'account_name',
        'site_url',
        'web_provider__name',
        'account_manager',
    ]

    # show vdp urls links
    @admin.display(
        description='VDP URLS', ordering='site_url'
    )  # description is  the column name
    def show_site_url(self, obj):
        if not obj.site_url:
            return ''
        return format_html(
            "<a href='{url}' target='_blank'>{url}</a>", url=obj.site_url
        )

    @admin.display(description='Account', ordering='account_status')
    def show_account_status(self, obj):
        return _account_status_icon(obj.account_status)

    # format date
    @admin.display(ordering='date_created')
    def date_created_fmt(self, obj):
        return obj.date_created.strftime('%Y-%m-%d')

    date_created_fmt.short_description = 'Date Created'

    # format date
    @admin.display(ordering='date_modified')
    def date_modified_fmt(self, obj):
        return obj.date_modified.strftime('%Y-%m-%d')

    date_modified_fmt.short_description = 'Date Modified'

    # auto change 'web_provider' field at TargetSite after saving
    # wrap it in `try...except` to get rid of error 'self.model.DoesNotExist'
    def save_model(self, request, obj, form, change):
        # Keep TargetSite provider/spider in sync when dealer provider changes.
        try:
            target_site = TargetSite.objects.get(site_name__account_id=obj.account_id)
            if obj.web_provider:
                sync_target_site_web_provider(target_site, obj.web_provider.name)
                target_site.save(update_fields=['web_provider', 'spider'])
        except TargetSite.DoesNotExist:
            # Dealer may not yet have a corresponding TargetSite record.
            pass

        # Track who created/updated dealer rows for auditability.
        if change:
            obj.modified_by = request.user

        # If the entry is being added, set the author field
        else:
            obj.author = request.user

        # Save the object with the user information
        super().save_model(request, obj, form, change)


class TargetSiteAdminView(
    DefaultActiveAccountAdminMixin, UnfoldModelAdmin, ScrapeEntryCode
):
    # ``exported_feed`` is pipeline-written only; admin shows a styled read-only chip.
    readonly_fields = ('display_exported_feed',)
    list_per_page = 10
    fieldsets = (
        (
            None,
            {
                'fields': (
                    'status',
                    'entry_code',
                    'project',
                    'site_id',
                    'site_name',
                    'site_url',
                    'web_provider',
                    'feed_id',
                    'display_exported_feed',
                    'spider',
                    'author',
                    'updated_by',
                    'note',
                ),
            },
        ),
        (
            'Scraped field flags',
            {
                'classes': ('collapse',),
                'fields': (
                    'condition',
                    'unit',
                    'year',
                    'make',
                    'model',
                    'trim',
                    'stock_number',
                    'vin',
                    'vehicle_url',
                    'msrp',
                    'price',
                    'selling_price',
                    'rebate',
                    'discount',
                    'images',
                    'images_count',
                ),
            },
        ),
    )
    # Account filter on linked dealer; defaults to ACTIVE (see DefaultActiveAccountAdminMixin).
    list_filter = [TargetSiteAccountFilter, 'status', 'web_provider']
    list_display_links = ['target_site_account_name']
    ordering = ('-entry_code',)

    list_display = (
        'show_account_status',
        'scrape_status',
        'entry_code',
        'target_site_account_id',
        'target_site_account_name',
        'web_provider',
        'show_site_url',
        'feed_id',
        'display_exported_feed',
        'last_scraped',
        'last_run',
    )
    search_fields = [
        'site_name__account_status',
        'entry_code',
        'site_name__account_id',
        'site_name__account_name',
        'status',
        'web_provider',
        'spider',
        'site_url',
        'feed_id',
    ]

    @admin.display(ordering='site_name__account_status', description='Account')
    def show_account_status(self, obj):
        if not obj.site_name_id:
            return '—'
        return _account_status_icon(obj.site_name.account_status)

    # style at `admin-extra.css`
    @admin.display(ordering='status', description='setup')
    def scrape_status(self, obj):
        # Mapping status to CSS classes defined in admin-extra.css
        status_map = {
            'Active': 'active',
            'Pending': 'pending',
            'Failed': 'failed',
            'Paused': 'paused',
        }

        # Get the class from the map, default to 'inactive' if not found
        css_class = status_map.get(obj.status, 'inactive')

        # Return safely using placeholders
        return format_html(
            '<span class="status-pill status {}">{}</span>',
            css_class,
            obj.status,
        )

    # sorting by `site_name__account_id`
    @admin.display(ordering='site_name__account_id', description='DID')
    def target_site_account_id(self, obj):
        return obj.site_name.account_id

    # /admin/project/account/28738/change/

    @admin.display(ordering='site_name__account_name', description='Dealer')
    def target_site_account_name(self, obj):
        return obj.site_name.account_name

    # allows you to override the default formfield for a foreign keys field
    # in this example, it only sorts the list
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'site_name':
            kwargs['queryset'] = Account.objects.order_by('account_name')
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    #  Manipulating Data in Django's Admin Panel on Save
    # NOTE: the `obj` is the direct Model's instance being displayed in that row,
    #  but still can access other Model's instance via ForeignKey
    def save_model(self, request, obj, form, change):
        # Backfill site_url from the linked dealer for legacy/manual entries.
        account_id = f'{obj.site_name}'.split('-')[0].strip()
        site = Account.objects.get(account_id=account_id).site_url

        if not obj.site_url:
            obj.site_url = site
            # obj.user = request.user

        # Generate entry code once and keep it stable afterwards.
        if not obj.entry_code:
            obj.entry_code = self.get_scrape_entry_code(form)

        if change:
            # Drives TargetSiteStatusEvent.actor on manual status edits in admin.
            obj.updated_by = request.user

        super().save_model(request, obj, form, change)

    # show vdp urls links
    @admin.display(description='Site Url', ordering='site_url')
    def show_site_url(self, obj):
        return format_html(
            "<a href='{url}' target='_blank'>{url}</a>", url=obj.site_url
        )

    # Read-only view of ``TargetSite.exported_feed`` (set by VdpUrlFtpExportPipeline).
    # Uses ``display_exported_feed`` instead of the raw field so we can style empty vs
    # set states. ``format_html`` for the filename (user data); ``mark_safe`` for the
    # static "None" pill (format_html requires at least one placeholder arg).
    @admin.display(description='Exported feed', ordering='exported_feed')
    def display_exported_feed(self, obj):
        if obj.exported_feed:
            return format_html(
                '<span class="exported-feed-pill exported-feed-pill--set" '
                'title="Last FTP export">{}</span>',
                obj.exported_feed,
            )
        return mark_safe(
            '<span class="exported-feed-pill exported-feed-pill--empty" '
            'title="No feed exported yet">None</span>'
        )

    # Annotated in ``get_queryset`` so sorting does not JOIN one row per child record.
    @admin.display(ordering='last_log_items_scraped', description='Last Scraped')
    def last_scraped(self, obj):
        try:
            count = obj.last_log_items_scraped
            if count is None:
                return mark_safe(
                    '<strong style="color:#ff0000" title="Failed to scrape">Error!</strong>'
                )

            did = obj.site_name.account_id
            d_name = obj.site_name.account_name

            return format_html(
                '<a href="/admin/project/scrape/?q={did} {name}" target="_blank"><u><strong>{count}</strong></u></a>',
                did=did,
                name=d_name,
                count=count,
            )
        except Exception:
            return mark_safe(
                '<strong style="color:#ff0000" title="Failed to scrape">Error!</strong>'
            )

    # Latest scrape timestamp per site; sort key is ``last_scrape_checked`` (see ``get_queryset``).
    @admin.display(ordering='last_scrape_checked', description='Last Run')
    def last_run(self, obj):
        checked = getattr(obj, 'last_scrape_checked', None)
        if checked is None:
            return mark_safe(
                '<strong> <p style="color:#ff0000" title="Failed to scrape">Error!</p> </strong>'
            )
        return checked.strftime('%Y-%m-%d')

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Do not order list_display columns by ``scrapes__*`` / ``spider_logs__*`` directly:
        # each related row duplicates the TargetSite in the changelist when sorted.
        latest_log = SpiderLog.objects.filter(target_site_id=OuterRef('pk')).order_by(
            '-date_created'
        )
        return qs.annotate(
            last_scrape_checked=Max('scrapes__last_checked'),
            last_log_items_scraped=Subquery(latest_log.values('items_scraped')[:1]),
        )


class TargetSiteStatusEventAdminView(UnfoldModelAdmin):
    """
    Read-only audit log for target site status transitions.

    Rows are created by model hooks (manual save, account cascade) — not by admins.
    """

    list_display = (
        'created_at',
        'target_site',
        'from_status',
        'to_status',
        'source',
        'detail',
        'actor',
    )
    list_filter = ['source', 'to_status', ('created_at', DateFieldListFilter)]
    search_fields = [
        'target_site__site_id',
        'target_site__entry_code',
        'target_site__site_name__account_name',
        'detail',
    ]
    ordering = ('-created_at',)
    readonly_fields = (
        'target_site',
        'from_status',
        'to_status',
        'source',
        'detail',
        'created_at',
        'actor',
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class DateYesterdayFieldListFilter(DateFieldListFilter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        today = dj_tz.now()
        if dj_tz.is_naive(today):
            today = dj_tz.make_aware(today, dj_tz.UTC)
        date = today.astimezone(ZoneInfo(settings.DEFAULT_TIME_ZONE))

        yesterday = date - datetime.timedelta(days=1)

        self.links = list(self.links)
        # Inject a quick "since yesterday" preset in the date sidebar filter.
        self.links.insert(
            2,
            (
                'since Yesterday',
                {
                    self.lookup_kwarg_since: yesterday,
                    self.lookup_kwarg_until: today,
                },
            ),
        )


class SpiderlogsAdminView(DefaultActiveAccountAdminMixin, UnfoldModelAdmin):
    # list_max_show_all = 500
    list_per_page = 10
    # Account filter via target_site → site_name; defaults to ACTIVE.
    list_filter = (
        SpiderLogAccountFilter,
        'target_site__web_provider',
        ('date_created', DateYesterdayFieldListFilter),
    )

    ordering = ('-items_scraped', '-date_created')

    list_display_links = ('target_site_account_name',)

    list_display = (
        'show_account_status',
        'target_site_account_id',
        'target_site_account_name',
        'target_site_site_url',  # via foreignkey
        'spider_name',
        'scraped',
        'elapsed_time',
        'date_created_fmt',
    )
    search_fields = [
        'target_site__site_name__account_id',
        'target_site__site_name__account_name',
        'target_site__web_provider',
        'spider_name',
        'items_scraped',
        'date_created',
    ]  # date search pattern: YYYY-MM-DD

    @admin.display(ordering='target_site__site_name__account_status', description='Account')
    def show_account_status(self, obj):
        dealer = obj.target_site.site_name
        if dealer is None:
            return '—'
        return _account_status_icon(dealer.account_status)

    @admin.display(ordering='target_site__site_name__account_id', description='DID')
    def target_site_account_id(self, obj):
        did = obj.target_site.site_name.account_id
        return format_html(
            '<a href="/admin/project/account/{}/change/" target="_blank"><u>{}</u></a>',
            did,
            did,
        )

    @admin.display(ordering='target_site__site_name__account_name', description='Dealer')
    def target_site_account_name(self, obj):
        return obj.target_site.site_name.account_name

    @admin.display()
    def target_site_site_url(self, obj):
        return format_html(
            "<a href='{url}' target='_blank'>{url}</a>", url=obj.target_site.site_url
        )

    @admin.display(ordering='date_created')
    def date_created_fmt(self, obj):
        return _format_display_datetime(obj.date_created)

    @admin.display(ordering='items_scraped')
    def scraped(self, obj):
        items_scraped = obj.items_scraped
        did = (
            obj.target_site.site_name.account_id
        )  # access via ForeignKey: Use dot(.) not underscore(_) or dunder(__)
        d_name = obj.target_site.site_name.account_name
        if items_scraped:
            return format_html(
                '<a href="/admin/project/scrape/?q={did} {name}" target="_blank"><u><strong>{count}</strong></u></a>',
                did=did,
                name=d_name,
                count=items_scraped,
            )
        return mark_safe('<strong><span style="color:#ff0000">-none-</span></strong>')


class ScrapeAdminView(UnfoldModelAdmin):
    list_per_page = 10
    list_filter = ['target_site', 'spider']

    list_display = (
        'target_site_account_id',
        'target_site_account_name',
        'spider',
        'vin',
        'vdp_url',
        'date_created_fmt',
    )
    search_fields = [
        'target_site__site_name__account_id',
        'target_site__site_name__account_name',
        'spider',
        'stock_number',
        'vin',
        'last_checked',
    ]  # __site_name -- refers to 'site_name' attribute

    list_display_links = ('target_site_account_name',)

    @admin.display(ordering='target_site__site_name__account_id', description='DID')
    def target_site_account_id(self, obj):
        return obj.target_site.site_name.account_id

    @admin.display(ordering='target_site__site_name__account_name', description='Dealer')
    def target_site_account_name(self, obj):
        return obj.target_site.site_name.account_name

    @admin.display()
    def vdp_url(self, obj):
        return format_html(
            "<a href='{url}' target='_blank'>{url}</a>", url=obj.vehicle_url
        )

    @admin.display(ordering='date_created')
    def date_created_fmt(self, obj):
        return _format_display_datetime(obj.last_checked)

    date_created_fmt.short_description = 'Date Created'


class ProjectAdminView(UnfoldModelAdmin):
    """Sidebar nav: color tag + sort_order control Target Sites link appearance."""

    list_display = ['name', 'color', 'sort_order', 'date_created']
    list_editable = ['color', 'sort_order']
    search_fields = ['name']
    ordering = ('sort_order', 'name')


class WebproviderAdminView(UnfoldModelAdmin):
    list_display = ['id', 'name']
    search_fields = ['id', 'name']
    ordering = ('name',)


# Re-register UserAdmin to customize use display info at admin ui
admin.site.unregister(User)
admin.site.register(User, UserAdmin)

admin.site.register(Account, AccountAdminView)
admin.site.register(TargetSite, TargetSiteAdminView)
# Append-only status audit — rows come from model hooks, not admin form saves.
admin.site.register(TargetSiteStatusEvent, TargetSiteStatusEventAdminView)
admin.site.register(Scrape, ScrapeAdminView)
admin.site.register(SpiderLog, SpiderlogsAdminView)
admin.site.register(Project, ProjectAdminView)
admin.site.register(Webprovider, WebproviderAdminView)


# change back Django Admin header
admin.site.site_header = 'VDP Scraper Admin'
admin.site.site_title = 'VDP Scraper'
admin.site.index_title = 'Admin Console'
