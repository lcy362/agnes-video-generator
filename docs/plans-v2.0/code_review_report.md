# Agnes Video Generator v2.0 — 全面代码审查报告

| 元数据 | 值 |
|--------|-----|
| 审查日期 | 2026-06-16 |
| 审查范围 | 全量代码（后端 / 音视频合成 / 前端 / 测试 / 构建 / 文档） |
| 审查方式 | 3 路并行代码审查 + 关键文件人工复核 |
| 问题总数 | 24（高 6 / 中 10 / 低 8） |
| 修复批次 | 阶段 1（P0 安全/正确性）→ 阶段 2（P1 健壮性）→ 阶段 3（P2 工程质量） |

---

## 修复状态总览

| 编号 | 严重度 | 问题 | 状态 |
|------|--------|------|------|
| H1 | 高 | 尾帧冻结输出被截断、音视频不同步 | ✅ 已修复 |
| H2 | 高 | API Key 明文落盘 + 权限 0644 | ✅ 已修复 |
| H3 | 高 | 前端存储型 XSS（innerHTML 未转义） | ✅ 已修复 |
| H4 | 高 | task_state.json 非原子写，崩溃即损坏 | ✅ 已修复 |
| H5 | 高 | WebSocket 连接覆盖竞态 + 进度回调失联 | ✅ 已修复 |
| H6 | 高 | _synth 缓存不复验、从不清理 | ✅ 已修复 |
| M1 | 中 | 字幕默认位置 bottom-80 偏移被丢弃 | ✅ 已修复 |
| M2 | 中 | stop() 无法中断阻塞中的 requests | ✅ 已修复 |
| M3 | 中 | _poll_task 无总超时上限 | ✅ 已修复 |
| M4 | 中 | video_duration Form 参数被静默丢弃 | ✅ 已修复 |
| M5 | 中 | 大量 except Exception: pass 静默吞异常 | ✅ 已修复 |
| M6 | 中 | asyncio.create_task 未持有引用 | ✅ 已修复 |
| M7 | 中 | EdgeTTS 无错误处理，抖动即任务失败 | ✅ 已修复 |
| M8 | 中 | regression_runner 参数与 server 不符 | ✅ 已修复 |
| M9 | 中 | 音量增益 2.5x 必然削波 | ✅ 已修复 |
| M10 | 中 | 字幕时间戳未按视频时长钳位 | ✅ 已修复 |
| L1 | 低 | 无自动化单元测试 | ✅ 已修复 |
| L2 | 低 | requirements 版本下限与 moviepy v2 API 矛盾 | ✅ 已修复 |
| L3 | 低 | .gitignore *.png/*.jpg 过于宽泛 | ✅ 已修复 |
| L4 | 低 | 上传文件名直接拼路径（穿越风险） | ✅ 已修复 |
| L5 | 低 | start.sh 无 python/ffmpeg/端口校验 | ✅ 已修复 |
| L6 | 低 | AGENTS.md 文档与代码多处不符 | ✅ 已修复 |
| L7 | 低 | concat method="compose" 不同分辨率会 pad 黑边 | ✅ 已修复 |
| L8 | 低 | WebSocket 重连逻辑失效 | ✅ 已修复 |

> 状态图例：⬜ 待修复 / 🔄 修复中 / ✅ 已修复 / ✔️ 已验证

---

## 🔴 高严重度问题

### H1. 尾帧冻结 `freeze_last_frame` 逻辑错误，导致音视频不同步
- **文件**：`core/compositor/processor.py:96-134`
- **根因**：
  1. 第 104 行 `trim=duration={freeze_duration}` 已将冻结段限制为 freeze 时长，但第 108 行又加了 `-t {freeze_duration}`，**把整个输出截断成只剩冻结段**——原视频内容被丢弃，违背函数"原视频 + 补齐冻结帧"语义。
  2. moviepy 回退分支（第 117 行）`clip.to_ImageClip(duration=freeze_duration)` 不是 moviepy 2.x 合法 API，会抛 `AttributeError`。
- **影响**：所有需要补齐音视频时长的 TTS 旁白视频最终成片错误。
- **修复方案**：重写 ffmpeg 滤镜，去掉冗余 `-t`，用 `tpad=stop_mode=clone:stop_duration=` 正确拼接；修正 moviepy 回退为 `ImageClip(clip.get_frame(clip.duration), duration=...)` 并加 try/except。
- **批次**：阶段 1

### H2. API Key 明文落盘且文件权限宽松（0644）
- **文件**：`core/config.py:79-108`
- **根因**：`save_config` 用 `open(CONFIG_FILE, "w")` 默认权限写入，无 `os.chmod(0o600)`；`load_config`/`save_config` 未指定 `encoding="utf-8"`，非 UTF-8 locale 下含中文 config 会报错。配合 `GET /api/config`（server.py:204）返回 key 前 8 位，构成信息泄露面。
- **影响**：同机其他用户可读取 API Key；非 UTF-8 系统读写崩溃。
- **修复方案**：`save_config` 写入后 `os.chmod(CONFIG_FILE, 0o600)`；目录 `os.chmod(0o700)`；统一加 `encoding="utf-8"`。
- **批次**：阶段 1

### H3. 前端存储型 XSS（任务列表直接拼 innerHTML）
- **文件**：`static/index.html:1424-1433, 1567-1581`
- **根因**：`task.idea` / `task.prompt` / `task.manuscript_text` / `task.creative_name` 等用户可控字段未做 HTML 转义直接拼进 `innerHTML`。攻击者提交 `idea="<img src=x onerror=alert(1)>"` 即可执行任意脚本；`task.task_id` 被拼进 `onclick='...'`，可用单引号闭合注入属性。
- **影响**：存储型 XSS，影响所有查看任务列表的用户。
- **修复方案**：新增 `escapeHtml(s)` 工具函数（转义 `& < > " '`），对所有动态字段统一转义；`task_id` 在 onclick 里额外清洗单引号/反斜杠。
- **批次**：阶段 1

### H4. task_state.json 非原子写入 + 长任务频繁全量重写
- **文件**：`core/task_manager.py:91-96`
- **根因**：`open(path, "w")` 直接覆盖。配合 server.py:716 的 `os._exit(1)`（第二次 Ctrl+C 立即终止进程），写入中途被杀会留下截断的损坏 JSON，`load()` 解析失败被 except 吞掉（line 87-89），任务永久丢失。creative pipeline 每个 step 都全量 `model_dump`，放大损坏窗口。
- **影响**：长视频生成任务中断后状态文件损坏，无法断点续传。
- **修复方案**：`_save` 改为写临时文件 `.tmp` + `os.replace` 原子替换（复用 agnes_video.py:88-95 已验证的 `.url` 缓存写法）。
- **批次**：阶段 1

### H5. WebSocket 连接覆盖竞态 + 进度回调失联
- **文件**：`server.py:142, 158-160, 172-173`
- **根因**：同一 task_id 重连时，新 WS 直接覆盖 `active_connections[task_id]`，旧 WS 既不 close 也不清理。新 WS 绑定到 pipeline 的 `progress_callback` 后若断开，`active_connections` 被删，但 pipeline 仍持有旧闭包，后续 `send_json` 抛异常被 `except Exception: pass`（line 155）静默吞掉——前端永远收不到进度。
- **影响**：断线重连后进度推送失效。
- **修复方案**：连接前检查并 `await old_ws.close()`；pipeline 通过 `_make_progress_callback(task_id)` 间接查找而非捕获具体 ws；断开时仅当确认是当前 WS 才删 key。
- **批次**：阶段 2

### H6. `concat_with_audio` 的 `_synth` 缓存不校验、不复验、从不清理
- **文件**：`core/compositor/concatenator.py:96-104`
- **根因**：只要 `_synth.mp4` 存在就直接复用，无版本/时长校验。上次运行失败留下的半成品、或字幕/音频配置已改后仍复用旧片段。`_synth.mp4` 是中间产物但从不清理（只清理 `_naked`/`_freeze`），长期堆积占满磁盘。
- **影响**：配置变更后不重建；磁盘泄漏。
- **修复方案**：加 content hash 或时长校验；合成完成后清理 `_synth` 文件。
- **批次**：阶段 2

---

## 🟠 中严重度问题

### M1. 字幕默认位置 `bottom-80` 偏移被静默丢弃
- **文件**：`core/config.py:170` → `core/compositor/concatenator.py:122-125`、`core/audio/subtitle.py`
- **根因**：默认配置 `position=("center","bottom-80")`，但 `_resolve_subtitle_position` 只匹配 `"bottom"` 子串，80px 偏移被丢弃，字幕实际贴底而非上移 80px。
- **修复方案**：在 `_resolve_subtitle_position` 中解析 `"bottom-N"`/`"top+N"` 格式，转换为数值或 lambda。
- **批次**：阶段 2

### M2. `stop()` 无法中断阻塞中的 `requests` 调用
- **文件**：`core/pipelines/__init__.py:63-65` + `core/api/agnes_video.py:198-203, 240`
- **根因**：`stop()` 只设 asyncio.Event，但所有 HTTP 用同步 `requests` + `to_thread`。`_poll_task` 的 `timeout=15`、submit 的 `timeout=(30,180)` 期间，停止信号要等当前请求返回才生效——最坏用户点停止后还要等 180s。
- **修复方案**：改用 `httpx.AsyncClient`（原生可取消），或 `to_thread` 外包 `asyncio.wait_for` + Event。
- **批次**：阶段 2

### M3. `_poll_task` 无总超时上限
- **文件**：`core/api/agnes_video.py:192-226`
- **根因**：`while True` 只在 completed/failed 退出；`except RequestException` 仅 warning 后继续轮询。若 Agnes API 持续 5xx 或网络中断，任务永远轮询占着 pipeline 槽位。
- **修复方案**：加 `max_poll_duration`（如 30 分钟）或连续失败计数器，超限后 raise。
- **批次**：阶段 2

### M4. `create_creative_task` 的 `video_duration` Form 参数被丢弃
- **文件**：`server.py:447, 474, 502`
- **根因**：端点声明了 `video_duration: int = Form(5)`，但实际用的是 `_parse_duration(user_requirement)`。前端/回归脚本填的 `video_duration` 被静默忽略，时长完全依赖 `user_requirement` 中文正则匹配（匹配不到就强制 5s）。
- **修复方案**：优先使用显式 `video_duration` 参数，仅在其为默认值时回退到解析。
- **批次**：阶段 2

### M5. 大量 `except Exception: pass` 静默吞异常（≥9 处）
- **文件**：`server.py:122, 155, 318`、`task_manager.py:160`、`agnes_video.py:84-85, 95-96` 等
- **根因**：出错后既不记日志也不上报，调试黑盒。尤其 line 155：WS 发送失败被吞，pipeline 继续往死 WS 推送。
- **修复方案**：至少 `logger.debug/warning` 记录；WS 发送失败时主动从 `active_connections` 移除并尝试重绑。
- **批次**：阶段 2

### M6. `asyncio.create_task` 未持有引用，可能被 GC 回收
- **文件**：`server.py:433, 523, 591, 680`
- **根因**：fire-and-forget 反模式，Python 文档明确警告不保存引用的任务可能被回收。
- **修复方案**：维护 `background_tasks: set`，`task.add_done_callback(background_tasks.discard)` 后再加入。
- **批次**：阶段 2

### M7. `EdgeTTSEngine.generate` 无错误处理，网络抖动即任务失败
- **文件**：`core/audio/tts.py:51-64`
- **根因**：stream 循环无 try/except，且 `SilentTTSEngine` 降级只在 narration 为空时触发，一次 edge_tts 抖动整个任务失败；失败时还会留下半成品 mp3 被下游误用。
- **修复方案**：try/except 包裹 stream 循环，失败时删半成品 + 降级到 SilentTTSEngine；加 ffmpeg probe 校验音频完整性。
- **批次**：阶段 2

### M8. regression_runner 参数与 server 实际行为不符
- **文件**：`scripts/regression_runner.py:128, 129, 137, 157`
- **根因**：creative 场景传 `video_duration: 5`（被 server 忽略，见 M4）；传 `chaining_mode: "independent"`（前端合法值是 `keyframes/ti2vid/none`）。回归测试在"假跑"，C1/C4 语义与真实 UI 不一致。
- **修复方案**：脚本参数改为 `chaining_mode: "none"`，并配合 M4 修复后 `video_duration` 才真正生效。
- **批次**：阶段 2

### M9. `audio_volume_scaled(2.5)` 固定增益必然削波
- **文件**：`core/compositor/concatenator.py:245-246, 357-358`
- **根因**：edge_tts 输出已是归一化的，2.5x 线性放大几乎必然 PCM 削波（>1.0 样本被 clip），无 limiter/normalize。
- **修复方案**：用 `afx.audio_normalize` 或动态范围压缩，或降到 1.5x 并加 limiter。
- **批次**：阶段 2

### M10. 字幕时间戳未按视频时长钳位
- **文件**：`core/compositor/concatenator.py:139-197`
- **根因**：SRT 的 `end_s` 可能超过视频实际时长（尤其 freeze 补齐后），TextClip `with_end` 超界导致渲染黑屏/报错。无 `end_s = min(end_s, video_duration)` 钳位。
- **修复方案**：传入 `video_duration` 参数，`end_s = min(end_s, video_duration - 0.01)`。
- **批次**：阶段 2

---

## 🟡 低严重度问题

### L1. 完全没有自动化单元测试
- **文件**：项目根目录（无 `tests/`、无 `test_*.py`、无 `conftest.py`）
- **根因**：AGENTS.md 第二层"单元测试"清单（models/task.py、`_split_long_text`、`split_manuscript`、`resolve_font_path`）在代码中不存在。根目录 `_test_reset.py` 硬编码 `.working_dir/67c01fcf7e7d/...`（该目录已不存在），运行必 `FileNotFoundError`。
- **修复方案**：新建 `tests/`，用 pytest 覆盖上述模块；删除或参数化 `_test_reset.py`。
- **批次**：阶段 3

### L2. requirements.txt 版本下限与 moviepy v2 API 矛盾
- **文件**：`requirements.txt:7`
- **根因**：`moviepy>=1.0.3`，但代码全用 `from moviepy import VideoFileClip`（v2 写法）。装 1.0.3 会 ImportError；所有依赖只用 `>=` 无上限/锁文件，"维护模式"下不可复现。
- **修复方案**：改用 `~=`/精确版本；至少 moviepy 锁到 `>=2.0.0`；生成 `requirements.lock`。
- **批次**：阶段 3

### L3. `.gitignore` 的 `*.png/*.jpg/*.mp4` 过于宽泛
- **文件**：`.gitignore:8-11`
- **根因**：会误伤 `docs/` 配图、README 截图、测试素材 `test_ref.png`/`test_end.png`（回归脚本依赖）。未忽略 `.writing/`、`.regression_server.log`（实际已存在残留）。
- **修复方案**：`*.png` 改为精确路径（如 `.working_dir/**/*.png`），用 `!test_ref.png` 强制保留测试素材；新增 `.writing/`、`.regression_server.log`。
- **批次**：阶段 3

### L4. 上传文件名直接拼路径（穿越风险）
- **文件**：`server.py:412, 512`
- **根因**：`reference_image.filename` 来自客户端，未做清洗就 `os.path.join`，可含 `../`。
- **修复方案**：用 `uuid` 或 `werkzeug.utils.secure_filename` 清洗，或用 `f"{task_id}_ref{os.path.splitext(filename)[1]}"`。
- **批次**：阶段 3

### L5. start.sh 无环境校验
- **文件**：`start.sh`
- **根因**：不检查 python3 版本（要求 3.10+）、不检查 ffmpeg 是否安装、不检测端口 8765 占用。
- **修复方案**：开头加 `python3 -c 'import sys; assert sys.version_info>=(3,10)'`、`command -v ffmpeg` 检查、`lsof -ti:8765` 检测。
- **批次**：阶段 3

### L6. AGENTS.md 文档与代码多处不符
- **文件**：`AGENTS.md:238-297, 349-357, 608`
- **根因**：目录树遗漏 `core/pipeline.py`、`core/image_generator.py`、`core/video_generator.py`、`docs/plans-v1.0/development_plan.md`、`docs/plans-v2.0/fix_plan.md`；场景权重表与代码 `SCENARIO_WEIGHTS` 不一致；D5 称"8 个参数"，实际 simple 端点 9 个。
- **修复方案**：对齐目录树、权重表、参数计数。
- **批次**：阶段 3

### L7. `concat_videos` 用 `method="compose"` 不同分辨率会 pad 黑边
- **文件**：`core/compositor/concatenator.py:52`
- **根因**：各场景分辨率有 ±px 抖动时，`compose` 会 pad 到最大公共尺寸（黑边）而非缩放对齐。
- **修复方案**：拼接前统一 `resize_video` 到目标分辨率，或文档约束各场景同尺寸。
- **批次**：阶段 3

### L8. WebSocket 重连逻辑失效
- **文件**：`static/index.html:1321-1339`
- **根因**：浏览器规范中 onerror 先于 onclose 触发，onclose 会抢先 `clearRunning()`，导致 onerror 里排的 3s 重连形同虚设；用户偶发断线就直接判死。
- **修复方案**：用指数退避重连（最多 5 次），`onclose` 里只有 `code!==1000 && 重试次数耗尽` 时才 `clearRunning`。
- **批次**：阶段 3

---

## 修复批次规划

| 批次 | 范围 | 问题 | 验收方式 |
|------|------|------|---------|
| **阶段 1** | P0 安全/正确性 | H1 H2 H3 H4 | py_compile + 导入 + ffmpeg 验证 + curl + XSS payload 验证 |
| **阶段 2** | P1 健壮性 | H5 H6 M1–M10 | 端点回归 + 手动断线/停止验证 |
| **阶段 3** | P2 工程质量 | L1–L8 | pytest 全绿 + 锁版本验证 + 文档 diff |

---

*报告版本：v1.4 | 最后更新：2026-06-16 | 全部 24 个问题已修复（H1–H6、M1–M10、L1–L8）*
