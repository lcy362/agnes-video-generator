"""core.screenwriter.style — 字幕 LLM 智能样式方法（Batch 4 拆分）"""
import logging

logger = logging.getLogger(__name__)


class ScreenwriterStyleMixin:
    """字幕 LLM 智能样式方法（Batch 4 拆分）。"""

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
