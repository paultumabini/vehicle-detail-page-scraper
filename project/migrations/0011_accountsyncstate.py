from django.db import migrations, models
from django.db.models import Max


def backfill_sync_state(apps, schema_editor):
    Account = apps.get_model('project', 'Account')
    AccountSyncState = apps.get_model('project', 'AccountSyncState')
    last = Account.objects.aggregate(m=Max('aim_last_synced_at'))['m']
    if last:
        AccountSyncState.objects.update_or_create(
            pk=1,
            defaults={'synced_at': last, 'accounts_created': 0},
        )


class Migration(migrations.Migration):

    dependencies = [
        ('project', '0010_account_aim_last_synced_at'),
    ]

    operations = [
        migrations.CreateModel(
            name='AccountSyncState',
            fields=[
                (
                    'id',
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name='ID',
                    ),
                ),
                ('synced_at', models.DateTimeField(blank=True, null=True)),
                ('accounts_created', models.PositiveIntegerField(default=0)),
            ],
            options={
                'verbose_name': 'Account sync state',
                'verbose_name_plural': 'Account sync state',
            },
        ),
        migrations.RunPython(backfill_sync_state, migrations.RunPython.noop),
    ]
