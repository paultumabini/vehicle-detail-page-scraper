from django.db import migrations

# Legacy slugs / admin typos for the primary AV AIM project bucket.
LEGACY_AIM_PROJECT_NAMES = ('aim-dealers', 'av aim', 'AV AIM', 'Av Aim')


def rename_aim_dealers_to_av_aim(apps, schema_editor):
    Project = apps.get_model('project', 'Project')
    for legacy_name in LEGACY_AIM_PROJECT_NAMES:
        Project.objects.filter(name=legacy_name).update(name='av-aim')


class Migration(migrations.Migration):
    dependencies = [
        ('project', '0008_account_verbose_names'),
    ]

    operations = [
        migrations.RunPython(rename_aim_dealers_to_av_aim, migrations.RunPython.noop),
    ]
