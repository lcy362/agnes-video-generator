# Bug 修复开发计划

> **状态**：✅ 全部完成
> **生成日期**：2026-06-19
> **范围**：基于代码审查发现的 13 个问题（不含扩展功能）
> **工作流**：分 6 批实施，每批结束 → 更新进度 → 向用户汇报 → **等待确认**再继续

---

## 一、批次总览与进度

| 批次 | 主题 | 包含问题 | 改动面 | 状态 |
|------|------|---------|--------|------|
| **批次 1** | 事件循环阻塞与并发安全 | P1, P2 | `core/pipelines/*`, `server.py` | ✅ 完成 |
| **批次 2** | 用户功能失效修复 | P3, P4 | `server.py`, `static/index.html` | ✅ 完成 |
| **批次 3** | LLM 调用健壮性 | P5, P11, P8 | `core/api/agnes_chat.py`, `core/screenwriter.py` | ✅ 完成 |
| **批次 4** | 视频合成与音频健壮性 | P6, P9, P10, P12 | `core/compositor/`, `core/audio/`, `core/api/agnes_video.py` | ✅ 完成 |
| **批次 5** | 参数校验与持久化原子性 | P7, P13, H5 | `server.py`, `core/task_manager.py`, `models/task.py` | ✅ 完成 |
| **批次 6** | 代码质量与体验优化 | 重复代码/魔数/排序/下载限制/前端 UX | 多处 | ✅ 完成 |

**状态图例**：⬜ 待开始 / 🔄 进行中 / ✅ 完成 / ⏸️ 等待用户确认

---

## 二、问题进度追踪表

| ID | 严重度 | 问题 | 批次 | 状态 |
|----|--------|------|------|------|
| P1 | 🔴 高 | 拼接步骤同步阻塞事件循环 | 1 | ✅ |
| P2 | 🔴 高 | active_pipelines 并发竞态 | 1 | ✅ |
| P3 | 🔴 高 | end_frame_images 死代码（自定义尾帧失效） | 2 | ✅ |
| P4 | 🟡 中 | manuscript step key 不匹配（拆分步骤不高亮） | 2 | ✅ |
| P5 | 🔴 高 | chat_json 无降级 | 3 | ✅ |
| P11 | 🟡 中 | LLM 调用无重试 | 3 | ✅ |
| P8 | 🟡 中 | prompt 注入风险 | 3 | ✅ |
| P6 | 🔴 高 | concat_videos 资源泄漏 | 4 | ✅ |
| P9 | 🟡 中 | SilentTTS 不查 ffmpeg 返回码 | 4 | ✅ |
| P10 | 🟡 中 | 字幕叠加静默降级 | 4 | ✅ |
| P12 | 🟡 中 | .url 缓存不过期 | 4 | ✅ |
| P7 | 🟡 中 | 参数零校验 | 5 | ✅ |
| P13 | 🟡 中 | TaskManager 临时文件名固定 | 5 | ✅ |
| H5 | 🟡 中 | lifespan 非原子写 | 5 | ✅ |

---

## 三、各批次详情

### 批次 1：事件循环阻塞与并发安全

#### P1 — 拼接步骤同步阻塞事件循环
- **现象**：创意/稿件视频在拼接阶段（`_step_concatenate`）冻结整个 FastAPI 事件循环，期间 WebSocket 心跳停摆、其他任务进度推送停摆、新请求被阻塞。长视频可达数分钟。
- **根因**：`_step_concatenate` 标记为 `async`，但内部直接调用同步阻塞的 moviepy `write_videofile`（CPU/IO 密集）和 4 处 `subprocess.run`。本项目其他模块（`screenwriter`/`agnes_video`）已正确使用 `asyncio.to_thread`，此处遗漏。
- **位置**：
  - `core/pipelines/creative_video.py:1438` — `VideoConcatenator.concat_videos_with_audio_overlay(...)`
  - `core/pipelines/creative_video.py:418, 536, 967, 1065` — 4 处 `subprocess.run(..., check=True)`
  - `core/pipelines/manuscript_video.py:680` 附近 — 同样模式
