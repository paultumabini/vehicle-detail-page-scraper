from datetime import datetime
import re
from zoneinfo import ZoneInfo

from django import template
from django.conf import settings
from django.utils import timezone as tz
from rest_framework.authtoken.models import Token

register = template.Library()


@register.filter(name='str_split')
def str_split(value, arg):
    return value.split(arg)


@register.filter(name='str_join')
def str_join(value, arg):
    return arg.join(value)


@register.filter(name='str_upper')
def str_upper(value, arg):
    return re.sub(arg, arg.upper(), value)


@register.filter(name='replace_if_empty')
def replace_if_empty(value, arg):
    return arg if not value else value


@register.filter(name='get_field_values')
def get_field_values(value, arg):
    values = value.values_list(arg, flat=True).distinct()
    # Return deterministic unique values for template iteration.
    return sorted(set(values))


def _format_last_run_dt(dt):
    """Format an annotated last-run datetime for the target sites table."""
    # Subquery annotations may return naive datetimes — localtime() requires aware.
    if tz.is_aware(dt):
        dt = tz.localtime(dt)
    return dt.strftime('%Y-%m-%d %H:%M:%S')


def _latest_last_run_dt(*dts):
    """
    Pick the most recent non-null datetime from spider-log and scrape annotations.

    SpiderLog is written when a crawl closes (success or failure); Scrape.last_checked
    moves when inventory rows are written. Either may lag the other, so we take max
    rather than requiring same-calendar-day match (the old rule showed "running…").
    """
    candidates = [dt for dt in dts if dt is not None]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda dt: (
            tz.make_aware(dt, tz.get_default_timezone())
            if tz.is_naive(dt)
            else dt
        ),
    )


@register.filter(name='target_site_last_run')
def target_site_last_run(site):
    """
    Last Run cell label for targetsites.html (uses annotated dates when present).

    Historical timestamp only — we do not poll crawls in real time, so this must
    never imply an in-progress run. Pending/Paused/Active belong in the Status column.
    """
    log_dt = getattr(site, 'latest_log_created', None)
    scrape_dt = getattr(site, 'latest_scrape_checked', None)
    last_dt = _latest_last_run_dt(log_dt, scrape_dt)
    if last_dt is None:
        return '—'

    return _format_last_run_dt(last_dt)


_STATUS_EVENT_SOURCE_LABELS = {
    'manual': 'Manual',
    'account_sync': 'AIM sync',
    'account_reactivate': 'Account reactivated',
    'system': 'System',
}


@register.filter(name='status_event_source_label')
def status_event_source_label(source):
    """Human label for TargetSiteStatusEvent.source in templates."""
    return _STATUS_EVENT_SOURCE_LABELS.get(source, source or 'Unknown')


@register.filter(name='target_site_status_tooltip')
def target_site_status_tooltip(site):
    """
    Status dot title on targetsites.html — pause reason for Inactive rows.

    Uses annotated latest event when present (SiteListView); falls back to
    inactive_due_to_account for legacy rows predating the audit log.
    """
    label = site.get_status_display()
    if site.status != 'Inactive':
        return label

    source = getattr(site, 'latest_status_event_source', None)
    detail = getattr(site, 'latest_status_event_detail', None)
    event_at = getattr(site, 'latest_status_event_at', None)

    if source == 'account_sync':
        message = f'{label} — paused via AIM sync'
    elif source == 'manual':
        message = f'{label} — set manually'
    elif source == 'account_reactivate':
        message = label
    elif site.inactive_due_to_account:
        # No event row yet (pre-audit) but flag shows account-driven pause.
        message = f'{label} — paused when AIM account went inactive/deleted'
    else:
        message = f'{label} — set inactive'

    if detail:
        message = f'{message} ({detail})'
    if event_at:
        if tz.is_aware(event_at):
            event_at = tz.localtime(event_at)
        message = f'{message} on {event_at.strftime("%Y-%m-%d %H:%M")}'
    return message


@register.filter(name='timezone_abbrev')
def timezone_abbrev(value):
    """EST/EDT (etc.) for a datetime in DEFAULT_TIME_ZONE — pairs with |timezone:display_time_zone|."""
    if not value:
        return ''
    target = ZoneInfo(settings.DEFAULT_TIME_ZONE)
    if tz.is_naive(value):
        value = tz.make_aware(value, tz.get_default_timezone())
    return value.astimezone(target).tzname() or ''


@register.filter(name='convert_str_date')
def convert_str_date(value):
    if not value:
        return None
    try:
        # fromisoformat handles the +00:00 suffix correctly
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (ValueError, TypeError):
        return value


@register.filter(name='sort_queryset')
def sort_queryset(value, arg):
    return value.order_by(arg)


@register.filter(name='get_api_authtoken')
def get_api_authtoken(value):
    try:
        token = Token.objects.get(user=value)
        return token.key
    except Token.DoesNotExist:
        return 'Auth token not found. Please contact admin.'
