# 水印功能实现 — 完成概览

## 改动清单

| # | 文件 | 操作 | 说明 |
|---|------|------|------|
| 1 | `core/compositor/watermark.py` | **新增** | WatermarkProcessor — ffmpeg drawtext 后处理，语言检测，字号自适应 |
| 2 | `core/config.py` | 修改 | 新增 `WatermarkConfig` 配置项（enabled/language）及读写函数 |
| 3 | `server.py` | 修改 | 导入水印配置函数，`GET /api/config` 返回水印状态，新增 `POST /api/config/watermark` |
| 4 | `static/index.html` | 修改 | 新增水印开关 UI（Toggle 组件 + 7 语言宣传文案），JS 交互逻辑 |
| 5 | `core/pipelines/simple_video.py` | 修改 | 在 `_submit_and_wait()` 后添加水印后处理 |
| 6 | `core/pipelines/creative_video.py` | 修改 | 在 `_step_concatenate()` 后添加水印后处理 |
| 7 | `core/pipelines/manuscript_video.py` | 修改 | 在 `_run_step_concatenate()` 后添加水印后处理 |
| 8 | `core/pipelines/anchor_video.py` | 修改 | 在 `_step_composite_anchor()` 和 `_run_model_audio()` 后添加水印后处理 |

## 验证结果

- 所有 7 个 `.py` 文件语法检查通过
- 模块导入测试通过：语言检测、参数计算、文本构建、配置读写
- Server 导入通过，`/api/config/watermark` 路由已注册
- 水印默认**关闭**

## 核心设计

- 语言感知：检测 prompt 中 CJK 字符 → 中/英文水印
- 字号自适应：`font_size = max(12, round(h × 0.022))`
- 双行水印：归属行 + URL 地址行
- 失败降级：ffmpeg 失败或字体缺失时复制原文件，不阻塞管线
