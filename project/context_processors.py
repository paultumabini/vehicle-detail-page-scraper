from django.conf import settings

from webscraping.constants import DEFAULT_PROJECT_LIST_SLUG

from .models import Project


def sidebar(request):
    """
    Inject Target Sites project links into every template.

    Active state (which project is selected) is set per-view via
    set_sidebar_nav() in utils.py — this processor only supplies the list.
    """
    return {
        'sidebar_projects': Project.objects.exclude(name__isnull=True)
        .exclude(name='')
        .order_by('sort_order', 'name'),
        'default_project_slug': DEFAULT_PROJECT_LIST_SLUG,
        'display_time_zone': getattr(settings, 'DISPLAY_TIME_ZONE', 'UTC'),
    }
