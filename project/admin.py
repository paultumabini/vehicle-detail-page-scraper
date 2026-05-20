import datetime

import pytz
from django.contrib import admin
from django.contrib.admin import DateFieldListFilter
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django.http import HttpResponseRedirect
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .models import AimDealer, Project, Scrape, SpiderLog, TargetSite, Webprovider
from .utils import ScrapeEntryCode

MANILA_TZ = pytz.timezone('Asia/Manila')

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


def _format_manila_datetime(dt_value):
    return pytz.utc.localize(dt_value).astimezone(MANILA_TZ).strftime('%Y-%m-%d %I:%M:%S %p')


# Shared query-string key for dealer account sidebar filters (AimDealer, TargetSite, SpiderLog).
ACCOUNT_FILTER_PARAM = 'dealer_account'
ACCOUNT_FILTER_ALL = 'all'  # explicit value so "All" does not fall back to the ACTIVE default
ACCOUNT_FILTER_DEFAULT = 'ACTIVE'


def make_dealer_account_filter(field_path):
    """Build a list_filter for ``AimDealer.account`` or a related path (e.g. ``site_name__account``)."""

    class DealerAccountListFilter(admin.SimpleListFilter):
        title = 'account'
        parameter_name = ACCOUNT_FILTER_PARAM

        def lookups(self, request, model_admin):
            return AimDealer.ACCOUNT_STATUS

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


# One filter class per admin model; field_path matches how each queryset reaches AimDealer.account.
AimDealerAccountFilter = make_dealer_account_filter('account')
TargetSiteAccountFilter = make_dealer_account_filter('site_name__account')
SpiderLogAccountFilter = make_dealer_account_filter('target_site__site_name__account')


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


