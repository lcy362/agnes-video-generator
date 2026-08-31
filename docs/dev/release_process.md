# Release 发布规范（release doc 规范）

> 关联：`docs/public/getting-started.md`（四种部署方式）、`.github/workflows/release.yml`（CI 发布）、`docs/public/release-notes/`（历史 release notes）
> 用户触发词：**"发版" / "发布" / "release"**（需附带版本类型或版本号）

---

## 一、定位

本规范定义 release 文档的**版本号规则**、**文档结构**（使用方式 + 新增内容）、**写作红线**与**发布流程**。AI Agent 与开发者在发版时统一遵循，保证：

1. 用户知道**本版相对上一版多了什么**（新增内容）
2. 用户知道**每个 release 包怎么用**（使用方式）
3. release 文档不堆砌对用户无价值的杂项（文档整理 / 纯营收向 SEO / 引流等）
4. release 内容满足 **SEO 优化、可独立检索**，后续供**官网板块展示**（见「3.4 SEO 优化与独立检索」）

---

## 二、版本号规则（大版本 / 中版本 / 小版本）

版本号三位 `X.Y.Z` 对应三种发版类型：

| 类型 | 号段 | 典型内容 | 说明 |
|------|------|----------|------|
| **大版本** | `X.0.0` | 架构级重构、新增任务类型、重大能力、破坏性变更 | 功能与影响面最大的发版 |
| **中版本** | `X.Y.0` | 新功能、功能增强、大型代码层优化/重构、批量优化 | 常规功能迭代 |
| **小版本** | `X.Y.Z` | Bug 修复、体验微调、回归修复 | 面向维护的小补丁 |

### 升位规则

- **中版本**：`Y+1`，`Z` 清零 → `X.Y+1.0`
- **大版本**：`X+1`，`Y/Z` 清零 → `X+1.0.0`
- **小版本**：仅 `Z+1` → `X.Y.Z+1`
- 已发版后发现问题需单独修复 → 本轮作小版本。

> ⚠️ **版本号修改只能由用户要求触发**（如「发个小版本 / 发布中版本 / 升到 vX.Y.Z」）。Agent 不得自行升版，也不得在功能未完成时提前占位版本号。

---

## 三、release 文档结构

每个 release 产出两份内容，共用**同一结构**：

1. **GitHub Release body** — 由 `release.yml` 自动组装（使用方式 + 新增内容）
2. **文档 `docs/public/release-notes/release_notes_vX.Y.Z.md`** — 仓库内留存

结构如下：

### 3.1 使用方式（原有，保留）

各 release 包的获取与运行方法：

- **Docker 镜像** — `docker pull ghcr.io/...` / Docker Hub，含数据持久化说明
- **npm** — `npx free-short-video` / `npm install -g` 全局安装
- **源码** — `git pull` + 依赖安装 + `./start.sh`
- **升级注意事项** — 本版特有的 breaking change、新增依赖、迁移/清零说明

### 3.2 新增内容（新增）

本版相对上一版**有实际价值**的变化，分三类：

- **大的功能更新**：逐条列出，说明能力是什么、如何用、影响哪些用户。大版本 / 中版本重点写，条目标题尽量用用户会搜索的功能关键词。
- **大的代码层面优化 / 重构（开源价值）**：本项目是开源项目，面向贡献者与高级用户，**大型**代码层优化、重构、架构演进（如性能提升、模块拆分、接口统一）可以体现。用可理解的语言说明对架构 / 性能 / 可维护性的意义，避免内部代号与过程细节。仅「大」的才写，零碎小改动归入 Bug 修复或直接不写。
- **小 bug 修复**：**集中概括**（按类别归纳成一条，如「修复数字人任务 TTS 失败时静音降级与字幕丢失」），不展开到单个触发细节与 issue 编号。小版本可适当细列，但仍保持简短。

> 稳定性 / 性能 / 兼容性提升：**仅当对用户可感知**时写入。

### 3.3 红线（不计入新增内容）

对用户无实际价值的内部工作一律**不提及**，即使数量巨大：

- 文档整理 / 重命名 / 文档目录重构、README 措辞调整
- **纯营收向的 SEO 优化、引流优化**：关键词堆砌、外链互换、渠道推广、镜像仓库引流同步（如 Gitee 同步、Docker Hub overview 更新）。注意与「3.4 内容型 SEO 写作」区分——前者是实施工作不写，后者是写法要求必须做
- 内部代码风格 / 静态分析（ruff/mypy）/ 测试基础设施
- **小型**重构、类名/模块迁移（对使用者与架构无实质影响时）；「大的代码层面优化/重构」除外（见 3.2）

