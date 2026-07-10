# Glovebox dealers that migrated to Convertus Achilles should use the tadvantage
# spider with feed_id set to the Convertus vmsID (same VMS API as convertus).

from django.db import migrations

# site_id -> Convertus vmsID (from dealer site vmsData JS)
MIGRATED_GLOVEBOX_SITES = (
    ('southcoasthyundai', '4346'),
)


def reassign_migrated_glovebox_to_tadvantage(apps, schema_editor):
    TargetSite = apps.get_model('project', 'TargetSite')
    Account = apps.get_model('project', 'Account')
    Webprovider = apps.get_model('project', 'Webprovider')
    Scrape = apps.get_model('project', 'Scrape')
    SpiderLog = apps.get_model('project', 'SpiderLog')

    wp = Webprovider.objects.filter(name__iexact='tadvantage').first()
    if wp is None:
        wp = Webprovider.objects.create(name='tadvantage')

    for site_id, feed_id in MIGRATED_GLOVEBOX_SITES:
        sites = TargetSite.objects.filter(site_id=site_id)
        if not sites.exists():
            continue

        sites.update(
            spider='tadvantage',
            web_provider='tadvantage',
            feed_id=feed_id,
        )

        ts = sites.first()
        if ts and ts.site_name_id:
            Account.objects.filter(pk=ts.site_name_id).update(web_provider_id=wp.pk)

        Scrape.objects.filter(target_site_id=site_id, spider='glovebox').update(
            spider='tadvantage'
        )
        SpiderLog.objects.filter(
            target_site_id=site_id, spider_name='glovebox'
        ).update(spider_name='tadvantage')


class Migration(migrations.Migration):

    dependencies = [
        ('project', '0019_rename_omni_auto_spider'),
    ]

    operations = [
        migrations.RunPython(
            reassign_migrated_glovebox_to_tadvantage,
            migrations.RunPython.noop,
        ),
    ]
