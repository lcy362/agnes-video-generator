# v8.0 版本计划（大版本 · 规划中）

> **文档定位**：v8.0 的**计划索引 / 占位记录**。仅登记已确定的两个方向，尚未做需求分析、PRD 与排期；
> 具体范围、验收标准、阶段划分在开工前按 `AGENTS.md`「新增功能」工作流补齐。
>
> **当前版本**：v7.2.5（`core/config.py` 的 `APP_VERSION`）
> **版本代号说明**：`8.0` 是下一个大版本的**计划代号**，不是已发版本号；`APP_VERSION` 与 tag 的修改只能由用户
> 触发发版时按 `docs/dev/release_process.md` 执行，本计划不提前占位版本号。
> **状态**：🟡 进行中（方向二 P0+P1 已实施；方向一未开工）
> **登记日期**：2026-11-06

---

## 一、方向一：UI 重构

- **范围（待定）**：前端整体界面与交互重构；源码 `frontend/`（Vue 3 + Vite + TS + Tailwind），构建产物提交到 `static/`。
- **已知约束**（方案阶段需逐项确认，避免回归）：
  - 22 语言 i18n（`frontend/src/i18n/`，22 个 JSON）与翻译缺失 CI 检查；
  - `frontend-build` job 会校验 `static/` 产物与 `frontend/` 源码一致，产物需一并提交；
  - 现有面板/增量功能不得丢失：`CreatePanel.vue`、`ProgressPage.vue`、`TaskListPanel.vue`、`GalleryPanel.vue`、
    `ConfigPanel.vue`，以及手动模式、快速重试、反馈区、风格预设、检查点详情等；
  - 大版本重构按 `docs/dev/regression_test_plan.md` 走全量回归。
- **待明确**：重构目标（视觉改版 / 组件与状态管理分层 / 响应式与首屏）、是否改动页面 URL 与 API 契约、是否分批落地与分批发版。

## 二、方向二：简单视频模式功能优化

- **状态**：🟢 P0（真一键）+ P1（接口能力对齐）已实施；P2 体验增强待评估。
- **文档**：`simple_video_PRD.md`（需求与验收）、`system_design.md`（契约与结构）、`implementation_plan.md`（实施记录与遗留）。
- **现状入口**：
  - 前端：`frontend/src/components/SimplePanel.vue`、`frontend/src/components/forms/SimpleForm.vue`
  - 后端：`POST /api/tasks/simple`（`web/routes/task_creation_routes.py`）、`models/task.py` 的
    `CreateSimpleTaskRequest` / `SimpleVideoTask`、`core/pipelines/simple_video.py`、`core/api/agnes_video.py`
- **已落地要点**：
  - 一键预设 `SIMPLE_DEFAULT_PRESET`（免费 2.5-flash / 文生视频 / 5s / 16:9 / 720P），经 `/api/models` 下发；
  - 默认进入简单视频并记住上次类型；
  - 表单分层：主区只留提示词 + 预设摘要，其余收进「修改设置」；
  - 对齐官方 2.5：原生首尾帧、多图参考、参考音频 URL、`<Picture N>` / `<Audio N>` 引导；
  - 付费档三重防护（免费优先排序 + 标签/警示 + 生成前二次确认）；
  - 能力表修正：`960P`（上游不存在）→ `1080P/1K/2K`。
- **已知约束**：上游行为以 `docs/dev/agnes_video_upstream_behavior.md` 为准（新增 §9.5 官方参数表）；
  请求参数或任务状态字段变更需保持历史任务反序列化兼容；`AGNES_KEYFRAME_NATIVE=0` 可回退 keyframe 降级。
- **遗留**：keyframe 输出尺寸需真实 Key 复验；本地音频上传、参考视频 `videos[]`、轮询节奏评估（见 `implementation_plan.md` §四）。

## 三、后续流转

1. 需求明确后按 `AGENTS.md`「新增功能：…」工作流：需求分析 → `docs/plans/v8.0/<主题>_PRD.md` →
   `system_design.md` → `implementation_plan.md`（含分阶段状态跟踪）。
2. 开工后把本文件「状态」更新为 🟡 进行中；每个方向完成标记 🟢，并在「变更记录」追加一行。
3. 实施时同步：`docs/dev/regression_test_plan.md`（回归条目）、`docs/public/api.md` / `docs/public/usage.md`
   （仅当用户可见行为变化）、`AGENTS.md` 配套文档索引。
4. 发版按 `docs/dev/release_process.md`，由用户明确版本类型 / 版本号后执行（大版本 `8.0.0`）。

## 四、变更记录

| 日期 | 变更 |
|------|------|
| 2026-11-06 | 建立 v8.0 计划索引，登记「UI 重构」「简单视频模式功能优化」两个方向 |
| 2026-11-09 | 方向二 P0+P1 实施：一键预设、默认类型记忆、表单分层、原生首尾帧/多图/参考音频、付费档防护、能力表修正 |
