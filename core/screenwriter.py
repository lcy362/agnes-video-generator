import base64
import json
import logging
import mimetypes
import os
import time as _time
import requests
from typing import List

logger = logging.getLogger(__name__)

BASE_URL = "https://apihub.agnes-ai.com/v1"


class Screenwriter:
    def __init__(self, api_key: str, model: str = "agnes-2.0-flash"):
        self.api_key = api_key
        self.model = model
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _chat(self, system_prompt: str, user_prompt: str) -> str:
        logger.info(f"[Screenwriter] Calling chat API ({self.model}), prompt length: {len(user_prompt)} chars...")
        resp = requests.post(
            f"{BASE_URL}/chat/completions",
            headers=self.headers,
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.7,
                "max_tokens": 4096,
            },
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    def _chat_json(self, system_prompt: str, user_prompt: str) -> dict:
        content = self._chat(system_prompt, user_prompt)
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1]
            if content.endswith("```"):
                content = content[:-3]
        return json.loads(content)

    def _image_to_b64_uri(self, path: str) -> str:
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        mime = mimetypes.guess_type(path)[0] or "image/png"
        return f"data:{mime};base64,{b64}"

    def _chat_multimodal(self, system_prompt: str, text_prompt: str, image_paths: List[str]) -> str:
        messages = [{"role": "system", "content": system_prompt}]

        user_content = [{"type": "text", "text": text_prompt}]
        for img_path in image_paths:
            if img_path.startswith(("http://", "https://")):
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": img_path},
                })
            elif os.path.exists(img_path):
                b64_uri = self._image_to_b64_uri(img_path)
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": b64_uri},
                })
        messages.append({"role": "user", "content": user_content})

        logger.info(f"[Screenwriter] Calling multimodal chat API ({self.model}), "
                     f"{len(image_paths)} image(s), prompt: {len(text_prompt)} chars...")
        resp = requests.post(
            f"{BASE_URL}/chat/completions",
            headers=self.headers,
            json={
                "model": self.model,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 4096,
            },
            timeout=300,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    def describe_images(self, image_paths: List[str], cache_dir: str = "") -> str:
        if not image_paths:
            return ""

        single_prompt = """\
Describe this image in rich visual detail. Note the character(s), their \
appearance (clothing, body type, hair, pose), the environment, colors and \
lighting, art style, and mood. Write 3-5 sentences in natural language — as if \
dictating to a story writer. Do NOT say "the image shows" — just describe what \
you see directly. Write in Chinese if the content appears Chinese, English \
otherwise.
"""

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
                        if cached_descriptions:
                            logger.info(f"[Screenwriter] Loaded {len(cached_descriptions)} cached descriptions")
                except Exception:
                    pass

        logger.info(f"[Screenwriter] Describing {total} images one by one...")

        descriptions = []
        for i, img_path in enumerate(image_paths):
            if i == 0:
                label = "起始帧"
            else:
                label = f"尾帧 {i - 1}"

            cache_key = str(i)
            if cache_key in cached_descriptions:
                desc = cached_descriptions[cache_key]
                descriptions.append(f"[{label}] {desc.strip()}")
                continue

            desc = self._describe_with_retry(single_prompt, img_path, label)
            descriptions.append(f"[{label}] {desc.strip()}")

            if cache_file:
                cached_descriptions[cache_key] = desc.strip()
                try:
                    with open(cache_file, "w", encoding="utf-8") as f:
                        json.dump({
                            "image_paths": image_paths,
                            "descriptions": cached_descriptions,
                        }, f, ensure_ascii=False, indent=2)
                except Exception:
                    pass

        combined = "\n\n".join(descriptions)
        logger.info(f"[Screenwriter] All {total} images described: {len(combined)} chars")
        return combined

    def _describe_with_retry(self, prompt: str, img_path: str, label: str, max_retries: int = 3) -> str:
        for attempt in range(max_retries):
            try:
                return self._chat_multimodal(prompt, "Describe this image.", [img_path])
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
                    return f"(分析失败: {str(e)[:100]})"

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
"""
        user_prompt = f"""\
<idea>
{idea}
</idea>

<user_requirement>
{user_requirement}
</user_requirement>

<style>
{style}
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
    "Scene 1 visual prompt (detailed English description for video generation)...",
    "Scene 2 visual prompt...",
    ...
  ]
}

Rules:
- Each scene MUST be a detailed VISUAL DESCRIPTION in ENGLISH, suitable for AI video generation.
- Do NOT include character names in angle brackets or dialogue tags.
- Focus on: camera movement, lighting, colors, environment, character actions, atmosphere, mood.
- Include specific visual details: lens type (wide/telephoto), depth of field, camera angle, \
lighting direction, color grading, particle effects, weather.
- Each scene should be 80-150 words, rich in cinematic detail.
- Maintain visual consistency across scenes (same character appearance, coherent world).
- Number of scenes MUST respect the user requirement constraints.
- The art style should match the requested style (realistic cinematic, anime, etc.).
- Describe MOTION and ACTION, not static images — this is for video generation.
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

The prompt should be in ENGLISH regardless of the story language, for best \
image generation results. It should be a single paragraph, 3-5 sentences, \
rich in visual detail. Include the art style (e.g., "realistic cinematic", \
"anime style", "watercolor illustration").

Output ONLY the image prompt text, no JSON, no explanation.
"""
        user_prompt = f"""\
<story>
{story}
</story>

<style>{style}</style>
"""
        logger.info("[Screenwriter] Extracting character reference prompt...")
        prompt = self._chat(system_prompt, user_prompt).strip()
        if prompt.startswith("```"):
            prompt = prompt.split("\n", 1)[1]
            if prompt.endswith("```"):
                prompt = prompt[:-3]
            prompt = prompt.strip()
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

Output ONLY the appearance description text. No JSON, no labels, no markdown.
"""
        appearance = self._chat(system_prompt, story).strip()
        if appearance.startswith("```"):
            appearance = appearance.split("\n", 1)[1]
            if appearance.endswith("```"):
                appearance = appearance[:-3]
            appearance = appearance.strip()
        logger.info(f"[Screenwriter] Character appearance: {appearance[:100]}...")
        return appearance

    def generate_end_frame_prompts(
        self, scenes: List[str], style: str, character_appearance: str = ""
    ) -> List[str]:
        if character_appearance:
            character_block = f"""
[CHARACTER APPEARANCE — This must appear verbatim in every prompt]
{character_appearance}

YOUR PROMPT MUST explicitly include ALL of the above appearance details
(hair, face, glasses, clothing, shoes) — word for word. Only the pose,
expression, and environment should change between scenes.
"""
        else:
            character_block = ""

        system_prompt = f"""\
You are a visual prompt engineer for AI image generation. Generate a STATIC \
image prompt that represents what this video scene looks like at its very END \
— the final frozen frame of the video.
{character_block}
Rules:
- Describe a STATIC frozen moment, NOT motion or action verbs.
- Focus on: pose, facial expression, hand position, body posture, camera angle, \
lighting, background elements — everything visible in a single frozen frame.
- Include art style (e.g., "realistic cinematic", "anime").
- 3-5 sentences, rich in visual detail.
- MUST be in ENGLISH.

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
            prompt = self._chat(system_prompt, user_prompt).strip()
            if prompt.startswith("```"):
                prompt = prompt.split("\n", 1)[1]
                if prompt.endswith("```"):
                    prompt = prompt[:-3]
                prompt = prompt.strip()
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