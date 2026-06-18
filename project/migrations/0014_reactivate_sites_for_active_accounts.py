# Backfill: ACTIVE AIM accounts should have runnable TargetSite rows after cascade deploy.
# Sites left Inactive (legacy 0002 backfill or pre-reactivate code) stay hidden behind
# the default Active filter on targetsites.html even though the account is ACTIVE again.
from django.db import migrations


def reactivate_sites_for_active_accounts(apps, schema_editor):
    TargetSite = apps.get_model('project', 'TargetSite')
    TargetSite.objects.filter(
        site_name__account_status='ACTIVE',
        status='Inactive',
    ).update(status='Active', inactive_due_to_account=False)


class Migration(migrations.Migration):

    dependencies = [
        ('project', '0013_targetsite_inactive_due_to_account'),
    ]

    operations = [
        migrations.RunPython(
            reactivate_sites_for_active_accounts,
            migrations.RunPython.noop,
        ),
    ]
