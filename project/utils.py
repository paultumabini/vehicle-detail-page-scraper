import functools
import re
from urllib.parse import urlparse

from django.http import HttpResponse

from .models import TargetSite

# Second-level labels that precede a country code (com.au, co.uk, net.nz, …).
# Shared with static/js/newscrape.js — update both if TLD rules change.
_COMPOUND_TLD_LABELS = frozenset({
    'com',
    'net',
    'org',
    'edu',
    'gov',
    'co',
    'ac',
    'asn',
    'id',
    'ne',
    'or',
    'web',
})


def entry_code_prefix(project_name):
    """First five letters of a project name, uppercase (e.g. ``av-aim`` -> ``AVAIM``)."""
    letters = re.sub(r'[^A-Za-z]', '', project_name or '')
    return letters[:5].upper()


def parse_entry_code_number(entry_code):
    """Digits after the hyphen (e.g. ``AVAIM-244`` -> ``244``)."""
    if not entry_code or '-' not in entry_code:
        return None
    suffix = entry_code.rsplit('-', 1)[-1]
    return int(suffix) if suffix.isdigit() else None


def format_entry_code(project_name, number):
    """Build ``{PREFIX}-{NNN}`` (e.g. ``AVAIM-245``)."""
    return f'{entry_code_prefix(project_name)}-{number:03d}'


def strip_site_id_from_hostname(hostname: str) -> str:
    """Drop www. and TLD — keep registrable name (mirrors newscrape.js)."""
    host = re.sub(r'^www\.', '', hostname or '', flags=re.I).strip()
    parts = [part for part in host.split('.') if part]
    if not parts:
        return ''
    if len(parts) == 1:
        return parts[0]

    tld = parts[-1].lower()
    sld = parts[-2].lower()
    compound_tld = len(tld) == 2 and sld in _COMPOUND_TLD_LABELS and len(parts) >= 3

    if compound_tld:
        return parts[-3]
    return parts[-2]


def extract_site_id_from_site_url(raw_url: str) -> str:
    """
    Site id label from a dealer URL — scheme/path/www stripped, TLD dropped.

    Keeps TargetSite.site_id aligned with the New Scrape form's domain field.
    """
    trimmed = (raw_url or '').strip()
    if not trimmed:
        return ''

    hostname = ''
    try:
        with_scheme = (
            trimmed
            if re.match(r'^https?://', trimmed, flags=re.I)
            else f'https://{trimmed}'
        )
        hostname = urlparse(with_scheme).hostname or ''
    except ValueError:
        hostname = re.sub(r'^https?://', '', trimmed, flags=re.I).split('/')[0]

    return strip_site_id_from_hostname(hostname)


def target_site_form_initial_from_account(account) -> dict:
    """
    Map Account fields onto SiteCreateForm initial values.

    Used by SiteCreateView.get_initial() for /scrape/new/?account=<pk> (Accounts + button).
    Only copies fields that exist on both models; project/feed_id stay blank.
    Domain name is derived from site_url — must stay aligned with newscrape.js.
    """
    initial = {'site_name': account.pk}

    if account.site_url:
        initial['site_url'] = account.site_url
        site_id = extract_site_id_from_site_url(account.site_url)
        if site_id:
            initial['site_id'] = site_id

    # Account.web_provider is a FK; TargetSite stores the provider name as text.
    provider = getattr(account, 'web_provider', None)
    if provider and provider.name:
        initial['web_provider'] = provider.name

    if account.note:
        initial['note'] = account.note

    return initial


class ScrapeEntryCode:
    def get_scrape_entry_code(self, form):
        """
        Build the next entry code for a project (e.g. ``AVAIM-246``).
        """
        project = form.instance.project
        if not project or not project.name:
            return ''

        numbers = []
        for site in TargetSite.objects.filter(project=project).exclude(entry_code=''):
            num = parse_entry_code_number(site.entry_code)
            if num is not None:
                numbers.append(num)

        next_num = max(numbers) + 1 if numbers else 1
        return format_entry_code(project.name, next_num)


def ajax_login_required(view_func):
    """Return HTTP 401 for unauthenticated AJAX requests."""
    @functools.wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if request.user.is_authenticated:
            return view_func(request, *args, **kwargs)
        return HttpResponse('<h1> 401 Unauthorized</h1>', status=401)

    return wrapper


def set_sidebar_nav(context, *, section=None, project_name=None):
    """
    Mark the active sidebar item in base.html.

    IA split: Accounts (registry) vs Target Sites (scrape projects).
    Call from each view's context; pairs with sidebar_projects from
    project.context_processors.sidebar.

    section: dashboard | accounts | target_sites | api | help
    project_name: Project.name slug when section is target_sites
    """
    context['sidebar_section'] = section
    context['sidebar_project'] = project_name