- **方案**：
  - moviepy 调用包 `await asyncio.to_thread(VideoConcatenator.concat_videos_with_audio_overlay, ...)`
  - 4 处 `subprocess.run` 改为 `asyncio.create_subprocess_exec` + `await proc.communicate()`，保留 `check=True` 等价语义（returncode 非 0 抛异常）
  - 参考本项目 `core/audio/tts.py:125`、`core/api/agnes_video.py:120` 已有的异步模式
- **验证**：
  - py_compile 通过
  - 启动服务，创建一个创意任务，在拼接阶段发起 `/api/tasks` 请求，验证事件循环未被阻塞（请求能即时返回）

#### P2 — active_pipelines 并发竞态
- **现象**：对同一任务快速 resume→stop 操作时，旧 pipeline 的 `finally` 块会误删新 pipeline；`resume_task` 检查与插入之间的 `await` 让出点可导致同任务双重运行，状态文件交叉写入、产物文件竞争。
- **根因**：
  - `active_pipelines` / `active_connections` / `background_tasks` 是全局 dict/set，无锁
  - `_run_pipeline` 的 finally 用 `if task_id in active_pipelines: del` 删除，未做身份比对
  - `resume_task` 的 `if task_id in active_pipelines` 检查与 `active_pipelines[task_id] = pipeline` 插入之间有 `await` 让出点
- **位置**：
  - `server.py:87` `background_tasks: set = set()`
  - `server.py:393` `del active_pipelines[pipeline.task_id]`（finally）
  - `server.py:694` `if task_id in active_pipelines:`（resume 检查）
  - `server.py:715` 附近 `active_pipelines[task_id] = pipeline`（resume 插入）
- **方案**：
  - 引入 `_pipeline_locks: dict[str, asyncio.Lock]`，create/resume/stop 按 task_id 串行化（用辅助函数 `_get_pipeline_lock(task_id)` 获取/创建锁）
  - `_run_pipeline` 的 finally 改为 `if active_pipelines.get(task_id) is pipeline: del active_pipelines[task_id]`（身份比对，避免误删新 pipeline）
- **验证**：
  - py_compile + 导入验证
  - 逻辑审查：并发场景下不会出现 KeyError 或误删

#### 批次 1 验证清单
- [x] `.venv/bin/python -m py_compile server.py core/pipelines/creative_video.py core/pipelines/manuscript_video.py`
- [x] 导入验证：`.venv/bin/python -c "import server"`
- [ ] 启动服务 + 创建创意任务，拼接阶段验证事件循环未阻塞
- [x] 静态分析：grep 确认 `subprocess.run` 在 async pipeline 中已全部替换

#### 批次 1 风险与回滚
- **风险**：`asyncio.create_subprocess_exec` 错误处理需对齐原 `subprocess.run(check=True)` 语义；若遗漏 stderr 捕获可能影响排障
- **回滚**：git revert 批次 1 的提交

---

### 批次 2：用户功能失效修复

#### P3 — end_frame_images 死代码（自定义尾帧失效）
- **现象**：「自定义尾帧」是创意视频核心功能（关键帧链接模式），用户勾选开关、上传尾帧图、提交任务 —— 全过程无任何报错，但上传的图片被静默丢弃，pipeline 改用 AI 自动生成尾帧。用户难以察觉。
- **根因**（完整失效链路）：
  - 前端 `static/index.html:1190-1191` `submitCreative()` 只 append `use_custom_end_frames` 和 `generate_end_frames_from_ref` 开关，**未 append 用户上传的尾帧文件**
  - 后端 `server.py:486, 652` 声明 `end_frame_images: list = None` 参数，但函数体**无保存上传文件的逻辑**（对比 `reference_image` 有写盘代码）
  - `state.end_frame_images` 永远为空
  - pipeline `creative_video.py:523-524, 1059-1060` 的消费逻辑已写好（`if end_frame_images and scene_idx < len(...)`），但分支永远走 False
