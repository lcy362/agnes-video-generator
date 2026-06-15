# Agnes Video Generator v2.1 — 代码与回归流程优化报告

## 修复日期
2026-06-15

## 一、字幕分割粒度过粗（核心修复）

**问题**：14 秒视频只有 5 条字幕，5 秒视频可能只有 1 条。edge_tts 默认生成的是句子级字幕。

**修复**：`core/audio/subtitle.py`

1. 新增 `_generate_fine_srt_from_word_cues()` — 利用 edge_tts 7.x SubMaker 的词级时间戳（`cues` 属性），按以下规则贪心分组：
   - 每条字幕最大 2.5 秒 / 18 字符
   - 优先在较长停顿处（>0.4s）断开
   - 尾部短组（<0.8s）仅在合并后不超限时才合并
2. 阈值保护：词级 cues < 6 个时回退到默认 SRT 生成
3. 容错处理：edge_tts 7.2.8 + 部分 srt 库的 `proprietary` 字段冲突会导致 `get_srt()` 崩溃，已添加 try/except 回退到手动构造

**效果**：14 秒视频预期从 5 条字幕提升到 6-7 条。

## 二、回归验证器误报修复

**问题**：上一轮回归报告中 C1/C4/M1/M2 共有 22 个"失败"检查，其中大多数是误报。

**修复**：`scripts/regression_runner.py`

| 修复项 | 根因 | 修复方式 |
|--------|------|---------|
| R3_all_completed | 非 keyframes 模式不运行 end_frame_prompts/generation 步骤 | 跳过模式特定步骤的检查 |
| R5_task_json / R5_has_video_id | 创意/稿件任务在子目录存储 task.json | 增加 scene_N//para_N/ 子目录扫描 |
| R6_curl_sh / R6_has_video_id_in_curl | 同理 | 同上 |
| R7_audio_files | 无配音场景判为 false | 根据 audio_enabled 参数判为 N/A |
| R10_srt_entries | 无配音场景仍检查 | 根据 audio_enabled 判为 N/A |
| 任务目录不存在 | C2/C3 因缺素材失败后验证崩溃 | 添加防御性处理 |

## 三、回归流程文档完善

**修复**：`docs/regression_test_plan.md`

1. **新增「八、工具依赖与问题排查」**：whisper/ffmpeg/moviepy 安装指南、常见问题、健康检查脚本
2. **新增「九、回归流程自迭代机制」**：执行时问题记录、迭代流程图、每次回归检查清单、验证逻辑修改原则
3. **新增测试素材自动生成**：PIL 可用时自动创建 test_ref.png/test_end.png
4. **章节重新编号**：原八→十，原九→十一

## 四、回归脚本增强

**修复**：`scripts/regression_runner.py`

- 新增 `_ensure_test_assets()` — 自动生成缺失的测试素材图片
- 在 `main()` 启动前调用素材检查

## 影响范围

| 文件 | 变更类型 | 风险 |
|------|---------|------|
| `core/audio/subtitle.py` | 新增细粒度 SRT + 容错 | 低（回退机制完整） |
| `scripts/regression_runner.py` | 修复验证误报 + 素材自动生成 | 低（仅改验证逻辑） |
| `docs/regression_test_plan.md` | 新增文档章节 | 无风险 |

## 后续建议

1. 下次执行回归时，关注字幕条目数是否合理（R10_srt_entries 预期 > 4）
2. C2/C3 需要准备 test_ref.png 才能正常通过
3. 如果 edge_tts 未来版本修复了 srt_composer 兼容性，可简化回退逻辑
