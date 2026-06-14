# Stores the last successful FTP export filename per TargetSite (see VdpUrlFtpExportPipeline).
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('project', '0002_inactivate_target_sites_for_deleted_dealers'),
    ]

    operations = [
        migrations.AddField(
            model_name='targetsite',
            name='exported_feed',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
    ]