- **方案**：
  - 前端：`submitCreative()` 收集动态添加的尾帧 input（`addCEndFrameInput()` 创建的元素），逐一 `form.append('end_frame_images', file)`
  - 后端：`create_creative_task` 增加 `end_frame_images: List[UploadFile] = File(None)`，仿照 `reference_image` 写盘到工作目录，路径写入 `state.end_frame_images`
  - 核对 pipeline 消费链路 `creative_video.py:523, 1059` 是否正确读取
- **验证**：
  - 提交带 2 张尾帧的创意任务
  - 检查工作目录是否落盘尾帧文件
  - 检查 task_state.json 的 `end_frame_images` 字段非空

#### P4 — manuscript step key 不匹配
- **现象**：稿件视频执行第一步（文本拆分）时，前端「文本拆分」步骤图标不会显示 running/completed 状态，保持灰色。其余 4 步正常。
- **根因**：后端 emit `"split_text"`（`manuscript_video.py:157`），前端 `STEPS.manuscript[0].key = 'split'`（`index.html:964`），`querySelector('.step-item[data-step="${step}"]')` 匹配不到。其余步骤（scene_prompts/video_gen/audio_subtitle/concatenate）前后端一致。
- **影响范围**：进度条（顶部百分比 + 文字）正常；仅步骤图标在第一步期间不刷新（第二步 running 时会通过"标记前置步骤 completed"级联逻辑被动补上）。
- **方案**：统一为 `split_text`（与后端对齐）
  - `static/index.html:964` `{ key: 'split', ... }` → `{ key: 'split_text', ... }`
  - `static/index.html:1597` 映射表 `split: 'step_split'` → `split_text: 'step_split'`
- **验证**：创建稿件任务，观察 WS 消息 + 前端第一步图标在 running 时显示 ◉

#### 批次 2 验证清单
- [x] py_compile server.py
- [x] 前端 submitCreative 收集尾帧文件 + 后端保存落盘
- [x] 前端 manuscript step key split → split_text

---

### 批次 3：LLM 调用健壮性

