# 🚀 快速开始

**[🌐 官网](https://video.lichuanyang.top)** | **[🎬 在线体验（免安装）](https://video.lichuanyang.top/demo)** | **[📚 模型文档](https://video.lichuanyang.top/api-docs)**

## 环境要求

- Python 3.10+
- ffmpeg（视频拼接和音频处理用）

就这些。不需要 GPU，不需要大内存，普通笔记本即可。

> 说明：手动部署（方式 A）需要本机 ffmpeg；Docker（方式 B）和 npm（方式 C）已内置 ffmpeg，无需另行安装。

## 方式 A：手动部署

**第一步 — 克隆 & 启动**

```bash
git clone https://github.com/lcy362/agnes-video-generator.git
cd agnes-video-generator
./start.sh
```

脚本会自动创建虚拟环境、安装依赖，并在浏览器中打开 `http://localhost:8765`。也可以手动启动：

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python server.py
```

**第二步 — 配置 API Key**

前往 [Agnes AI](https://platform.agnes-ai.com) 获取免费 API Key，然后二选一：

```bash
# 方式 1：环境变量
export AGNES_API_KEY="your-api-key"

# 方式 2：通过 API 设置（等同于在 Web UI 中填写；端点接收表单数据）
curl -X POST http://localhost:8765/api/config \
  -F 'api_key=your-api-key'
```

> **⚠️ 让 Key 与站点匹配（避免 `401` / "无效的令牌"）。** Agnes 各站点接口独立，`401` 几乎都是 Key 被发到了错误的站点：
> - `apihub.agnes-ai.com`（国际站）——国际站申请的 Key。
> - `api.agnes-ai.cn`（国内站）——**仅限国内站专属 Key**。
> - `apihub.agnes-ai.cn`（备用）——国内、国际 Key 均可用。
>
> 域名在 **Web 配置页**选择，**不通过 `.env` 配置**。用 `.env` / 环境变量写入的 Key 属于 env 来源：它们**不能逐个绑定域名，也不参与「自动探测域名」**，一律使用你在 Web 页设定的那个**全局默认域名**。因此：
> - **只用单站点 Key：** 把全局默认域名设为与该 Key 站点一致即可。
> - **混用不同站点的 Key：** 请改到 Web 配置页逐个添加（config 来源），每个 Key 都有独立域名下拉，或点「自动探测域名」一次性补全，且重启不丢。
>
> 多 Key 轮换时，只要有一个 Key 与域名不匹配或已失效，任务轮到它就会间歇性报 `401`——请修正或移除该 Key。

**第三步 — 创建第一个视频**

打开 `http://localhost:8765`，从六种任务类型中选择——**单镜头短片**（原「简单视频」）、**多镜头故事**（原「创意长视频」）、稿件长视频、数字人口播、诗词视频、简单图片，输入创意描述后点击"开始生成视频"。

## 方式 B：Docker 部署（无需安装 Python/FFmpeg）

每次 release 都会推送预构建的多平台镜像（`linux/amd64`、`linux/arm64`）至 **GitHub Container Registry (GHCR)** 和 **Docker Hub**。

**拉取并运行**

```bash
# GHCR
docker run -d -p 8765:8765 \
  -e AGNES_API_KEY=<你的key> \
  -v ~/agnes-data/working:/app/.working_dir \
  -v ~/agnes-data/config:/app/.agnes_config \
  ghcr.io/lcy362/free-short-video:latest

# Docker Hub
docker run -d -p 8765:8765 \
  -e AGNES_API_KEY=<你的key> \
  -v ~/agnes-data/working:/app/.working_dir \
  -v ~/agnes-data/config:/app/.agnes_config \
  lcy362/free-short-video:latest
```

然后打开 `http://localhost:8765`。

**数据持久化**：应用会将视频、上传文件和设置写在容器内的 `/app/.working_dir` 和 `/app/.agnes_config` 目录。务必挂载到本机，否则容器重建后数据丢失且无法导出。挂载后生成的视频就在 `~/agnes-data/working/` 目录，直接可拷。

也可以用项目自带的 `docker-compose.yml` 一键启动：

```bash
git clone https://github.com/lcy362/agnes-video-generator.git
cd agnes-video-generator
AGNES_API_KEY=<你的key> docker compose up -d
```

## 方式 C：npm 部署（一条命令）

如果你已安装 **Node.js 18+** 和 **Python 3.10+**，整个服务以 npm 包形式提供——无需克隆代码、无需手动建 venv：

```bash
# 直接运行，无需安装
npx free-short-video

# 或全局安装后运行
npm install -g free-short-video
free-short-video          # 简写别名：fsv
```

首次运行时，启动器会自动创建本地虚拟环境、安装 Python 依赖、接入**内置的 ffmpeg**（`imageio-ffmpeg` 提供的静态二进制，现已在 `requirements.txt` 中显式声明，因此无需在系统中安装 ffmpeg），在 `http://localhost:8765` 启动服务并打开浏览器。可通过环境变量传入 Key，或稍后在 Web UI 中设置：

```bash
AGNES_API_KEY=<你的key> npx free-short-video
```

可用参数：`--port <n>`、`--host <h>`（用 `0.0.0.0` 允许局域网访问）、`--no-open`。

### ffmpeg：默认内置，或自行安装

使用 npm 包时，**通常无需自行安装 ffmpeg**——启动器（`bin/cli.js`）会自动把 `imageio-ffmpeg`（静态 ffmpeg 二进制，已在 `requirements.txt` 中显式声明）安装到本地 venv，并将其所在目录加入 `PATH`，因此 Python 服务内部所有 `ffmpeg` 调用都会解析到内置二进制。在 macOS、Linux、Windows 上均可开箱即用。

**如果你想在系统中自行安装 ffmpeg**（推荐用于生产 / 追求最高稳定性的场景——系统 ffmpeg 在 `PATH` 中位置更靠前，会优先于内置二进制被使用）：

```bash
# macOS
brew install ffmpeg

# Ubuntu / Debian
sudo apt update && sudo apt install ffmpeg

# CentOS / RHEL（需先启用 RPM Fusion）
sudo dnf install ffmpeg

# Windows（Chocolatey）
choco install ffmpeg

# Windows（Scoop）
scoop install ffmpeg
```

也可从 <https://ffmpeg.org/download.html> 下载并加入 `PATH`。验证：

```bash
ffmpeg -version
```

**如果不安装系统 ffmpeg（即完全依赖内置 `imageio-ffmpeg`）可能存在的风险：**

- **平台 / 架构支持** —— `imageio-ffmpeg` 仅为常见平台提供预编译二进制（macOS x86_64/arm64、Linux x86_64/arm64、Windows x64）。在极小众或老旧架构上可能不存在对应的 wheel，导致内置二进制缺失。
- **单一依赖来源** —— 全部 ffmpeg 能力都来自这一份静态二进制。若其安装 / 解压异常（磁盘权限、文件损坏），问题只会在**生成视频时**才暴露，而非服务启动时；报错为底层 `FileNotFoundError: 'ffmpeg'`，比启动期检查更难排查。
- **版本固定** —— 内置 ffmpeg 被锁定为 `imageio-ffmpeg` 所附带的具体版本（如 ffmpeg 7.1），无法自行升级。
- **缓解建议** —— 对生产或稳定性要求较高的用户，建议按上文自行安装系统 ffmpeg；内置二进制则作为兜底。

## 方式 D：AI Agent 辅助部署

本项目由一个 skill 驱动：装一次，之后只描述想要的结果，不必再敲命令。权威说明见
**[让 AI Agent 来操作本项目](agent-operations.zh.md)**。

**装这个 skill。** 它只是普通目录加几个小脚本——不含服务代码，也不经手任何密钥：

```bash
git clone https://github.com/lcy362/agnes-video-generator-skills.git
npx flint-skills-hub     # Sources → 添加刚 clone 的目录（flint 会读它的 skills/ 子目录）
```

[**flint**](https://github.com/lcy362/flint) 是一个本地优先的开源技能管理器：通过 symlink 或复制把这个 skill 投放到任意 Agent 目录（Claude Code、Cursor、Codex、TRAE 等），无云端、无账号、无上报。它只认**本地**源——不会替你联网拉取任何东西，所以要登记的就是刚 clone 下来的那个目录。

**或者手动拷贝**——不用 flint 也行，代价是每个项目、每上一个新 Agent 都要再来一次：

```bash
cp -R agnes-video-generator-skills/skills/agnes-video <项目>/.agents/skills/   # 任何读 .agents/skills 的 Agent 都能用
```

**服务也由 skill 装。** 你不必先 clone 本仓库：skill 会跑 `scripts/bootstrap.py install`，把服务装进 `~/.agnes-video`（可用 `AGNES_HOME` 覆盖），在同一处维护自己的 virtualenv，在 `localhost:8765` 启动，并且第二次使用不重复安装。配置、工作区、成片与日志都在这同一个数据根目录里。

**然后，交代结果。** 这个 skill 是一条闭环——安装、创作、交付、排查，以及（在你同意后）修一个真正的缺陷并提交 PR：

> "做一条关于旅行者号的创意长视频，要旁白和字幕。"

> "我的任务 `4de1bcd26fda` 失败了——查清原因，并告诉我值不值得修。"

**[去 GitHub 给 flint 点个 Star ⭐](https://github.com/lcy362/flint)**


---

> 💡 想跳过安装？直接打开 [在线体验](https://video.lichuanyang.top/demo) 免安装使用。
