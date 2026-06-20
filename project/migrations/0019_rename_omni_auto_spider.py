from django.db import migrations


def rename_omni_auto_spider(apps, schema_editor):
    TargetSite = apps.get_model('project', 'TargetSite')
    Scrape = apps.get_model('project', 'Scrape')
    SpiderLog = apps.get_model('project', 'SpiderLog')
    Webprovider = apps.get_model('project', 'Webprovider')

    TargetSite.objects.filter(spider='omni_auto').update(spider='omniauto')
    Scrape.objects.filter(spider='omni_auto').update(spider='omniauto')
    SpiderLog.objects.filter(spider_name='omni_auto').update(spider_name='omniauto')

    TargetSite.objects.filter(web_provider__iexact='omni').update(web_provider='omniauto')

    if Webprovider.objects.filter(name__iexact='omni').exists():
        if not Webprovider.objects.filter(name__iexact='omniauto').exists():
            Webprovider.objects.filter(name__iexact='omni').update(name='omniauto')


class Migration(migrations.Migration):

    dependencies = [
        ('project', '0018_account_vdp_data_source_fields'),
    ]

    operations = [
        migrations.RunPython(rename_omni_auto_spider, migrations.RunPython.noop),
    ]
