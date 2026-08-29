# PR #32 阿拉伯语支持：遗留问题与多语言缺口补齐（Arabic PR Follow-up）

> **来源**：GitHub PR #32「Arabic Language Added」（Khaled97Sho，2026-08-29 合并入 master `db33d23`；随附兼容性修复 `e8c31fa`）。
> **性质**：A 节为合并评审时发现并接受的遗留瑕疵；B 节为以 PR #32 实施模式为模板、补齐其余 UI 语言缺口的待办。
> **注意**：PR #32 改动目前仅在 master；v6.0-dev 需合并 master 后才会包含阿语链路，本文引用的代码位置以 master 为准。

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

### 未实施原因

* 合并评审时判定为可接受瑕疵，不阻断合并；留待下次触碰 `voices.py` 时顺手修复。

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

### 未实施原因

* 未排期。PR #32 刚合并，先观察阿语链路在真实任务中的稳定性（重点：reshape+bidi 字幕渲染、阿语字体回退），再决定是否按此模板批量补齐。

* 触发条件：出现 tr/vi/th/hi/fa/bn/ur 用户的明确反馈，或规划下一个小/中版本时纳入实施批次。

