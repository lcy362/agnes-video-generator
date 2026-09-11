# 🎬 Agnes Video Generator 新手完全指南

> 写给第一次接触开源项目的你——这篇文章会手把手教你从零开始，把 AI 视频生成器跑起来。

---

## 先别急着装，最简单的办法在这里 👇

**这个项目有一个在线网站**，你不需要装任何东西就能直接用：

👉 **[https://video.lichuanyang.top](https://video.lichuanyang.top)**

打开浏览器，输入一段文字描述（比如「一只猫在花园里追蝴蝶」），点一下按钮，就可以生成 AI 视频。完全免费，不需要注册付费，不需要高端电脑。

如果你只是想快速体验一下 AI 视频生成，直接用网站就够了。

**那为什么还要自己装到电脑上？** 因为本地部署后可以使用更多功能——创意长视频（AI 自动写故事、分场景、配旁白）、稿件转视频（把你的文章变成带配音的视频）、数字人口播等等，而且所有数据都在你自己的电脑上。

---

## 第一章：认识「终端」

很多教程里会写「打开终端，输入 xxx」——但没有人告诉你**终端（Terminal）是什么，在哪里打开**。别担心，看完这节你就懂了。

终端是一个**黑色的文字窗口**，你可以在里面输入命令来控制电脑。看起来像黑客电影里的界面，但它其实就是一个普通的工具，就像记事本一样。

### Windows 系统

Windows 上有两种终端，**建议用 PowerShell**（更现代）：

**方法 1 — 搜索打开（推荐）**
1. 按键盘上的 `Win` 键（左下角四个方块的键），或点击屏幕左下角的开始菜单
2. 直接输入 `powershell`（不用管输入框在哪里，直接打字就行）
3. 看到「Windows PowerShell」后，点击打开

**方法 2 — 右键打开**
1. 打开任意文件夹
2. 按住 `Shift` 键不放，在文件夹空白处点右键
3. 选择「在此处打开 PowerShell 窗口」

**方法 3 — 运行打开**
1. 按 `Win + R` 键
2. 输入 `powershell`，回车

打开后你会看到一个蓝色或黑色的窗口，上面有一些白色文字——这就是终端。你可以在里面输入命令。

> 💡 **提示**：如果你看到的是「命令提示符」（黑底白字、标题栏写着 CMD），也可以用来操作，但本文建议用 PowerShell。

### macOS 系统

macOS 的终端叫「终端.app」：

**方法 1 — Spotlight 搜索（最快）**
1. 按 `Command（⌘）+ 空格键`
2. 输入 `terminal` 或 `终端`
3. 看到「终端.app」后回车打开

**方法 2 — 从文件夹打开**
1. 打开「访达（Finder）」
2. 左侧点击「应用程序」
3. 找到「实用工具」文件夹，点进去
4. 双击「终端」

**方法 3 — Launchpad**
1. 点击 Dock 栏上的 Launchpad 图标（火箭图标）
2. 找到「其他」文件夹
3. 点击「终端」

### Linux 系统（Ubuntu / Debian 等）

大多数 Linux 发行版都自带终端：

- **Ubuntu**：按 `Ctrl + Alt + T` 直接打开
- 或者在应用菜单里搜索「Terminal」/「终端」

---

## 第二章：安装必要的工具

这个项目需要三个东西：**Python**、**Git**、**ffmpeg**。下面按操作系统一一说明怎么装。

> ⚠️ 如果你打算用 **Docker** 方式安装（见后面第三章的「方式 C」），那这三个都不需要装！Docker 会自动处理好一切。

### 2.1 安装 Python 3.10+

**怎么检查你电脑上有没有 Python？**
打开终端，输入 `python3 --version`（Windows 输入 `python --version`），然后回车。如果看到类似 `Python 3.12.0` 的输出，说明已经装好了。如果版本号小于 3.10（比如 3.8），需要升级。如果提示「找不到命令」，说明没装。

**Windows：**
1. 打开浏览器，访问 [https://www.python.org/downloads/](https://www.python.org/downloads/)
2. 点击黄色的大按钮「Download Python 3.x.x」（会自动推荐最新版）
3. 下载完成后双击安装程序
4. ⚠️ **重要**：安装界面的第一页，**务必勾选底部的「Add Python to PATH」**（把 Python 添加到系统路径），然后点击「Install Now」
5. 等待安装完成，关闭窗口

验证：重新打开一个 PowerShell 窗口（已打开的窗口需要关掉重开），输入 `python --version`，应该看到版本号。

**macOS：**
打开终端，输入以下命令（需要先装 Homebrew，见下方说明）：

```bash
brew install python3
```

如果提示 `brew: command not found`，说明还没装 Homebrew。Homebrew 是 macOS 的软件包管理器——先装它：

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

安装过程中会提示你按回车确认，按提示操作即可。装完 Homebrew 后，再运行 `brew install python3`。

**Ubuntu / Debian Linux：**
```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip
```

验证：终端输入 `python3 --version`，应该看到 `Python 3.10.x` 或更高。

### 2.2 安装 Git

Git 是用来从 GitHub 下载代码的工具。

**Windows：**
1. 访问 [https://git-scm.com/download/win](https://git-scm.com/download/win)
2. 下载安装程序，一路点「Next」安装即可（所有选项保持默认就行）

**macOS：**
```bash
brew install git
```
或者如果之前没装 Homebrew，也可以去 [https://git-scm.com/download/mac](https://git-scm.com/download/mac) 下载安装包。

**Ubuntu / Debian Linux：**
```bash
sudo apt install git
```

验证：终端输入 `git --version`，应该看到版本号。

### 2.3 安装 ffmpeg

ffmpeg 是处理视频和音频的工具，用于最后把多段视频拼接起来。

**Windows：**
1. 访问 [https://ffmpeg.org/download.html](https://ffmpeg.org/download.html)
2. 找到 Windows 部分，点击「Windows builds from gyan.dev」
3. 下载 `ffmpeg-release-essentials.zip`
4. 解压到 `C:\ffmpeg`
5. 把 `C:\ffmpeg\bin` 添加到系统 PATH：
   - 按 `Win` 键，输入「环境变量」，选择「编辑系统环境变量」
   - 点「环境变量」→ 在「系统变量」中找到 `Path` → 编辑 → 新建 → 输入 `C:\ffmpeg\bin` → 确定
6. 重新打开 PowerShell，输入 `ffmpeg -version` 验证

**macOS：**
```bash
brew install ffmpeg
```

**Ubuntu / Debian Linux：**
```bash
sudo apt install ffmpeg
```

验证：终端输入 `ffmpeg -version`，应该看到版本信息。

---

## 第三章：安装 Agnes Video Generator（四种方式任选）

这里有四种安装方式，从上到下越来越简单。**新手推荐方式 B（npx 一行命令）或方式 D（直接用网站）**。

### 方式 A：手动安装（最传统，适合想了解每一步发生了什么）

**第一步 — 下载代码**

打开终端，输入以下命令：

```bash
git clone https://github.com/lcy362/agnes-video-generator.git
```

这行命令的意思是「从 GitHub 把这个项目的代码复制到你的电脑上」。执行后，你当前所在的文件夹里会多出一个 `agnes-video-generator` 文件夹。

**第二步 — 进入项目文件夹**

```bash
cd agnes-video-generator
```

`cd` 是「change directory」的缩写，意思是「切换目录（文件夹）」。这行命令让你进入刚才下载的项目文件夹。

**第三步 — 一键启动**

```bash
./start.sh
```

> ⚠️ Windows 用户注意：这个脚本是为 macOS/Linux 写的。Windows 用户请改用下面的手动步骤：

```powershell
# Windows PowerShell 中手动执行：
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python server.py
```

`start.sh` 这个脚本会自动做三件事：
1. 创建一个「虚拟环境」（给这个项目一个独立的 Python 运行空间，不跟你电脑上其他 Python 项目冲突）
2. 安装项目需要的 Python 包
3. 启动服务

启动成功后，终端会显示一些日志，然后你的浏览器会自动打开 `http://localhost:8765`。

**如果浏览器没自动打开**：手动打开浏览器，地址栏输入 `http://localhost:8765`。

---

### 方式 B：npx 一行命令（最简单，推荐新手）

如果你的电脑已经有 **Node.js 18+** 和 **Python 3.10+**，这是最简单的方式——不需要下载代码，不需要手动创建虚拟环境：

```bash
npx free-short-video
```

这一行命令会自动完成所有事情：创建虚拟环境、安装依赖、内置 ffmpeg（不需要你单独装）、启动服务。第一次运行需要下载一些东西，等几分钟就好。

如果想把 API Key 也一起传入：
```bash
AGNES_API_KEY=你的key npx free-short-video
```

**怎么检查有没有 Node.js？** 终端输入 `node --version`。如果提示找不到，去 [https://nodejs.org](https://nodejs.org) 下载安装（选 LTS 版本，点左边绿色的大按钮）。

---

### 方式 C：Docker（完全不需要装 Python / ffmpeg）

Docker 像一个「集装箱」——它把项目连同所有依赖（Python、ffmpeg 等）打包在一起，你只需要装 Docker 本身，其他什么都不用管。

**怎么安装 Docker：**
- **Windows / macOS**：去 [https://www.docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop) 下载 Docker Desktop，安装后运行（会在任务栏/菜单栏出现一个小鲸鱼图标）。
- **Linux**：`sudo apt install docker.io`（Ubuntu），然后 `sudo systemctl start docker`。

安装 Docker 后，在终端中运行：

```bash
docker run -d -p 8765:8765 \
  -e AGNES_API_KEY=你的key \
  -v ~/agnes-data/working:/app/.working_dir \
  -v ~/agnes-data/config:/app/.agnes_config \
  ghcr.io/lcy362/free-short-video:latest
```

> 注意：命令末尾的 `\` 表示「这行没完，下面继续」，在 Windows PowerShell 中请把 `\` 换成 `` ` ``（反引号），或者把所有内容写成一行（去掉 `\` 和换行）。

执行后，打开浏览器访问 `http://localhost:8765`。生成的视频会自动保存在你电脑的 `~/agnes-data/working/` 文件夹。

**怎么关闭：** 终端输入 `docker ps` 查看正在运行的容器，找到对应的 CONTAINER ID，然后 `docker stop <ID>`。

---

### 方式 D：直接用网站（零安装）

再次提醒——如果你只是想体验一下，不需要本地部署：

👉 **[https://video.lichuanyang.top](https://video.lichuanyang.top)**

打开就能用，支持「简单视频」模式，输入文字就能生成 AI 视频。

---

## 第四章：获取 API Key 并配置

不管用哪种方式，你都需要一个**免费的 API Key**：

1. 打开 [https://platform.agnes-ai.com](https://platform.agnes-ai.com)
2. 注册账号（用邮箱注册即可，免费）
3. 登录后在后台找到「API Key」或「密钥管理」
4. 复制你的 API Key（一串很长的字母和数字）

有两种方式配置 API Key：

**方法 1 — 在网页上填**（推荐新手）
- 服务启动后，打开 `http://localhost:8765`
- 页面顶部有一个输入框，把 API Key 粘贴进去，点保存

**方法 2 — 启动时通过环境变量传入**
```bash
# macOS / Linux
export AGNES_API_KEY="你的key"
# 然后再启动服务...

# 或者在启动命令前加上：
AGNES_API_KEY=你的key ./start.sh
```

---

## 第五章：开始生成视频

服务启动后，打开 `http://localhost:8765`，你会看到四个标签页：

| 模式 | 做什么用 | 适合场景 |
|------|---------|---------|
| **简单视频** | 输入一句话 → 生成一段 AI 视频 | 快速体验、单段视频 |
| **创意长视频** | AI 自动写故事、分场景、配旁白、加字幕 | 讲故事的视频 |
| **稿件视频** | 粘贴一篇长文章 → 自动分段 → 生成带配音的视频 | 解说类视频、课程 |
| **数字人口播** | 虚拟主播朗读你的文案 | 产品介绍、新闻播报 |

**新手建议**：先从「简单视频」开始。在提示词框里输入一段英文描述（比如 `a cat chasing a butterfly in a garden, cinematic`），选择时长 5 秒，点「开始生成」。等待 1-3 分钟，视频就出来了。

---

## 常见问题 FAQ

### Q: 启动时提示 `python3: command not found`
**A:** Python 没装或者 PATH 没配好。回到第二章 2.1 节重新安装。Windows 用户特别注意安装时必须勾选「Add Python to PATH」。

### Q: 提示 `ffmpeg not found`
**A:** ffmpeg 没装。回到第二章 2.3 节安装。或者用 Docker / npx 方式部署，这两种方式自带 ffmpeg。

### Q: 生成视频时报 401 错误
**A:** API Key 没配或配错了。检查一下 API Key 是否正确粘贴（注意不要多复制空格）。

### Q: 端口 8765 被占用
**A:** 之前启动的服务没关。终端执行：
- macOS / Linux: `lsof -ti:8765 | xargs kill`
- Windows: `netstat -ano | findstr :8765` 找到 PID，然后 `taskkill /PID <PID> /F`

### Q: 我想让局域网内其他设备也能访问
**A:** 启动时这样：
- npm 方式：`npx free-short-video --host 0.0.0.0`
- 手动方式：`HOST=0.0.0.0 .venv/bin/python server.py`
- 然后在其他设备的浏览器输入 `http://<你电脑的IP>:8765`

### Q: 生成视频要多久？
**A:** 简单视频约 1-3 分钟，创意长视频（5 个场景）约 10-20 分钟。因为存在共享 API 调用限速（单 Key 约 16 次/分钟，配置多个 Key 后配额线性放大；视频提交另有独立限速桶），场景越多等得越久——这是为了免费而做的限速，不是你的电脑慢。

### Q: 视频生成失败或卡住了怎么办？
**A:** 按 `Ctrl + C` 停止服务，再重新启动。项目支持「断点续传」——重新启动后去「任务列表」里找到之前的任务，点「续传」就会从上次中断的地方继续，不会重复生成。

### Q: 字幕出现方块乱码？
**A:** 这个项目自带了中文字体，一般不会出现。如果遇到了，检查 `resource/fonts/` 目录下的字体文件是否完整。

---

## 最后说几句

你不是「stupid」。**每个玩开源的人都是从「看不懂终端」开始的。** 这些看起来像黑客操作的界面，其实只是另一种操作电脑的方式——就像你第一次用智能手机也要学怎么滑屏、怎么装 App 一样。

开源社区有一个很大的问题：大多数教程默认读者已经「懂了那些没人教过的基础知识」。这不是你的问题，是教程的问题。希望这份指南帮你跨过了那道隐形的门槛。

如果还有问题，去项目的 [GitHub Issues](https://github.com/lcy362/agnes-video-generator/issues) 提问——怕英文不好就用中文写，开发者看得懂。

Good luck, and have fun creating videos! 🎬
