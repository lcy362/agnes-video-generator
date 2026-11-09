# 📋 API 接口

> 前端通过 `GET /api/tasks/{id}` 轮询任务状态 — **无 WebSocket** 端点。

## 配置与工作区

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | Web UI 页面 |
| GET | `/api/config` | 获取 API Key（脱敏） |
| POST | `/api/config` | 保存 API Key |
| DELETE | `/api/config` | 清除 API Key |
| GET | `/api/models` | 拉取 Agnes 模型列表（text/image/video 分组，缓存） |
| POST | `/api/config/models` | 保存选中的模型配置 |
| POST | `/api/config/watermark` | 保存水印开关配置 |
| POST | `/api/config/domain` | 设置 Agnes API 域名后缀（`com`/`cn`） |
| GET | `/api/workspaces` | 列出工作区 |
| POST | `/api/workspaces` | 新建工作区 |
| DELETE | `/api/workspaces` | 删除工作区 |
| POST | `/api/workspaces/active` | 激活工作区 |
| GET | `/api/workspaces/pick-directory` | 原生目录选择对话框 |

## 音色

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/voices` | 列出可用 TTS 音色（按 22 语言分组） |
| GET | `/api/voices/preview` | 音色试听（生成/缓存样本） |
| GET | `/api/voices/compat` | 音色与语言兼容性校验 |

## 图片

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/image/generate` | 生成简单图片（t2i / i2i） |
| GET | `/api/image/{task_id}` | 下载/预览生成的图片 |

## 任务创建

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/tasks/simple` | 创建简单视频任务 |
| POST | `/api/tasks/creative` | 创建创意长视频任务 |
| POST | `/api/tasks/manuscript` | 创建稿件长视频任务 |
| POST | `/api/tasks/poetry` | 创建诗词视频任务 |
| POST | `/api/tasks/anchor` | 创建数字人口播任务 |
| POST | `/api/tasks` | 兼容旧版（映射到 creative） |
| GET | `/api/poetry-scene-prompt` | 诗词场景 prompt 预生成 |

**`POST /api/tasks/simple` 参数（v8.0）**：只有 `prompt` 必填，其余走一键预设
（免费 `agnes-video-2.5-flash` / 文生视频 / 5s / 16:9 / 720P）。

| 参数 | 说明 |
|------|------|
| `prompt` | 必填，视频描述（≤5000 字符） |
| `mode` | `t2v`（默认）/ `i2v` / `ti2vid` / `keyframes` |
| `duration` | 4 / 5 / 6 / 8 / 10 / 12（秒） |
| `video_width` / `video_height` | 像素宽高，仅用于推导 2.5 `aspect_ratio`（默认 1280×720） |
| `video_size` | `720P`（flash 固定）/ `1080P` / `1K` / `2K`；历史 `960P` 自动归一为 `1080P` |
| `seed` | 可选随机种子 |
| `reference_images` | `i2v`/reference：多张参考图（Flash ≤5，2.5 ≤8） |
| `first_frame_image` / `last_frame_image` | `keyframes`：原生首帧 / 尾帧（至少 1 张） |
| `reference_audio_urls` | reference：参考音频公开 URL，换行分隔，≤3 段 |

> 模式与素材互斥：`keyframes` 不允许同时传 `reference_images` / `reference_audio_urls`（返回 422）。
> 参考图/音频需可被 Agnes 服务公开访问。

## 任务查询与控制

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/tasks` | 列出所有任务（含 task_type 标识） |
| GET | `/api/tasks/{task_id}` | 查询任务详情（轮询进度） |
| POST | `/api/tasks/{task_id}/resume` | 续传中断任务 |
| POST | `/api/tasks/{task_id}/stop` | 停止运行中的任务 |
| POST | `/api/tasks/sweep` | 僵尸任务磁盘清理 |
| GET | `/api/concurrency` | 并发信号量利用率状态 |
| GET | `/api/video/{task_id}` | 下载/流式播放最终视频 |

## 中间产物（artifacts）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/tasks/{task_id}/artifacts` | 列举任务的所有中间产物 |
| GET | `/api/tasks/{task_id}/artifacts/{artifact_id}/file` | 下载单个产物文件 |
| GET | `/api/tasks/{task_id}/artifacts/{artifact_id}/cascade-preview` | 预览级联删除影响 |
| DELETE | `/api/tasks/{task_id}/artifacts/{artifact_id}` | 删除产物（含级联删除） |

## 运维

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/cleanup-regression` | 清理回归测试产物 |

## 快速示例（curl）

```bash
# 1. 保存 API Key（免费获取：https://platform.agnes-ai.com）
curl -X POST http://localhost:8765/api/config -F "api_key=sk-你的Key"

# 2. 创建简单视频任务（只传 prompt = 一键预设：免费 flash / 5s / 16:9 / 720P）
curl -X POST http://localhost:8765/api/tasks/simple \
  -F "prompt=一只橘猫趴在雨后窗台上打盹，4K 写实"

# 2b. 自定义参数（官方 2.5 协议；分辨率用 video_size，画幅由宽高推导）
curl -X POST http://localhost:8765/api/tasks/simple \
  -F "prompt=一只橘猫趴在雨后窗台上打盹，4K 写实" \
  -F "mode=t2v" -F "duration=8" \
  -F "video_width=1280" -F "video_height=720" -F "video_size=720P"

# 2c. 首尾帧（原生 keyframe）：至少 1 张
curl -X POST http://localhost:8765/api/tasks/simple \
  -F "prompt=人物转身走向窗边" -F "mode=keyframes" \
  -F "first_frame_image=@first.png" -F "last_frame_image=@last.png"

# 2d. 多图 + 参考音频（公开 URL，≤3 段）
curl -X POST http://localhost:8765/api/tasks/simple \
  -F "prompt=以 <Picture 1> 的角色为主角，跟随 <Audio 1> 的节奏" \
  -F "mode=i2v" \
  -F "reference_images=@a.png" -F "reference_images=@b.png" \
  -F "reference_audio_urls=https://example.com/music.mp3"

# 3. 轮询任务状态，直到 status=completed
curl http://localhost:8765/api/tasks/<task_id>

# 4. 下载最终视频
curl -o output.mp4 http://localhost:8765/api/video/<task_id>
```