class AimDealerAdminView(DefaultActiveAccountAdminMixin, admin.ModelAdmin):
    list_max_show_all = 500
    list_per_page = 10
    # Account filter defaults to ACTIVE; use sidebar "All" for every status.
    list_filter = [AimDealerAccountFilter, 'web_provider', 'account_manager']
    list_display_links = ('dealer_id', 'dealer_name')
    ordering = ('dealer_name',)

    list_display = (
        'account_status',
        'dealer_id',
        'dealer_name',
        'show_site_url',
        'web_provider',
        'account_manager',
        'date_created_fmt',
        'date_modified_fmt',
    )
    search_fields = [
        'account',
        'dealer_id',
        'dealer_name',
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

    @admin.display(description='Account', ordering='account')
    def account_status(self, obj):
        return _account_status_icon(obj.account)

    # format date
    @admin.display(ordering='date_created')
    def date_created_fmt(self, obj):
        return obj.date_created.strftime("%Y-%m-%d")

    date_created_fmt.short_description = 'Date Created'

    # format date
    @admin.display(ordering='date_modified')
    def date_modified_fmt(self, obj):
        return obj.date_modified.strftime("%Y-%m-%d")

    date_modified_fmt.short_description = 'Date Modified'

    # auto change 'web_provider' field at TargetSite after saving
    # wrap it in `try...except` to get rid of error 'self.model.DoesNotExist'
    def save_model(self, request, obj, form, change):
        # Keep TargetSite provider/spider in sync when dealer provider changes.
        try:
            target_site = TargetSite.objects.get(site_name__dealer_id=obj.dealer_id)
            target_site.web_provider = obj.web_provider.name
            target_site.spider = obj.web_provider.name
            target_site.save()
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


class TargetSiteAdminView(DefaultActiveAccountAdminMixin, admin.ModelAdmin, ScrapeEntryCode):
    # list_per_page = 10
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
    list_display_links = ['target_site_dealer_name']
    ordering = ('-entry_code',)

    list_display = (
        'account_status',
        'scrape_status',
        'entry_code',
        'target_site_dealer_id',
        'target_site_dealer_name',
        'web_provider',
        'show_site_url',
        'feed_id',
        'last_scraped',
        'last_run',
    )
    search_fields = [
        'site_name__account',
        'entry_code',
        'site_name__dealer_id',
        'site_name__dealer_name',
        'status',
        'web_provider',
        'spider',
        'site_url',
        'feed_id',
    ]

    @admin.display(ordering='site_name__account', description='Account')
    def account_status(self, obj):
        if not obj.site_name_id:
            return '—'
        return _account_status_icon(obj.site_name.account)

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

    # sorting by `site_name__dealer_id`
    @admin.display(ordering='site_name__dealer_id', description='DID')
    def target_site_dealer_id(self, obj):
        return obj.site_name.dealer_id

    # /admin/project/aimdealer/28738/change/

    @admin.display(ordering='site_name__dealer_name', description='Dealer')
    def target_site_dealer_name(self, obj):
        return obj.site_name.dealer_name

    # allows you to override the default formfield for a foreign keys field
    # in this example, it only sorts the list
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'site_name':
            kwargs["queryset"] = AimDealer.objects.order_by('dealer_name')
        return super().formfield_for_foreignkey(
            db_field, request, **kwargs
        )

    #  Manipulating Data in Django's Admin Panel on Save
    # NOTE: the `obj` is the direct Model's instance being displayed in that row,
    #  but still can access other Model's instance via ForeignKey
    def save_model(self, request, obj, form, change):
        # Backfill site_url from the linked dealer for legacy/manual entries.
        dealer_id = f'{obj.site_name}'.split('-')[0].strip()
        site = AimDealer.objects.get(dealer_id=dealer_id).site_url

        if not obj.site_url:
            obj.site_url = site
            # obj.user = request.user

        # Generate entry code once and keep it stable afterwards.
        if not obj.entry_code:
            obj.entry_code = self.get_scrape_entry_code(form)

        super().save_model(request, obj, form, change)

    # show vdp urls links
    @admin.display(description='Site Url', ordering='site_url')
    def show_site_url(self, obj):
        return format_html(
            "<a href='{url}' target='_blank'>{url}</a>", url=obj.site_url
        )

    # get total `spider_logs.items_scraped` via foreign key using related_name='spider_logs'
    @admin.display(ordering='spider_logs__items_scraped', description='Last Scraped')
    def last_scraped(self, obj):
        try:
            last_log = obj.spider_logs.last()

            if not last_log or last_log.items_scraped is None:
                return mark_safe('<strong style="color:#ff0000" title="Failed to scrape">Error!</strong>')

            did = obj.site_name.dealer_id
            d_name = obj.site_name.dealer_name
            count = last_log.items_scraped

            return format_html(
                '<a href="/admin/project/scrape/?q={did} {name}" target="_blank"><u><strong>{count}</strong></u></a>',
                did=did,
                name=d_name,
                count=count
            )
        except Exception:
            return mark_safe('<strong style="color:#ff0000" title="Failed to scrape">Error!</strong>')

    # get from `scrapes.last_checked` via foreign key using `related_name='scrapes'`
    @admin.display(ordering='scrapes__last_checked', description='Last Run')
    def last_run(self, obj):
        try:
            lr = TargetSite.objects.filter(site_id=obj.site_id).first()
            return lr.scrapes.last().last_checked.strftime("%Y-%m-%d")
        except BaseException:
            return mark_safe(
                '<strong> <p style="color:#ff0000" title="Failed to scrape">Error!</p> </strong>'
            )

    # To avoid duplicating rows values when sorting table at UI
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Avoid duplicate rows from JOIN-heavy admin sorting/filtering.
        return qs.distinct()


class DateYesterdayFieldListFilter(DateFieldListFilter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        today = datetime.datetime.now()  # utc
        date = pytz.utc.localize(today).astimezone(MANILA_TZ)

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


class SpiderlogsAdminView(DefaultActiveAccountAdminMixin, admin.ModelAdmin):
    # list_max_show_all = 500
    # list_per_page = 15
    # Account filter via target_site → site_name; defaults to ACTIVE.
    list_filter = (
        SpiderLogAccountFilter,
        'target_site__web_provider',
        ('date_created', DateYesterdayFieldListFilter),
    )

    ordering = ('-items_scraped', '-date_created')

    list_display_links = ('target_site_dealer_name',)

    list_display = (
        'account_status',
        'target_site_dealer_id',
        'target_site_dealer_name',
        'target_site_site_url',  # via foreignkey
        'spider_name',
        'scraped',
        'elapsed_time',
        'date_created_fmt',
    )
    search_fields = [
        'target_site__site_name__dealer_id',
        'target_site__site_name__dealer_name',
        'target_site__web_provider',
        'spider_name',
        'items_scraped',
        'date_created',
    ]  # date search pattern: YYYY-MM-DD

    @admin.display(ordering='target_site__site_name__account', description='Account')
    def account_status(self, obj):
        dealer = obj.target_site.site_name
        if dealer is None:
            return '—'
        return _account_status_icon(dealer.account)

    @admin.display(ordering='target_site__site_name__dealer_id', description='DID')
    def target_site_dealer_id(self, obj):
        did = obj.target_site.site_name.dealer_id
        return format_html(
            '<a href="/admin/project/aimdealer/{}/change/" target="_blank"><u>{}</u></a>',
            did,
            did,
        )

    @admin.display(ordering='target_site__site_name__dealer_name', description='Dealer')
    def target_site_dealer_name(self, obj):
        return obj.target_site.site_name.dealer_name

    @admin.display()
    def target_site_site_url(self, obj):
        return format_html(
            "<a href='{url}' target='_blank'>{url}</a>", url=obj.target_site.site_url
        )

    @admin.display(ordering='date_created')
    def date_created_fmt(self, obj):
        return _format_manila_datetime(obj.date_created)

    @admin.display(ordering='items_scraped')
    def scraped(self, obj):
        items_scraped = obj.items_scraped
        did = (
            obj.target_site.site_name.dealer_id
        )  # access via ForeignKey: Use dot(.) not underscore(_) or dunder(__)
        d_name = obj.target_site.site_name.dealer_name
        if items_scraped:
            return format_html(
                '<a href="/admin/project/scrape/?q={did} {name}" target="_blank"><u><strong>{count}</strong></u></a>',
                did=did,
                name=d_name,
                count=items_scraped
            )
        return mark_safe('<strong><span style="color:#ff0000">-none-</span></strong>')



class ScrapeAdminView(admin.ModelAdmin):
    list_filter = ['target_site', 'spider']

    list_display = (
        'target_site_dealer_id',
        'target_site_dealer_name',
        'spider',
        'vin',
        'vdp_url',
        'date_created_fmt',
    )
    search_fields = [
        'target_site__site_name__dealer_id',
        'target_site__site_name__dealer_name',
        'spider',
        'stock_number',
        'vin',
        'last_checked',
    ]  # __site_name -- refers to 'site_name' attribute

    list_display_links = ('target_site_dealer_name',)

    @admin.display(ordering='target_site__site_name__dealer_id', description='DID')
    def target_site_dealer_id(self, obj):
        return obj.target_site.site_name.dealer_id

    @admin.display(ordering='target_site__site_name__dealer_name', description='Dealer')
    def target_site_dealer_name(self, obj):
        return obj.target_site.site_name.dealer_name

    @admin.display()
    def vdp_url(self, obj):
        return format_html(
            "<a href='{url}' target='_blank'>{url}</a>", url=obj.vehicle_url
        )

    @admin.display(ordering='date_created')
    def date_created_fmt(self, obj):
        return _format_manila_datetime(obj.last_checked)

    date_created_fmt.short_description = 'Date Created'


class WebproviderAdminView(admin.ModelAdmin):
    list_display = ['id', 'name']
    search_fields = ['id', 'name']
    ordering = ('name',)


# Re-register UserAdmin to customize use display info at admin ui
admin.site.unregister(User)
admin.site.register(User, UserAdmin)

admin.site.register(Project)
admin.site.register(AimDealer, AimDealerAdminView)
admin.site.register(TargetSite, TargetSiteAdminView)
admin.site.register(Scrape, ScrapeAdminView)
admin.site.register(SpiderLog, SpiderlogsAdminView)
admin.site.register(Webprovider, WebproviderAdminView)


# change back Django Admin header
admin.site.site_header = 'Scrape Bucket Admin'
admin.site.site_title = 'Web Scraping'
admin.site.index_title = 'Admin Console'
