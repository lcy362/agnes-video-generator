# 自动生成 Prompt 语言跟随 — 完整修复

## 第一轮：遗漏清理

修复了 5 个文件中自动生成的 prompt 硬编码特定语言的遗漏问题。

| 文件 | 问题 | 修复 |
|---|---|---|
| `simple_video.py` | 英文分隔符 | 根据 prompt 语言自适应 |
| `anchor_video.py` | 中文默认主播描述 | 中英双语 + 语言检测 |
| `creative_video.py` | 英文尾帧/标签/过渡 (3处) | 3 个本地化辅助函数 |
| `server.py` | 英文解密指令 | 根据 system_prompt 语言自适应 |
| `screenwriter.py` | 中文标签 + 英文文本提示 | `language_hint` 参数 |

## 第二轮：System Prompt 全量中文化

将 `core/screenwriter.py` 中所有用于生成提示词的 meta-prompt（system_prompt 和 user_prompt 指令）全部转换为中英双语版本。

### 架构设计

```
Screenwriter.__init__(api_key, model, language=None)
    │
    ├── language 参数:
    │   ├── None → 使用 PROMPT_LANGUAGE 环境变量（默认 "zh"）
    │   ├── "zh" → 所有 meta-prompt 使用中文
    │   └── "en" → 所有 meta-prompt 使用英文
    │
    └── _prompt(zh_text, en_text) → 根据 self.language 返回对应语言版本
```

### 切换方式

```bash
# 默认使用中文提示词（无需设置）
# 切换为英文提示词：
export PROMPT_LANGUAGE=en

# 或在代码中显式指定：
Screenwriter(api_key="...", language="en")
```

### 已中文化的 14 个方法

| 方法 | 转换内容 |
|---|---|
| `describe_images` | system_prompt + describe_text + 标签 |
| `_describe_with_retry` | 默认 text_prompt |
| `develop_story` | system_prompt + image_context 指令 |
| `write_script` | system_prompt |
| `extract_character_description` | system_prompt + user_prompt 指令 |
| `get_character_appearance` | system_prompt |
| `generate_end_frame_prompts` | context_block + system_prompt + user_prompt 指令 |
| `design_shots_for_scene` | system_prompt |
| `generate_scene_prompt_for_paragraph` | system_prompt + user_prompt 指令 |
| `generate_anchor_clip_prompt` | system_prompt + user_prompt 指令 |
| `generate_anchor_smooth_loop_prompt` | system_prompt + user_prompt 指令 |
| `generate_anchor_model_audio_prompt` | system_prompt + user_prompt 指令 |
| `generate_narration_for_video` | system_prompt + user_prompt 指令 |
| `generate_subtitle_styles` | role_context + system_prompt + user_prompt 指令 |

### 已修复的管道层双语化（第一轮）

| 文件 | 修复内容 |
|---|---|
| `creative_video.py` | `_fallback_end_frame()`、`_localize_transition_prompt()`、`_localize_preserve_tags()` |
| `anchor_video.py` | `_DEFAULT_ANCHOR_PROMPT_ZH` / `_DEFAULT_ANCHOR_PROMPT_EN` + 语言检测 |
| `simple_video.py` | 分隔符根据 prompt 语言自适应 |
| `server.py` | `_build_encrypted_image_prompt` 解密指令双语化 |

## 验证

所有修改文件通过 `py_compile` 语法检查，无错误。
