# Backfill: align TargetSite.status with AimDealer.account for rows already DELETED in prod.
from django.db import migrations


def inactivate_target_sites_for_deleted_dealers(apps, schema_editor):
    TargetSite = apps.get_model('project', 'TargetSite')
    TargetSite.objects.filter(site_name__account='DELETED').exclude(
        status='Inactive'
    ).update(status='Inactive')


class Migration(migrations.Migration):

    dependencies = [
        ('project', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(
            inactivate_target_sites_for_deleted_dealers,
            migrations.RunPython.noop,
        ),
    ]
