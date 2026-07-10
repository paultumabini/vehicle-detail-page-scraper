"""
Scrapy spiders for dealer inventory — one module per platform or WordPress theme.

Crawl jobs inject ``url`` (and sometimes middleware-specific options). Shared spider
bases live in ``base_spider.py``; shared utilities live under ``spider_helpers``. Code
that imports Django models must call ``django_setup.ensure_django()`` before ORM use
(see ``url_qs`` and similar).
"""
