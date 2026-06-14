import csv
import logging
import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Count, Exists, IntegerField, Max, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Cast
from django.views.decorators.http import require_POST
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    UpdateView,
)

from .forms import AccountUpdateForm, ProjectCreateForm, SiteCreateForm
from .models import Account, AccountSyncState, Project, Scrape, SpiderLog, TargetSite, Webprovider
from .spider_provider import spider_for_web_provider, sync_target_site_web_provider
from .utils import ScrapeEntryCode, ajax_login_required, set_sidebar_nav
from webscraping.constants import (
    DEFAULT_PROJECT_LIST_SLUG,
    DEMO_READ_ONLY_USERNAME,
)

logger = logging.getLogger(__name__)


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

    Mirrors Accounts page semantics:
      - configured  → ACTIVE account with at least one TargetSite row
      - need_setup  → ACTIVE account with zero TargetSite rows
      - active_site_count → TargetSite.status == 'Active' (excludes DELETED accounts);
                            shown on dashboard as "Scrape Sites"

    Serialized into home.html via json_script for chart.js (no extra API call).
    """
    active_accounts = Account.objects.filter(account_status='ACTIVE')
    active_account_count = active_accounts.count()
    # Same rule as accounts_datatable_json setup_filter == 'configured'.
    configured_count = (
        active_accounts.annotate(site_count=Count('targetsite'))
        .filter(site_count__gt=0)
        .count()
    )

    # "Scrape Sites" KPI — runnable scrape targets only, not all TargetSite rows.
    active_sites_qs = TargetSite.objects.filter(status='Active').exclude(
        site_name__account_status='DELETED'
    )
    active_site_count = active_sites_qs.count()

    # Feeds the "Target site status" horizontal bar chart on the dashboard.
    site_status_rows = (
        TargetSite.objects.exclude(site_name__account_status='DELETED')
        .values('status')
        .annotate(c=Count('site_id'))
        .order_by('status')
    )
    site_status = {row['status']: row['c'] for row in site_status_rows}

    return {
        'active_account_count': active_account_count,
        'configured_count': configured_count,
        'need_setup_count': max(active_account_count - configured_count, 0),
        'active_site_count': active_site_count,
        'site_status': site_status,
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
        'total_scrapes': (
            f'{total:,}' if total else None
        ),  # '{:,}' ⟶ comma separated number, i.e,  1234567 ⟶ 1,234,567
    }
    # Sidebar: Dashboard is top-level; not under Accounts or Target Sites.
    set_sidebar_nav(context, section='dashboard')

    return render(request, 'project/home.html', context)


class SiteListView(LoginRequiredMixin, ListView):
    template_name = 'project/targetsites.html'
    context_object_name = 'sites'
    ordering = ['-date_created']
    # filter project key passed in the url to get the specific project
    def get_queryset(self):
        self.project = get_object_or_404(Project, name=self.kwargs.get('project_name'))

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

        return (
            self.project.projects.all()
            .select_related('site_name', 'author', 'author__profile', 'project')
            .annotate(
                latest_scrape_checked=Subquery(latest_scrape_checked),
                latest_log_created=Subquery(latest_log_created),
            )
            .order_by('-date_created')
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Sidebar: highlight this project under Target Sites (sidebar_projects).
        set_sidebar_nav(context, section='target_sites', project_name=self.project.name)

        # section label
        context['project'] = self.project.name
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
        return context


class SiteCreateView(LoginRequiredMixin, CreateView, ScrapeEntryCode):
    model = TargetSite
    form_class = SiteCreateForm

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields['site_name'].queryset = _site_form_account_queryset()
        return form

    def get_initial(self):
        """Pre-select account when opened from Accounts + button (?account=<pk>).

        Must be its own method — not inside get_form() (return would skip this).
        """
        initial = super().get_initial()
        account_id = self.request.GET.get('account')
        if account_id and account_id.isdigit():
            initial['site_name'] = int(account_id)
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

    return Account.objects.annotate(
        total_sites=Count('targetsite', distinct=True),
        primary_site_id=Subquery(primary_site.values('site_id')[:1]),
        primary_site_project=Subquery(primary_site.values('project__name')[:1]),
    )


def _apply_accounts_setup_filter(qs, setup_filter):
    """
    Narrow accounts by whether any TargetSite row exists for the dealer.

    Uses Exists (not total_sites=0) so filtering stays correct with annotations/joins.
    Values match account_row.html Scraping column: configured | not-configured.
    """
    linked_site = TargetSite.objects.filter(site_name_id=OuterRef('account_id'))
    if setup_filter == 'configured':
        return qs.filter(Exists(linked_site))
    if setup_filter == 'not-configured':
        return qs.filter(~Exists(linked_site))
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
    """Render account_row.html as a list of inner-HTML strings per <td> (for AJAX table)."""
    row_html = render_to_string(
        'project/partials/account_row.html',
        {'account': account},
        request=request,
    )
    return re.findall(r'<td[^>]*>(.*?)</td>', row_html, flags=re.S | re.I)


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

    account_filter = request.GET.get('columns[3][search][value]', '').strip()
    if account_filter:
        qs = qs.filter(account_status=account_filter)

    setup_filter = (
        request.GET.get('setup', '').strip()
        or request.GET.get('columns[4][search][value]', '').strip()
    )
    # Whitelist only — flat ?setup= from dashboard deep link; columns[4] from accounts.js.
    if setup_filter in ('configured', 'not-configured'):
        qs = _apply_accounts_setup_filter(qs, setup_filter)

    new_filter = request.GET.get('columns[1][search][value]', '').strip()
    if new_filter == 'new':
        qs = qs.filter(is_new_account=True)

    records_filtered = qs.count()

    order_col = int(request.GET.get('order[0][column]', 1))
    order_dir = request.GET.get('order[0][dir]', 'asc')
    order_fields = {
        0: 'account_id',
        1: 'account_name',
        2: 'city',
        3: 'account_status',
        4: 'total_sites',
        5: 'new_active_stats',
        6: 'used_active_stats',
        7: 'facebook_feed',
        8: 'date_modified',
    }
    order_field = order_fields.get(order_col, 'account_name')
    if order_dir == 'desc':
        order_field = f'-{order_field}'
    qs = qs.order_by(order_field, 'account_id')

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
    if setup_filter not in ('configured', 'not-configured'):
        setup_filter = ''

    status_counts = _account_status_counts()
    # Header card defaults; overridden when ?setup= narrows the table.
    header_count = status_counts.get('ACTIVE', 0)
    header_label = 'Active'
    if setup_filter == 'not-configured':
        header_count = _dashboard_stats()['need_setup_count']
        header_label = 'Need setup'
    elif setup_filter == 'configured':
        header_count = _dashboard_stats()['configured_count']
        header_label = 'Configured'

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
