# PR #32 阿拉伯语支持：遗留问题与多语言缺口补齐（Arabic PR Follow-up）

> **来源**：GitHub PR #32「Arabic Language Added」（Khaled97Sho，2026-08-29 合并入 master `db33d23`；随附兼容性修复 `e8c31fa`）。
> **性质**：A 节为合并评审时发现并接受的遗留瑕疵；B 节为以 PR #32 实施模式为模板、补齐其余 UI 语言缺口的待办。
> **注意**：PR #32 改动目前仅在 master；v6.0-dev 需合并 master 后才会包含阿语链路，本文引用的代码位置以 master 为准。
> **状态（2026-08-30）**：✅ **A 节与 B 节均已实施完成**。A 节修复 `_ARABIC_RE` 排除 U+FEFF；B 节补齐 tr/vi/th/tl/hi/fa/bn/ur 共 8 种语言后端链路（音色分组/试听/脚本检测/字幕字体/RTL）。详见各节「实施记录」。

***

## A. 遗留问题：`_ARABIC_RE` 区间上限含 U+FEFF（BOM）

### 现状盘点

* `core/audio/voices.py` 的 `_ARABIC_RE = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-]")`，最后一个区间为 U+FE70–U+FEFF；U+FEFF 是零宽不换行空格（BOM），并非阿拉伯字符。

* 影响链路：`detect_text_script()` → 字幕渲染的阿语字体强制回退（`core/compositor/concatenator/concat.py`）与 `is_voice_compatible_with_text()` 的脚本级判定。

### 拟增强内容

* 将区间上限收紧至 U+FEFF 之前（拆分区间或显式排除），一行改动。

### 预判效果与代价

* 效果：消除「含 BOM 文本被误判为阿语 → 字幕误切阿语字体」的理论误报。

* 代价：极低。实际触发概率接近零（SRT 文本源自 TTS 输出，正常不含 BOM；且 `_shape_bidi_text` 对非阿文原样返回，误判后果仅为字体替换，视觉差异极小）。

### 实施记录（2026-08-30）

* `core/audio/voices.py`：`_ARABIC_RE` 末区间由 `ﹰ-﻿`（U+FE70–U+FEFF）收紧为 `ﹰ-ﻼ`（U+FE70–U+FEFC），显式排除 U+FEFF（BOM）。同时新增 `_THAI_RE` / `_DEVANAGARI_RE` / `_BENGALI_RE` 三个脚本正则（配合 B 节）。
* 验证：`detect_text_script("\ufeffHello") == "latin"`、`detect_text_script("\ufeff") != "arabic"`，单测覆盖（`tests/test_voice_multilang.py::test_bom_not_detected_as_arabic`）。

***

## B. 待办：以 PR #32 为模板补齐其余 UI 语言缺口

### 现状盘点

* 前端 UI 支持 22 种语言，音色目录 `PROJECT_LANGUAGES` 仅 14 种（zh/en/ja/ko/ru/de/fr/nl/es/pt/it/id/ms/ar）。缺口 8 种：**tr（土耳其语）/ vi（越南语）/ th（泰语）/ tl（菲律宾语）/ hi（印地语）/ fa（波斯语）/ bn（孟加拉语）/ ur（乌尔都语）**。

* PR #32 已完成阿语全链路：音色分组 → 姓名本地化（32 个）→ 试听文案（含 ar-SY 方言覆盖）→ 字幕 reshape+bidi → 内置 NotoNaskhArabicUI 字体。

* master `e8c31fa` 已对这 8 种语言跳过语言级音色校验（防 422 阻断任务创建），但体验仍是降级：无音色分组、无试听文案、字幕链路无对应字形支持。

* 脚本检测注意点：fa/ur 共用阿拉伯字母，现有 `_ARABIC_RE` 字符区间已覆盖；但 `_SCRIPT_COMPAT_VOICES["arabic"] = {"ar"}` 仅放行阿语音色，补齐 fa/ur 时需将其加入该集合。

### 拟增强内容（逐语言对照 PR #32 五件套）

