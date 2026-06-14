from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('project', '0003_targetsite_exported_feed'),
    ]

    operations = [
        migrations.AddField(
            model_name='aimdealer',
            name='city',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name='aimdealer',
            name='province',
            field=models.CharField(blank=True, max_length=10, null=True),
        ),
        migrations.AddField(
            model_name='aimdealer',
            name='new_active_stats',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='aimdealer',
            name='used_active_stats',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='aimdealer',
            name='new_rebated',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='aimdealer',
            name='lease_count',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='aimdealer',
            name='auto_lease_on',
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='aimdealer',
            name='facebook_feed',
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='aimdealer',
            name='av_360',
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='aimdealer',
            name='aim_360',
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='aimdealer',
            name='image_pipeline_on',
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='aimdealer',
            name='is_new_account',
            field=models.BooleanField(
                default=False,
                help_text='Flagged True when first created via API sync. Clear once reviewed.',
            ),
        ),
    ]
