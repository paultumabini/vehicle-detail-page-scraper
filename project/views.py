import csv
import logging
import re
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import (
    Case,
    Count,
    Exists,
    F,
    IntegerField,
    Max,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Cast
from django.views.decorators.http import require_POST
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    UpdateView,
)

from .forms import AccountUpdateForm, ProjectCreateForm, SiteCreateForm
from .models import (
    Account,
    AccountSyncState,
    Project,
    Scrape,
    SpiderLog,
    TargetSite,
    TargetSiteStatusEvent,
    Webprovider,
)
from .spider_provider import (
    registered_spider_names,
    spider_for_web_provider,
    spider_template_rows,
    spiders_in_use_counts,
    sync_target_site_web_provider,
)
from .utils import (
    ScrapeEntryCode,
    ajax_login_required,
    set_sidebar_nav,
    target_site_form_initial_from_account,
)
from webscraping.constants import (
    DEFAULT_PROJECT_LIST_SLUG,
    DEMO_READ_ONLY_USERNAME,
)

logger = logging.getLogger(__name__)

# Window for the collapsible "Recent deactivations" panel (below the target sites table).
RECENT_DEACTIVATION_DAYS = 30


def _recent_target_site_deactivations(
    project, *, days=RECENT_DEACTIVATION_DAYS, limit=25
):
    """
    Inactive transitions for the project list panel.

    Answers "which sites dropped out recently?" without comparing scrape-log snapshots.
    Includes both manual pauses and AIM sync cascades (to_status='Inactive' only).
    """
    cutoff = timezone.now() - timedelta(days=days)
    return (
        TargetSiteStatusEvent.objects.filter(
            target_site__project=project,
            to_status='Inactive',
            created_at__gte=cutoff,
        )
        .select_related('target_site', 'target_site__site_name', 'actor')
        .order_by('-created_at')[:limit]
    )


def _project_slug_for_urls(project):
    """Resolve ForeignKey Project (or None) to the URL path segment for project_name."""
    if project is None:
        return DEFAULT_PROJECT_LIST_SLUG
    name = getattr(project, 'name', None)
    return name if name else DEFAULT_PROJECT_LIST_SLUG


def _normalize_provider_name(provider_value):
    """Normalize provider text to canonical spider/provider key."""
    if not provider_value:
        return ''
    return ''.join(token.lower() for token in provider_value.split())


def _is_restricted_user(user):
    return user.get_username() == DEMO_READ_ONLY_USERNAME


def _dashboard_stats():
    """
    KPI + setup-coverage figures for the home dashboard.

    Mirrors Accounts page semantics (ACTIVE accounts only):
      - configured          → SCRAPE + at least one TargetSite row
      - need_setup          → SCRAPE + zero TargetSite rows
      - direct_feed_count   → DIRECT_FEED (no scrape target required)
      - covered_count       → configured + direct_feed (VDP supply complete)
      - active_spider_count → distinct spider templates on runnable TargetSite rows

    Serialized into home.html via json_script for chart.js (no extra API call).
    """
    active_accounts = Account.objects.filter(account_status='ACTIVE')
    active_account_count = active_accounts.count()
    linked_site = TargetSite.objects.filter(site_name_id=OuterRef('account_id'))
    scrape_accounts = active_accounts.filter(vdp_data_source='SCRAPE')
    configured_count = scrape_accounts.filter(Exists(linked_site)).count()
    need_setup_count = scrape_accounts.filter(~Exists(linked_site)).count()
    direct_feed_count = active_accounts.filter(vdp_data_source='DIRECT_FEED').count()
    # Donut “VDP covered” segment — scrape configured ∪ direct feed (see chartSetupCoverage).
    covered_count = configured_count + direct_feed_count

    # "Spiders in Use" KPI — count distinct templates in production, not SpiderLoader.list().
    # Same runnable queryset as runspider / match_spiders; blank spider rows are excluded.
    active_spider_count = (
        TargetSite.objects.runnable()
        .exclude(spider__isnull=True)
        .exclude(spider='')
        .values('spider')
        .distinct()
        .count()
    )

    # Feeds the "Target site status" horizontal bar chart on the dashboard.
    # Status chart — omit dealers whose AIM account is off (scrape setups are paused).
    site_status_rows = (
        TargetSite.objects.exclude(
            site_name__account_status__in=('INACTIVE', 'DELETED')
        )
        .values('status')
        .annotate(c=Count('site_id'))
        .order_by('status')
    )
    site_status = {row['status']: row['c'] for row in site_status_rows}

    accounts_url = reverse('accounts')
    return {
        'active_account_count': active_account_count,
        'configured_count': configured_count,
        'need_setup_count': need_setup_count,
        'direct_feed_count': direct_feed_count,
        'covered_count': covered_count,
        'active_spider_count': active_spider_count,
        'registered_spider_count': len(registered_spider_names()),
        'site_status': site_status,
        # Deep links for breakdown bar chart clicks (coverage donut is display-only).
        'accounts_links': {
            'active': accounts_url,
            'covered': f'{accounts_url}?setup=covered',
            'configured': f'{accounts_url}?setup=configured',
            'need_setup': f'{accounts_url}?setup=not-configured',
            'direct_feed': f'{accounts_url}?setup=direct-feed',
        },
    }