1. `PROJECT_LANGUAGES` / `LANG_COMPAT` / `VOICE_PREVIEW_TEXTS` 增加对应语言条目；
2. 脚本检测正则：泰文 / 天城文（hi）/ 孟加拉文需新增 script 判定与 `_SCRIPT_COMPAT_VOICES` 映射；
3. 音色姓名本地化映射（edge-tts 仅提供拉丁转写，参照 `ARABIC_VOICE_NAMES` 的做法）；
4. 字幕字体：th/hi/bn 需内置对应 Noto 字体（每种约 100–300KB）；fa/ur 可复用 NotoNaskhArabicUI（需先验证波斯语专用字符 پ چ ژ گ 的字形覆盖）；
5. RTL：fa/ur 直接复用 `_shape_bidi_text` 的 reshape+bidi 管线，无需新增代码。

### 预判效果与代价

* 效果：8 种语言用户从「界面可看」升级到「声音可听、字幕可看」，与 PR #32 对阿语的提升同构。

* 代价：中低。数据条目级增量（正则 / 映射 / 文案），主要成本是内置字体二进制与逐语言回归验证；无架构改动。

### 实施记录（2026-08-30）

逐语言对照 PR #32 五件套完成：

1. **`PROJECT_LANGUAGES` / `LANG_COMPAT` / `VOICE_PREVIEW_TEXTS`**（`core/audio/voices.py`）：
   - 新增 8 种语言条目（tr/vi/tl=拉丁，th=thai，hi=devanagari，bn=bengali，fa/ur=arabic），共 22 种；
   - `LANG_COMPAT`：tr/vi/tl 并入拉丁互通集合；th/hi/bn/fa/ur 仅自身；
   - `VOICE_PREVIEW_TEXTS`：8 种语言各配本地试听句。
2. **脚本检测正则**（`core/audio/voices.py`）：新增 `_THAI_RE`（U+0E00–0E7F）/ `_DEVANAGARI_RE`（U+0900–097F）/ `_BENGALI_RE`（U+0980–09FF），`detect_text_script` 增加对应分支；`_SCRIPT_COMPAT_VOICES` 增加 thai→{th}、devanagari→{hi}、bengali→{bn}，并将 arabic 集合扩为 {ar, fa, ur}。
3. **音色姓名本地化映射**（`core/audio/voices.py`）：`ARABIC_VOICE_NAMES` 重构为按语言分组的 `_VOICE_NATIVE_NAMES`，新增 fa（2）/ur（4）/th（2）/hi（2）/bn（4）共 14 个本地姓名；保留 `ARABIC_VOICE_NAMES` 兼容别名。
4. **字幕字体**（`core/config.py` + `core/compositor/concatenator/{concat,audio_overlay}.py`）：
   - `config.py` 新增 `DEFAULT_THAI_FONT` / `DEFAULT_DEVANAGARI_FONT` / `DEFAULT_BENGALI_FONT`，并从 Google Fonts 下载 `NotoSansThai-Regular.ttf`（38KB）/ `NotoSansDevanagari-Regular.ttf`（244KB）/ `NotoSansBengali-Regular.ttf`（143KB）至 `resource/fonts/`；
   - fa/ur 复用 `NotoNaskhArabicUI.ttf`（已验证覆盖波斯语 پ چ ژ گ 与乌尔都语特殊字符）；
   - moviepy 字幕路径（`concat.py`）与 ASS 路径（`audio_overlay.py`）均改为逐条按脚本回退字体（`\fn` 覆盖）。
5. **RTL**：fa/ur 直接复用 `_shape_bidi_text` 的 reshape+bidi 管线，无新增代码。
6. **voice id 归一**：`get_voice_lang` 新增 `fil`→`tl` 映射（edge-tts Tagalog 音色前缀为 `fil-PH` 而非 `tl-PH`）。

**自验**：`tests/test_voice_multilang.py` 新增 32 项单测全通过（脚本检测 / voice 归一 / 兼容矩阵 / 本地姓名 / 目录分组 / ASS 字体回退）；全量后端单测（不含 mock_regression）459 项通过；mock_regression 28 项通过；`ruff` 零告警；`i18n_check` 通过。

