# 自动生成 Prompt 语言跟随修复 — 遗漏清理

## 修复概述

修复了 5 个文件中自动生成的 prompt 硬编码特定语言（而非跟随用户输入语言）的遗漏问题。

## 修复清单

### 1. `core/pipelines/simple_video.py` (HIGH)
- **行 136**：视频 prompt 分隔符 `"--- Generate image/video strictly based on..."` 硬编码英文
- **修复**：根据 `self._state.prompt` 检测语言，中文用户使用 `"--- 请严格按照以下描述生成图像/视频 ---"`

### 2. `core/pipelines/anchor_video.py` (HIGH)
- **行 32-35**：默认主播形象描述 `_DEFAULT_ANCHOR_PROMPT` 硬编码中文
- **修复**：拆分为 `_DEFAULT_ANCHOR_PROMPT_ZH` / `_DEFAULT_ANCHOR_PROMPT_EN`，新增 `_get_default_anchor_prompt()` 方法根据 `script_text` 语言返回对应版本

### 3. `core/pipelines/creative_video.py` (HIGH — 3处)
- **行 647/698/1163**：尾帧回退描述 `"cinematic end frame"` 硬编码英文
- **行 653-658/1173-1179**：`[PRESERVE]/[CHANGE]` 标签及身份保持指令硬编码英文
- **行 1056-1059**：过渡帧 prompt 硬编码英文
- **修复**：新增 3 个辅助函数 `_fallback_end_frame()`、`_localize_transition_prompt()`、`_localize_preserve_tags()`，根据场景文本语言返回对应版本

### 4. `server.py` (MEDIUM)
- **行 649-659**：`_build_encrypted_image_prompt()` 中的 Base64 解密指令硬编码英文
- **修复**：根据 `system_prompt` 语言返回对应的中文/英文解密说明

### 5. `core/screenwriter.py` (LOW)
- **行 92/94**：图片描述标签 `"起始帧"` / `"尾帧 {i-1}"` 硬编码中文
- **行 142**：`_describe_with_retry` 中的 `"Describe this image."` 硬编码英文
- **修复**：`describe_images()` 新增 `language_hint` 参数，根据用户输入语言使用对应标签和提示文本

## 未修改的（已有语言跟随机制）

`core/screenwriter.py` 中所有 12 个 system prompt 函数已在前期修复中包含 `"SAME LANGUAGE as the input"` 指令，模型会根据输入语言自动适配输出语言，无需额外处理。

## 验证

所有 5 个修改文件通过 `py_compile` 语法检查，无错误。