> 目的：避免给用户「功能变多了」的错觉，聚焦真正影响使用与社区价值的变化。

### 3.4 SEO 优化与独立检索（面向官网板块展示）

release 内容后续会在**官网开辟板块展示**，并被搜索引擎**独立检索**，因此 release 文档本身即内容型 SEO 资产，写作时满足：

1. **独立成档、自包含**：每份 `release_notes_vX.Y.Z.md` 不依赖其他文档即可理解（版本、日期、能力、用法都在本页）。
2. **标题含关键词**：`# Release vX.Y.Z — <一句话核心卖点>`，卖点用用户会搜索的功能关键词（如「数字人视频生成」「AI 字幕样式」「图片生成」）。
3. **Overview 覆盖关键词**：总览 1-3 句内自然覆盖本版核心能力关键词，便于搜索引擎收录该版本的搜索意图。
4. **结构清晰可抓取**：H1/H2/H3 层级与「使用方式 / 新增内容」分段固定，便于官网板块渲染与站内/站外检索。
5. **版本与时间可读**：标题含版本号、顶部标注 release date，URL 稳定（`docs/public/release-notes/release_notes_vX.Y.Z.md`），可长期引用。
6. **反作弊红线**：只做内容型 SEO，不做纯 SEO 作弊（无意义关键词堆砌、隐藏文本、重复内容），否则同样视为营收向引流工作，不写。

---

## 四、各版本类型的写法侧重

| 版本类型 | 新增内容写法 |
|----------|--------------|
| 大版本 | 以「大的功能更新」为主，每项能力分节详细介绍；重大架构演进可单独成节；Bug 修复一句话带过 |
| 中版本 | 功能更新与修复并重：功能分条说明，大型代码层优化/重构按影响单列，修复按类归纳 |
| 小版本 | 以「小 bug 修复」为主，按类归纳成几条即可；偶有体验增强可并入功能更新 |

---

## 五、release 文档模板

> ⚠️ **章节锚点与 CI 提取一致**：`release.yml`、`.github/scripts/update_dockerhub_overview.py` 均以 **`## What's New`** 为提取锚点（`awk '/^## What.s New/{f=1} f'`），因此文档必须使用**英文章节标题** `## Overview` / `## Usage` / `## What's New`。**⚠️ 对外产物（GitHub Release body / release notes 文档 / Docker Hub / npm README）必须全英文**——release notes 文档整体用英文撰写（标题、正文、章节皆英文），禁止中英混杂（如中文标题 + 英文正文）。`release.yml` 组装 GitHub Release body 时使用英文标题 `## Usage`（勿改回中文）。该 `What's New` 章节会被自动前置到 **GitHub Release 正文、Docker Hub 页面前部、npm README 前部**（见「六、发布流程」第 7 步）。

```markdown
# Release vX.Y.Z — <一句话副标题>

> Release date: YYYY-MM-DD

## Overview

<1-3 句总览：本版是大/中/小版本，核心变化是什么，覆盖本版功能关键词>

## Usage（使用方式）

<各 release 包（Docker / npm / 源码）获取与运行方法；本版特有的升级注意事项>

## What's New（新增内容）

### Features & Improvements（功能更新）

- <大的功能更新逐条列出，说明能力与如何使用；条目标题用用户可搜索的关键词>

### Refactoring & Optimizations（代码层优化与重构）

- <大型代码层优化 / 架构演进，面向开源社区，说明对性能/架构/可维护性的意义>

### Bug Fixes（Bug 修复）

- <集中概括的修复列表：按类别归纳，不展开细节>

---

<可选>兼容性 / 配置变更提醒（仅当影响用户时）
```

> **SEO 提示**：标题副标题与 Overview 覆盖本版核心功能关键词；整篇自包含、层级清晰，供官网板块展示与独立检索（见「3.4 SEO 优化与独立检索」）。

---

## 六、发布流程（融合现有 release 流程）

