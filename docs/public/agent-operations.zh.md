# 🤖 让 AI Agent 来操作本项目

> 本文是"用编程 Agent 驱动 Agnes Video Generator"的**权威说明**。官网的相关指南与 wiki 页面都由本文摘要而来——若两者与本文不一致，以本文为准。

Agnes Video Generator 由一个 skill 驱动：**`agnes-video`**。装一次，之后只描述想要的结果，不必再敲命令。

> "用《静夜思》做一条 90 秒的诗词视频，配上旁白。"

这就是全部的形状。这个 skill 是独立的——它自己出片，本项目只是它驱动的引擎。你不必 clone 本仓库，也不必自己装服务：skill 会按需把服务装进 `~/.agnes-video`，之后一直复用。

它也是**最省钱的入口**：无订阅、无积分包、无按秒计费、不用显卡。生成跑在 Agnes AI 的免费模型上，服务 MIT 开源、跑在本地，唯一要注册的是一个免费 API key——一次性安装花的是几分钟和磁盘，不是钱。

---

## 1. 装一次 skill

最短路径，不用 clone、不用管理器：

```bash
npx skills add lcy362/agnes-video-generator-skills --skill agnes-video
```

想用本地管理器管起来？clone 后把目录登记进去：

```bash
git clone https://github.com/lcy362/agnes-video-generator-skills.git
npx flint-skills-hub      # 打开本地界面 http://localhost:8787
# Sources → 添加刚 clone 下来的目录；flint 会从它的 skills/ 子目录里找到这个 skill
```

[**flint**](https://github.com/lcy362/flint) 是一个本地优先的开源技能管理器：通过 symlink 或复制把这个 skill 投放到任意 Agent 目录（Claude Code、Cursor、Codex、TRAE 等），并且只认**本地**源——它不会替你联网拉取任何东西。无云端、无账号、无上报；skill 始终是你磁盘上的普通目录，**即使以后不用 flint 了也照常可用**。**[去 GitHub 给 flint 点个 Star ⭐](https://github.com/lcy362/flint)**

不用 flint 也行，手动拷进去：

```bash
git clone https://github.com/lcy362/agnes-video-generator-skills.git /tmp/agnes-skills
cp -R /tmp/agnes-skills/skills/agnes-video <项目>/.agents/skills/   # 任何读 .agents/skills 的 Agent 都能用
```

### 服务也由 skill 装

`scripts/bootstrap.py install` 会：

- 把服务装进 `~/.agnes-video`（可用 `AGNES_HOME` 覆盖），
- 在同一处维护自己的 virtualenv，只在依赖真的变化时才重跑 `pip`，
- 在 `localhost:8765` 启动服务，并通过真实端点验证可用，
- 把配置、工作区、成片与日志都放在同一个数据根目录。

它不会往你的项目里写任何东西，第二次使用不会再装一遍。

---

## 2. 然后，交代结果

不用再写命令，直接说目标：

> 做一条关于旅行者号的创意长视频，要旁白和字幕。

> 我的任务 `4de1bcd26fda` 失败了——查清原因，并告诉我值不值得修。

> 竖屏视频出来是躺倒的。诊断一下，并把配置修好。

> 拿我那个已完成的任务，把分镜提示词优化一下，然后只重跑受影响的部分。

---

## 3. 它做什么：一条闭环，五个阶段

| 阶段 | 具体做什么 |
|------|------------|
| **安装** | 探测环境，安装前先征得同意，启动服务并验证 |
| **创作** | 选流水线（简单 / 创意 / 稿件 / 数字人 / 诗词 / 图片），通过网页或 stdin 安全接收 API Key，提交任务 |
| **交付** | 运行中汇报增量，完成后给出文件绝对路径、时长与分辨率 |
| **排查** | 失败时取证：诊断端点、`error_logs` 与 `ffprobe`，然后归类为配置问题、上游容量问题或真正的缺陷 |
| **修复** | 仅针对小而可复现的缺陷，且**在你同意之后**：fork、建分支、修、跑等价于 CI 的自检、提交 PR |

有两条边界值得说明：skill **从不发版**（发版仅限维护者，需人工确认），也**从不在你看清根因、同意修复之前**改代码。

仓库：[**lcy362/agnes-video-generator-skills**](https://github.com/lcy362/agnes-video-generator-skills)

---

## 4. Agent 最能帮上忙的地方：手动模式

手动模式会在检查点暂停一次运行，让 Agent 先改产物再继续。Agent 读任务的 `manifest.json`、就地编辑文件、预演哪些下游步骤会重跑，然后确认继续——于是"润色旁白""修字幕"变成一次交代，而不是来回复制粘贴。

详见：[手动模式指南](manual_mode_guide.md)。

---

## 5. 如果你不想用 Agent

| 你想要 | 用什么 |
|--------|--------|
| 现在就要一条视频，什么都不装 | [Studio](https://video.lichuanyang.top/studio) —— 浏览器里直接跑 |
| 完整功能、数据留在本地 | [部署指南](getting-started.zh.md) —— Docker 或 `./start.sh` |
| 自己改本项目的代码 | [`AGENTS.md`](../../AGENTS.md) —— 约定、验证、发版流程 |

Agent 路线是给"宁愿描述结果、不想敲命令"的人准备的，而不是因为 Web UI 次一等。

---

## 相关文档

- [部署指南](getting-started.zh.md) —— 其中的"方式 D"是本文的最短形式，与本文保持同步
- [使用指南](usage.zh.md) —— 模式、检查点、配置
- [手动模式指南](manual_mode_guide.md) —— 检查点与外部 Agent 协作协议
- [API 参考](api.zh.md) —— Agent 所驱动的那些端点
- [常见问题](faq.zh.md) —— 含"多个 Agent 之间这个 skill 怎么保持同步"
