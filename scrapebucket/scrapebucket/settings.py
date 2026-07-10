# Scrapy settings for the scrapebucket project.
# https://docs.scrapy.org/en/latest/topics/settings.html

BOT_NAME = 'scrapebucket'

DOMAIN_NAME = ''

SPIDER_MODULES = ['scrapebucket.spiders']
NEWSPIDER_MODULE = 'scrapebucket.spiders'

# USER_AGENT = '...'  # Set per-spider or via downloader middleware if needed.

# Many dealer sites block or throttle unknown bots; we still default to False for
# historical jobs. Prefer per-spider policies or a curated allow-list before enabling.
ROBOTSTXT_OBEY = False

DOWNLOADER_MIDDLEWARES = {
    'scrapebucket.middlewares.ScrapebucketDownloaderMiddleware': 543,
}

ITEM_PIPELINES = {
    'scrapebucket.pipelines.ScrapebucketPipeline': 300,
    # Post-crawl FTP export; higher number = runs after DB pipeline on close_spider.
    'scrapebucket.pipelines.VdpUrlFtpExportPipeline': 400,
}

AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 2
AUTOTHROTTLE_MAX_DELAY = 10

FEED_EXPORT_ENCODING = 'utf-8'
# Some dealer HTML is sloppy; do not fail the whole response on declared length mismatch.
DOWNLOAD_FAIL_ON_DATALOSS = False
RETRY_ENABLED = True

REQUEST_FINGERPRINTER_IMPLEMENTATION = '2.7'

# Global spider middleware: crawl stats → SpiderLog (see middlewares).
# VDP CSV → FTP export lives in ITEM_PIPELINES (VdpUrlFtpExportPipeline).
SPIDER_MIDDLEWARES = {
    'scrapebucket.middlewares.JobStatLogsMiddleware': 300,
}

# --- Django bootstrap ---
# Initialise Django here — the earliest point in Scrapy's load order — so that
# middlewares and pipelines can import ORM models without each needing their own
# setup block.  The helper is idempotent; repeat calls from those modules are no-ops.
from scrapebucket.django_setup import ensure_django  # noqa: E402

ensure_django()
