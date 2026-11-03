# ❓ 常见问题

### Agnes Video Generator 真的完全免费吗？有没有隐藏费用？

是的，**完全免费**。所有 AI 模型调用（Agnes Chat、Agnes Image、Agnes Video）均免费，无试用期、无水印、无用量限制。唯一的 TTS 集成（微软 Edge TTS）也是免费的，无需额外 API Key。你只需要从 [Agnes AI](https://platform.agnes-ai.com) 获取一个免费的 API Key 即可开始使用。

### 运行这个 AI 视频生成器需要 GPU 吗？

不需要。所有 AI 计算都在云端通过 Agnes AI 的免费 API 完成。你只需要一台能运行 Python 3.10+ 和 ffmpeg 的普通电脑，无需 GPU、无需大内存、无需任何特殊硬件。

### 这个工具和 Runway、Pika、Sora 有什么不同？

商业 AI 视频工具每月收费 $10–$95，而 Agnes Video Generator 完全免费且开源（MIT）。它还内置了多场景流水线、AI 旁白配音、自动字幕和数字人口播——这些功能在其他平台要么需要第三方工具，要么需要手动编辑。详见 [README 中的对比表格](../README_ZH.md#对比agnes-与商业-ai-视频工具)。

### 支持哪些视频生成模式？

六种任务类型：**简单视频**（单条 prompt，完整参数控制）、**创意长视频**（AI 故事 → 多场景视频 + 旁白）、**稿件长视频**（长文本 → 自动拆段 → 配音视频）、**数字人口播**（AI 数字人 + 口型音频）、**诗词视频**（古诗 → 逐句场景 + 朗诵 + 定时字幕）、**简单图片**（一次调用文生图 / 图生图）。额外支持文生视频、图生视频、关键帧动画、图生图尾帧等。

### 可以使用自己的图片作为参考吗？

可以。你可以上传参考图来保持角色或场景的一致性，使用自定义尾帧精确控制画面过渡，或选择 img2img 从参考图自动生成尾帧。创意长视频、稿件长视频（按段落映射参考图引导 i2v 画面）与数字人口播模式均支持参考图。

### Web UI 支持哪些语言？

界面支持 22 种语言：中文、English、Deutsch、Français、Nederlands、Español、Português、Italiano、Русский、日本語、한국어、Bahasa Melayu、Bahasa Indonesia、العربية、Türkçe、Tiếng Việt、ไทย、Tagalog、हिन्दी、فارسی、বাংলা、اردو。字幕以源文本语言生成，内置 CJK / 阿拉伯 / 泰 / 印地（天城文）/ 孟加拉字体支持。

### 可以用 Docker 部署吗？

可以。预构建镜像已推送至 [GHCR](https://github.com/lcy362/agnes-video-generator/pkgs/container/free-short-video) 和 [Docker Hub](https://hub.docker.com/r/lcy362/free-short-video)。拉取 `latest` 标签后直接运行，无需安装 Python 或 ffmpeg。详见快速开始中的 **[方式 B：Docker 部署](./getting-started.zh.md#方式-bdocker-部署无需安装-pythonffmpeg)**。

### 可以部署在自己的服务器上吗？

完全可以。本项目专为自托管设计。克隆仓库后运行 `./start.sh`，服务即启动在 `http://localhost:8765`。无外部依赖、无云锁定。详见 [快速开始](./getting-started.zh.md)。

### 能让 AI Agent 来操作这个项目吗？

可以，本项目就是按这个思路设计的。装一个独立的 **[`agnes-video` skill](https://github.com/lcy362/agnes-video-generator-skills)**：它会按需把服务装进 `~/.agnes-video`，然后出片、交付文件、排查失败，并在你同意后修一个真正的缺陷、提交 PR。你不必 clone 本项目，也不用记命令，只描述想要的结果。（`AGENTS.md` 仍在仓库里，用于修改本项目代码。）完整说明见 **[让 AI Agent 来操作本项目](./agent-operations.zh.md)**。

### 我同时在用好几个 AI Agent，这个 skill 怎么保持同步？

把技能库在 [flint](https://github.com/lcy362/flint) 里登记一次即可。flint 是本地优先的技能管理器：把 skill 集中在一处，通过 symlink 或复制投放到你用到的每个 Agent 目录与项目目录，将来新增 Agent 只需一键分发。它完全本地运行——无云端、无账号、无上报。安装：`npx flint-skills-hub`（界面在 `http://localhost:8787`）。整体思路见 **[让 AI Agent 来操作本项目](./agent-operations.zh.md)**。

### 生成失败了怎么办？

大多数失败由模型服务波动、网络超时或限流等**偶发因素**导致。请在应用内的**失败面板**先点击「重试任务」，任务会从失败环节断点续传，多数情况下即可自愈，无需重新提交。

若多次重试（≥ 2 次）仍失败，失败面板会**自动展开反馈区**，支持一键复制诊断信息并跳转到预填好的 GitHub Issue，无需手动描述环境。

### 一开始就报 `403 insufficient_user_quota`（remaining: `$0.000000`）怎么办？

这是 Agnes 直接拒掉了提交：**你当前选中的视频模型需要账户余额**，而这把 Key 对应的账户余额是 **$0**。请求没有建出任务，既没生成内容也没扣配额，重试不花钱。

两个模型要分清：

- `agnes-video-2.5-flash`：免费（限时），720P、4–12 秒，余额为 0 也能用。
- `agnes-video-2.5`：付费（720P $0.025/s · 960P $0.04/s · 2K $0.055/s），余额为 0 时每次提交都会返回这个 403。

**怎么办**：打开配置页把视频模型切到 `agnes-video-2.5-flash`，再点「重试任务」——任务从视频生成这一步继续，稿件与场景描述都会保留。只有确实需要 960P/2K 才需要充值并留在 `agnes-video-2.5`。不换模型反复重试只会一次次撞同一堵墙，这个报错是确定性的，不是临时抖动。

### 报 `402 Payment Required` / `Insufficient Balance` 怎么办？

这是**你自己配置的第三方文本模型供应商**在拒单，不是 Agnes 的问题，也不是应用的故障。如果你在配置页的「文本模型供应商」里把文本模型切到了外部服务（例如 DeepSeek），那么编剧、场景描述这类文本调用都会走该服务；该账户余额为 0 时，对方会直接返回 `402 Payment Required`（`insufficient_balance_error`）。任务在第一步就中止，没有生成内容，也没有消耗任何配额，重试不花钱。

可选出路：

1. 给该供应商账户充值，然后点「重试任务」从同一步继续；
2. 或把供应商切回内置的 **Agnes（内置）**（免费、不需要自备 Key），保存后再重试；
3. 若长期使用该供应商，确认 Key、服务地址与账户属于同一个账户且有余额。

不换供应商也不充值的情况下，重试必然复现同一个 `402`。

### 生成跑了很久，最后一步才失败，报 `getaddrinfo failed` / `[Errno 11004]`

这是**你本机的 DNS 解析问题**，不是生成失败。提交任务和轮询走 API 域名，而生成好的视频、图片存放在独立的输出域名上（视频为 `cos-platform-outputs.agnes-ai.cn`，图片为 `platform-outputs.agnes-ai.space`）。当本机解析不到输出域名时，服务端其实已经完成，只是这台机器取不回文件，于是任务恰好卡在下载环节，每次重试也都死在同一处。

按顺序排查：

1. 换成能解析该域名的 DNS。国内可用 `223.5.5.5`（AliDNS）或 `119.29.29.29`（DNSPod）；海外用 `1.1.1.1` 或运营商默认 DNS 即可。
2. 关闭 VPN / 代理客户端的 DNS 劫持，检查 hosts 条目与安全检查软件是否拦截了不认识的域名。
3. 刷新本机 DNS 缓存（Windows `ipconfig /flushdns`，macOS `sudo dscacheutil -flushcache`），然后重新打开页面。
4. 点击「重试任务」。已生成的 video id 保存在任务目录里，续传只会重新拉取文件，不会重复提交、不额外消耗配额。

自 **v6.4.8** 起，这类错误在失败面板会被明确标成「网络诊断」提示并写出解析失败的域名，而不是只显示 `RetryError[...]`；预填 Issue 里的「失败环节」也会指向真正出错的环节。

### 为什么报 `401` / 「无效令牌」，即使我的 API Key 看起来是对的？

`401 Unauthorized` 或「无效的令牌」通常意味着 **API Key 与请求的域名不匹配**——例如在国际站领取的 key 用到了国内站专属域名 `api.agnes-ai.cn`（或反之）。不同 key 属于不同站点，域名不对时令牌会被拒绝。

自 **v6.4.2** 起，每个 key 可绑定自己的接入域名，并新增一键「自动探测域名」按钮，逐 key 在 `com` / `cn` / `cn_bak` 中探测并自动补上匹配域名。在 API Key 面板选择与你的 key 匹配的域名，或直接点击自动探测即可。国际站 key 应使用 `apihub.agnes-ai.com`，或 `cn_bak` 兜底域名（`apihub.agnes-ai.cn`，同时兼容国内与国际 key）。

> **注意——env Key 与 Web 页 Key 的差别。** 逐 Key 绑定域名和「自动探测域名」**只对在 Web 配置页添加的 Key 生效**。用 `.env` / 环境变量写入的是 env Key：它们无法逐个绑定域名、也会被自动探测跳过，一律使用你在 Web 页设定的那个**全局默认域名**。所以 env Key 报 `401` 的正确修正是：把全局默认域名切到与该 Key 站点一致，或把该 Key 改到 Web 配置页添加。另外，多 Key 轮换时只要有一个 Key 与域名不匹配或已失效，任务轮到它就会间歇性报 `401`。

### 把提示词贴到 GitHub Issue 里，能帮我生成视频吗？

不能。本项目是**自托管工具**，不是在线生成服务——维护者不会代你跑任务，把提示词贴进 Issue 或评论不会产出任何视频，并会作为无效反馈被关闭。请使用下面两个真实入口之一：

- **本地部署**：运行 `./start.sh`（或 Docker / npm），打开 `http://localhost:8765` 后在应用内填写提示词。详见 [快速开始](./getting-started.zh.md)。
- **免安装在线体验**：[video.lichuanyang.top/demo](https://video.lichuanyang.top/demo) —— 完全在浏览器内运行，使用你自己的 Agnes API Key。

Issue 请用于它真正擅长的事情：**缺陷反馈**（错误信息、任务类型、失败环节——应用内失败面板会自动为你填好）与**功能请求**。如果是*在应用内*某个提示词生成效果不理想，那属于提示词/模型问题，请附上提示词、模式、模型与分辨率，我们会来看。

### 如何获取帮助或报告问题？

应用内与官网提供双向反馈入口：

- **应用内一键反馈**：任务失败时，失败面板会提供「复制诊断信息」与「去 GitHub 提 Issue」按钮，自动拼接版本号、任务类型、失败环节、错误信息与重试次数，帮助维护者快速定位。
- **官网 / GitHub**：也可直接访问 [GitHub Issues](https://github.com/lcy362/agnes-video-generator/issues) 页面查看已有报告或提交新 Issue。项目还包含完整的 `AGENTS.md` 部署指引，支持 AI 编程助手辅助调试。

> 💡 提示：提交 Issue 前请先确认已按上述「生成失败了怎么办？」尝试重试，以减少偶发故障的重复上报。

---

## 📚 更多资源

- [🌐 官网](https://video.lichuanyang.top) — 项目主页与最新资讯
- [🎬 在线体验](https://video.lichuanyang.top/demo) — 免安装直接使用
- [📋 API 文档](https://video.lichuanyang.top/api-docs) — 完整接口列表
