# rime.ai 语音模型评估（能否帮到本项目）

> 调研日期：2026-11-13
> **状态**：❌ 明确不做（作为默认/内置 TTS 引擎）；仅保留「非中文 + BYO Key 的可选插件引擎」这一窄口径待复查方向，优先级低于 R2（Kokoro 等本地开源 TTS）。
> 调研对象：[Rime AI](https://www.rime.ai)（企业级对话语音模型，非 rime.im 输入法）
> 关联条目：R2 [tts_research_report.md](tts_research_report.md)、项目决策 D8（不引入付费/自建 TTS，仅用 edge_tts）

---

## 一、结论先行

| 判断 | 结论 |
|------|------|
| 能否替代 edge_tts | ❌ **不能**。核心场景是中文，而 Rime 云端 TTS **完全没有中文**（官方语言矩阵与实时音色目录双重确认） |
| 能否提升非中文旁白质量 | ⚠️ **有限**。10 种语言里与项目 22 语言交集仅 10 种，且只有 6 种能拿到词级时间戳 |
| 对字幕体系的影响 | ❌ **负向**。时间戳只在 WebSocket/gRPC 上给，且仅 de/en/es/fr/it/pt；ja/ar/hi/nl 有音频无时戳，字幕会从「词级真值」退回启发式估算 |
| 与项目定位是否冲突 | ✅ **冲突**。项目卖点是「完全免费、无需任何 API Key」，引入 Rime 需要注册账号 + Bearer Key + 按分钟计费 |
| 与既有决策是否冲突 | ✅ **冲突**。D8 已定「不引入付费/自建 TTS」，R2 已就替代方案做过完整调研并维持现状 |
| 是否存在真实未被满足的增量 | ❌ 无。Rime 的强项（TTFA 30–37ms、对话式韵律、BAA/SOC 2、VPC/on-prem）对本项目（离线批量出片）全部无关 |

一句话：**Rime 是给实时语音坐席/IVR 用的对话型 TTS，本项目是「中文优先 + 词级字幕对齐 + 零成本」的批量视频生成器，两者的最优解不重叠。**

---

## 二、Rime 产品与能力盘点（截至 2026-11-13）

官方产品线：[Prism](https://www.rime.ai/prism)（语音到语音，实时代理）、[Coda v2 / Mist v3](https://www.rime.ai/tts-models)（TTS）、Rime STT（英/西）。与项目相关的只有 TTS。

| 维度 | Coda v2（旗舰） | Mist v3（最快） |
|------|----------------|----------------|
| 定位 | 质量优先，human eval 最高分 | 延迟优先，~37ms TTFB |
| 语言 | 10 种：en/es/fr/de/it/pt/ja/ar/hi/nl | 4 种：en/es/fr/de |
| 音色数 | 313 | 78 |
| 词级时间戳 | ✅ 仅 WebSocket / gRPC，仅 de/en/es/fr/it/pt | ✅ 仅 WebSocket / gRPC，仅英文 |
| 发音控制 | custom lexicon（X-SAMPA，仅 en/de/es/fr/it/pt）+ `spell()` | 英文 inline 发音控制 + 自定义停顿 |
| 语速 | `timeScaleFactor` 0.4–2.5（连续） | 同左 |
| 单请求上限 | 1,000 字符 | 1,000 字符 |
| 部署 | 云 / VPC / on-prem | 同左 |

### 2.1 中文：确认缺席（关键否决项）

- 官方语言矩阵（[Voices 文档](https://docs.rime.ai/docs/voices)）明确列出 10 种语言，**无 zh / Mandarin**；Arcana v3 时代（2026-02）的语言表同样只有 de/en/es/fr/he/ja/pt/si/ta，从未出现中文。
- 直接拉取官方实时音色目录 `https://users.rime.ai/data/voices/all-v2.json` 复核，结果为：

  ```
  coda  : eng jpn spa por ger fra ara hin ita nld   （10 种，313 音色）
  mistv3: eng spa ger fra                            （4 种，83 音色）
  ```

  即「中文」在 Rime 云端**没有任何一个可用音色**，不是「质量差」而是「不存在」。本项目的简单/创意/稿件/数字人/诗词五条流水线，主要旁白语言都是中文。

- 唯一理论出口是企业级 **voice cloning**（Enterprise 套餐，用自有录音训练定制音色）。这与「开源免费工具开箱即用」的产品形态完全不兼容，且克隆一个中文音色仍受底座语言能力限制，不在本次评估范围。

### 2.2 时间戳：只有 6 种语言，且只在 WebSocket 上

[Streaming HTTP 接口](https://docs.rime.ai/api-reference/coda/http)的参数表里**没有时间戳开关**；[WebSocket v1](https://docs.rime.ai/api-reference/coda/websocket-v1) 才有 `timestamps.enable`，时戳在音频结束后随 `done` 事件一次性返回 spans：

```json
{"text": "Smith", "start": "0.320s", "end": "0.720s"}
```

- 覆盖语言仅 `de/en/es/fr/it/pt`；文档明说「a context in a language Coda does not align, such as `ja` … gets no spans」。
- 单 context 音频超过 180 秒同样拿不到 spans。

对本项目意味着：英文视频可保留词级字幕真值；日语/阿拉伯语/印地语/荷兰语会**丢失**词级真值，字幕退化到 `estimate` 启发式（`generate_scene_aware_srt` 的兜底路径），比现在 edge_tts 还差。

### 2.3 定价

| 套餐 | 价格 | 备注 |
|------|------|------|
| Free | $0/月，含 **$50 用量** | 无需信用卡，$50 每月重置不滚存 |
| Flex | Coda **$0.05/分钟**、Mist **$0.03/分钟** | 约 1,000 字符 ≈ 1 分钟音频；按量计费 |
| Scale | $100/月，全档 8 折 | — |

按「1 分钟成片 ≈ 900–1,200 字符」粗算，Coda 约 **$0.05/条**；免费额度约覆盖 1,000 分钟音频/月。**单看钱不算贵，但对一个以「完全免费」为卖点的工具，任何按量计费 + 必须注册 Key，都是定位级冲突，而非成本级问题。**

---

## 三、项目现状盘点（对照基线）

| 项 | 现状 | 出处 |
|----|------|------|
| TTS 实现 | `EdgeTTSEngine` / `SilentTTSEngine`，抽象基类 `TTSEngine` | `core/audio/tts.py` |
| 成本 | 0，无需 API Key | — |
| 字幕真值 | 依赖 `edge_tts.SubMaker.cues` 逐词时间戳（v5.1 起为唯一真值来源） | `core/audio/subtitle/generator.py` |
| 降级链 | EdgeTTS 失败 → 静音占位 + legacy 启发式字幕 | `core/pipelines/__init__.py::_generate_audio_and_cues` |
| 音色 | 动态拉取 edge_tts 目录，按 22 种项目语言分组 | `core/audio/voices.py::PROJECT_LANGUAGES` |
| 既有决策 | D8：不引入付费/自建 TTS；R2 调研后维持 edge_tts | `docs/plans/v6.0/optimization_roadmap.md` |
| 依赖 | `websockets>=12.0,<14.0` **已在** requirements 中 | 接 Rime WS 不需新增依赖 |

`PROJECT_LANGUAGES` 22 种与 Rime 的交集：

```
交集(10)：en es fr de it pt ja ar hi nl
有词级时戳(6)：en es fr de it pt
项目缺口语种(12)：zh ko ru id ms tr vi th tl fa bn ur
```

---

## 四、假如要接：真实增量与代价

### 4.1 能拿到的增量（仅非中文场景）

| 增量 | 说明 | 是否值得 |
|------|------|---------|
| 音色自然度 | Coda 在对话语料上训练，human eval 优于 ElevenLabs Flash 2.5（官方口径） | ⚠️ 边际。本项目是旁白/朗诵，官方明确「trained on full-duplex conversations, not audiobook narrators」，register 并不对齐 |
| 发音控制 | `customLexicon`（X-SAMPA）、`spell()`、`timeScaleFactor` 0.4–2.5 | ✅ 真实空白。edge_tts 无任何专名/缩写控制手段 |
| 时戳 | 6 种语言词级 spans | ⚠️ 与 edge_tts 已有的 WordBoundary 能力重复，无净增 |
| 延迟 | 30–37ms TTFA | ❌ 无关。批量出片瓶颈是视频队列，不是 TTS 首字节 |
| 合规/部署 | BAA、SOC 2、VPC/on-prem | ❌ 无关。个人自部署工具无此诉求 |

### 4.2 代价

- **代码**：新增 `core/audio/rime_tts.py`（HTTP 合成 mp3 + WS 取时戳 + spans→`srt.Subtitle` 适配，约 300–500 行），改 `_generate_audio_and_cues` 的引擎选择、cue 缓存兼容、失败降级链。
- **配置/前端**：API Key 管理、引擎开关、Rime 音色→项目 22 语言的映射表、音色试听、22 语言 i18n 文案。
- **回归面**：字幕时间线是全项目最敏感的链路（S1/C1–C5/M1–M4/A1–A2/P1 全部涉及），换引擎必须重跑大版本回归。
- **产品面**：破坏「零 Key、零成本、开箱即用」，需要在 README/官网额外解释「什么情况下要配 Rime」，认知成本高于收益。
- **维护面**：Rime 正处于模型快速迭代期（Arcana→Coda 迁移、Mist v1/v2 于 2026-12-03 退役），跟进成本不低。

### 4.3 定性结论

即便只看英文视频，收益也只是「音色更好听 + 能控制专名发音」，代价是「付费依赖 + 一条新引擎的长期维护 + 全量字幕回归」。这在项目当前阶段（🟢 维护模式，优先级是稳定性）性价比为负。

---

## 五、未实施原因（归档依据）

1. **硬限制**：无中文音色 —— 主场景直接被排除，且这是模型能力问题，不是接入问题。
2. **硬限制**：词级时戳仅 6 种语言且仅 WS —— 接入后项目 22 语言中 16 种拿不到字幕真值，比现状更差。
3. **决策冲突**：D8「不引入付费/自建 TTS」仍然成立；R2 已就「替代 edge_tts」做过完整选型并维持现状。
4. **定位冲突**：「完全免费、无需 API Key」是项目核心卖点，按分钟计费的第三方 TTS 与之不相容。
5. **无独特增量**：Rime 的差异化能力（超低延迟、对话韵律、合规、私有化）全部落在本项目的需求之外。

---

## 六、复查触发条件

出现以下任一情况时，重新评估（且届时按「可选插件引擎 / BYO Key」形态，而非默认替换）：

1. Rime 云端上线 **zh / Mandarin** 音色，**且**中文也支持词级时间戳。
2. 项目定位发生实质变化：例如转向「付费/企业交付」，或明确要做**英文/日语为主**的播客、有声书、数字人口播产品线。
3. edge_tts 出现持续性封禁/限流，导致批量出片失败率不可接受（此条同时是 R2 的复查触发条件，届时应把 R2 的本地开源候选与 Rime 放在同一张表里比）。
4. 项目引入「多 TTS 引擎插件化」架构（D8 松动的先兆），Rime 可作为非中文档位的一个候选实现。

> 若触发条件 1 成立，本条的评级可从「❌ 不做」上调为「⚠️ 可评估」，但仍需先解决第 4 条的插件化前提。

---

## 七、如果目标是「提升中文 TTS」，正确的候选不是 Rime

R2 已系统比较过本地开源方案（Kokoro-82M / MeloTTS / CosyVoice 2 / GPT-SoVITS / Fish Speech），结论是 Kokoro-82M 为首选但因 D8 未实施。本次调研不重复该工作，只补充判断依据：

- 中文 + 词级时间戳 + 免费，三者同时满足的路径是「本地开源 TTS + 强制对齐（forced alignment）」，而不是换一家云端商用 API。
- 任何「云端按量计费 + 无中文」的组合（Rime 即此类）在中文场景下都不构成候选。

---

## 八、参考资料

- [Rime 官网](https://www.rime.ai) / [TTS 模型对比](https://www.rime.ai/tts-models) / [定价](https://www.rime.ai/pricing)
- [语言矩阵（Voices）](https://docs.rime.ai/docs/voices)
- [Coda Streaming HTTP 接口](https://docs.rime.ai/api-reference/coda/http)
- [Coda WebSocket v1（含时间戳章节）](https://docs.rime.ai/api-reference/coda/websocket-v1)
- [Changelog（无中文相关条目）](https://docs.rime.ai/docs/changelog)
- 实时音色目录：`https://users.rime.ai/data/voices/all-v2.json`