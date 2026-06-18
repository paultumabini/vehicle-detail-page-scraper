# One-time seed for Inactive TargetSite rows that predate the status audit log.
# Uses account sync/modified timestamps where available; skips sites that already
# have events (safe to re-run logic inside the migration — it only runs once).
from django.db import migrations
from django.utils import timezone


def _event_timestamp(account, site):
    for candidate in (
        getattr(account, 'aim_last_synced_at', None),
        getattr(account, 'date_modified', None),
        getattr(site, 'date_updated', None),
    ):
        if candidate is not None:
            return candidate
    return timezone.now()


def backfill_target_site_status_events(apps, schema_editor):
    TargetSite = apps.get_model('project', 'TargetSite')
    TargetSiteStatusEvent = apps.get_model('project', 'TargetSiteStatusEvent')

    inactive_sites = (
        TargetSite.objects.filter(status='Inactive')
        .select_related('site_name')
        .order_by('site_id')
    )

    events = []
    for site in inactive_sites:
        # Do not duplicate rows if audit logging was already live on this environment.
        if TargetSiteStatusEvent.objects.filter(target_site_id=site.pk).exists():
            continue

        account = site.site_name
        account_status = getattr(account, 'account_status', None) if account else None
        # inactive_due_to_account=False can still mean account-driven (site was already
        # Inactive before cascade); DELETED/INACTIVE account is the stronger signal.
        paused_by_account = bool(
            site.inactive_due_to_account
            or account_status in ('INACTIVE', 'DELETED')
        )

        if paused_by_account and account is not None:
            events.append(
                TargetSiteStatusEvent(
                    target_site_id=site.pk,
                    from_status='Active',
                    to_status='Inactive',
                    source='account_sync',
                    detail=f'Historical backfill — AIM account → {account_status}',
                    created_at=_event_timestamp(account, site),
                )
            )
        else:
            events.append(
                TargetSiteStatusEvent(
                    target_site_id=site.pk,
                    from_status='Active',
                    to_status='Inactive',
                    source='manual',
                    detail='Historical backfill — set inactive manually',
                    created_at=getattr(site, 'date_updated', None) or timezone.now(),
                )
            )

    if events:
        TargetSiteStatusEvent.objects.bulk_create(events)


class Migration(migrations.Migration):

    dependencies = [
        ('project', '0015_targetsitestatusevent'),
    ]

    operations = [
        migrations.RunPython(
            backfill_target_site_status_events,
            migrations.RunPython.noop,
        ),
    ]
