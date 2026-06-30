import base64
import html
import json
import logging
import mimetypes
import os
import re
import time as _time
import requests
from typing import List

from core.api.agnes_chat import AgnesChatAPI, strip_code_fence

logger = logging.getLogger(__name__)

BASE_URL = "https://apihub.agnes-ai.com/v1"

# 提示词语言配置：通过环境变量 PROMPT_LANGUAGE 切换
#   "zh" — 所有 meta-prompt 使用中文（默认）
#   "en" — 所有 meta-prompt 使用英文
# 示例：export PROMPT_LANGUAGE=en
PROMPT_LANGUAGE = os.environ.get("PROMPT_LANGUAGE", "zh")


def _xml_escape(text: str) -> str:
    """XML 转义用户输入，防止 prompt 注入。

    将 < > & " ' 转义为 XML 实体，避免用户输入中的标签
    提前闭合 XML 结构（如 </idea>）导致指令注入。
    """
    if not text:
        return text
    return html.escape(text, quote=True)


class Screenwriter:
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

        has_chinese = (
            bool(re.search(r'[\u4e00-\u9fff]', language_hint))
            if language_hint
            else self.language == "zh"
        )

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
                    delay = 15 * (attempt + 1)
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

    def extract_scene_info_from_idea(self, idea: str, style: str) -> dict:
        """从创意描述中提取场景数和每个场景的时长。

        当用户选择「从 prompt 中获取」时调用，让 LLM 分析 idea 文本，
        提取其中暗含的场景数量和每场景时长。如果提取失败，抛出异常。

        Args:
            idea: 用户的创意描述文本。
            style: 视觉风格描述。

        Returns:
            dict{"scene_count": int, "durations": [int, ...]}

        Raises:
            RuntimeError: 无法从 idea 中提取到场景信息。
        """
        system_prompt = self._prompt(
            zh_text="""\
你是一个视频制作需求分析专家。仔细阅读用户的创意描述，提取其中关于
场景数量和每场景时长的信息。

输出一个 JSON 对象：
{
  "scene_count": 3,
  "durations": [5, 8, 12],
  "reasoning": "分析依据的简要说明"
}

规则：
- scene_count: 从描述中推断的场景数量，整数。如果描述中提到"几个场景"、\
"几幕"等，提取明确的数字。如果描述是故事性叙述（如"一个小男孩在森林里迷路了，\
后来遇到了精灵..."），根据故事情节合理拆分（一般 3-6 个场景）。
- durations: 每个场景的建议时长（秒），列表长度等于 scene_count。\
如果描述中提到具体时长（如"每个场景5秒"、"第一幕10秒"、"3个8秒的场景"），\
使用这些值；否则根据每个场景的内容复杂度合理估计（3-15 秒之间）。
- reasoning: 用与输入相同的语言，简要说明提取/推断的依据。

约束：
- 如果 idea 中完全没有任何关于场景数或时长的线索，返回一个空对象 {}，\
表示提取失败。
- 不要编造不存在的数字。
- 每个场景时长不超过 30 秒，不少于 2 秒。
""",
            en_text="""\
You are a video production requirements analyst. Read the user's creative idea
carefully and extract information about the number of scenes and per-scene duration.

Output a JSON object:
{
  "scene_count": 3,
  "durations": [5, 8, 12],
  "reasoning": "Brief explanation of the analysis"
}

Rules:
- scene_count: the number of scenes inferred from the description, as an integer.
- durations: suggested duration (in seconds) for each scene. List length must equal\
scene_count. If specific durations are mentioned, use those values; otherwise estimate\
based on content complexity (3-15 seconds).
- reasoning: in the same language as input, briefly explain the extraction logic.

Constraints:
- If the idea contains NO clues about scene count or durations, return an empty object\
{}, indicating extraction failure.
- Do not fabricate numbers that don't exist in the text.
- Each scene duration must be between 2 and 30 seconds.
""",
        )
        user_prompt = f"""\
<style>{style}</style>

<idea>
{idea}
</idea>
"""
        logger.info("[Screenwriter] Extracting scene info from idea...")
        result = self._chat_json(system_prompt, user_prompt)

        scene_count = result.get("scene_count")
        durations = result.get("durations")

        if not scene_count or not durations or len(durations) != scene_count:
            reasoning = result.get("reasoning", "")
            logger.error(
                f"[Screenwriter] Failed to extract scene info from idea: "
                f"scene_count={scene_count}, durations={durations}, reasoning={reasoning}"
            )
            raise RuntimeError(
                "无法从创意描述中提取场景数和时长信息。"
                "请手动设置场景数和每场景时长，或修改创意描述使其包含更明确的场景信息。"
            )

        # 校验时长范围
        for i, d in enumerate(durations):
            if d < 2 or d > 30:
                durations[i] = max(2, min(30, d))

        logger.info(
            f"[Screenwriter] Extracted scene info: {scene_count} scenes, "
            f"durations={durations}"
        )
        return {"scene_count": scene_count, "durations": durations}

    def develop_story(self, idea: str, user_requirement: str = "", style: str = "",
                      image_context: str = "", scene_count: int = 0,
                      scene_durations: List[int] = None) -> str:
        """Develop a story from the idea, with optional scene configuration.

        Args:
            idea: Creative idea text.
            user_requirement: (deprecated) Old-style user requirement string.
                Kept for backward compat; overridden by scene_count/scene_durations
                when provided.
            style: Visual style description.
            image_context: Optional image analysis context.
            scene_count: Number of scenes (v3.x).
            scene_durations: Per-scene durations in seconds (v3.x).
        """
        # Build scene requirement string for the LLM prompt
        if scene_count > 0 and scene_durations:
            durations_str = "、".join(f"场景{i+1} {d}秒" for i, d in enumerate(scene_durations))
            requirement_text = f"共 {scene_count} 个场景，时长分别为：{durations_str}"
        elif scene_count > 0:
            requirement_text = f"共 {scene_count} 个场景"
        elif user_requirement:
            requirement_text = user_requirement
        else:
            requirement_text = "3个场景，每场景5秒，电影质感"

        system_prompt = self._prompt(
            zh_text="""\
你是一位经验丰富的创意故事生成专家。你将创意想法扩展为结构清晰、\
有明确场景、角色和对白的完整故事。

[输出格式] 一个包含以下内容的完整故事：
- 故事标题
- 目标受众与类型
- 故事大纲（1 段）
- 主要角色介绍（含详细的外貌描述）
- 完整故事叙述（引入 → 发展 → 高潮 → 结局）

重要提示：请使用与输入想法相同的语言来撰写故事。
保持简洁但生动，适合改编为短视频场景。
包含详细的角色外貌描述（服装、体型、发型、\
显著特征、配色方案），以确保图像生成的一致性。

叙事指导：
- 使用富有感染力的文学语言，通过氛围、张力和潜台词来传达情感深度，\
而非直白的描写。
- 对于紧张或激烈的情节：通过电影感氛围、情感布局、\
凝重的寂静、视觉符号和角色反应来表达。
- 浪漫或亲密段落：聚焦情感联结、温柔的举止、\
意味深长的对视和当下的氛围。
- 动作/张力段落：强调博弈、紧迫感、决心，通过充满能量的节奏呈现视觉张力。
- 故事将被改编为视频——描述发生了什么以及感受如何，用适合电影化呈现的语言。
""",
            en_text="""\
You are a seasoned creative story generation expert. You expand ideas into \
well-structured stories with clear scenes, characters, and dialogue.

[Output] A complete story in paragraphs with:
- Story Title
- Target Audience & Genre
- Story Outline (1 paragraph)
- Main Characters Introduction (with detailed appearance descriptions)
- Full Story Narrative (Introduction -> Development -> Climax -> Conclusion)

IMPORTANT: Write the story in the SAME LANGUAGE as the input idea.
Keep it concise but vivid, suitable for adaptation into short video scenes.
Include DETAILED character appearance descriptions (clothing, body type, \
hair, distinguishing features, color palette) to enable consistent image generation.

STORYTELLING GUIDANCE:
- Use evocative, literary language that conveys emotional depth through \
atmosphere, tension, and subtext rather than explicit depictions.
- For intense or charged moments, express through: cinematic atmosphere, \
emotional staging, charged silences, visual symbolism, and character reactions.
- Romantic or intimate beats: focus on emotional connection, tender gestures, \
meaningful glances, and the mood of the moment.
- Action/tension: emphasize stakes, urgency, determination, and the visual \
drama of the situation through energetic pacing.
- The story will be adapted into video — describe what HAPPENS and how it \
FEELS, using language suitable for cinematic interpretation.
""",
        )
        user_prompt = f"""\
<idea>
{_xml_escape(idea)}
</idea>

<user_requirement>
{_xml_escape(requirement_text)}
</user_requirement>

<style>
{_xml_escape(style)}
</style>
"""
        if image_context:
            image_context_instruction = self._prompt(
                zh_text="""以下内容描述了将用作视频关键帧的实际图片。
故事必须与下方描述的视觉内容保持一致——使用相同的\
角色、场景、色彩和氛围。""",
                en_text="""The following describes actual images that will be used as keyframes in the video.
The story MUST align with the visual content described below — use the same
characters, settings, colors, and mood.""",
            )
            user_prompt += f"""
<image_context>
{image_context_instruction}

{image_context}
</image_context>
"""
        logger.info("[Screenwriter] Developing story..." + (" (with image context)" if image_context else ""))
        story = self._chat(system_prompt, user_prompt)
        logger.info(f"[Screenwriter] Story developed: {len(story)} chars")
        return story

    def write_script(self, story: str, user_requirement: str = "", style: str = "",
                     scene_count: int = 0, scene_durations: List[int] = None) -> List[str]:
        """Write a scene-by-scene visual script.

        Args:
            story: Full story text.
            user_requirement: (deprecated) Old-style requirement string.
                Overridden by scene_count/scene_durations when provided.
            style: Visual style.
            scene_count: Target number of scenes (v3.x).
            scene_durations: Per-scene durations in seconds (v3.x).
        """
        # Build scene requirement string
        if scene_count > 0 and scene_durations:
            durations_str = "、".join(f"场景{i+1} {d}秒" for i, d in enumerate(scene_durations))
            requirement_text = (
                f"共 {scene_count} 个场景，时长分别为：{durations_str}。"
                f"每个场景的视觉提示词应与其时长匹配——时长较短的场景简洁有力，"
                f"时长较长的场景细节丰富。"
            )
        elif scene_count > 0:
            requirement_text = f"共 {scene_count} 个场景"
        elif user_requirement:
            requirement_text = user_requirement
        else:
            requirement_text = "3个场景，每场景5秒，电影质感"

        system_prompt = self._prompt(
            zh_text="""\
你是一位专业的视频导演和视觉提示词工程师。请将给定的故事改编为\
面向 AI 视频生成的详细视觉场景描述。

[输出格式] 返回一个 JSON 对象：
{
  "scenes": [
    "场景 1 视觉提示词...",
    "场景 2 视觉提示词...",
    ...
  ]
}

规则：
- 每个场景必须是详细的视觉描述，使用与输入故事相同的语言。
- 不要包含尖括号中的角色名称或对话标签。
- 聚焦于：镜头运动、光线、色彩、环境、角色动作、氛围、情绪。
- 包含具体的视觉细节：镜头类型（广角/长焦）、景深、拍摄角度、\
光源方向、调色、粒子效果、天气。
- 每个场景 80-150 词，充满电影感细节。
- 保持场景间的视觉一致性（相同的角色外观、连贯的世界观）。
- 场景数量必须遵守用户需求的约束条件。
- 艺术风格应与请求的风格匹配（写实电影感、动漫等）。
- 描述动作和动态，而非静态图像——这是用于视频生成的。

紧张/激烈内容的用词指导：
- 通过电影感术语来构图戏剧性或紧张的时刻："紧张对峙"\
"戏剧性对抗"、"充满张力的氛围"、"高风险遭遇"。
- 使用符合类型的视觉语言："暗黑奇幻美学"、"黑色电影光影"、\
"哥特式氛围"、"心理惊悚布光"。
- 通过光线和构图传达情感强度："强烈的阴影暗示紧张"、\
"温暖的金色光线唤起亲密感"、"冷蓝色调营造不安"。
- 动作场面："动态镜头运动"、"快速蒙太奇剪辑"、\
"爆发式编排"、"充满能量的动感"。
- 浪漫/亲密场景："温柔靠近"、"温暖拥抱"、"亲密特写"、\
"柔焦与柔和光线"。
- 避免临床或直白的术语——通过视觉隐喻和电影技法来表达。
- 目标是使用专业的电影制作语言，聚焦镜头所看到的内容和感受，\
传达相同的叙事冲击力。
""",
            en_text="""\
You are a professional video director and visual prompt engineer. Adapt the \
given story into detailed visual scene descriptions for AI video generation.

[Output Format] Return a JSON object:
{
  "scenes": [
    "Scene 1 visual prompt...",
    "Scene 2 visual prompt...",
    ...
  ]
}

Rules:
- Each scene MUST be a detailed VISUAL DESCRIPTION, written in the SAME LANGUAGE \
as the input story.
- Do NOT include character names in angle brackets or dialogue tags.
- Focus on: camera movement, lighting, colors, environment, character actions, atmosphere, mood.
- Include specific visual details: lens type (wide/telephoto), depth of field, camera angle, \
lighting direction, color grading, particle effects, weather.
- Each scene should be 80-150 words, rich in cinematic detail.
- Maintain visual consistency across scenes (same character appearance, coherent world).
- Number of scenes MUST respect the user requirement constraints.
- The art style should match the requested style (realistic cinematic, anime, etc.).
- Describe MOTION and ACTION, not static images — this is for video generation.

VOCABULARY GUIDANCE FOR INTENSE/TENSE CONTENT:
- Frame dramatic or tense moments through cinematic terms: "intense standoff", \
"dramatic confrontation", "charged atmosphere", "high-stakes encounter".
- Use genre-appropriate visual language: "dark fantasy aesthetic", "noir shadow work", \
"gothic atmosphere", "psychological thriller lighting".
- Describe emotional intensity via lighting and composition: "harsh shadows suggest tension", \
"warm golden light evokes intimacy", "cold blue grading creates unease".
- For action sequences: "dynamic camera work", "rapid montage cutting", \
"explosive choreography", "energy-filled movement".
- For romantic/intimate scenes: "tender proximity", "warm embrace", "intimate close-up", \
"soft focus and gentle lighting".
- Avoid clinical or graphic terminology — express through visual metaphor and \
cinematic technique.
- The goal is to CONVEY THE SAME NARRATIVE IMPACT using professional filmmaking \
language that focuses on what the camera sees and how it feels.
""",
        )
        user_prompt = f"""\
<story>
{story}
</story>

<user_requirement>
{requirement_text}
</user_requirement>

<style>
{style}
</style>
"""
        logger.info("[Screenwriter] Writing script (visual prompts for video generation)...")
        result = self._chat_json(system_prompt, user_prompt)
        scenes = result.get("scenes", [])
        logger.info(f"[Screenwriter] Script written: {len(scenes)} scenes")
        return scenes

    def extract_character_description(self, story: str, style: str) -> str:
        system_prompt = self._prompt(
            zh_text="""\
你是一位视觉设计专家。你的任务是从故事中提取主要角色的详细\
图像生成提示词，适用于生成角色参考图。

参考图应展示主要角色以清晰、全身或四分之三\
视角、中性站立姿势呈现，显著特征清晰可见。图片应准确捕捉\
故事中描述的角色外貌，包括：

- 体型与姿态
- 服装与配饰
- 发型与发色
- 面部特征与表情
- 肤色、纹理或材质（非人角色）
- 任何标志性特征、疤痕或特点
- 角色的配色方案

重要提示——参考图将用作 i2i 身份锚点，因此\
提示词还必须指定：
- 清晰、正面的面部，眼睛和嘴巴完全可见
- 无遮挡（手、头发或物体不能挡住面部）
- 均匀、柔和的布光（面部无强阴影）
- 中性或浅笑表情

应为一个段落，3-5 句话，\
视觉细节丰富。包含艺术风格（如"写实电影感"、\
"动漫风格"、"水彩插画"）。

关键要求：使用与输入故事相同的语言输出提示词。\
如果故事是中文，用中文写提示词。如果是英文，用英文写。\
这是强制要求。

只输出图像提示词文本，不要 JSON，不要解释。
""",
            en_text="""\
You are a visual design expert. Your job is to extract a detailed image \
generation prompt for the MAIN CHARACTER from the story, suitable for \
generating a CHARACTER REFERENCE IMAGE.

The reference image should show the main character in a clear, full-body \
or three-quarter view pose, in a neutral standing position, with distinctive \
features clearly visible. The image should capture the character's appearance \
exactly as described in the story, including:

- Body type and posture
- Clothing and accessories
- Hair style and color
- Facial features and expressions
- Skin color, texture, or material (for non-human characters)
- Any distinguishing marks, scars, or features
- Color palette of the character

IMPORTANT — the reference image will be used as an i2i identity anchor, so \
the prompt MUST also specify:
- Clear, front-facing face with eyes and mouth fully visible
- No occlusion (no hands, hair, or objects blocking the face)
- Even, diffused lighting (no harsh shadows on the face)
- Neutral or slight smile expression

It should be a single paragraph, 3-5 sentences, \
rich in visual detail. Include the art style (e.g., "realistic cinematic", \
"anime style", "watercolor illustration").

CRITICAL: Output the prompt in the SAME LANGUAGE as the input story. \
If the story is in Chinese, write the prompt in Chinese. If in English, \
write in English. This is mandatory.

Output ONLY the image prompt text, no JSON, no explanation.
""",
        )
        user_prompt = f"""\
<story>
{story}
</story>

<style>{style}</style>

{self._prompt(
    zh_text="请使用与上方故事相同的语言编写角色图像提示词。",
    en_text='Write the character image prompt in the SAME LANGUAGE as the story above.'
)}
"""
        logger.info("[Screenwriter] Extracting character reference prompt...")
        prompt = strip_code_fence(self._chat(system_prompt, user_prompt))
        logger.info(f"[Screenwriter] Character prompt: {prompt[:100]}...")
        return prompt

    def get_character_appearance(self, story: str) -> str:
        system_prompt = self._prompt(
            zh_text="""\
仅从此故事中提取主要角色的物理外貌。
输出一段简洁的描述，概括其固定外观——包含所有细节：
- 发型与发色
- 面部特征（眼镜等）
- 体型与姿态
- 服装（所有单品：外套、连衣裙、裤子等）
- 鞋子
- 任何配饰

以一段描述性文字输出，3-5 句话。保持客观且可视化\
——像警方画像描述一样。不要包含性格、\
对话或故事情节。

关键要求：使用与输入故事相同的语言输出。如果故事是\
中文，用中文写。如果是英文，用英文写。这是强制要求。

仅输出外貌描述文本。不要 JSON、不要标签、不要 markdown。
""",
            en_text="""\
Extract ONLY the main protagonist's physical appearance from this story.
Output a CONCISE paragraph describing their fixed look — include EVERY detail:
- Hair style and color
- Facial features (glasses, etc.)
- Body type and posture
- Clothing (ALL pieces: coat, dress, pants, etc.)
- Shoes
- Any accessories

Write as a single descriptive paragraph, 3-5 sentences. Keep it factual and
visual — like a police sketch description. Do NOT include their personality,
dialogue, or story events.

CRITICAL: Output in the SAME LANGUAGE as the input story. If the story is in
Chinese, write in Chinese. If in English, write in English. This is mandatory.

Output ONLY the appearance description text. No JSON, no labels, no markdown.
""",
        )
        appearance = strip_code_fence(self._chat(system_prompt, story))
        logger.info(f"[Screenwriter] Character appearance: {appearance[:100]}...")
        return appearance

    def generate_end_frame_prompts(
        self, scenes: List[str], style: str, character_appearance: str = ""
    ) -> List[str]:
        # 批次4：角色外观由批次3的程序化拼入处理，LLM 只输出 [CHANGE] 部分
        # 系统提示中仍提供 character_appearance 作为上下文参考，避免 LLM 描述与角色矛盾
        if character_appearance:
            context_block = self._prompt(
                zh_text=f"""
[上下文 — 角色外貌仅供参考，不要复制到输出中]
{character_appearance}

你的提示词应仅描述场景的尾帧——环境、姿态、\
光线、氛围、拍摄角度。不要重复角色的发型、面部、\
服装或配饰——这些由程序化方式注入。
""",
                en_text=f"""
[CONTEXT — Character appearance for reference only, do NOT copy into output]
{character_appearance}

Your prompt should describe the SCENE'S END FRAME only — environment, pose, \
lighting, mood, camera angle. Do NOT repeat the character's hair, face, \
clothing, or accessories — those are injected programmatically.
""",
            )
        else:
            context_block = ""

        system_prompt = self._prompt(
            zh_text=f"""\
你是一位面向 AI 图像生成的视觉提示词工程师。请生成一个静态\
图像提示词，描述该视频场景在结尾处的画面\
——即视频的最终定格帧。
{context_block}
规则：
- 描述一个静态的定格瞬间，不要使用运动或动作动词。
- 聚焦于：姿态、面部表情、手部位置、身体姿势、拍摄角度、\
光线、背景元素——单个定格帧中可见的一切。
- 包含艺术风格（如"写实电影感"、"动漫"）。
- 3-5 句话，视觉细节丰富。
- 必须使用与输入场景相同的语言。
- 不要描述角色的外貌（发型、服装、面部）——只描述\
场景环境、姿态、光线和氛围。

用词指导：
- 通过视觉氛围构图戏剧性或紧张的元素："充满张力的\
静默"、"定格中的紧张沉寂"、"戏剧性的光影处理"。
- 使用光线和构图传达情感分量："强烈的顶光\
营造阴郁氛围"、"柔和的金色逆光暗示希望"、"冷蓝色调\
增加情感疏离感"。
- 对于情感充沛的场景，聚焦肢体语言和环境叙事：\
"疲惫的姿态映衬在空旷的窗前"、"温暖环境光中的\
温柔亲近"、"画面中央的有力站姿"。
- 让镜头语言承载叙事冲击力——构图、色彩和\
光线来完成叙事。

只输出图像提示词文本，不要 JSON，不要解释。
""",
            en_text=f"""\
You are a visual prompt engineer for AI image generation. Generate a STATIC \
image prompt that represents what this video scene looks like at its very END \
— the final frozen frame of the video.
{context_block}
Rules:
- Describe a STATIC frozen moment, NOT motion or action verbs.
- Focus on: pose, facial expression, hand position, body posture, camera angle, \
lighting, background elements — everything visible in a single frozen frame.
- Include art style (e.g., "realistic cinematic", "anime").
- 3-5 sentences, rich in visual detail.
- MUST be in the SAME LANGUAGE as the input scene.
- Do NOT describe the character's appearance (hair, clothing, face) — only the \
scene environment, pose, lighting, and mood.

VOCABULARY GUIDANCE:
- Frame dramatic or intense elements through visual atmosphere: "charged \
stillness", "tense silence captured in frame", "dramatic shadow work".
- Use lighting and composition to convey emotional weight: "harsh overhead light \
creates a somber mood", "soft golden backlight suggests hope", "cold blue tint \
adds emotional distance".
- For emotionally charged scenes, focus on body language and environmental \
storytelling: "defeated posture silhouetted against a stark window", \
"tender closeness in warm ambient light", "powerful stance centered in frame".
- Let the camera language carry the narrative impact — composition, color, and \
lighting do the storytelling.

Output ONLY the image prompt text, no JSON, no explanation.
""",
        )
        end_frames = []
        for scene_idx, scene_text in enumerate(scenes):
            logger.info(f"[Screenwriter] Generating end frame prompt for scene {scene_idx}...")
            user_prompt = f"""\
<style>{style}</style>

<scene>
{scene_text}
</scene>

{self._prompt(
    zh_text="请为此场景编写静态尾帧图像提示词。描述该场景最终定格帧的样子——场景结束时的姿态、表情、光线和环境。",
    en_text="Write the STATIC end-frame image prompt for this scene. This should describe what the final frozen frame of this scene looks like — the pose, expression, lighting, and environment at the moment this scene ends."
)}
"""
            prompt = strip_code_fence(self._chat(system_prompt, user_prompt))
            end_frames.append(prompt)
            logger.info(f"[Screenwriter] End frame {scene_idx} prompt: {prompt[:80]}...")

        logger.info(f"[Screenwriter] Generated {len(end_frames)} end frame prompts")
        return end_frames

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
        logger.info(f"[Screenwriter] Designing shots for scene...")
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

    def generate_anchor_clip_prompt(
        self,
        paragraph_text: str,
        anchor_prompt: str,
        segment_index: int,
        total_segments: int,
    ) -> str:
        """为数字人口播分段生成视频动态 prompt（v3.1 方案 B，语言跟随输入）。

        基于段落语义和主播形象，为每段生成不同的自然动作描述，
        确保相邻段落的动作有变化（说话、点头、手势、微笑等），
        同时保持主播形象一致性，便于 i2v 生成带口型近似匹配的视频。

        Args:
            paragraph_text: 段落文本（本段内容）。
            anchor_prompt: 主播形象描述。
            segment_index: 当前段落索引（0-based）。
            total_segments: 总段落数。

        Returns:
            视频动态 prompt 字符串（语言与输入一致）。
        """
        system_prompt = self._prompt(
            zh_text=f"""\
你是一位专精数字人口播视频的专业视频导演。\
给定一段旁白文本和主播的外貌描述，\
为 AI 视频生成（i2v）生成一个简短的动态提示词。

规则：
- 描述主播在朗读此段落时的自然动作。
- 必须包含细微的嘴唇/口部运动，如同正在朗读旁白。
- 各段落的动作要有变化：配合手势说话、点头、\
轻微歪头、微笑、认真表情、思考停顿等。
- 动作应匹配文本内容的情感基调。
- 保持起止姿势几乎一致（以利于平滑拼接）。
- 动作应温和自然——不做夸张运动。
- 30-60 词，使用与输入旁白文本相同的语言。
- 不要描述环境或光线（这些由主播图像固定）。
- 不要描述主播的服装或外貌（已在参考图中确定）。

情感基调表达：
- 通过面部微表情和细微肢体语言表达情感基调：\
"温暖关切的表情"、"诚恳点头并轻轻加重语气"、\
"思考停顿伴随轻微歪头"、"严肃聚焦的目光"。
- 对于紧张/严肃内容："克制的审慎手势"、"肃穆的\
表情"、"沉稳踏实的姿态"。
- 对于温暖/振奋内容："真诚温暖的微笑"、"开放邀请的\
手势"、"明亮投入的表情"。
- 通过微妙的专业表达传达情感深度——像\
一位资深新闻主播用庄重而不夸张的方式传达分量。

变化上下文：
- 这是第 {segment_index} 段，共 {total_segments} 段。
- 靠前段落：更有活力、欢迎感的手势。
- 中间段落：专注、解说性手势，偶尔加强重点。
- 靠后段落：总结性、收束的手势。

只输出动态提示词文本，不要 JSON，不要解释。
""",
            en_text=f"""\
You are a professional video director specializing in digital human anchorperson videos.
Given a segment of narration text and the anchor's appearance description, \
generate a SHORT motion prompt for AI video generation (i2v).

Rules:
- Describe the anchorperson's NATURAL MOTIONS while speaking this segment.
- MUST include subtle lip/mouth movements as if speaking the narration.
- Vary the gestures across segments: speaking with hand gestures, nodding, \
slight head tilt, smile, earnest expression, thoughtful pause, etc.
- The motion should MATCH the emotional tone of the text content.
- Keep the starting and ending posture nearly identical (for smooth concatenation).
- Motions should be GENTLE and NATURAL — no exaggerated movements.
- 30-60 words, in the SAME LANGUAGE as the input narration text.
- Do NOT describe the environment or lighting (those are fixed from the anchor image).
- Do NOT describe the anchor's clothing or appearance (already in the reference image).

EMOTIONAL TONE EXPRESSION:
- Express emotional tone through facial micro-expressions and subtle body \
language: "warm concerned expression", "earnest nod with gentle emphasis", \
"thoughtful pause with slight head tilt", "serious focused gaze".
- For intense/serious content: "measured deliberate gestures", "solemn \
expression", "composed and grounded posture".
- For warm/uplifting content: "genuine warm smile", "open inviting gesture", \
"bright engaging expression".
- Convey emotional depth through subtle professional delivery — like a \
skilled news anchor conveying gravitas without melodrama.

Context for variation:
- This is segment {segment_index} of {total_segments}.
- Early segments: more energetic, welcoming gestures.
- Middle segments: focused, explanatory gestures with occasional emphasis.
- Later segments: conclusive, summarizing gestures.

Output ONLY the motion prompt text, no JSON, no explanation.
""",
        )

        user_prompt = f"""\
<anchor_appearance>
{anchor_prompt}
</anchor_appearance>

<narration_segment>
{paragraph_text}
</narration_segment>

{self._prompt(
    zh_text="请为此段落生成动态提示词。",
    en_text="Generate the motion prompt for this segment."
)}
"""
        logger.info(
            f"[Screenwriter] Generating anchor clip prompt for segment "
            f"{segment_index + 1}/{total_segments} ({len(paragraph_text)} chars)..."
        )
        prompt = strip_code_fence(self._chat(system_prompt, user_prompt))
        logger.info(f"[Screenwriter] Anchor clip prompt: {prompt[:100]}...")
        return prompt

    def generate_anchor_smooth_loop_prompt(
        self,
        anchor_prompt: str,
    ) -> str:
        """为数字人口播后拼接音频模式生成单段循环优化的动态 prompt（语言跟随输入）。

        只生成一段 5 秒的 i2v 视频，循环播放配合完整 TTS 音频。
        prompt 强调微小幅度动作，确保起止姿态高度一致，循环衔接流畅。

        Args:
            anchor_prompt: 主播形象描述。

        Returns:
            视频动态 prompt 字符串（语言与输入一致）。
        """
        system_prompt = self._prompt(
            zh_text="""\
你是一位专精数字人口播视频的专业视频导演。\
为 AI 视频生成（i2v）生成一个简短的动态提示词。

此视频将被循环播放以覆盖完整旁白时长。\
因此动作必须设计为可无缝循环播放。

关键规则：
- 结束姿势必须与起始姿势几乎完全相同。
- 动作必须极其细微——仅允许几乎不可察觉的微运动。
- 不允许大幅度手势、转头、抬手。
- 仅允许胸/肩部的轻微呼吸运动。
- 极小幅度的微点头或微表情变化（幅度小于 5%）。
- 面部和身体位置应几乎静止——仿佛是静态照片\
  加上最微弱的真人微运动。
- 嘴巴应几乎无运动（这是循环片段，音频在后期添加）。
- 想象"活人肖像"——一张几乎静止但微微呼吸的照片。
- 20-40 词，使用与主播外貌描述相同的语言。
- 不要描述环境、光线、服装或外貌。

情感基调：
- 通过微妙的微表情传达情绪："几乎无法察觉的温柔\
微笑"、"眼神中微妙的温暖"、"隐约的严肃沉稳"、\
"关切真诚的微表情"。
- 所有表达保持在"活人肖像"约束内——仅嘴角和\
眼神的微小变化，无可见表演。

只输出动态提示词文本，不要 JSON，不要解释。
""",
            en_text="""\
You are a professional video director specializing in digital human anchorperson videos.
Generate a SHORT motion prompt for AI video generation (i2v).

This video will be LOOPED (played on repeat) to cover the full narration duration.
Therefore the motion MUST be designed for seamless loop playback.

CRITICAL RULES:
- The ending posture MUST be nearly IDENTICAL to the starting posture.
- Motions must be EXTREMELY SUBTLE — barely perceptible micro-movements only.
- NO large gestures, NO head turning, NO hand raising.
- ONLY subtle breathing motion in the chest/shoulders.
- VERY slight micro-nod or micro-smile changes (under 5% amplitude).
- The face and body position should appear nearly frozen — as if a static image
  with the faintest living-person micro-motions.
- Mouth should have near-zero movement (this is a loop-clip, audio is added in post).
- Think "living portrait" — a photo that barely breathes.
- 20-40 words, in the SAME LANGUAGE as the anchor appearance description.
- Do NOT describe environment, lighting, clothing, or appearance.

EMOTIONAL TONE:
- Use subtle micro-expressions to convey mood: "barely perceptible gentle \
smile", "subtle warmth in the eyes", "faint serious composure", \
"micro-expression of concerned sincerity".
- Keep all expression within the "living portrait" constraint — tiny shifts \
in mouth corners and eyes only, no visible performance.

Output ONLY the motion prompt text, no JSON, no explanation.
""",
        )

        user_prompt = f"""\
<anchor_appearance>
{anchor_prompt}
</anchor_appearance>

{self._prompt(
    zh_text="请为 5 秒循环片段生成平滑循环的动态提示词。",
    en_text="Generate the smooth-loop motion prompt for a 5-second looping clip."
)}
"""
        logger.info(
            f"[Screenwriter] Generating anchor smooth-loop prompt "
            f"({len(anchor_prompt)} chars)..."
        )
        prompt = strip_code_fence(self._chat(system_prompt, user_prompt))
        logger.info(f"[Screenwriter] Anchor smooth-loop prompt: {prompt[:100]}...")
        return prompt

    def generate_anchor_model_audio_prompt(
        self,
        anchor_prompt: str,
        script_text: str,
    ) -> str:
        """为数字人口播模型音频模式生成含口播文本的视频 prompt（语言跟随输入）。

        模型音频模式下，视频模型同时生成视频和音频，
        prompt 需包含说话口型描述和口播文本内容。

        Args:
            anchor_prompt: 主播形象描述。
            script_text: 口播稿件全文。

        Returns:
            视频 prompt 字符串（语言与输入一致）。
        """
        system_prompt = self._prompt(
            zh_text="""\
你是一位专精数字人口播视频的专业视频导演。\
为 AI 视频生成（i2v）生成一个简短的视频提示词。

视频模型将同时生成视频和音频（主播朗读旁白）。\
因此：
- 包含主播匹配语音的嘴唇/口部运动。
- 动作应温和自然——轻微的点头、轻轻的手势。
- 保持身体位置相对稳定。
- 30-50 词，使用与旁白文本相同的语言。
- 不要描述环境、光线、服装或外貌。

语气表达：
- 通过微妙的表达线索传达旁白的情感基调：\
"温暖交谈的语气"、"诚恳真挚的表达"、\
"审慎严肃的态度"、"温柔强调的手势"。
- 所有表达保持在自然、专业的主播表达范围内\
——细腻而不戏剧化。

只输出提示词文本，不要 JSON，不要解释。
""",
            en_text="""\
You are a professional video director specializing in digital human anchorperson videos.
Generate a SHORT video prompt for AI video generation (i2v).

The video model will generate BOTH video and audio (the anchor speaking the narration).
Therefore:
- Include the anchor's lip/mouth movements matching the speech.
- The motion should be gentle and natural — subtle head nods, slight hand gestures.
- Keep body position relatively stable.
- 30-50 words, in the SAME LANGUAGE as the narration text.
- Do NOT describe environment, lighting, clothing, or appearance.

TONE EXPRESSION:
- Express the emotional tone of the narration through subtle delivery cues: \
"warm conversational tone", "earnest and sincere delivery", \
"measured serious demeanor", "gentle emphatic gestures".
- Keep all expression within natural, professional anchor delivery \
— nuanced but not theatrical.

Output ONLY the prompt text, no JSON, no explanation.
""",
        )

        user_prompt = f"""\
<anchor_appearance>
{anchor_prompt}
</anchor_appearance>

<narration>
{script_text[:500]}
</narration>

{self._prompt(
    zh_text="请为此带内置音频的主播片段生成视频提示词。",
    en_text="Generate the video prompt for this anchor segment with built-in audio."
)}
"""
        logger.info(
            f"[Screenwriter] Generating anchor model-audio prompt "
            f"({len(anchor_prompt)} chars, {len(script_text)} script chars)..."
        )
        prompt = strip_code_fence(self._chat(system_prompt, user_prompt))
        logger.info(f"[Screenwriter] Anchor model-audio prompt: {prompt[:100]}...")
        return prompt

    def generate_narration_for_video(
        self, story: str, scenes: List[str], total_duration: float, style: str = ""
    ) -> str:
        """为整个视频一次性生成旁白文案（语言跟随输入）。

        基于故事全文和所有场景描述，生成一段完整的旁白文本，
        时长匹配视频总时长（num_scenes * video_duration）。

        Args:
            story: 完整故事文本
            scenes: 所有场景的视觉描述列表
            total_duration: 视频总时长（秒）
            style: 风格描述（可选）

        Returns:
            完整的旁白文本字符串（语言与输入一致）
        """
        max_chars = max(int(total_duration * 4.0), 40)
        scene_count = len(scenes)

        scene_summary = "\n".join(
            f"Scene {i+1}: {s[:300]}" for i, s in enumerate(scenes)
        )

        system_prompt = self._prompt(
            zh_text=f"""\
你是一位专业的视频旁白员和剧本作家。给定完整故事\
和所有场景的视觉描述，写一段单一的连续旁白\
配音，从头到尾覆盖整个视频。

规则：
- 使用与输入故事相同的语言编写，自然且适合配音朗读。
- 旁白应不超过 {max_chars} 字，以适配一个\
{total_duration:.0f} 秒的视频（{scene_count} 个场景 × 每场景 {total_duration/scene_count:.0f} 秒，\
语速约 4 字/秒）。
- 作为一个连贯的配音讲述完整故事——不要将每个\
场景视为独立的旁白。这是覆盖整个视频的\
一段连续旁白。
- 旁白节奏匹配视觉流：在场景出现时引入场景\
上下文，描述动作/情感/氛围。
- 使用生动、电影化的语言，适合短视频旁白。
- 不要逐字重复视觉描述——讲述故事。
- 以自然的句子结束（。！？）。
- 只输出旁白文本，不加引号，不解释。

旁白指导：
- 使用富有感染力的文学语言，通过氛围、节奏和\
潜台词传达情感深度。
- 紧张或激烈的情节：通过戏剧性节奏、暗示的\
张力、氛围细节和角色情感反应来表达。
- 浪漫或温柔节拍：聚焦情感联结、未言明的感受、\
当下的氛围。
- 动作/张力：充满能量的节奏、生动的感官细节、博弈和紧迫感。
- 旁白应像一个引人入胜的音频故事——让暗示\
和氛围承载分量，而非直白描写。

目标长度约为 {max_chars} 字。
""",
            en_text=f"""\
You are a professional video narrator and scriptwriter. Given the full story \
and all scene visual descriptions, write a SINGLE CONTINUOUS narration \
voiceover that covers the ENTIRE video from beginning to end.

Rules:
- Write in the SAME LANGUAGE as the input story, natural and suitable for voiceover narration.
- The narration should be {max_chars} characters or fewer to fit a \
{total_duration:.0f}-second video ({scene_count} scenes × {total_duration/scene_count:.0f}s each, \
speech rate ~4 chars/sec).
- Tell the complete story as a cohesive voiceover — do NOT treat each \
scene as a separate narration. This is ONE continuous narration for the \
whole video.
- Match the narration pacing to the visual flow: introduce the scene \
context as the scene appears, describe actions/emotions/atmosphere.
- Use vivid, cinematic language suitable for short video narration.
- Do NOT repeat the visual descriptions verbatim — narrate the STORY.
- End with a natural sentence boundary (。！？).
- Output ONLY the narration text, no quotes, no explanation.

NARRATION GUIDANCE:
- Use evocative, literary language that conveys emotional depth through \
atmosphere, pacing, and subtext.
- Intense or charged moments: express through dramatic pacing, implied \
tension, atmospheric detail, and character emotional response.
- Romantic or tender beats: focus on emotional connection, unspoken feelings, \
the mood of the moment.
- Action/tension: energetic pacing, vivid sensory details, stakes and urgency.
- The narration should feel like a compelling audio story — let implication \
and atmosphere carry weight rather than explicit description.

The target length is approximately {max_chars} characters total.
""",
        )
        style_block = f"\n<style>{style}</style>\n" if style else ""
        user_prompt = f"""\
<story>
{story}
</story>

<scenes>
{scene_summary}
</scenes>
{style_block}
{self._prompt(
    zh_text=f"请为整个视频编写一段连续的旁白配音，使用与故事相同的语言，约 {max_chars} 字。",
    en_text=f"Write ONE continuous narration voiceover in the SAME LANGUAGE as the story for the entire video, approximately {max_chars} characters total."
)}
"""
        logger.info(
            f"[Screenwriter] Generating narration for video "
            f"(max {max_chars} chars, {total_duration:.0f}s total, {scene_count} scenes)..."
        )
        narration = strip_code_fence(self._chat(system_prompt, user_prompt))
        logger.info(f"[Screenwriter] Narration: {narration[:80]}... ({len(narration)} chars)")
        return narration

    def generate_subtitle_styles(
        self,
        srt_path: str,
        video_width: int,
        video_height: int,
        style_hints: str = "",
        role: str = "",
    ) -> list[dict]:
        """为每条字幕生成位置、颜色、字号样式（Phase 2: LLM 智能样式）。

        读取 SRT 文件，将每条字幕文本 + 时间码发给 LLM，
        LLM 为每条字幕决定 position / color / fontsize，
        输出 JSON 数组用于逐条渲染。

        Args:
            srt_path: SRT 字幕文件路径。
            video_width: 视频宽度（像素）。
            video_height: 视频高度（像素）。
            style_hints: 用户对样式的自然语言偏好描述。
            role: 场景角色描述（如"数字人口播主播"），用于指导 LLM 定位。

        Returns:
            list[dict]: 样式列表，每项含 index, position, color, fontsize。
        """
        import srt as srt_lib

        with open(srt_path, "r", encoding="utf-8") as f:
            subs = list(srt_lib.parse(f))

        if not subs:
            logger.warning("[Screenwriter] generate_subtitle_styles: empty SRT")
            return []

        entries_text = "\n".join(
            f"  [{s.index}] {s.start.total_seconds():.1f}s-{s.end.total_seconds():.1f}s: {s.content}"
            for s in subs
        )

        safe_w = video_width - 80
        safe_h = video_height - 80

        role_context = self._prompt(
            zh_text=f"场景为{role}场景。" if role else "",
            en_text=f"The scene is a {role} scenario." if role else "",
        )

        system_prompt = self._prompt(
            zh_text=f"""\
你是一位专业的短视频字幕设计师。\
给定字幕列表和视频尺寸，为每条字幕分配\
能提升观看体验的视觉样式。

视频尺寸：{video_width}x{video_height}px
安全区域：每边 40px 边距 = 可用 {safe_w}x{safe_h}px

{role_context}

输出 JSON 数组，每条字幕一个对象：
[
  {{{{
    "index": <int, 匹配字幕序号>,
    "position": ["<水平>", "<垂直>"],
    "color": "<颜色名或 #RRGGBB>",
    "fontsize": <int 18-80>
  }}}},
  ...
]

关键——垂直多样性要求：
字幕位置必须分布在三个垂直区域中：
- 约 1/3 字幕在上方区域：vertical = "top+N"（N = 40–120）
- 约 1/3 字幕在中间区域：vertical = "center" 或 "center" 配合水平偏移
- 约 1/3 字幕在下方区域：vertical = "bottom-N"（N = 60–160）
不要把所有字幕都放在 bottom-N——这会导致视觉单调。
相邻字幕必须交替垂直区域以显得灵动。

位置规则：
- horizontal："center"、"left"、"right"（推荐使用字符串标记，可自动安全对齐）
            或 "left+N"、"right+N"（N = 像素偏移，仅使用小数值 20–120）
- vertical：  "top+N"（N = 40–120）、"center"、"bottom-N"（N = 60–160）
            中间区域使用 "center"——不要用像素值。

坏例子（单调，全在底部）：
  ["center", "bottom-80"], ["center", "bottom-60"], ["left+40", "bottom-80"]

好例子（多样的垂直区域）：
  ["center", "top+60"],   ["right", "center"],     ["center", "bottom-80"]
  ["left",  "top+100"],   ["center", "center"],     ["right", "bottom-120"]

样式规则：
- 相邻字幕应变化位置以避免视觉单调。
- 新话题或语义转换可使用新位置和颜色。
- 强调/结论内容：更大字号（56-72）和醒目颜色（金色、红色、#FFD700）。
- 确保与典型视频背景有足够对比度。
- 默认/叙述内容：白色，36-48px。
- 以下用户的 style_hints 是最强约束——优先遵循。
- 所有位置必须保持文本完全在安全区域内（40px 边距）。
- 不要改变条目的数量或顺序——输出必须匹配输入。
""",
            en_text=f"""\
You are a professional subtitle stylist for short video production. \
Given a subtitle list and video dimensions, assign each subtitle a visual \
style that enhances the viewing experience.

Video size: {video_width}x{video_height}px
Safe area: 40px margin on each side = {safe_w}x{safe_h}px available

{role_context}

Output a JSON array, one object per subtitle:
[
  {{{{
    "index": <int, matching the subtitle index>,
    "position": ["<horizontal>", "<vertical>"],
    "color": "<color name or #RRGGBB>",
    "fontsize": <int 18-80>
  }}}},
  ...
]

CRITICAL — VERTICAL DIVERSITY REQUIREMENT:
Subtitle positions MUST be distributed across THREE vertical zones:
- ~1/3 of subtitles in UPPER zone: vertical = "top+N" (N = 40–120)
- ~1/3 of subtitles in MIDDLE zone: vertical = "center" or "center" with horizontal offset
- ~1/3 of subtitles in LOWER zone: vertical = "bottom-N" (N = 60–160)
Do NOT put all subtitles at bottom-N — that causes visual monotony.
Adjacent subtitles MUST alternate vertical zones to feel dynamic.

Position rules:
- horizontal: "center", "left", "right" (PREFER string tokens, they auto-align safely)
            or "left+N", "right+N" (N = pixel offset, only use small values 20–120)
- vertical:   "top+N" (N = 40–120), "center", "bottom-N" (N = 60–160)
            Use "center" for the middle zone — not pixel values.

BAD examples (monotonous, all bottom):
  ["center", "bottom-80"], ["center", "bottom-60"], ["left+40", "bottom-80"]

GOOD examples (diverse vertical zones):
  ["center", "top+60"],   ["right", "center"],     ["center", "bottom-80"]
  ["left",  "top+100"],   ["center", "center"],     ["right", "bottom-120"]

Styling rules:
- Adjacent subtitles should vary position to avoid visual monotony.
- New topics or semantic shifts can use new positions and colors.
- Emphasized / conclusion content: larger font (56-72) and eye-catching color (gold, red, #FFD700).
- Ensure sufficient contrast against typical video backgrounds.
- Default / narrative content: white, 36-48px.
- User style_hints below are the STRONGEST constraint — follow them first.
- All positions MUST keep text fully inside the safe area (40px margin).
- Do NOT change the number of items or their order — output must match input.
""",
        )

        user_prompt = f"""\
<subtitle_entries>
{entries_text}
</subtitle_entries>

<style_hints>
{style_hints or self._prompt(zh_text="（无特定偏好——使用专业默认值）", en_text="(no specific preference — use professional defaults)")}
</style_hints>

{self._prompt(
    zh_text="为每条字幕分配样式并返回 JSON 数组。",
    en_text="Assign styles to each subtitle and return the JSON array."
)}
"""

        logger.info(
            f"[Screenwriter] Generating subtitle styles for {len(subs)} entries "
            f"({video_width}x{video_height}, hints={repr(style_hints[:50])})..."
        )

        try:
            result = self._chat_json(system_prompt, user_prompt)
        except (ValueError, Exception) as e:
            logger.warning(f"[Screenwriter] LLM subtitle styles failed: {e}, using defaults")
            return self._fallback_styles(subs)

        if isinstance(result, dict) and "styles" in result:
            styles = result["styles"]
        elif isinstance(result, list):
            styles = result
        else:
            logger.warning(f"[Screenwriter] Unexpected LLM response format: {type(result)}, using defaults")
            return self._fallback_styles(subs)

        validated = self._validate_styles(styles, len(subs))
        logger.info(f"[Screenwriter] Subtitle styles generated: {len(validated)} entries")
        return validated

    def _validate_styles(self, styles: list, expected_count: int) -> list[dict]:
        """验证并修复 LLM 输出的样式列表。"""
        import re as _re

        # 循环位置池，确保即使是缺失项也能分布在不同区域
        _position_pool = [
            ["center", "top+80"],
            ["center", "center"],
            ["center", "bottom-100"],
            ["right", "top+60"],
            ["left", "center"],
            ["right", "bottom-120"],
            ["left", "top+100"],
            ["center", "center"],
        ]

        valid = []
        seen_indices = set()
        for item in styles:
            idx = item.get("index", 0)
            if not isinstance(idx, int) or idx < 1 or idx > expected_count or idx in seen_indices:
                continue
            seen_indices.add(idx)

            pos = item.get("position", ["center", "bottom-80"])
            if not isinstance(pos, (list, tuple)) or len(pos) != 2:
                pos = ["center", "bottom-80"]

            color = item.get("color", "white")
            if not isinstance(color, str):
                color = "white"

            fs = item.get("fontsize", 48)
            if not isinstance(fs, int) or fs < 18 or fs > 80:
                fs = 48

            valid.append({
                "index": idx,
                "position": pos,
                "color": color,
                "fontsize": fs,
            })

        missing = [i for i in range(1, expected_count + 1) if i not in seen_indices]
        for i, idx in enumerate(missing):
            valid.append({
                "index": idx,
                "position": _position_pool[i % len(_position_pool)],
                "color": "white",
                "fontsize": 48,
            })

        valid.sort(key=lambda x: x["index"])
        return valid

    @staticmethod
    def _fallback_styles(subs: list) -> list[dict]:
        """LLM 调用失败时的回退样式（循环不同位置保持多样性）。"""
        _positions = [
            ["center", "top+80"],
            ["center", "center"],
            ["center", "bottom-100"],
            ["right", "top+60"],
            ["left", "center"],
            ["right", "bottom-120"],
        ]
        return [
            {
                "index": s.index,
                "position": _positions[(s.index - 1) % len(_positions)],
                "color": "white",
                "fontsize": 48,
            }
            for s in subs
        ]