```
1. 用户触发发版（含版本类型或明确版本号）
2. 确认版本类型 → 按「二、版本号规则」升位，确定 vX.Y.Z
3. 汇总本版变化 → 按「三、release 文档结构」筛选「新增内容」（过滤红线）
4. 撰写 docs/public/release-notes/release_notes_vX.Y.Z.md（按「五、模板」，必须含 ## What's New 锚点，**全文英文**）
5. 🔴 人工审核更新日志：将生成的更新日志草案（release notes / What's New 内容）展示给用户审阅，
   与用户确认**通过后**才可进入后续步骤。用户可提出增删 / 措辞调整，Agent 修改后再次确认，
   直至用户明确批准方可继续。（发版前强制人工确认，默认不自动进入升版 / 打 tag / 推送）
6. 自验：.venv/bin/python -m py_compile <改动文件>；涉及流水线跑 ./scripts/run_mock_regression.sh
7. git tag vX.Y.Z && git push origin vX.Y.Z
8. CI（.github/workflows/release.yml）自动：
   - 构建多平台镜像 → GHCR / Docker Hub（同步 Docker Hub overview：description + README）
   - npm 发布（整个项目作为 free-short-video 包）
   - GitHub Release（body = 使用方式 + What's New，读取 release notes 文档）
   - **Docker Hub 页面前部**：.github/scripts/update_dockerhub_overview.py 把本版
     What's New 章节前置到 overview 顶部（Quick Start 之后）
   - **npm README 前部**：release.yml 把本版 What's New 章节 + npm Quick Start
     前置到发布用 README 顶部
9. 若有版本号示例位置需同步（README / docker-compose / AGENTS.md），一并更新
```

> **`APP_VERSION` 同步**：自 v6.1 起，`core/config.py` 的 `APP_VERSION` 常量作为「应用版本」通过 `GET /api/config` 暴露给前端（失败面板诊断信息使用）。**发版时必须同步更新**该常量为本版 `vX.Y.Z`，否则失败反馈的诊断信息会显示过期版本号。建议在第 4 步写 release notes 时一并修改（含 3.4 所述、release notes 中体现的版本号）。

> **Docker / npm 页面前置规则**：每个版本的 release 新增内容（`## What's New` 章节）必须自动展示在 **Docker Hub 仓库页**与 **npm 包 README** 的**前部**（顶部），让访问分发页面的用户第一眼看到本版更新。此规则已固化在 CI（第 8 步），发版时无需手工操作；但**缺失 release notes 文档时 CI 会跳过前置并输出 warning**，因此第 4 步的文档是强制项。

> **🔴 Docker Hub overview 更新的 Cloudflare WAF 坑（v6.3.0 实录，2026-08-30）**：`update_dockerhub_overview.py` 脚本 PATCH `hub.docker.com/v2/repositories/{user}/{repo}/` 返回 403，响应体是 **Cloudflare "Attention Required!" HTML 页面**（而非 Docker Hub API 的 JSON 错误）——请求被 WAF 拦截，未到达 API 层。**根因：README 中的 schema.org JSON-LD `<script type="application/ld+json">` 块**（v6.2.1 发版后当天由 BK-1 提交引入）：PATCH 请求体携带原始 `<script>` 文本触发 Cloudflare WAF 的 XSS 拦截规则。**易误判方向**（均已排查排除）：token 权限（docker CLI 推送同 token 正常，因其走 registry API 不经该 WAF）、TLS 指纹（urllib / curl / curl_cffi impersonate chrome 均被拦）、payload 大小（15KB 修复版可过、13KB 含 `<script>` 被拦）。**修复（已固化在脚本，2026-08-31）**：① 从 `full_description` 剥离 `<script>` 块（Docker Hub 页面无需 SEO 结构化数据）；② JSON 序列化时将 `<` 转义为 `\u003c`（纵深防御，服务端解码后内容不变）。**预防**：README 新增 HTML 标签（script/iframe 等）后，Docker Hub overview 自动更新可能被 WAF 拦截；该步骤为 `continue-on-error` 非关键步骤，临时可到 Docker Hub 网页手动更新。诊断技巧：单独建一个仅跑该脚本的临时 workflow（checkout + 直接执行），远快于重推 tag 触发完整 release（5 分钟镜像构建）。

### 用户要求与版本号映射

| 用户说法示例 | Agent 动作 |
|--------------|------------|
| 「发个小版本」/「小版本 +1」 | `Z+1`，以 Bug 修复为主 |
| 「发布中版本」/「新功能发版」 | `Y+1`，`Z` 清零 |
| 「发大版本」/「重大变更发版」 | `X+1`，`Y/Z` 清零 |
| 「升到 vX.Y.Z」 | 直接采用用户给定的版本号 |

---

*文档版本：v1.4 | 更新日期：2026-08-31 | 状态：✅ 已生效*