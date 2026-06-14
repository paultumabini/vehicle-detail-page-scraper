from django.db import migrations, models


class Migration(migrations.Migration):
    """aim_last_synced_at — set only by sync_accounts; null for manual accounts."""

    dependencies = [
        ('project', '0009_rename_aim_dealers_to_av_aim'),
    ]

    operations = [
        migrations.AddField(
            model_name='account',
            name='aim_last_synced_at',
            field=models.DateTimeField(
                blank=True,
                help_text='Set when account fields are written by sync_accounts / AIM Admin API.',
                null=True,
            ),
        ),
    ]
