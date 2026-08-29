"""core.screenwriter.scenes — 分镜/段落场景 prompt/诗词场景方法（Batch 4 拆分）"""
import logging
import re
from typing import List, Optional

from core.api.agnes_chat import strip_code_fence

logger = logging.getLogger(__name__)


class ScreenwriterScenesMixin:
    """分镜设计/段落场景 prompt/诗词场景拆分方法（Batch 4 拆分）。"""

    def design_shots_for_scene(self, scene_text: str, style: str, max_shots: int = 5) -> list:
        system_prompt = self._prompt(
            zh_text="""\
你是一位专业的分镜师。为单个场景设计镜头。

[输出格式] 返回一个 JSON 对象：
{
  "shots": [
    {
      "visual_desc": "镜头的整体视觉描述",
      "variation_type": "large|medium|small",
      "ff_desc": "首帧——静态快照描述",
      "lf_desc": "末帧——静态快照描述",
      "motion_desc": "帧间运动。对话格式：<角色>说：\\"文本\\"",
      "audio_desc": "[音效] 描述"
    }
  ]
}

规则：
- 第一个镜头必须建立场景环境。
- 最后一个镜头应自然地结束场景。
- variation_type："large"（大幅场景变化）、"medium"（新元素出现）、"small"（微小运动）
- 首帧/末帧描述是静态图像——不使用运动词汇。
- 运动描述包含所有动作和对话。
- 包含丰富的视觉细节用于图像生成（光线、色彩、构图）。
- 使用与输入场景相同的语言输出。

构图用词指导：
- 戏剧性/紧张场景："具有强烈对角线的引人注目构图"、\
"紧凑取景增强幽闭感"、"低角度强调权力关系"、\
"推镜营造张力升级"。
- 情感节拍用电影化速写："更宽广的取景创造情感距离"、\
"浅景深将角色孤立在情感中"、\
"缓慢的轨道后拉揭示时刻的分量"。
- 动作/兴奋场景："充满动能的动态构图"、\
"快速摇镜暗示混乱"、"爆发式运动定格在画面中"。
- 浪漫/亲密内容："特写中的柔和温暖亲密感"、\
"沐浴在柔和金色光线中"、"中景取景中温柔相依"。
- 使用专业的电影摄影术语和视觉构图语言表达所有叙事内容。

使用与输入场景相同的语言输出。
""",
            en_text="""\
You are a professional storyboard artist. Design shots for a single scene.

[Output Format] Return a JSON object:
{
  "shots": [
    {
      "visual_desc": "Overall visual description of the shot",
      "variation_type": "large|medium|small",
      "ff_desc": "First frame — static snapshot description",
      "lf_desc": "Last frame — static snapshot description",
      "motion_desc": "Motion between frames. Include dialogue as: <Char> says: \\"text\\"",
      "audio_desc": "[Sound Effect] description"
    }
  ]
}

Rules:
- First shot must establish the scene environment.
- Last shot should end the scene naturally.
- variation_type: "large" (big scene change), "medium" (new element appears), "small" (minor movement)
- First/last frame descriptions are STATIC images — no motion words.
- Motion description includes all movement AND dialogue.
- Include rich visual details for image generation (lighting, colors, composition).
- Output in the SAME LANGUAGE as the input scene.

VOCABULARY GUIDANCE FOR COMPOSITION:
- For dramatic/tension-filled scenes: "striking composition with strong diagonals", \
"tight framing heightens claustrophobic feel", "low angle emphasizes power dynamic", \
"camera push creates mounting intensity".
- Use cinematic shorthand for emotional beats: "wider shot creates emotional \
distance", "shallow focus isolates the character emotionally", \
"slow dolly pull reveals the gravity of the moment".
- Frame action/excitement as: "dynamic composition with kinetic energy", \
"rapid whip-pan suggests chaos", "explosive movement captured in frame".
- Frame romantic/intimate content as: "soft, warm intimacy in close-up", \
"bathing in gentle golden light", "tender proximity framed in medium shot".
- Express ALL narrative content through professional cinematography terminology \
and visual composition language.

Output in the SAME LANGUAGE as the input scene.
""",
        )
        user_prompt = f"""\
<scene>
{scene_text}
</scene>

<style>{style}</style>
<max_shots>{max_shots}</max_shots>
"""
        logger.info("[Screenwriter] Designing shots for scene...")
        result = self._chat_json(system_prompt, user_prompt)
        shots = result.get("shots", [])
        logger.info(f"[Screenwriter] Designed {len(shots)} shots")
        return shots

    def generate_scene_prompt_for_paragraph(self, text: str, style: str = "") -> str:
        """为稿件段落生成视频场景 prompt（语言跟随输入段落）。

        基于段落语义生成适合 AI 视频生成的视觉描述，
        原文将直接作为旁白文本 + 字幕内容（D2 决策）。

        Args:
            text: 段落文本
            style: 风格描述（可选）

        Returns:
            视频 prompt 字符串（语言与输入一致）
        """
        system_prompt = self._prompt(
            zh_text="""\
你是一位专业的视频导演和视觉提示词工程师。给定一段\
将作为旁白朗读的文本，请生成一个详细的视觉描述\
用于 AI 视频生成。

规则：
- 使用与输入段落相同的语言编写详细的视觉描述，\
80-150 词。
- 聚焦于：环境、光线、色彩、镜头运动、氛围、情绪。
- 包含电影感细节：镜头类型、景深、调色、\
天气、时间。
- 不要在描述中包含任何文字叠加、标题或字幕。
- 不要描述旁白本身——描述观众看到的内容。
- 视觉应补充和增强文本的含义。
- 描述动作和动态，而非静态图像。

用词指导：
- 使用电影化语言传达情感基调："充满张力的氛围"、\
"戏剧性光线"、"亲密取景"、"富有诗意的镜头运动"。
- 对于紧张或激烈的段落，依靠视觉隐喻和氛围\
描述："随着张力升级阴影加深"、"不安的镜头运动\
映射内心动荡"、"光与影的强烈对比"。
- 对于情感共鸣的时刻："轻柔的镜头推进捕捉到\
温柔"、"温暖色调唤起怀旧"、"柔焦赋予\
梦幻质感"。
- 通过镜头所见来表达叙事冲击力——让视觉\
构图承载情感分量。

只输出视觉提示词文本，不要 JSON，不要解释。
""",
            en_text="""\
You are a professional video director and visual prompt engineer. Given a \
paragraph of text that will be narrated as voiceover, generate a \
detailed VISUAL DESCRIPTION for AI video generation.

Rules:
- Write a detailed VISUAL DESCRIPTION in the SAME LANGUAGE as the input paragraph, \
80-150 words.
- Focus on: environment, lighting, colors, camera movement, atmosphere, mood.
- Include cinematic details: lens type, depth of field, color grading, \
weather, time of day.
- Do NOT include any text overlays, titles, or subtitles in the description.
- Do NOT describe the narration itself — describe what the VIEWER SEES.
- The visual should complement and enhance the meaning of the text.
- Describe MOTION and ACTION, not a static image.

VOCABULARY GUIDANCE:
- Use cinematic language to convey emotional tone: "charged atmosphere", \
"dramatic lighting", "intimate framing", "lyrical camera movement".
- For intense or tense segments, rely on visual metaphor and atmospheric \
description: "shadows deepen as tension mounts", "restless camera work \
mirrors inner turmoil", "stark contrast between light and shadow".
- For emotionally resonant moments: "gentle camera push captures the \
tenderness", "warm color palette evokes nostalgia", "soft focus lends a \
dreamlike quality".
- Express the narrative impact through what the CAMERA sees — let visual \
composition carry the emotional weight.

Output ONLY the visual prompt text, no JSON, no explanation.
""",
        )
        style_block = f"\n<style>{style}</style>\n" if style else ""
        user_prompt = f"""\
<paragraph>
{text}
</paragraph>
{style_block}
{self._prompt(
    zh_text="请为此段落生成一个详细的视觉提示词。",
    en_text="Generate a detailed visual prompt for this paragraph."
)}
"""
        logger.info(f"[Screenwriter] Generating scene prompt for paragraph ({len(text)} chars)...")
        prompt = strip_code_fence(self._chat(system_prompt, user_prompt))
        logger.info(f"[Screenwriter] Scene prompt: {prompt[:100]}...")
        return prompt

    def generate_poetry_scenes(
        self,
        poem_text: str,
        scene_count: int = 0,
        scene_durations: Optional[List[int]] = None,
        total_duration: int = 30,
        style: str = "",
    ) -> List[dict]:
        """LLM 拆分整首诗词为若干场景（朗诵文案 + 视频 prompt），以行格式返回。

        与「用户直接粘贴的分镜描述」保持同一格式：``原诗句 | 画面描述``。
        每行一个场景，「|」左为对应原诗片段（narration），右为视频画面描述。
        这样内部 LLM 生成与外部 LLM（用户拿同样提示词生成后贴回）输出完全一致。

        Args:
            poem_text: 整首诗词原文。
            scene_count: 期望分镜数；0 表示自动（prompt 来源模式）。
            scene_durations: 各场景时长（秒）列表；非空时提示词写出每场景时长+合计，
                与可复制提示词、实际视频生成时长完全一致。
            total_duration: 目标总时长（秒），用于 prompt/auto 模式把握节奏。
            style: 视觉风格（与创意视频一致），注入每个场景画面描述。

        Returns:
            场景列表，每个元素为 {"narration": str, "scene_prompt": str}。
            朗诵文案严格保留原诗文字，不改写不翻译。
        """
        system_prompt, user_prompt = self._poetry_scene_prompts(
            poem_text, scene_count, scene_durations or [], total_duration, style)
        logger.info(
            f"[Screenwriter] Splitting poem into scenes (count={scene_count or 'auto'}, "
            f"durations={scene_durations or 'auto'})..."
        )
        raw = self._chat(system_prompt, user_prompt)
        scenes = self._parse_poetry_scene_lines(raw)
        logger.info(f"[Screenwriter] Poetry scenes: {len(scenes)}")
        return scenes

    def _poetry_scene_prompts(
        self,
        poem_text: str,
        scene_count: int,
        scene_durations: List[int],
        total_duration: int,
        style: str,
    ) -> tuple:
        """返回（system_prompt, user_prompt）。

        内部 LLM 与外部 LLM（用户拿同样提示词生成后贴回）共用此提示词，
        UI 端点 ``build_poetry_scene_prompt`` 也复用同一份，保证格式一致。
        时长表达：有每场景时长时写出「各场景时长：d1,d2…秒（合计T秒）」，
        否则（auto/prompt 模式）写「目标总时长：T秒」。
        """
        count_hint = (
            f"{scene_count} 个" if scene_count and scene_count > 0
            else "由你依据诗意自行决定（通常 2-6 个）"
        )
        if scene_durations:
            dur_list = "、".join(f"{d}秒" for d in scene_durations)
            total = sum(scene_durations)
            dur_hint = f"各场景时长：{dur_list}（合计 {total} 秒）"
        else:
            dur_hint = f"目标总时长：{total_duration} 秒（用于把握节奏，不要求每句等长）"
        style_hint = style.strip() if style and style.strip() else "未指定，请采用通用电影质感写实风格"
        system_prompt = self._prompt(
            zh_text="""你是一位诗意的视觉艺术家兼诗词分镜导演，专精将中国古典诗词转化为视频分镜。
请将整首诗拆分为若干场景，每个场景一行，严格使用如下格式：

原诗句 | 画面描述

规则：
- 「|」左侧为该场景对应的原诗片段（朗诵文案），严格保留原诗文字，不要改写、翻译或意译；
- 「|」右侧为该场景的视频画面描述（只描述视觉，15-30 字，不描述声音或文字）；
- 按诗意的自然段落或意象切分场景，使每段画面连贯且独立；
- 每行一个场景，不要编号、不要解释、不要输出 JSON、不要使用代码块围栏。
示例：
春眠不觉晓，处处闻啼鸟。 | 春日清晨薄雾，枝头鸟鸣
夜来风雨声，花落知多少。 | 夜雨敲窗，落花满地青石""",
            en_text="""You are a poetic visual artist and poetry storyboard director specializing in transforming classical poetry into video scenes.
Split the whole poem into scenes, ONE scene per line, strict format:

original verse | visual description

Rules:
- Left of "|" is the original poem line(s) verbatim (narration); do NOT rewrite/translate/paraphrase.
- Right of "|" is the visual description (15-30 words, visuals only, no audio/text).
- Split by stanzas or imagery; coherent, self-contained scenes.
- One scene per line; no numbering, no explanation, no JSON, no code fences.
Example:
Spring sleeps, unaware of dawn... | Misty spring morning, birds singing
Night rain, wind sounds... | Rain on window, petals on stone""",
        )
        user_prompt = f"""<poem>
{poem_text}
</poem>

<requirements>
- 场景数量：{count_hint}
- {dur_hint}
- 视觉风格：{style_hint}（请将该风格融入每个场景的画面描述）
</requirements>
"""
        return system_prompt, user_prompt

    def _parse_poetry_scene_lines(self, raw: str) -> List[dict]:
        """把 LLM 返回的行格式文本解析为场景列表。

        每行 ``原诗句 | 画面描述``；无 ``|`` 的行视为纯画面描述（诗句留空）。
        自动去除编号/标签前缀（如「1. 」「场景1：」），对外部 LLM 的输出更鲁棒。
        """
        if not raw:
            return []
        raw = strip_code_fence(raw)
        scenes: List[dict] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            # 跳过纯场景标签行（如「场景 1（00:00 - 00:10）」），避免被误判为分镜
            if re.match(r"^(场景|Scene)\s*\d+", line, re.IGNORECASE):
                continue
            # 去掉可能的编号/标签前缀
            line = re.sub(r"^[\d]+\s*[\.、)]\s*", "", line)
            line = re.sub(r"^(场景|Scene)\s*\d*\s*[:：]\s*", "", line, flags=re.IGNORECASE)
            if "|" in line:
                verse, _, prompt = line.partition("|")
                verse = verse.strip()
                prompt = prompt.strip()
            else:
                # 纯画面描述（无诗句）：诗句留空，由调用方处理
                verse, prompt = "", line
            if not prompt:
                continue
            scenes.append({"narration": verse, "scene_prompt": prompt})
        return scenes
