"""
Playwright (sync) helpers for pagination and raw HTML used by some spiders.
"""

from __future__ import annotations

import re
from functools import reduce

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

_stealth = Stealth()


class PlaywrightHelper:
    def __init__(self, url: str, selector: str, wait_until: str):
        self.url = url
        self.selector = selector
        self.wait_until_selector = wait_until

    def get_pagination_no_text(self, page, browser) -> int:
        page.wait_for_selector(self.wait_until_selector)
        elements = page.query_selector_all(self.selector)
        pagination = []
        for el in elements:
            try:
                pagination.append(int(el.inner_text()))
            except (TypeError, ValueError):
                continue
        if not pagination:
            browser.close()
            return 1
        page_number = reduce(lambda a, b: a if a > b else b, pagination)
        browser.close()
        return page_number

    def get_pagination_remove_text(self, page, browser) -> int:
        page.wait_for_selector(self.wait_until_selector)
        elements = page.query_selector_all(self.selector)
        digits: list[int] = []
        for el in elements:
            raw = re.sub(r'[^0-9]', '', el.inner_text() or '')
            if raw.isdigit():
                digits.append(int(raw))
        browser.close()
        return max(digits) if digits else 1

    def get_pagination_remove_text_legacy(self, page, browser) -> int:
        """Avada theme: parse the first pagination link, drop its leading digit char."""
        page.wait_for_selector(self.wait_until_selector)
        elements = page.query_selector_all(self.selector)
        browser.close()
        if not elements:
            return 1
        digits = re.sub(r'[^0-9]', '', elements[0].inner_text() or '')
        if not digits:
            return 1
        tail = digits[1:] if len(digits) > 1 else digits
        return int(tail)

    def get_page_num_src(self, method: str) -> int:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            _stealth.apply_stealth_sync(page)
            page.goto(self.url, timeout=60_000)
            try:
                fn = getattr(self, method)
                return fn(page, browser)
            except Exception:
                if browser.is_connected():
                    browser.close()
                raise


class PlaywrightPageSourceHelper:
    def __init__(self, url: str, selector: str, wait_until: str):
        self.url = url
        self.selector = selector
        self.wait_until_selector = wait_until

    def get_page_source_text(self, page, browser):
        page.wait_for_selector(self.wait_until_selector)
        texts = page.query_selector_all(self.selector)
        browser.close()
        return texts

    def get_page_source(self) -> str:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                _stealth.apply_stealth_sync(page)
                page.goto(self.url, timeout=60_000)
                page.wait_for_selector(self.wait_until_selector)
                return page.content()
            finally:
                if browser.is_connected():
                    browser.close()
