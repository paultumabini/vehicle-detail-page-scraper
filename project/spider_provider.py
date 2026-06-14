"""
Map AIM ``web_provider`` values to Scrapy ``spider`` names.

AIM vendor labels do not always match spider module names (e.g. ``omni`` vs
``omni_auto``). Admin sync and site forms should use these helpers instead of
copying ``web_provider`` into ``spider`` verbatim.
"""

from __future__ import annotations

from functools import lru_cache

# AIM Webprovider.name -> scrapebucket spider ``name`` when they differ.
WEB_PROVIDER_SPIDER: dict[str, str] = {
    'omni': 'omni_auto',
    'omniauto': 'omni_auto',
    'astrawordpress': 'wp_astra',
}


@lru_cache(maxsize=1)
def registered_spider_names() -> frozenset[str]:
    """Scrapy spider ``name`` values registered in scrapebucket (cached)."""
    import sys
    from pathlib import Path

    from scrapy import spiderloader
    from scrapy.utils.project import get_project_settings

    scrape_root = Path(__file__).resolve().parent.parent / 'scrapebucket'
    scrape_root_str = str(scrape_root)
    if scrape_root_str not in sys.path:
        sys.path.insert(0, scrape_root_str)

    loader = spiderloader.SpiderLoader.from_settings(get_project_settings())
    return frozenset(loader.list())


def spider_for_web_provider(provider_name: str | None) -> str | None:
    """
    Resolve a Scrapy spider name from an AIM web provider label.

    Returns ``None`` when ``provider_name`` is empty or does not map to a known
    spider (caller should preserve an existing TargetSite.spider in that case).
    """
    provider = (provider_name or '').strip().lower()
    if not provider:
        return None

    if provider in WEB_PROVIDER_SPIDER:
        return WEB_PROVIDER_SPIDER[provider]

    registered = registered_spider_names()
    if provider in registered:
        return provider

    return None


def sync_target_site_web_provider(target_site, provider_name: str | None) -> None:
    """
    Copy AIM provider onto ``TargetSite`` and update ``spider`` when appropriate.

    ``spider`` is only changed when the provider value changed or no spider is
    set yet, so operator overrides (e.g. ``nabthat`` on a ``d2cmedia`` site)
    are not clobbered by unrelated Account saves.
    """
    new_provider = (provider_name or '').strip()
    old_provider = (target_site.web_provider or '').strip()
    provider_changed = old_provider.lower() != new_provider.lower()

    target_site.web_provider = new_provider or None

    if not provider_changed and target_site.spider:
        return

    resolved = spider_for_web_provider(new_provider)
    if resolved:
        target_site.spider = resolved
