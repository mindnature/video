"""Gemini website director via an operator-authenticated, local Chrome session.

Uses only visible, user-verified UI controls. Never reads cookies, private APIs,
network interception, or claims responses unless validated from visible text.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

from .core import StudioError, validate, write_json
from .templates import preset

DEFAULT_GEMINI_UI = {
    "cdp_url": "http://127.0.0.1:9222",
    "prompt_selector": "",
    "send_button_selector": "",
    "response_selector": "",
    "new_chat_button_selector": "",
    "reference_file_input_selector": "",
    "manual_references_loaded": False,
    "response_timeout_seconds": 240,
    "stable_polls": 4,
}


def load_gemini_ui(path: Path | None) -> dict:
    config = dict(DEFAULT_GEMINI_UI)
    if path is not None:
        source = Path(path).expanduser().resolve()
        if not source.is_file():
            raise StudioError(f"Gemini UI config not found: {source}")
        supplied = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(supplied, dict) or any(key not in config for key in supplied):
            raise StudioError("Gemini UI config has unsupported keys")
        config.update(supplied)
    config["cdp_url"] = os.getenv("VIDEO_CDP_URL", config["cdp_url"])
    parts = urlsplit(config["cdp_url"])
    if parts.scheme != "http" or parts.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise StudioError("Gemini CDP must be local HTTP only")
    if type(config["response_timeout_seconds"]) is not int or not 15 <= config["response_timeout_seconds"] <= 1800:
        raise StudioError("response_timeout_seconds must be between 15 and 1800")
    if type(config["stable_polls"]) is not int or not 2 <= config["stable_polls"] <= 10:
        raise StudioError("stable_polls must be between 2 and 10")
    return config


def gemini_page(browser):
    pages = [page for context in browser.contexts for page in context.pages
             if urlsplit(page.url).hostname == "gemini.google.com"]
    if len(pages) != 1:
        raise StudioError(f"Expected exactly one Gemini tab in dedicated Chrome; found {len(pages)}")
    return pages[0]


def one(page, selector: str, label: str):
    if not selector:
        raise StudioError(f"Gemini {label} selector unset; inspect-gemini and configure visible controls")
    locator = page.locator(selector)
    count = locator.count()
    if count != 1:
        raise StudioError(f"Gemini {label} selector matched {count} elements; require exactly one")
    return locator


def extract_project(text: str, mode: str, shots: int) -> dict:
    """Accept JSON or one Markdown JSON fence; reject extra text and wrong schema."""
    if len(text) > 220_000:
        raise StudioError("Gemini response too large for the expected storyboard JSON")
    body = text.strip()
    if body.startswith("```"):
        match = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", body, flags=re.IGNORECASE)
        if not match:
            raise StudioError("Gemini response contains malformed Markdown code fence")
        body = match.group(1).strip()
    try:
        value = json.loads(body)
    except (ValueError, TypeError) as exc:
        raise StudioError("Gemini response was not a single valid project JSON object; inspect the visible response") from exc
    validate(value)
    if value["mode"] != mode or len(value["shots"]) != shots:
        raise StudioError("Gemini returned incorrect mode or shot count")
    return value


def director_prompt(idea: str, mode: str, title: str, shots: int, reference_count: int) -> str:
    example = preset(mode, title)
    return (
        "你是专业影视分镜导演。请直接返回一个合法的 JSON 对象，不能有 Markdown 代码围栏或说明文字。\n"
        "仅用创意与我上传的图片做素材，切勿声称你已经打开其他网页或实际拍摄视频。\n"
        f"创意：{idea}\n标题：{title}；模式：{mode}；镜头数量：{shots}。\n"
        f"已指定的参考图数量：{reference_count}。如果看到参考图，先分析画面，不要虚构材料及工序。\n"
        "每镜提供 id、scene、action、camera、duration、materials、beats、dialogue。"
        "handcraft 默认竖版 9:16 每镜10秒，明确材料真实可辨和手/工具执行每一步，无瞬移、无材料凭空出现。"
        "story 默认横版16:9每镜12秒，角色设定跨镜一致，避免多人同时说话，末段留至少1秒安静反应。"
        "beats 不重叠且在该镜头时长以内；有对白时包含 speaker、text、start、end。"
        "所有文字/字幕/UI 交给后期，生成提示词中不要要求模型绘制乱码文字。\n"
        "严格按此 JSON 字段结构输出，但必须重写主题和镜头：\n"
        + json.dumps(example, ensure_ascii=False, indent=2)
    )


class GeminiBrowser:
    def __init__(self, config_path: Path | None = None):
        self.config = load_gemini_ui(config_path)

    def preflight(self, references: list[Path]) -> None:
        """Read-only UI checks; no chat is submitted at this stage."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise StudioError("Install browser support: pip install -e '.[flow]'") from exc
        config = self.config
        for key in ("prompt_selector", "send_button_selector", "response_selector"):
            if not config[key]:
                raise StudioError(f"Set verified {key} in local Gemini UI config")
        if references and not config["reference_file_input_selector"] and not config["manual_references_loaded"]:
            raise StudioError("Reference images require a verified file input or explicit manual upload")
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(config["cdp_url"], timeout=15000)
            page = gemini_page(browser)
            one(page, config["prompt_selector"], "prompt")
            one(page, config["send_button_selector"], "send")
            # Multiple historical assistant replies are allowed; selector must match at least one after a reply.
            if references and config["reference_file_input_selector"]:
                one(page, config["reference_file_input_selector"], "file upload")

    def inspect(self, root: Path) -> Path:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise StudioError("Install browser support: pip install -e '.[flow]'") from exc
        output = root / "production" / "gemini_browser"
        output.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(self.config["cdp_url"], timeout=15000)
            page = gemini_page(browser)
            page.screenshot(path=str(output / "gemini_screenshot.png"), full_page=False)
            counts = {field: {"selector": self.config[field], "matches": page.locator(self.config[field]).count() if self.config[field] else 0}
                      for field in ("prompt_selector", "send_button_selector", "response_selector",
                                    "new_chat_button_selector", "reference_file_input_selector")}
            write_json(output / "ui_probe.json", {
                "url": page.url,
                "textboxes": page.get_by_role("textbox").count(),
                "textarea": page.locator("textarea").count(),
                "contenteditable": page.locator('[contenteditable="true"]').count(),
                "configured": counts,
            })
        return output / "ui_probe.json"

    def generate_plan(self, idea: str, mode: str, title: str, shots: int, references: list[Path]) -> dict:
        """Send a SINGLE web chat turn, then parse the most recent visible assistant reply.

        Caller persists 'submission_uncertain' before calling this method. Any timeout or
        invalid JSON must be resolved by operator; this method never retries.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise StudioError("Install browser support: pip install -e '.[flow]'") from exc
        cfg = self.config
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(cfg["cdp_url"], timeout=15000)
            page = gemini_page(browser)
            if cfg["new_chat_button_selector"]:
                one(page, cfg["new_chat_button_selector"], "new chat").click(timeout=10000)
            if references and cfg["reference_file_input_selector"]:
                one(page, cfg["reference_file_input_selector"], "upload").set_input_files([str(p) for p in references])
            locator = page.locator(cfg["response_selector"])
            original_count = locator.count()
            original_text = locator.last.inner_text(timeout=5000) if original_count else ""
            one(page, cfg["prompt_selector"], "prompt").fill(director_prompt(idea, mode, title, shots, len(references)))
            one(page, cfg["send_button_selector"], "send").click(timeout=15000)
            deadline = time.monotonic() + cfg["response_timeout_seconds"]
            previous = ""
            unchanged = 0
            while time.monotonic() < deadline:
                page.wait_for_timeout(1200)
                items = page.locator(cfg["response_selector"])
                if items.count() == 0:
                    continue
                current = items.last.inner_text(timeout=5000).strip()
                if not current or (items.count() == original_count and current == original_text):
                    continue
                if current == previous:
                    unchanged += 1
                else:
                    previous, unchanged = current, 0
                if unchanged >= cfg["stable_polls"]:
                    return extract_project(current, mode, shots)
            raise StudioError("Gemini visible response did not stabilize in time; check the page before retrying")