def _site_form_account_queryset(current_account_id=None):
    """ACTIVE dealers for Site Name | Dealership dropdown on scrape create/update."""
    qs = Account.objects.filter(account_status='ACTIVE')
    if current_account_id:
        # Keep the linked dealer visible when editing a site whose account went inactive.
        qs = qs | Account.objects.filter(pk=current_account_id)
    return qs.order_by('account_name')


class StaffRequiredMixin(UserPassesTestMixin):
    """Gate Target Sites project management — matches sidebar Add project link."""

    def test_func(self):
        return self.request.user.is_staff


@login_required
def home(request):
    # Aggregate across all logs; empty table yields None from Sum (not a falsy manager check).
    total = (
        SpiderLog.objects.annotate(as_int=Cast('items_scraped', IntegerField()))
        .aggregate(Sum('as_int'))
        .get('as_int__sum')
    )

    dashboard = _dashboard_stats()
    context = {
        'project': Project.objects.all(),
        # Replaces legacy `provider` queryset — KPI cards + json_script for setup charts.
        'dashboard': dashboard,
        # Raw int for data-target; initDashboardCounter() formats with toLocaleString().
        'total_scrapes_count': total or 0,
    }
    # Sidebar: Dashboard is top-level; not under Accounts or Target Sites.
    set_sidebar_nav(context, section='dashboard')

    return render(request, 'project/home.html', context)


