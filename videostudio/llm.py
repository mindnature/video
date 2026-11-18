"""Optional OpenAI-compatible LLM draft creation; never used without explicit command."""
from __future__ import annotations

import base64
import json
import mimetypes
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import quote

from .core import StudioError, validate
from .templates import preset


def draft(idea: str, mode: str, title: str, count: int | None = None, provider: str = "compatible", images: list[Path] | None = None) -> dict:
    if provider not in ("compatible", "gemini"):
        raise StudioError("provider must be compatible or gemini")
    example = preset(mode, title)
    if count is None:
        count = 6 if mode == "handcraft" else 5
    instructions = (
        "你是专业影视导演与视频模型制作技术总监。严格返回一个 JSON 对象，不要代码围栏。"
        "JSON 必须符合以下范例的字段结构（但创作全新内容）：" + json.dumps(example, ensure_ascii=False) + "。"
        f"必须生成 {count} 个镜头；mode={mode}，作品标题={title}。"
        "每个镜头必须包含 id, scene, action, camera, duration, materials, beats, dialogue。"
        "handcraft 时每镜10秒，9:16，明确真正可由手和工具完成的材料工序，不可跳步、瞬间变形或漂浮。"
        "story 时每镜12秒，16:9，固定角色识别词，单个时间段仅一名角色讲话，最后留1.5秒无声。"
        "beats 按时间递增不重叠，每个区间不得超过本镜时长；dialogue 每条须包含speaker,text,start,end。"
        "请用可执行的具体动作，而非空洞的形容词。"
    )
    if provider == "gemini":
        key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        model = os.getenv("GEMINI_MODEL")
        if not key or not model:
            raise StudioError("Set GEMINI_API_KEY and GEMINI_MODEL for --provider gemini; the model must be available to your account")
        url = "https://generativelanguage.googleapis.com/v1beta/models/" + quote(model, safe="") + ":generateContent"
        parts = [{"text": idea}]
        for image in images or []:
            image = Path(image)
            if image.stat().st_size > 12 * 1024 * 1024:
                raise StudioError(f"Image too large (>12MB): {image.name}; resize before calling Gemini")
            mime, _ = mimetypes.guess_type(image.name)
            if mime not in ("image/jpeg", "image/png", "image/webp"):
                raise StudioError(f"Unsupported reference image type: {image.suffix}")
            parts.append({"inline_data": {"mime_type": mime,
                                          "data": base64.b64encode(image.read_bytes()).decode("ascii")}})
        payload = {"systemInstruction": {"parts": [{"text": instructions}]},
                   "contents": [{"role": "user", "parts": parts}],
                   "generationConfig": {"responseMimeType": "application/json", "temperature": 0.5}}
        headers = {"x-goog-api-key": key, "Content-Type": "application/json"}
    else:
        if images:
            raise StudioError("Image references are supported only by --provider gemini")
        base = os.getenv("VIDEO_LLM_BASE_URL", "").rstrip("/")
        key = os.getenv("VIDEO_LLM_API_KEY", "")
        model = os.getenv("VIDEO_LLM_MODEL", "")
        if not (base and key and model):
            raise StudioError("Set VIDEO_LLM_BASE_URL, VIDEO_LLM_API_KEY and VIDEO_LLM_MODEL before 'draft'.")
        if not base.startswith("https://") and not base.startswith("http://127.0.0.1") and not base.startswith("http://localhost"):
            raise StudioError("LLM endpoint must be HTTPS (or localhost for a local model).")
        url = base + "/chat/completions"
        payload = {"model": model, "messages": [{"role": "system", "content": instructions},
                                                 {"role": "user", "content": idea}], "temperature": 0.5}
        headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
    request = Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    try:
        with urlopen(request, timeout=120) as resp:
            obj = json.load(resp)
    except (HTTPError, URLError) as exc:
        raise StudioError(f"LLM request failed: {type(exc).__name__} ({getattr(exc, 'code', 'connection')})") from exc
    try:
        content = (obj["candidates"][0]["content"]["parts"][0]["text"] if provider == "gemini"
                   else obj["choices"][0]["message"]["content"]).strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        result = json.loads(content)
        validate(result)
        if len(result["shots"]) != count or result["mode"] != mode:
            raise StudioError("Generated JSON has wrong number of shots or mode; retry or edit manually")
        return result
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise StudioError("LLM response is not valid project JSON; try again or use init preset") from exc
