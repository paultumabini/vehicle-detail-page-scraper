from datetime import datetime
import re
from zoneinfo import ZoneInfo

from django import template
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


@register.filter(name='target_site_last_run')
def target_site_last_run(site):
    """
    Last Run cell label for targetsites.html (uses annotated dates when present).
    """
    status = site.status
    if status == 'Pending':
        return 'processing...'
    if status == 'Inactive':
        return 'paused'

    log_dt = getattr(site, 'latest_log_created', None)
    scrape_dt = getattr(site, 'latest_scrape_checked', None)
    if log_dt and scrape_dt:
        log_day = log_dt.date() if hasattr(log_dt, 'date') else log_dt
        scrape_day = scrape_dt.date() if hasattr(scrape_dt, 'date') else scrape_dt
        if log_day == scrape_day:
            # Subquery annotations may return naive datetimes — localtime() requires aware.
            if tz.is_aware(scrape_dt):
                scrape_dt = tz.localtime(scrape_dt)
            return scrape_dt.strftime('%Y-%m-%d %H:%M:%S')

    return 'running...'


@register.filter(name='timezone_abbrev')
def timezone_abbrev(value, tz_name):
    """EST/EDT (etc.) for a datetime in the given IANA zone — pairs with |timezone:…|."""
    if not value:
        return ''
    try:
        target = ZoneInfo(tz_name)
    except Exception:
        return ''
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
