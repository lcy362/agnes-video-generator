"""core.screenwriter.story — 旁白清洗 + 故事/脚本/旁白生成方法（Batch 4 拆分）"""
import html
import logging
import re
from typing import List

from core.api.agnes_chat import strip_code_fence

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════
# 共享文本工具（__init__.py re-export）
# ═══════════════════════════════════════════════

def _xml_escape(text: str) -> str:
    """XML 转义用户输入，防止 prompt 注入。

    将 < > & " ' 转义为 XML 实体，避免用户输入中的标签
    提前闭合 XML 结构（如 </idea>）导致指令注入。
    """
    if not text:
        return text
    return html.escape(text, quote=True)

_NARRATION_METADATA_PREFIXES = (
    "故事标题", "目标受众", "故事大纲", "角色介绍", "主要角色", "故事梗概",
    "故事正文", "故事设定", "内容风格", "视频类型",
    "story title", "target audience", "story outline", "main character",
    "character introduction", "full story narrative", "synopsis", "logline",
    "content style", "video type",
)
_NARRATION_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+")
_NARRATION_BULLET_RE = re.compile(r"^\s*[-*]\s+")
# 元数据字段行：**字段**：值（定义列表项，典型的文档结构而非旁白）
_NARRATION_FIELD_RE = re.compile(r"^\*\*.+?\*\*[:：]")

def clean_narration_text(text: str) -> str:
    """清洗 LLM 返回的旁白文本，去除 Markdown 结构与元数据行。

    用于防止把 ``# 故事标题`` / ``## 目标受众`` / ``**受众**：…`` 等文档结构
    当作旁白念出，只保留纯叙事正文，并合并为**单独的一段纯文本**（配音不需要换行）。

    清洗规则：
        - 丢弃 ``**字段**：值`` 形式的元数据字段行（定义列表项）
        - 去除 Markdown 标题符号（``#`` / ``##`` …）
        - 去除加粗符号（``**``）与列表符号（``- `` / ``* ``）
        - 丢弃以元数据前缀开头的整行（标题/受众/大纲/角色等）
        - 合并为单行连续文本，压缩多余空白

    若清洗后文本过短（< 5 字），返回空串交由调用方回退。
    """
    if not text:
        return ""
    out_lines: list[str] = []
    for line in text.split("\n"):
        s = line.strip()
        if not s:
            continue
        s = _NARRATION_HEADING_RE.sub("", s).strip()   # 去标题 #
        if not s:
            continue
        s = _NARRATION_BULLET_RE.sub("", s).strip()     # 去列表符号
        if not s:
            continue
        # 元数据字段行：**字段**：值（如 **受众**：16-35岁…）
        if _NARRATION_FIELD_RE.match(s):
            continue
        s = s.replace("**", "").strip()                 # 去加粗
        if not s:
            continue
        low = s.lower()
        if any(low.startswith(p) for p in _NARRATION_METADATA_PREFIXES):
            continue
        out_lines.append(s)
    # 合并为一段连续旁白（配音不需要换行）
    result = "".join(out_lines)
    result = re.sub(r"\s{2,}", " ", result).strip()
    return result

class ScreenwriterStoryMixin:
    """故事/脚本/旁白生成方法（Batch 4 拆分，由 Screenwriter 组合）。"""

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
        raw = strip_code_fence(self._chat(system_prompt, user_prompt))
        # 清洗：剥离 LLM 可能回显的 Markdown 标题/加粗与元数据（故事标题/受众/大纲等）
        narration = clean_narration_text(raw)
        logger.info(
            f"[Screenwriter] Narration: {narration[:80]!r} "
            f"({len(narration)} chars, raw={len(raw)})"
        )
        return narration
