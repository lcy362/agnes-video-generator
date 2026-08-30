# 🎬 Agnes Video Generator — 完全免费的 AI 视频生成工具

[![English](https://img.shields.io/badge/EN-English-blue)](/README.md)
[![GitHub Stars](https://img.shields.io/github/stars/lcy362/agnes-video-generator?style=social)](https://github.com/lcy362/agnes-video-generator)
[![License](https://img.shields.io/github/license/lcy362/agnes-video-generator)](https://github.com/lcy362/agnes-video-generator/blob/main/LICENSE)
[![Python](https://img.shields.io/badge/python-3.10+-blue)](https://www.python.org/)
[![Website](https://img.shields.io/badge/website-video.lichuanyang.top-8A2BE2)](https://video.lichuanyang.top)
[![Docker Hub](https://img.shields.io/docker/pulls/lcy362/free-short-video?label=docker%20pulls)](https://hub.docker.com/r/lcy362/free-short-video)
[![npm](https://img.shields.io/npm/v/free-short-video?label=npm)](https://www.npmjs.com/package/free-short-video)

<p align="center">
  <img src="images/home.png" alt="Agnes Video Generator — 免费 AI 视频生成工具" width="720">
</p>

<!--
schema.org 结构化数据，供搜索引擎与 AI 引擎索引。GitHub 不会执行该脚本，但源码中的 JSON-LD 可被爬取 README 的引擎读取。
-->
<!--
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  "name": "Agnes Video Generator",
  "alternateName": "免费 AI 视频生成工具",
  "applicationCategory": "MultimediaApplication",
  "operatingSystem": "Linux, macOS, Windows",
  "description": "一个完全免费、开源的 AI 视频生成工具。无需订阅、无需高端显卡、没有用量限制——输入一段文字创意，即可自动生成带旁白配音与字幕的多场景 AI 视频。支持文生视频、图生视频、关键帧动画、数字人口播与文章成片。",
  "url": "https://github.com/lcy362/agnes-video-generator",
  "downloadUrl": "https://github.com/lcy362/agnes-video-generator",
  "softwareVersion": "1.0.0",
  "license": "https://opensource.org/licenses/MIT",
  "keywords": "免费AI视频生成器, AI视频生成工具, 文字转视频AI, 免费AI视频制作, 开源视频生成器, AI旁白配音, 自动字幕, 多场景视频, Runway开源替代, Pika开源替代",
  "offers": {
    "@type": "Offer",
    "price": "0",
    "priceCurrency": "USD"
  },
  "author": {
    "@type": "Person",
    "@id": "https://lichuanyang.top/#author",
    "name": "SandGrid",
    "alternateName": "lcy362",
    "url": "https://lichuanyang.top/",
    "sameAs": [
      "https://github.com/lcy362",
      "https://gitee.com/sandgrid/agnes-video-generator",
      "https://video.lichuanyang.top/"
    ]
  }
}
</script>
-->

> **🌏 镜像说明 / Mirror Notice**
> 本项目在国内 Gitee 设有镜像仓库（[gitee.com/sandgrid/agnes-video-generator](https://gitee.com/sandgrid/agnes-video-generator)），便于国内访问加速；**GitHub 为项目主仓库**，Issue / PR / Star 均在 GitHub 提交。
> This project is also mirrored on Gitee for faster access in mainland China; the GitHub repository is the primary home for issues, PRs and stars.

> **完全免费的 AI 视频生成工具** — 基于 Agnes AI 免费模型，无需订阅、无需高端显卡、没有用量限制。输入一段文字创意，就能自动生成带旁白配音和字幕的多场景 AI 视频。支持文生视频、图生视频、关键帧动画、数字人口播等多种模式，所有 AI 计算在云端完成，普通笔记本就能跑。**[在线体验 →](https://video.lichuanyang.top)**

> "解决的办法不是压制 AI，而是让它变成一种更平权的能力，让每个人都知道如何借 AI 创造更多。这也是我们公司很重要的愿景，让世界级的 AI 属于每一个人。我们能做的可能微不足道，但这个愿景非常长久、持久。"
>
> —— Bruce Yang，Agnes AI 创始人

**[🌐 官网](https://video.lichuanyang.top)** | **[📝 博客文章（中文）](https://lichuanyang.top/posts/22470/)** | **[📝 Blog (English)](https://lichuanyang.top/en/posts/22470/)**

> **🖥️ 在线体验 — 免安装：** 打开 [video.lichuanyang.top](https://video.lichuanyang.top) 即可在浏览器中使用 **简单视频** 模式。输入提示词，立刻生成免费的 AI 视频。

## 🚀 两种使用方式 — 均完全免费

| 项目 | 运行方式 | 功能定位 | 链接 |
|------|---------|---------|------|
| **[Agnes Video Generator](https://github.com/lcy362/agnes-video-generator)**（本项目） | **下载后本地运行** | **功能更强大** —— TTS 配音、自动字幕、数字人、图生视频、关键帧动画、文章成片、断点续传等 | [GitHub](https://github.com/lcy362/agnes-video-generator) |
| **[FreeShortVideoStudio](https://github.com/lcy362/free-short-video-studio)** | **完全在线，浏览器内运行** | 轻量免安装、零配置，**功能建设中** | [video.lichuanyang.top/studio](https://video.lichuanyang.top/studio) · [GitHub](https://github.com/lcy362/free-short-video-studio) |

## ⭐ 支持与贡献

如果你觉得这个项目有用，请给 **[GitHub 仓库](https://github.com/lcy362/agnes-video-generator)点个 Star** ⭐ —— 你的支持能让更多人发现这个免费开源的 AI 视频生成工具。

欢迎通过 [GitHub Issues](https://github.com/lcy362/agnes-video-generator/issues) 提交问题反馈或功能建议。

### 💝 支持开发者

Agnes Video Generator 完全免费且开源，**本项目绝不会提供付费计划、增值服务或订阅模式**——无论现在还是将来。

如果你觉得这个项目对你有帮助，可以通过以下方式支持它持续发展：

- **⭐ 在 GitHub 上点 Star** — 给[仓库](https://github.com/lcy362/agnes-video-generator)点个 Star，帮助更多人发现这个项目。
- **🌐 在官网关闭去广告插件** — 在 [video.lichuanyang.top](https://video.lichuanyang.top) 上关闭 AdBlock 等去广告工具，看到感兴趣的广告可以点一下。举手之劳，却是实实在在的支持。
- **📢 分享你的创作** — 将你用 Agnes Video Generator 生成的视频发布到社交媒体（抖音、YouTube、小红书等）并标注本项目。让更多人知道这个工具，更多的用户意味着更多的反馈，项目也会变得更好。

## 🎥 Demo

### 1. 创意视频 — 无配音

> 暗黑童话 —《青蛙王子》，5 个场景，keyframes 串联，全自动生成。

[![青蛙王子 — 演示视频](https://img.shields.io/badge/▶%20观看演示-FF0050?style=for-the-badge&logo=tiktok&logoColor=white)](https://v.douyin.com/L4F6KdGnD6U/)

### 2. 创意视频 — 带 TTS 配音

> 同样的《青蛙王子》故事，增加 AI 生成的 TTS 旁白配音和自动字幕。

[![青蛙王子配音版 — 演示](https://img.shields.io/badge/▶%20观看演示-FF0050?style=for-the-badge&logo=tiktok&logoColor=white)](https://v.douyin.com/l2FlbF1Jdz0/)

### 3. 稿件视频 — 长文转视频

> 粘贴长文/稿件 → 自动拆段 → 逐段 AI 视频 → 统一 TTS 旁白 + 字幕叠加 → 最终视频。

[![稿件视频演示](https://img.shields.io/badge/▶%20观看演示-FF0050?style=for-the-badge&logo=tiktok&logoColor=white)](https://v.douyin.com/eSGE9KENWVU/)

<sub>点击在抖音观看</sub>

## 为什么选择 Agnes Video Generator？

现在做 AI 视频，门槛高得离谱。国外的 Runway、Pika 按月订阅动辄几十美元，国内的即梦、可灵免费额度一用完就按秒计费。想自己在本地跑开源模型？一张能跑视频生成的显卡轻松上万。对于大多数想尝试 AI 视频创作的人来说，这道门基本上是关着的。

我们相信 Bruce Yang 说的那句话——AI 应该是一种更平权的能力。世界级的 AI 应该属于每一个人，而不是只属于付得起账单的人。

坦白讲，Agnes 的视频模型现在还不够完美。生成的画面有时不够稳定，复杂动作偶尔会变形。但它**完全免费、没有用量限制**，而且迭代速度很快。我们选择跟它一起成长，而不是等着一个「完美」的商业方案出现。如果你也认同这个想法，那么这个项目就是为你准备的——你只需要一个免费的 [Agnes AI](https://platform.agnes-ai.com) API Key 和一台能跑 Python 的普通电脑，就可以零成本开始 AI 视频创作。

### 对比：Agnes 与商业 AI 视频工具

| 特性 | Agnes Video Generator | Runway Gen-3 | Pika 2.0 | OpenAI Sora | 可灵 Kling 1.6 |
|------|:---:|:---:|:---:|:---:|:---:|
| **价格** | 完全免费 | $15–$95/月 | $10–$95/月 | $20+/月（限量） | 免费额度后按秒计费 |
| **开源** | ✅ 是（MIT） | ❌ 否 | ❌ 否 | ❌ 否 | ❌ 否 |
| **自托管** | ✅ 支持 | ❌ 不支持 | ❌ 不支持 | ❌ 不支持 | ❌ 不支持 |
| **单段最长时长** | 20秒，场景数不限 | 10秒 | 10秒 | 20秒 | 10秒 |
| **多场景流水线** | ✅ 内置（创意/稿件模式） | ❌ 需手动编辑 | ❌ 需手动编辑 | ❌ 需手动编辑 | ❌ 需手动编辑 |
| **AI 旁白配音** | ✅ 免费内置 | ❌ 需第三方 | ❌ 需第三方 | ❌ 不支持 | ❌ 不支持 |
| **自动字幕** | ✅ 词级 SRT | ❌ 不支持 | ❌ 不支持 | ❌ 不支持 | ❌ 不支持 |
| **数字人口播** | ✅ 内置 | ❌ 无 | ❌ 无 | ❌ 无 | ❌ 无 |
| **分辨率选项** | 9:16 / 16:9 / 1:1 | 多种 | 多种 | 多种 | 多种 |
| **图生视频** | ✅ 支持 | ✅ 支持 | ✅ 支持 | ✅ 支持 | ✅ 支持 |
| **关键帧动画** | ✅ 支持 | ✅ 支持 | ✅ 支持 | ❌ 不支持 | ❌ 不支持 |
| **本地 GPU 需求** | ❌ 不需要（云端 API） | ❌ 不需要（云端） | ❌ 不需要（云端） | ❌ 不需要（云端） | ❌ 不需要（云端） |
| **水印** | 无水印 | 内置水印 | 内置水印 | C2PA 元数据 | 内置水印 |
| **使用限制** | 无限（16次/分钟限速） | 按计算量计费 | 按生成量计费 | 按生成量计费 | 按生成量计费 |

## ⚙️ 配置说明

所有配置均通过环境变量设置，无需配置文件。如需一份带注释的模板，可直接复制项目自带的 `.env.example`：

```bash
cp .env.example .env    # 然后编辑其中的 AGNES_API_KEY
```

[`.env.example`](.env.example) 列出了全部支持的环境变量及其默认值：API Key、多 Key 轮询、限速参数、服务端口、模型覆盖与运维选项。

> **有多个 API Key？** 依次设置 `AGNES_API_KEY`、`AGNES_API_KEY_2`、`AGNES_API_KEY_3` …（序号必须连续）。限速配额会随 Key 数量线性放大，遇到 429 会自动轮换到下一个 Key，并发上限也随之提升。

完整步骤见：[快速开始 → 配置 API Key](docs/public/getting-started.zh.md)。

## 📚 文档导航

- **[核心功能](docs/public/features.zh.md)** — 多种创作模式、完全免费的 AI 模型链、AI 旁白配音与智能字幕、灵活的创作控制、生产级可靠性与多语言 Web UI。
- **[快速开始](docs/public/getting-started.zh.md)** — 4 种部署方式：手动（`start.sh`）、Docker、npm（`npx free-short-video`）、AI Agent 辅助。
- **[使用说明](docs/public/usage.zh.md)** — 配置 API Key、选择视频模式、断点续传、三种串联模式，以及日志与输出目录。
- **[项目架构](docs/public/architecture.zh.md)** — 项目结构与技术栈。
- **[API 接口](docs/public/api.zh.md)** — 完整 REST + WebSocket 接口列表。
- **[常见问题](docs/public/faq.zh.md)** — 高频疑问解答。
- **[关于与许可](docs/public/about.zh.md)** — 致谢与 MIT 开源协议。

**关键词**：免费AI视频生成器, AI视频生成工具, 文字转视频AI, 免费AI视频制作, AI视频创作, 开源视频生成器, Agnes AI, 文生视频, 图生视频, 关键帧视频, AI旁白配音, 自动字幕, 多场景视频, 零成本AI视频, 无需订阅的AI视频工具, 数字人口播, 自托管AI视频生成器, Runway开源替代
