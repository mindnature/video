"""Authorized Playwright/CDP interaction with the *visible* Google Flow UI.

No private API, anti-bot workarounds, cookies, tokens, or hidden video links.
Selectors are user-confirmed and intentionally configurable because UI changes.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from .core import StudioError, shot_prompt, write_json

DEFAULT_FLOW_UI = {
    "cdp_url": "http://127.0.0.1:9222",
    "prompt_selector": "",
    "generate_button_selector": "",
    "reference_file_input_selector": "",
    "result_tile_selector": "",
    "result_download_selector": "",
    "download_menu_option_selector": "",
    "generation_timeout_seconds": 900,
    "manual_references_loaded": False,
}


def load_ui(path: Path | None) -> dict:
    config = dict(DEFAULT_FLOW_UI)
    if path:
        source = Path(path).expanduser().resolve()
        if not source.is_file():
            raise StudioError(f"Flow UI config not found: {source}")
        supplied = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(supplied, dict) or any(k not in config for k in supplied):
            raise StudioError("Flow UI configuration contains unsupported keys")
        config.update(supplied)
    config["cdp_url"] = os.getenv("FLOW_CDP_URL", config["cdp_url"])
    parts = urlsplit(config["cdp_url"])
    if parts.scheme not in ("http", "https") or parts.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise StudioError("CDP must be localhost only. Never expose Chrome debugging to the network")
    if not 5 <= config["generation_timeout_seconds"] <= 3600:
        raise StudioError("generation_timeout_seconds must be between 5 and 3600")
    return config


def flow_page(browser):
    pages = [page for context in browser.contexts for page in context.pages
             if urlsplit(page.url).hostname in ("flow.google", "flow.google.com", "labs.google", "labs.google.com")
             and ("flow" in page.url.lower())]
    if len(pages) != 1:
        raise StudioError(f"Expected exactly one open Google Flow tab, found {len(pages)}; open one in your dedicated Chrome profile")
    return pages[0]


def one(page, selector: str, label: str):
    if not selector:
        raise StudioError(f"Missing {label} selector. Run inspect-flow and configure a verified CSS selector")
    target = page.locator(selector)
    count = target.count()
    if count != 1:
        raise StudioError(f"{label} selector matched {count} elements (expected exactly 1). UI not changed")
    return target


class FlowBrowser:
    def __init__(self, config_path: Path | None = None):
        self.config = load_ui(config_path)
        self.on_submit = None  # optional event callback; does not prove paid Google job

    def preflight(self, references: list[Path]) -> None:
        """Read-only configuration and browser checks before reserving a paid attempt."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise StudioError("Install browser support: pip install -e '.[flow]'") from exc
        config = self.config
        if not config["prompt_selector"] or not config["generate_button_selector"]:
            raise StudioError("Configure verified prompt_selector and generate_button_selector before spending credits")
        if references and not config["reference_file_input_selector"] and not config["manual_references_loaded"]:
            raise StudioError("Upload reference images manually and confirm, or configure the upload selector")
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(config["cdp_url"], timeout=15000)
            page = flow_page(browser)
            one(page, config["prompt_selector"], "prompt")
            one(page, config["generate_button_selector"], "Generate")
            if references and config["reference_file_input_selector"]:
                one(page, config["reference_file_input_selector"], "reference upload input")

    def inspect(self, root: Path) -> Path:
        """Capture one screenshot and minimal selector counts for operator calibration."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise StudioError("Install browser support: pip install -e '.[flow]'") from exc
        output = root / "production" / "flow_browser"
        output.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(self.config["cdp_url"], timeout=15000)
            page = flow_page(browser)
            # Screenshot is kept in a gitignored local project directory.
            page.screenshot(path=str(output / "flow_screenshot.png"), full_page=False)
            info = {"page_url": page.url,
                    "textbox_count": page.get_by_role("textbox").count(),
                    "textarea_count": page.locator("textarea").count(),
                    "contenteditable_count": page.locator('[contenteditable="true"]').count(),
                    "config_selectors": {name: {"selector": self.config[name],
                                               "matches": page.locator(self.config[name]).count() if self.config[name] else 0}
                                         for name in ("prompt_selector", "generate_button_selector", "reference_file_input_selector",
                                                      "result_tile_selector", "result_download_selector")}}
            write_json(output / "ui_probe.json", info)
        return output / "ui_probe.json"

    def generate(self, root: Path, project: dict, shot: dict, references: list[Path]) -> Path | None:
        """Submit exactly one shot, then attempt a user-visible browser download.

        Returns None when Flow output must be downloaded manually. Do not call this
        twice for the same attempt: a timeout could still have consumed credits.
        """
        try:
            from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
        except ImportError as exc:
            raise StudioError("Install browser support: pip install -e '.[flow]'") from exc
        config = self.config
        if not config["prompt_selector"] or not config["generate_button_selector"]:
            raise StudioError("Configure verified prompt_selector and generate_button_selector before submission")
        if references and not config["reference_file_input_selector"] and not config["manual_references_loaded"]:
            raise StudioError("Reference images exist. Configure reference_file_input_selector or explicitly verify they are loaded in Flow")
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(config["cdp_url"], timeout=15000)
            page = flow_page(browser)
            if references and config["reference_file_input_selector"]:
                uploads = one(page, config["reference_file_input_selector"], "reference upload input")
                uploads.set_input_files([str(file) for file in references])
            prompt = one(page, config["prompt_selector"], "prompt")
            button = one(page, config["generate_button_selector"], "Generate")
            existing = page.locator(config["result_tile_selector"]).count() if config["result_tile_selector"] else None
            prompt.fill(shot_prompt(project, shot))
            button.click(timeout=15000)
            if callable(self.on_submit):
                self.on_submit(shot["id"])
            if not config["result_tile_selector"] or not config["result_download_selector"]:
                return None
            tiles = page.locator(config["result_tile_selector"])
            try:
                # Distinguish a new result from previously displayed gallery items.
                page.wait_for_function("([sel,count]) => document.querySelectorAll(sel).length > count",
                                       arg=[config["result_tile_selector"], existing],
                                       timeout=config["generation_timeout_seconds"] * 1000)
            except PlaywrightTimeout:
                # May already be generated despite no visible count change.
                raise StudioError("No new identifiable Flow result tile; check Flow before attempting another generation")
            tile = tiles.nth(existing)
            downloader = tile.locator(config["result_download_selector"])
            if downloader.count() != 1:
                raise StudioError("New tile found but download control is ambiguous; use Flow UI to download manually")
            downloads = root / "work" / "flow_downloads"
            downloads.mkdir(parents=True, exist_ok=True)
            with page.expect_download(timeout=45000) as download_event:
                downloader.click()
                if config["download_menu_option_selector"]:
                    page.locator(config["download_menu_option_selector"]).click()
            download = download_event.value
            suffix = Path(download.suggested_filename).suffix.lower()
            if suffix not in (".mp4", ".webm", ".mov", ".mkv"):
                raise StudioError("Flow downloaded a non-video file; use the normal Flow download menu")
            target = downloads / f"shot_{shot['id']}_attempt_{len(list(downloads.glob('shot_' + shot['id'] + '_attempt_*'))) + 1}{suffix}"
            download.save_as(str(target))
            return target
