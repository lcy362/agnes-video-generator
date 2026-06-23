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


def _xml_escape(text: str) -> str:
    """XML 转义用户输入，防止 prompt 注入。

    将 < > & " ' 转义为 XML 实体，避免用户输入中的标签
    提前闭合 XML 结构（如 </idea>）导致指令注入。
    """
    if not text:
        return text
    return html.escape(text, quote=True)


class Screenwriter:
    def __init__(self, api_key: str, model: str = "agnes-2.0-flash"):
        self.api_key = api_key
        self.model = model
        self.chat_api = AgnesChatAPI(api_key=api_key, model=model)
        # 保持旧 headers 供直接引用（兼容）
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

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
            else False
        )

        if has_chinese:
            single_prompt = """\
请用丰富的视觉细节描述这张图片。包括角色（服装、体型、发型、姿势）、\
环境、色彩与光线、艺术风格和氛围。用自然语言写 3-5 句话——就像口述给\
故事编剧一样。不要写"图片展示了"——直接描述你看到的内容。用中文输出。
"""
            describe_text = "请描述这张图片。"
            label_start = "起始帧"
            label_end = "尾帧"
        else:
            single_prompt = """\
Describe this image in rich visual detail. Note the character(s), their \
appearance (clothing, body type, hair, pose), the environment, colors and \
lighting, art style, and mood. Write 3-5 sentences in natural language — as if \
dictating to a story writer. Do NOT say "the image shows" — just describe what \
you see directly. Write in Chinese if the content appears Chinese, English \
otherwise.
"""
            describe_text = "Describe this image."
            label_start = "Start Frame"
            label_end = "End Frame"

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

    def _describe_with_retry(self, prompt: str, img_path: str, label: str, text_prompt: str = "Describe this image.", max_retries: int = 3) -> str:
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

    def develop_story(self, idea: str, user_requirement: str, style: str, image_context: str = "") -> str:
        system_prompt = """\
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
"""
        user_prompt = f"""\
<idea>
{_xml_escape(idea)}
</idea>

<user_requirement>
{_xml_escape(user_requirement)}
</user_requirement>

<style>
{_xml_escape(style)}
</style>
"""
        if image_context:
            user_prompt += f"""
<image_context>
The following describes actual images that will be used as keyframes in the video.
The story MUST align with the visual content described below — use the same
characters, settings, colors, and mood.

{image_context}
</image_context>
"""
        logger.info("[Screenwriter] Developing story..." + (" (with image context)" if image_context else ""))
        story = self._chat(system_prompt, user_prompt)
        logger.info(f"[Screenwriter] Story developed: {len(story)} chars")
        return story

    def write_script(self, story: str, user_requirement: str, style: str) -> List[str]:
        system_prompt = """\
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
"""
        user_prompt = f"""\
<story>
{story}
</story>

<user_requirement>
{user_requirement}
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
        system_prompt = """\
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
"""
        user_prompt = f"""\
<story>
{story}
</story>

<style>{style}</style>

Write the character image prompt in the SAME LANGUAGE as the story above.
"""
        logger.info("[Screenwriter] Extracting character reference prompt...")
        prompt = strip_code_fence(self._chat(system_prompt, user_prompt))
        logger.info(f"[Screenwriter] Character prompt: {prompt[:100]}...")
        return prompt

    def get_character_appearance(self, story: str) -> str:
        system_prompt = """\
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
"""
        appearance = strip_code_fence(self._chat(system_prompt, story))
        logger.info(f"[Screenwriter] Character appearance: {appearance[:100]}...")
        return appearance

    def generate_end_frame_prompts(
        self, scenes: List[str], style: str, character_appearance: str = ""
    ) -> List[str]:
        # 批次4：角色外观由批次3的程序化拼入处理，LLM 只输出 [CHANGE] 部分
        # 系统提示中仍提供 character_appearance 作为上下文参考，避免 LLM 描述与角色矛盾
        if character_appearance:
            context_block = f"""
[CONTEXT — Character appearance for reference only, do NOT copy into output]
{character_appearance}

Your prompt should describe the SCENE'S END FRAME only — environment, pose, \
lighting, mood, camera angle. Do NOT repeat the character's hair, face, \
clothing, or accessories — those are injected programmatically.
"""
        else:
            context_block = ""

        system_prompt = f"""\
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
"""
        end_frames = []
        for scene_idx, scene_text in enumerate(scenes):
            logger.info(f"[Screenwriter] Generating end frame prompt for scene {scene_idx}...")
            user_prompt = f"""\
<style>{style}</style>

<scene>
{scene_text}
</scene>

Write the STATIC end-frame image prompt for this scene. This should describe
what the final frozen frame of this scene looks like — the pose, expression,
lighting, and environment at the moment this scene ends.
"""
            prompt = strip_code_fence(self._chat(system_prompt, user_prompt))
            end_frames.append(prompt)
            logger.info(f"[Screenwriter] End frame {scene_idx} prompt: {prompt[:80]}...")

        logger.info(f"[Screenwriter] Generated {len(end_frames)} end frame prompts")
        return end_frames

    def design_shots_for_scene(self, scene_text: str, style: str, max_shots: int = 5) -> list:
        system_prompt = """\
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
"""
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
        system_prompt = """\
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
"""
        style_block = f"\n<style>{style}</style>\n" if style else ""
        user_prompt = f"""\
<paragraph>
{text}
</paragraph>
{style_block}
Generate a detailed visual prompt for this paragraph.
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
        system_prompt = """\
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
""".format(segment_index=segment_index + 1, total_segments=total_segments)

        user_prompt = f"""\
<anchor_appearance>
{anchor_prompt}
</anchor_appearance>

<narration_segment>
{paragraph_text}
</narration_segment>

Generate the motion prompt for this segment.
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
        system_prompt = """\
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
"""

        user_prompt = f"""\
<anchor_appearance>
{anchor_prompt}
</anchor_appearance>

Generate the smooth-loop motion prompt for a 5-second looping clip.
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
        system_prompt = """\
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
"""

        user_prompt = f"""\
<anchor_appearance>
{anchor_prompt}
</anchor_appearance>

<narration>
{script_text[:500]}
</narration>

Generate the video prompt for this anchor segment with built-in audio.
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

        system_prompt = f"""\
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
"""
        style_block = f"\n<style>{style}</style>\n" if style else ""
        user_prompt = f"""\
<story>
{story}
</story>

<scenes>
{scene_summary}
</scenes>
{style_block}
Write ONE continuous narration voiceover in the SAME LANGUAGE as the story for the entire video, \
approximately {max_chars} characters total.
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

        role_context = f"The scene is a {role} scenario." if role else ""

        system_prompt = f"""\
You are a professional subtitle stylist for short video production. \
Given a subtitle list and video dimensions, assign each subtitle a visual \
style that enhances the viewing experience.

Video size: {video_width}x{video_height}px
Safe area: 40px margin on each side = {safe_w}x{safe_h}px available

{role_context}

Output a JSON array, one object per subtitle:
[
  {{
    "index": <int, matching the subtitle index>,
    "position": ["<horizontal>", "<vertical>"],
    "color": "<color name or #RRGGBB>",
    "fontsize": <int 18-80>
  }},
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
"""

        user_prompt = f"""\
<subtitle_entries>
{entries_text}
</subtitle_entries>

<style_hints>
{style_hints or "(no specific preference — use professional defaults)"}
</style_hints>

Assign styles to each subtitle and return the JSON array.
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