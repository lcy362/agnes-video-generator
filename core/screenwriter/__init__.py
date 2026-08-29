"""core.screenwriter — AI 编剧 Agent（v5.0 Batch 4 拆分后的包入口）

Screenwriter 类由四个职责 mixin（story/scenes/characters/style）+ 本模块的
核心聊天基础设施组合而成；对外保留全部原符号（零调用点改动）。"""

import json
import logging
import os
import time as _time
from typing import List, Optional

from core.api.agnes_chat import AgnesChatAPI

from .characters import ScreenwriterCharactersMixin
from .scenes import ScreenwriterScenesMixin
from .story import (
    ScreenwriterStoryMixin,
    _xml_escape,  # 兼容 re-export（develop_story 使用）
    clean_narration_text,  # 兼容 re-export（外部 pipeline 导入）
)
from .style import ScreenwriterStyleMixin

logger = logging.getLogger(__name__)

# 提示词语言配置：通过环境变量 PROMPT_LANGUAGE 切换
#   "zh" — 所有 meta-prompt 使用中文（默认）
#   "en" — 所有 meta-prompt 使用英文
# 示例：export PROMPT_LANGUAGE=en
PROMPT_LANGUAGE = os.environ.get("PROMPT_LANGUAGE", "zh")

# 图片描述重试间隔基数（秒）：delay = 基数 * (attempt + 1)
_DESCRIBE_RETRY_BASE_DELAY_SECONDS = 15


