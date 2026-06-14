import functools
import re

from django.http import HttpResponse

from .models import TargetSite


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