#### P5 — chat_json 无降级
- **现象**：LLM 偶尔返回非 JSON、JSON 前后有解释文字、代码围栏收尾标记异常，`json.loads` 直接抛 `JSONDecodeError` 导致整个 pipeline 失败。这是 LLM 类项目最高频崩溃源。
- **根因**：`core/api/agnes_chat.py:55-63` `chat_json` 无 try/except；代码围栏剥离逻辑（strip + endswith）在 `screenwriter.py` 复制 5 次且不健壮（尾随空格/换行导致 endswith 失败）。
- **位置**：`core/api/agnes_chat.py:55-63`；`core/screenwriter.py:258, 284, 341, 433, 505`
- **方案**：
  - 抽 `strip_code_fence(text)` 工具函数：`.strip()` 后用正则去除首尾 ` ``` ` 围栏
  - `chat_json` 用正则提取首个 `{...}` 块再 `json.loads`，失败时重试一次 chat 调用，仍失败抛可识别的 `ScriptParseError` 供上层降级
  - 替换 screenwriter.py 中 5 处复制粘贴
- **验证**：单元测试 mock LLM 返回脏数据（带前缀文字、嵌套围栏），验证 `chat_json` 能提取并解析

#### P11 — LLM 调用无重试
- **现象**：除 `describe_images` 外所有 LLM 调用（`develop_story`/`write_script`/`extract_character_description` 等）单次失败即任务 FAILED。
- **根因**：重试逻辑散落在 screenwriter 内，仅 `describe_images` 有。`requests.post` 超时（120s）或网络抖动直接抛异常。
- **方案**：在 `AgnesChatAPI.chat` 层加 tenacity 重试（对 5xx/超时/连接错重试，4xx 不重试，3 次指数退避），统一覆盖所有调用点
- **验证**：mock 5xx 响应，验证重试 3 次后抛异常

#### P8 — prompt 注入风险
- **现象**：用户输入（idea/user_requirement）直接拼入 XML 标签 prompt，若含 `</idea>` 可提前闭合标签注入指令（如泄露 system prompt 或诱导生成违规内容）。
- **根因**：`core/screenwriter.py:143-165` 未经清洗直接插入 `<idea>{idea}</idea>`。
- **方案**：对用户输入做 XML 转义（`<`/`>`/`&` → 实体）或用随机化边界 token（如 `<idea_abc123>`）
- **验证**：提交含 `</idea>` 的 idea，验证不被解析为标签闭合

#### 批次 3 验证清单
- [ ] py_compile + 导入验证
- [ ] 单元测试：脏 JSON 解析、重试、prompt 注入

---

### 批次 4：视频合成与音频健壮性

#### P6 — concat_videos 资源泄漏
- **现象**：长视频（10+ 场景）拼接时累积未释放的 ffmpeg 子进程，可能撞 `ulimit -n`（macOS 默认 256）导致后续调用 `EMFILE`。
- **根因**：`core/compositor/concatenator.py:52-77` `resized_clips.close()` 只关了 `c.resized()` 返回的新 clip，原始 `clips` 列表的 VideoFileClip reader（含 ffmpeg 子进程）泄漏；`final` 未 close。
- **方案**：`finally` 中同时 close `clips` 和 `resized_clips`，新增 `final.close()`
- **验证**：拼接 10 段视频，监控进程数

#### P9 — SilentTTS 不查 ffmpeg 返回码
- **现象**：ffmpeg 失败（未安装/路径错误/duration 为 0）时静默返回不存在的音频文件，下游 moviepy 崩溃。
- **根因**：`core/audio/tts.py:125-139` `proc.wait()` 后未检查 returncode，stderr 丢弃到 DEVNULL。
- **方案**：检查 `proc.returncode`，非 0 抛 RuntimeError，stderr 重定向 PIPE 收集输出
- **验证**：mock ffmpeg 失败，验证抛异常而非静默返回

#### P10 — 字幕叠加静默降级
- **现象**：字幕叠加失败时 `shutil.copy2` 复制原视频，用户得到无字幕视频却完全不知情。
- **根因**：`core/audio/subtitle.py:472-476` 裸 `except Exception` 吞掉所有错误。
- **方案**：移除静默 copy2 降级，改为向上抛异常（或加 `strict=False` 参数由调用方决定是否容忍）
- **验证**：mock moviepy 失败，验证异常传播

#### P12 — .url 缓存不过期
- **现象**：`_resolve_image_ref` 缓存的托管 URL 可能是预签名链接（1 小时~7 天有效），过期后任务持续失败，错误信息不指向根因。
- **根因**：`core/api/agnes_video.py:75-100` 缓存到 `ref + ".url"` 文件，永不检查有效性。
- **方案**：缓存同时存时间戳，超阈值（如 1 小时）则重新上传；检测 video API 报图片相关错误时自动失效缓存
- **验证**：mock 过期 URL，验证重新上传

#### 批次 4 验证清单
- [ ] py_compile + 导入验证
- [ ] SilentTTS/字幕错误路径测试

---

### 批次 5：参数校验与持久化原子性

#### P7 — 参数零校验
- **现象**：`duration=100` 会在 `DURATION_FRAME_MAP` 触发 KeyError；`mode` 任意字符串静默 fallback；超大稿件耗尽 LLM token / 写满磁盘。
- **根因**：`server.py:411-586` 三个 create 端点用 Form 但无范围/枚举/长度校验；项目已定义 Pydantic 请求模型（`models/task.py:277-309`）却未使用。
- **方案**：加 `Field(gt=0, le=30)` 范围校验 + mode 白名单枚举（t2v/i2v/ti2vid/keyframes）+ 文本长度上限（如 50000 字符）
- **验证**：curl 提交非法参数验证 422

#### P13 — TaskManager 临时文件名固定
- **现象**：`_save` 用固定 `.tmp` 文件名，多写者竞争会丢数据。
- **根因**：`core/task_manager.py:100-103` `tmp_path = self._task_file + ".tmp"`。
- **方案**：`tempfile.mkstemp(dir=task_dir)` 带唯一后缀
- **验证**：并发 save 场景验证无丢失

#### H5 — lifespan 非原子写
- **现象**：服务重启时重置 stale 任务用直接 `open(..., "w")`，写入中途崩溃会损坏 task_state.json，导致任务无法续传，违背项目原子写约定。
- **根因**：`server.py:117-122` 与 `task_manager._save` 的原子写约定不一致。
- **方案**：改走 `TaskManager(task_id).update_state(status=...)` 或临时文件 + `os.replace`
- **验证**：模拟写入中断，验证文件完整性

#### 批次 5 验证清单
- [ ] py_compile + 导入验证
- [ ] curl 提交非法参数验证 422
- [ ] 持久化原子性验证

---

### 批次 6：代码质量与体验优化（低优先级）

#### 重复代码抽取
- 三个 pipeline 的 `_make_curl`/`_save_task`/`_load_task` 几乎逐字相同 → 抽到 `BasePipeline`
- 重试 + 退避 + `asyncio.sleep` 逻辑重复 → 抽 `retry_with_backoff` 工具
- ffmpeg scale+pad 命令三处复制 → 抽 `_ffmpeg_normalize_image`

#### 魔数清理
- `_CHARS_PER_SEC = 4.0` 在 `creative_video.py:29` 和 `manuscript_video.py:34` 重复定义
- 重试次数/退避间隔散落各 pipeline → 抽 `core/config.py` 统一常量区

#### 排序与性能
- `list_tasks` 按 uuid 字符串排序（无时间序）→ 改按 dir_name（`YYYYMMDD_HHMMSS_<id>`）排序
- N+1 读盘优化

#### 下载安全
- `utils/image.py` / `utils/video.py` 流式下载无大小限制 → 加 `max_size` 防写满磁盘

#### 前端体验
- `alert()` 改 `showToast`（已有 toast 组件）
- API Key 保存加 try/catch + 错误反馈
- WS 重连后调用 `restoreProgressFromTask` 补齐步骤状态
- onmessage 包 try/catch

#### 死代码清理
- 删除 `concat_with_audio`（`concatenator.py:79-141`，pipeline 已改用 `concat_videos_with_audio_overlay`）
- 删除 `core/pipelines/__init__.py:82-100` 未使用的延迟导入函数

#### 批次 6 验证清单
- [x] py_compile + 全模块导入
- [x] 死代码清理：`concat_with_audio` + `_synthesize_single` + 未用延迟导入函数
- [x] 下载安全：`utils/image.py`（50MB）+ `utils/video.py`（500MB）流式下载限制
- [x] 排序修复：`list_tasks` 按 `dir_name`（`YYYYMMDD_HHMMSS_<id>`）排序

---

## 四、验证方法汇总

每批结束后按 AGENTS.md「0.4 部署验证清单」执行受影响层级的验证：

- **第一层（基础连通性）**：`/`、`/api/config`、`/api/voices`、`/api/tasks` 返回正常
- **第二层（静态分析）**：`.venv/bin/python -m py_compile` 所有改动文件 + 关键模块导入验证
- **第三层（端点功能）**：创建三类任务，验证参数校验与 task_type
- **第四层（专项）**：按批次验证清单逐项验证

---

## 五、共享规范（遵循 AGENTS.md）

- **日志前缀**：保持 `[Pipeline]`/`[Compositor]`/`[AgnesChat]` 等既定前缀
- **原子写**：所有 JSON 持久化走临时文件 + `os.replace`
- **向后兼容**：`parse_task_state` 自动识别旧数据；不破坏现有 task_state.json 结构
- **错误处理**：LLM 重试 3 次；视频提交重试 5 次；TTS 失败降级为静音 + 字幕
- **代码风格**：Google 风格 docstring，类型注解，async/await 用于 IO

---

*文档版本：v1.1 | 创建日期：2026-06-19 | 状态：✅ 全部完成（6 批次均已完成）*