class SiteListView(LoginRequiredMixin, ListView):
    """
    Project-scoped Target Sites list (targetsites.html).

    Annotates each row for Items Scraped and Last Run columns without N+1 queries.
    Site URL / author / date_created are omitted from the table — see site detail.
    """

    template_name = 'project/targetsites.html'
    context_object_name = 'sites'
    ordering = ['-date_created']

    # filter project key passed in the url to get the specific project
    def get_queryset(self):
        self.project = get_object_or_404(Project, name=self.kwargs.get('project_name'))

        # Subqueries for Last Run / Items Scraped columns — see target_site_last_run filter.
        latest_scrape_checked = (
            Scrape.objects.filter(
                target_site=OuterRef('pk'),
            )
            .order_by('-last_checked')
            .values('last_checked')[:1]
        )

        latest_log_created = (
            SpiderLog.objects.filter(
                target_site=OuterRef('pk'),
            )
            .order_by('-date_created')
            .values('date_created')[:1]
        )

        latest_log_items_scraped = (
            SpiderLog.objects.filter(
                target_site=OuterRef('pk'),
            )
            .order_by('-date_created')
            .values('items_scraped')[:1]
        )

        latest_status_event = TargetSiteStatusEvent.objects.filter(
            target_site=OuterRef('pk'),
        ).order_by('-created_at')

        return (
            self.project.projects.all()
            .select_related('site_name', 'project')
            .annotate(
                latest_scrape_checked=Subquery(latest_scrape_checked),
                latest_log_created=Subquery(latest_log_created),
                # Items Scraped column — count from most recent spider log.
                last_log_items_scraped=Subquery(latest_log_items_scraped),
                # Status dot tooltip (|target_site_status_tooltip|) — latest pause reason.
                latest_status_event_source=Subquery(
                    latest_status_event.values('source')[:1]
                ),
                latest_status_event_detail=Subquery(
                    latest_status_event.values('detail')[:1]
                ),
                latest_status_event_at=Subquery(
                    latest_status_event.values('created_at')[:1]
                ),
            )
            # Last Run column — |target_site_last_run| picks max(latest_log_created, latest_scrape_checked).
            .order_by('-date_created')
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Sidebar: highlight this project under Target Sites (sidebar_projects).
        set_sidebar_nav(context, section='target_sites', project_name=self.project.name)

        # section label
        context['project'] = self.project.name
        context['recent_deactivations'] = _recent_target_site_deactivations(
            self.project
        )
        context['recent_deactivation_days'] = RECENT_DEACTIVATION_DAYS
        return context


class ProjectCreateView(StaffRequiredMixin, LoginRequiredMixin, CreateView):
    """
    Frontend project creation — staff only.

    Replaces the old sidebar link to Django admin so operators stay in-app.
    """

    model = Project
    form_class = ProjectCreateForm
    template_name = 'project/project_form.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        set_sidebar_nav(context, section='target_sites')
        return context

    def form_valid(self, form):
        messages.success(
            self.request,
            f"Project '{form.instance.display_label}' created. Add target sites via New Scrape.",
            extra_tags='check',
        )
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('site-list', kwargs={'project_name': self.object.name})


class SiteDetailView(LoginRequiredMixin, DetailView):
    model = TargetSite

    context_object_name = 'sites'  # or just use {{object.<property>}} in the template

    # set additional context
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        site = get_object_or_404(TargetSite, site_id=self.kwargs.get('pk'))
        project_name = _project_slug_for_urls(site.project)

        # Sidebar: site detail belongs to the site's project bucket.
        set_sidebar_nav(context, section='target_sites', project_name=project_name)
        # Per-site audit trail — newest first; cap keeps the detail page responsive.
        context['status_events'] = site.status_events.select_related('actor').order_by(
            '-created_at'
        )[:50]
        return context


class SiteCreateView(LoginRequiredMixin, CreateView, ScrapeEntryCode):
    model = TargetSite
    form_class = SiteCreateForm

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields['site_name'].queryset = _site_form_account_queryset()
        return form

    def get_initial(self):
        """Pre-fill from Account when opened via Accounts + button (?account=<pk>).

        Server-side so fields render on first paint; newscrape.js mirrors the same
        mapping when the dealership dropdown changes or after /account-provider-json/.
        Must be its own method — not inside get_form() (return would skip this).
        """
        initial = super().get_initial()
        account_id = self.request.GET.get('account')
        if account_id and account_id.isdigit():
            # select_related: web_provider name is copied into the form initial.
            account = (
                Account.objects.filter(pk=int(account_id))
                .select_related('web_provider')
                .first()
            )
            if account:
                initial.update(target_site_form_initial_from_account(account))
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # New scrape: Target Sites section active, no single project highlighted.
        set_sidebar_nav(context, section='target_sites')
        return context

    def form_valid(self, form):
        # Keep the seeded demo account read-only in production/admin environments.
        if _is_restricted_user(self.request.user):
            messages.add_message(
                self.request,
                messages.WARNING,
                'This user is not authorized to submit this request. Please ask for assistance.',
                extra_tags='exclamation',
            )
            return redirect('new-scrape')

        form.instance.author = self.request.user
        form.instance.updated_by = self.request.user
        # Belt-and-suspenders: status is not posted on create (hidden field only on edit).
        form.instance.status = form.cleaned_data.get('status') or 'Pending'
        form.instance.entry_code = self.get_scrape_entry_code(form)

        # Normalize provider to lowercase slug-style value used by spiders.
        provider = _normalize_provider_name(form.cleaned_data.get('web_provider'))
        form.instance.web_provider = provider
        form.instance.spider = spider_for_web_provider(provider) or provider

        # Ensure provider lookup table stays in sync with manual entries.
        if not Webprovider.objects.filter(name__iexact=provider).first():
            Webprovider.objects.create(name=provider)

        messages.success(
            self.request,
            f"Scrape request for '{form.cleaned_data.get('site_name')}' has been successfully submitted.",
            extra_tags='check',
        )
        return super().form_valid(form)

    def get_success_url(self):
        # CreateView has no default redirect — land on the new target site detail page
        # (same route as the Accounts table "view" icon after scraping is configured).
        return self.object.get_absolute_url()

    # if not log in and trying to access this route:
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            # messages.add_message(request, messages.WARNING, ' Please log in to have access to this page', extra_tags='text-center')
            return self.handle_no_permission()
        return super().dispatch(request, *args, **kwargs)


class SiteUpdateView(LoginRequiredMixin, UpdateView, ScrapeEntryCode):
    model = TargetSite
    form_class = SiteCreateForm

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        current_id = (
            self.object.site_name_id
            if getattr(self.object, 'site_name_id', None)
            else None
        )
        form.fields['site_name'].queryset = _site_form_account_queryset(current_id)
        return form

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Sidebar: keep the edited site's project highlighted.
        set_sidebar_nav(
            context,
            section='target_sites',
            project_name=_project_slug_for_urls(self.object.project),
        )
        return context

    def form_valid(self, form):
        # Keep the seeded demo account read-only in production/admin environments.
        if _is_restricted_user(self.request.user):
            messages.add_message(
                self.request,
                messages.WARNING,
                'This user is not authorized to submit this request. Please ask for assistance.',
                extra_tags='exclamation',
            )
            return redirect(
                'update-scrape',
                project_name=_project_slug_for_urls(self.object.project),
                pk=self.kwargs.get('pk'),
            )

        form.instance.updated_by = self.request.user
        # Non-superusers do not post status (field hidden in targetsite_form.html).
        form.instance.status = form.cleaned_data.get('status') or self.object.status

        # Keep provider normalization consistent between create and update flows.
        provider = _normalize_provider_name(form.cleaned_data.get('web_provider'))
        form.instance.web_provider = provider
        form.instance.spider = spider_for_web_provider(provider) or provider

        if not Webprovider.objects.filter(name__iexact=provider).first():
            Webprovider.objects.create(name=provider)

        messages.success(
            self.request,
            f"  '{form.cleaned_data.get('site_name')}' info has been successfully updated.",
            extra_tags='check',
        )

        return super().form_valid(form)

    def get_success_url(self):
        return self.object.get_absolute_url()


class AccountUpdateView(StaffRequiredMixin, LoginRequiredMixin, UpdateView):
    """
    In-app account edit — staff only (/accounts/<id>/edit/).

    Replaces the Django admin shortcut from the Accounts table. Does not touch
    aim_last_synced_at; only sync_accounts sets that timestamp.
    """

    model = Account
    form_class = AccountUpdateForm
    template_name = 'project/account_form.html'
    pk_url_kwarg = 'account_id'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        set_sidebar_nav(context, section='accounts')
        return context

    def form_valid(self, form):
        form.instance.modified_by = self.request.user
        response = super().form_valid(form)
        self._sync_linked_target_site(self.object)
        messages.success(
            self.request,
            f"Account '{self.object.account_name or self.object.account_id}' updated.",
            extra_tags='check',
        )
        return response

    def get_success_url(self):
        return reverse('accounts')

    def _sync_linked_target_site(self, account):
        """Mirror AccountAdminView.save_model — keep TargetSite provider/spider aligned."""
        if not account.web_provider_id:
            return
        try:
            target_site = TargetSite.objects.get(site_name_id=account.account_id)
        except TargetSite.DoesNotExist:
            return
        sync_target_site_web_provider(target_site, account.web_provider.name)
        target_site.save(update_fields=['web_provider', 'spider'])


#  CBV delete view
class SiteDeleteView(LoginRequiredMixin, DeleteView):
    model = TargetSite

    def dispatch(self, request, *args, **kwargs):
        site = self.get_object()
        if not self.request.user.is_superuser:
            messages.warning(
                request,
                f'You are not authorized to execute this request. Please ask for assistance',
                extra_tags='exclamation',
            )
            return redirect(
                'site-detail',
                pk=self.kwargs.get('pk'),
                project_name=_project_slug_for_urls(site.project),
            )
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        messages.success(
            self.request,
            f'Successfully deleted: {self.object.site_name} ',
            extra_tags='check',
        )
        return reverse(
            'site-list',
            kwargs={'project_name': _project_slug_for_urls(self.object.project)},
        )


@login_required
def api_docs(request):
    """
    In-app REST API reference (/api-docs/).

    Documents ``project.api.views.get_scraped_items`` (scraped-items endpoint).
    Builds absolute example URLs from the current host so docs match the environment.
    """
    from webscraping.constants import DEFAULT_PROJECT_LIST_SLUG, LEGACY_AIM_PROJECT_SLUG

    base = request.build_absolute_uri('/').rstrip('/')
    api_path = f'api/scraped-items/{DEFAULT_PROJECT_LIST_SLUG}/'
    context = {
        'title': 'API Documentation',
        # Template uses these for copy-paste examples (host-aware, not hardcoded scrapesbucket.com)
        'api_endpoint': f'{base}/{api_path}',
        'api_legacy_endpoint': f'{base}/api/scraped-items/{LEGACY_AIM_PROJECT_SLUG}/',
        'api_sample_url': f'{base}/{api_path}?webproviders=available&domains=all',
    }
    set_sidebar_nav(context, section='api')
    return render(request, 'project/api_docs.html', context)


@login_required
def help(request):
    """
    Operator FAQ (/help/).

    Static guidance for scraping workflow, new-scrape form rules, and support contact.
    """
    context = {'title': 'Help'}
    set_sidebar_nav(context, section='help')
    return render(request, 'project/help.html', context)


@login_required
def spider_templates_view(request):
    """
    Spider template registry — templates in use on runnable sites vs all registered.

    Deep link from dashboard KPI: ?view=in-use | ?view=registered (default: registered).
    """
    view = request.GET.get('view', 'registered').strip()
    if view not in ('in-use', 'registered'):
        view = 'registered'

    templates = spider_template_rows(view=view)
    context = {
        'view': view,
        'templates': templates,
        'in_use_count': len(spiders_in_use_counts()),
        'registered_count': len(registered_spider_names()),
    }
    set_sidebar_nav(context, section='dashboard')
    return render(request, 'project/spider_templates.html', context)


# json data
@ajax_login_required
def scrape_data_json(request):
    response = list(Scrape.objects.values())
    return JsonResponse(response, safe=False)


@ajax_login_required
def spider_logs_json(request):
    response = list(SpiderLog.objects.values())
    return JsonResponse(response, safe=False)


@ajax_login_required
def web_providers_json(request):
    response = list(Webprovider.objects.values())
    return JsonResponse(response, safe=False)


@ajax_login_required
def accounts_json(request):
    response = list(Account.objects.filter(account_status='ACTIVE').values())
    return JsonResponse(response, safe=False)


def _accounts_queryset():
    """Annotated queryset shared by the page shell and accounts_datatable_json."""
    primary_site = TargetSite.objects.filter(
        site_name_id=OuterRef('account_id'),
    ).order_by('-date_created')
    linked_site = Exists(TargetSite.objects.filter(site_name_id=OuterRef('account_id')))

    return Account.objects.annotate(
        total_sites=Count('targetsite', distinct=True),
        primary_site_id=Subquery(primary_site.values('site_id')[:1]),
        primary_site_project=Subquery(primary_site.values('project__name')[:1]),
        # Sort key for VDP setup column: not-configured < configured < direct-feed.
        vdp_setup_sort=Case(
            When(vdp_data_source='DIRECT_FEED', then=Value(2)),
            When(linked_site, then=Value(1)),
            default=Value(0),
            output_field=IntegerField(),
        ),
    )


def _accounts_order_by(order_col, order_dir):
    """
    Order expressions for accounts_datatable_json.

    Nullable stats/flags/dates use nulls_last so numeric and date sorts match
    displayed values (— rows stay at the bottom in both directions).
    """
    order_fields = {
        0: 'account_status',
        1: 'account_id',
        2: 'account_name',
        3: 'city',
        4: 'vdp_setup_sort',
        5: 'new_active_stats',
        6: 'used_active_stats',
        7: 'facebook_feed',
        8: 'aim_last_synced_at',
    }
    field = order_fields.get(order_col, 'account_name')
    desc = order_dir == 'desc'
    nullable_cols = {5, 6, 7, 8}
    if order_col in nullable_cols:
        expr = F(field)
        primary = expr.desc(nulls_last=True) if desc else expr.asc(nulls_last=True)
        return [primary, 'account_id']
    if desc:
        return [f'-{field}', 'account_id']
    return [field, 'account_id']


def _apply_accounts_setup_filter(qs, setup_filter):
    """
    Narrow accounts by VDP setup status (Scraping / VDP setup column).

    Uses Exists (not total_sites=0) so filtering stays correct with annotations/joins.
    Values match account_row.html: configured | not-configured | direct-feed | covered.
    """
    linked_site = TargetSite.objects.filter(site_name_id=OuterRef('account_id'))
    if setup_filter == 'configured':
        return qs.filter(vdp_data_source='SCRAPE').filter(Exists(linked_site))
    if setup_filter == 'not-configured':
        return qs.filter(vdp_data_source='SCRAPE').filter(~Exists(linked_site))
    if setup_filter == 'direct-feed':
        return qs.filter(vdp_data_source='DIRECT_FEED')
    # Union of dashboard covered_count — not exposed in Accounts dropdown (donut-only metric).
    if setup_filter == 'covered':
        return qs.filter(
            Q(vdp_data_source='DIRECT_FEED')
            | (Q(vdp_data_source='SCRAPE') & Q(Exists(linked_site)))
        )
    return qs


def _account_status_counts():
    """Per-status totals for SSR count card before accounts.js loads (empty key = All)."""
    by_status = {
        row['account_status']: row['c']
        for row in Account.objects.values('account_status').annotate(
            c=Count('account_id')
        )
    }
    total = sum(by_status.values())
    return {
        '': total,
        'ACTIVE': by_status.get('ACTIVE', 0),
        'INACTIVE': by_status.get('INACTIVE', 0),
        'DELETED': by_status.get('DELETED', 0),
    }


def _accounts_sync_banner():
    """
    Header stats for /accounts/ — last sync_accounts run and dealers created that run.

    Reads AccountSyncState (DB singleton) so manage.py sync and the web app share data.
    Falls back to max(aim_last_synced_at) when state row has no synced_at yet.
    """
    state = AccountSyncState.singleton()
    synced_at = state.synced_at
    if synced_at is None:
        synced_at = Account.objects.aggregate(last=Max('aim_last_synced_at'))['last']
    if state.synced_at is not None:
        created_count = state.accounts_created
    else:
        created_count = Account.objects.filter(is_new_account=True).count()
    return {
        'aim_last_synced_at': synced_at,
        'aim_sync_created_count': created_count,
    }


def _account_row_cells(account, request):
    """Render account_row.html as a list of <td>…</td> fragments (for AJAX table)."""
    row_html = render_to_string(
        'project/partials/account_row.html',
        {'account': account},
        request=request,
    )
    return re.findall(r'(<td[^>]*>.*?</td>)', row_html, flags=re.S | re.I)


@login_required
def accounts_datatable_json(request):
    """
    Paginated JSON feed for the Accounts table (accounts.js).

    Query params mirror the old DataTables server-side format so filters/sort
    keep working without jQuery. Returns pre-rendered HTML per cell from account_row.html.
    """
    draw = int(request.GET.get('draw', 1))
    start = max(int(request.GET.get('start', 0)), 0)
    length = min(max(int(request.GET.get('length', 25)), 1), 100)

    qs = _accounts_queryset()
    records_total = qs.count()

    search_val = request.GET.get('search[value]', '').strip()
    if search_val:
        search_q = (
            Q(account_name__icontains=search_val)
            | Q(city__icontains=search_val)
            | Q(province__icontains=search_val)
            | Q(account_status__icontains=search_val)
        )
        if search_val.isdigit():
            search_q |= Q(account_id=int(search_val))
        qs = qs.filter(search_q)

    account_filter = request.GET.get('columns[0][search][value]', '').strip()
    if account_filter:
        qs = qs.filter(account_status=account_filter)

    setup_filter = (
        request.GET.get('setup', '').strip()
        or request.GET.get('columns[4][search][value]', '').strip()
    )
    # Whitelist only — flat ?setup= from dashboard deep link; columns[4] from accounts.js.
    if setup_filter in ('configured', 'not-configured', 'direct-feed', 'covered'):
        qs = _apply_accounts_setup_filter(qs, setup_filter)

    new_filter = request.GET.get('columns[2][search][value]', '').strip()
    if new_filter == 'new':
        qs = qs.filter(is_new_account=True)

    records_filtered = qs.count()

    order_col = int(request.GET.get('order[0][column]', 2))
    order_dir = request.GET.get('order[0][dir]', 'asc')
    qs = qs.order_by(*_accounts_order_by(order_col, order_dir))

    page = qs[start : start + length]
    data = [_account_row_cells(account, request) for account in page]

    return JsonResponse(
        {
            'draw': draw,
            'recordsTotal': records_total,
            'recordsFiltered': records_filtered,
            'data': data,
        }
    )


@login_required
def accounts_view(request):
    """
    Accounts page shell — rows load via accounts.js + accounts_datatable_json.

    Deep link from dashboard Need Setup card: /accounts/?setup=not-configured
      - initial_setup_filter pre-selects the Scraping Setup dropdown (SSR)
      - header_count / header_label match the filtered KPI before JS loads
      - accounts.js applies the same filter to columns[4] on first fetch
    """
    setup_filter = request.GET.get('setup', '').strip()
    if setup_filter not in ('configured', 'not-configured', 'direct-feed', 'covered'):
        setup_filter = ''

    status_counts = _account_status_counts()
    # Header card defaults; overridden when ?setup= narrows the table.
    header_count = status_counts.get('ACTIVE', 0)
    header_label = 'Active'
    stats = _dashboard_stats()
    if setup_filter == 'not-configured':
        header_count = stats['need_setup_count']
        header_label = 'Need setup'
    elif setup_filter == 'configured':
        header_count = stats['configured_count']
        header_label = 'Configured'
    elif setup_filter == 'direct-feed':
        header_count = stats['direct_feed_count']
        header_label = 'Direct feed'
    elif setup_filter == 'covered':
        header_count = stats['covered_count']
        header_label = 'VDP covered'

    context = {
        'status_counts': status_counts,
        # Whitelisted GET param — synced with filter-setup options + accounts.js URL handler.
        'initial_setup_filter': setup_filter,
        'header_count': header_count,
        'header_label': header_label,
        **_accounts_sync_banner(),
    }
    set_sidebar_nav(context, section='accounts')
    return render(request, 'project/accounts.html', context)


@login_required
@require_POST  # only POST — this modifies data
def account_clear_new(request, account_id):
    """
    Clears is_new_account on a single Account.
    Called by htmx — returns a rendered <tr> fragment.
    htmx swaps just that row without a full page reload.
    """
    account = get_object_or_404(Account, account_id=account_id)
    account.is_new_account = False
    account.save(update_fields=['is_new_account'])

    # Re-annotate so the partial template has total_sites for the Scraping column.
    account = _accounts_queryset().get(account_id=account_id)

    return render(request, 'project/partials/account_row.html', {'account': account})


@login_required
def scrape_data_csv(request, project_name):
    target_site_id = request.GET.get('target_id')
    if not target_site_id:
        messages.warning(
            request,
            'Missing target site. Choose a site and try again.',
            extra_tags='exclamation',
        )
        return redirect('site-list', project_name=project_name)

    checkboxes = {
        'condition': 'condition',
        'unit': 'unit',
        'year': 'year',
        'make': 'make',
        'model': 'model',
        'trim': 'trim',
        'stock_number': 'stock_number',
        'vin': 'vin',
        'vehicle_url': 'vehicle_url',
        'msrp': 'msrp',
        'price': 'price',
        'selling_price': 'selling_price',
        'rebate': 'rebate',
        'discount': 'discount',
        'images': 'image_urls',
        'images_count': 'images_count',
    }

    target = get_object_or_404(TargetSite, site_id=target_site_id)
    try:
        scrapes = target.scrapes.all()
        first_row = scrapes.first()
        if not first_row or not first_row.last_checked:
            raise ValueError('No scrape data with a valid date for this site.')

        scrape_date = first_row.last_checked.strftime('%Y-%m-%d')

        checkbox_selected = []
        for k, v in checkboxes.items():
            if TargetSite.objects.filter(
                **{k: True, 'site_id': target_site_id}
            ).exists():
                checkbox_selected.append(v)

        if not checkbox_selected:
            raise ValueError('No export columns selected on the target site.')

        items_filtered = []
        for item in scrapes.values():
            filtered = {col: item.get(col) for col in checkbox_selected}
            items_filtered.append(filtered)

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = (
            f'attachment;filename={target_site_id}_scraped_{scrape_date}.csv'
        )

        writer = csv.writer(response)
        field_names = list(items_filtered[0].keys())
        writer.writerow(field_names)
        for item in items_filtered:
            writer.writerow(list(item.values()))
        return response

    except ValueError as exc:
        logger.warning('CSV export failed: %s', exc)
        messages.warning(
            request,
            'No available data to download. Please check site details below or contact support.',
            extra_tags='exclamation',
        )
        return redirect('site-detail', pk=target_site_id, project_name=project_name)
