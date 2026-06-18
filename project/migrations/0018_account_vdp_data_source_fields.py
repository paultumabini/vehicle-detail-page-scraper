from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Inbound VDP supply on Account (operator-managed; default SCRAPE).

    Powers Accounts “VDP setup” column, dashboard covered/need_setup KPIs, and
    account edit form — not written by sync_accounts.
    """

    dependencies = [
        ('project', '0017_rename_omni_auto_spider'),
    ]

    operations = [
        migrations.AddField(
            model_name='account',
            name='vdp_data_source',
            field=models.CharField(
                choices=[
                    ('SCRAPE', 'Requires scrape setup'),
                    ('DIRECT_FEED', 'Direct feed'),
                ],
                default='SCRAPE',
                help_text='How this account supplies VDP data to AIM.',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='account',
            name='direct_feed_file',
            field=models.CharField(
                blank=True,
                help_text=(
                    'FTP filename for this dealer\'s individual VDP feed file '
                    '(including when derived from a batch feed).'
                ),
                max_length=200,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='account',
            name='batch_feed_source',
            field=models.CharField(
                blank=True,
                help_text=(
                    'Shared batch file or feed name when VDP data is parsed from a multi-dealer file.'
                ),
                max_length=200,
                null=True,
            ),
        ),
    ]
