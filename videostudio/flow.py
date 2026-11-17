"""Opt-in, best-effort Playwright helper for a user-controlled Google Flow tab.

No auth bypass, direct media URL extraction, credits purchasing or scraping.
Flow selectors change over time; operator validates before submission.
"""
from __future__ import annotations

import os
from pathlib import Path

from .core import StudioError


def assist(prompt: Path, selector: str | None, button: str | None, submit: bool) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise StudioError("Install optional browser dependency: pip install -e '.[flow]'; python -m playwright install chromium") from exc
    url = os.getenv("FLOW_CDP_URL", "http://127.0.0.1:9222")
    content = prompt.read_text(encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(url, timeout=15000)
        pages = [page for context in browser.contexts for page in context.pages if "flow.google" in page.url]
        if len(pages) != 1:
            raise StudioError(f"Expected exactly one open Flow tab, found {len(pages)}. Open one logged-in Flow tab first.")
        page = pages[0]
        textboxes = page.locator(selector) if selector else page.get_by_role("textbox")
        count = textboxes.count()
        if count != 1:
            raise StudioError(f"Expected one prompt textbox, found {count}; pass --selector explicitly. No UI action was taken.")
        textboxes.first.fill(content)
        if submit:
            if not button:
                raise StudioError("For automatic submission explicitly pass --button with a verified CSS selector.")
            buttons = page.locator(button)
            if buttons.count() != 1:
                raise StudioError("Submit button selector is ambiguous; no submission attempted.")
            buttons.first.click()
            print("Prompt submitted through your open Flow tab. Verify generation and download the result manually.")
        else:
            print("Prompt populated in your open Flow tab; review settings, model, credits, and manually press Generate.")
        # Do not close the user's Chrome session.