class Screenwriter(
    ScreenwriterStoryMixin,
    ScreenwriterScenesMixin,
    ScreenwriterCharactersMixin,
    ScreenwriterStyleMixin,
):
    """AI 编剧 Agent：故事/脚本/旁白/角色/尾帧/诗词场景/字幕样式生成。

    v5.0 Batch 4（S5）拆分：核心聊天基础设施（直接使用 AgnesChatAPI）保留在本
    模块，其余方法按职责拆入 story/scenes/characters/style 四个 mixin。
    对外接口与拆分前完全一致（mixin 组合，方法经 MRO 解析）。
    """

    def __init__(self, api_key: str, model: str = "agnes-2.0-flash", language: str = None):
        self.api_key = api_key
        self.model = model
        self.language = language if language else PROMPT_LANGUAGE  # "zh" 中文 / "en" 英文
        self.chat_api = AgnesChatAPI(api_key=api_key, model=model)
        # 保持旧 headers 供直接引用（兼容）
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _prompt(self, zh_text: str, en_text: str) -> str:
        """根据 language 设置返回中文或英文提示词。"""
        return zh_text if self.language == "zh" else en_text

    def _chat(self, system_prompt: str, user_prompt: str) -> str:
        return self.chat_api.chat(system_prompt, user_prompt)

    def _chat_json(self, system_prompt: str, user_prompt: str) -> dict:
        return self.chat_api.chat_json(system_prompt, user_prompt)

    def _image_to_b64_uri(self, path: str) -> str:
        return self.chat_api._image_to_b64_uri(path)

    def _chat_multimodal(self, system_prompt: str, text_prompt: str, image_paths: List[str]) -> str:
        return self.chat_api.chat_multimodal(system_prompt, text_prompt, image_paths)

    def describe_images(self, image_paths: List[str], cache_dir: str = "", language_hint: str = "") -> str:
        if not image_paths:
            return ""


        single_prompt = self._prompt(
            zh_text="""\
请用丰富的视觉细节描述这张图片。包括角色（服装、体型、发型、姿势）、\
环境、色彩与光线、艺术风格和氛围。用自然语言写 3-5 句话——就像口述给\
故事编剧一样。不要写"图片展示了"——直接描述你看到的内容。用中文输出。
""",
            en_text="""\
Describe this image in rich visual detail. Note the character(s), their \
appearance (clothing, body type, hair, pose), the environment, colors and \
lighting, art style, and mood. Write 3-5 sentences in natural language — as if \
dictating to a story writer. Do NOT say "the image shows" — just describe what \
you see directly. Write in Chinese if the content appears Chinese, English \
otherwise.
""",
        )

        describe_text = self._prompt(
            zh_text="请描述这张图片。",
            en_text="Describe this image.",
        )

        label_start = self._prompt(
            zh_text="起始帧",
            en_text="Start Frame",
        )

        label_end = self._prompt(
            zh_text="尾帧",
            en_text="End Frame",
        )

        total = len(image_paths)

        cached_descriptions = {}
        cache_file = ""
        if cache_dir:
            cache_file = os.path.join(cache_dir, "image_analysis.json")
            if os.path.exists(cache_file):
                try:
                    with open(cache_file, "r", encoding="utf-8") as f:
                        cached = json.load(f)
                    if cached.get("image_paths") == image_paths:
                        cached_descriptions = cached.get("descriptions", {})
                        # 过滤掉失败的错误描述，强制重新分析
                        cached_descriptions = {
                            k: v for k, v in cached_descriptions.items()
                            if not v.startswith("(分析失败")
                        }
                        if cached_descriptions:
                            logger.info(f"[Screenwriter] Loaded {len(cached_descriptions)} cached descriptions")
                except Exception as e:
                    logger.debug(f"[Screenwriter] Failed to load image description cache: {e}")

        logger.info(f"[Screenwriter] Describing {total} images one by one...")

        descriptions = []
        for i, img_path in enumerate(image_paths):
            if i == 0:
                label = label_start
            else:
                label = f"{label_end} {i - 1}"

            cache_key = str(i)
            if cache_key in cached_descriptions:
                desc = cached_descriptions[cache_key]
                descriptions.append(f"[{label}] {desc.strip()}")
                continue

            desc = self._describe_with_retry(single_prompt, img_path, label, describe_text)
            descriptions.append(f"[{label}] {desc.strip()}")

            if cache_file:
                cached_descriptions[cache_key] = desc.strip()
                try:
                    with open(cache_file, "w", encoding="utf-8") as f:
                        json.dump({
                            "image_paths": image_paths,
                            "descriptions": cached_descriptions,
                        }, f, ensure_ascii=False, indent=2)
                except Exception as e:
                    logger.debug(f"[Screenwriter] Failed to write image description cache: {e}")

        combined = "\n\n".join(descriptions)
        logger.info(f"[Screenwriter] All {total} images described: {len(combined)} chars")
        return combined

    def _describe_with_retry(self, prompt: str, img_path: str, label: str, text_prompt: str = None, max_retries: int = 3) -> str:
        if text_prompt is None:
            text_prompt = self._prompt(zh_text="请描述这张图片。", en_text="Describe this image.")
        for attempt in range(max_retries):
            try:
                return self._chat_multimodal(prompt, text_prompt, [img_path])
            except Exception as e:
                if attempt < max_retries - 1:
                    delay = _DESCRIBE_RETRY_BASE_DELAY_SECONDS * (attempt + 1)
                    logger.warning(
                        f"[Screenwriter] {label} attempt {attempt+1}/{max_retries} failed: {e}. "
                        f"Retrying in {delay}s..."
                    )
                    _time.sleep(delay)
                else:
                    logger.error(f"[Screenwriter] {label} failed after {max_retries} attempts: {e}")
                    raise RuntimeError(
                        f"图片分析失败（{label}）: {e}"
                    ) from e

def build_poetry_scene_prompt(
    poem: str,
    scene_count: int = 0,
    scene_durations: Optional[List[int]] = None,
    total_duration: int = 30,
    style: str = "",
) -> dict:
    """返回已填充的诗歌分镜提示词（中文），供前端展示与复制。

    直接复用内部 LLM 所用的 ``_poetry_scene_prompts``，并用同一份参数
    （poem / scene_count / scene_durations / total_duration / style）填充，
    保证「用户拿去外部 LLM 生成后贴回」与「系统内 LLM 生成」提示词逐字一致。
    """
    sw = Screenwriter(api_key="", language="zh")
    system_prompt, user_prompt = sw._poetry_scene_prompts(
        poem, scene_count, scene_durations or [], total_duration, style)
    return {"system_prompt": system_prompt, "user_prompt": user_prompt}

__all__ = [
    "Screenwriter",
    "clean_narration_text",
    "build_poetry_scene_prompt",
    "_xml_escape",
    "ScreenwriterStoryMixin",
    "ScreenwriterScenesMixin",
    "ScreenwriterCharactersMixin",
    "ScreenwriterStyleMixin",
]

