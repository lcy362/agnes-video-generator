# 贡献指南 / Contributing Guide

感谢愿意为 **Agnes Video Generator** 出力。本文档说明「怎么提」、「提什么」、「评审看什么」。

> Thanks for contributing! This guide covers how to file reports, submit code, and share your creations.

---

## 一、先选对渠道 / Pick the right channel

| 我想… / I want to… | 去哪里 / Where |
|---|---|
| 反馈缺陷、生成失败、异常报错 | **Issues** → `Bug report` 模板（使用应用内「去 GitHub 提 Issue」时诊断信息会预填） |
| 提功能建议、问用法问题 | **Discussions** → `Q&A` / `General` |
| 自部署遇到问题 | 先查 [`docs/public/getting-started.md`](docs/public/getting-started.md) 与 [FAQ](https://video.lichuanyang.top/faq)，仍无解再开 `Q&A` |
| **分享自己用本项目做出来的作品与提示词** | **Discussions** → `Show and tell`（有投稿表单，见第三节） |
| 直接改代码 | Pull Request（见第二节） |

> 只想生成视频？去 **[在线体验](https://video.lichuanyang.top/demo)**（浏览器内运行，用你自己的 API Key）。Issues 不是生成入口。

---

## 二、代码贡献 / Code contributions

### 2.1 本地环境

```bash
python3 --version   # 需 3.10+
./start.sh          # 一键：建 venv + 装依赖 + 启动 http://localhost:8765
```

完整部署方式（手动 / Docker / npm）见 [`docs/public/getting-started.md`](docs/public/getting-started.md)。

### 2.2 提交前的必过检查（与 CI 一致）

```bash
# 1) 静态检查（CI 用 ruff；改动文件也要 py_compile）
ruff check core/ web/ utils/ models/ scripts/
.venv/bin/python -m py_compile <你改动的文件>

# 2) 多语言完整性（en 缺失硬阻断、返回码 2；其余语言缺失列出提醒）
python scripts/i18n_check.py

# 3) 单元测试（CI 门槛：整体覆盖率不得低于 55%）
.venv/bin/python -m pytest tests/ -q

# 4) 改了前端源码，必须重新 build 并提交产物（CI 会校验 static/ 与源码一致）
cd frontend && npm test && npm run build
```

### 2.3 硬约束（违反会被 CI 拦下或引入回归）

1. **新增任何用户可见文案，22 个语言包必须同步补齐**（`i18n/langs/*.json`）。`en` 缺失会被 `scripts/i18n_check.py` 硬阻断。
2. **前端产物必须与源码一致**：改动 `frontend/` 后必须 `npm run build` 并提交 `static/` 的 diff。
3. **密钥与隐私不入库**：API Key、token、私人路径、邮箱、手机号一律不得出现在代码、测试、文档与截图里。
4. **不要改动与本次目标无关的文件**，不要顺手重构；大范围重命名请先在 Discussions 提出来。
5. **改动流水线 / 上游重试策略前**，先读 [`docs/dev/agnes_video_upstream_behavior.md`](docs/dev/agnes_video_upstream_behavior.md)（上游接口的真实行为，含失败以 HTTP 200 返回、队列饱和、15 分钟推理硬闸等实测结论）。

### 2.4 Pull Request 流程

1. Fork 或在本仓库开分支（建议 `fix/xxx`、`feat/xxx`、`docs/xxx`）。
2. 一个 PR 只做一件事；描述里写清「问题 → 改动 → 验证方式」（贴出上面 4 项检查的实际结果）。
3. 提交信息用**英文**，标题简洁、祈使句（如 `Fix subtitle drift on long scenes`）。
4. 关联 Issue 用 `Fixes #123`。
5. CI 全绿 + 维护者评审通过后合并；发版规则见 [`docs/dev/release_process.md`](docs/dev/release_process.md)。

---

## 三、作品投稿（Showcase）/ Sharing your creations

用本项目生成了好作品？欢迎分享 —— 官网设有 Showcase 展示区，会同时展示**视频**与**提示词**。

### 3.1 怎么投稿

在 **Discussions → `Show and tell`** 分类下按表单投稿（字段为必填/可选已在表单里标注）。需要提供：

- 视频链接（公开可访问）
- 作品标题（原文 + 英文）
- **提示词原文（原样粘贴，不翻译、不精简）** 及其语言
- 英文含义说明（可选，会作为跨语言读者的统一说明）
- 任务类型（simple / creative / manuscript / anchor / poetry / image）
- 生成参数（可选）

### 3.2 投稿后会发生什么

| 去向 | 说明 |
|---|---|
| ✅ 你自己的账号 | 视频始终发布在**你自己的**频道/平台，播放量与订阅都归你 |
| ✅ 官网 Showcase 页 | 被精选后展示视频（嵌入播放）+ 提示词 + 生成参数，**署名并回链你的主页** |
| ✅ 官方 YouTube 播放列表 `Community Showcase` | 被精选后可能被收进该播放列表（YouTube 允许把任何公开视频加入自己的播放列表，**不涉及二次上传**） |
| ❌ **不会**上传到项目官方频道 | 我们**不**把投稿视频重新上传到官方频道（避免版权与账号责任问题）；如确有联合出品需求，请先开 `General` 讨论并单独确认授权 |

### 3.3 授权范围（重要）

提交投稿即表示你：

1. **保证权利完整**：作品为你本人原创，或你已获得全部必要授权；视频中所用音频（TTS / 音乐）与出现的肖像，责任由你承担。
2. **授予可撤销、非独占、无偿、全球范围的展示许可**：允许本项目在官网展示该作品与提示词，并将其收录进官方 YouTube 播放列表 `Community Showcase`（含署名）。
3. **保留著作权**：作品的著作权仍归你，本授权**不转移所有权**。
4. **可随时要求移除**：在投稿帖下留言即可；官网为静态站点，移除会在**下一次部署**时生效（通常 1~2 天），播放列表移除即时生效。
5. **理解筛选权**：投稿不等于一定被收录；维护者可按「成片完整、提示词可复现、无版权与肖像风险」的标准筛选，并可随时移除已收录内容，无需说明理由。

### 3.4 不被收录的常见原因

- 成片不完整 / 明显是失败的测试产物
- 提示词缺失或被精简到无法复现
- 含第三方音乐、影视素材、真实人物肖像且无授权
- 内容不适合官方站点展示（暴力、色情、政治敏感、医疗/金融等误导性内容等）

---

## 四、行为准则 / Code of Conduct

参与本项目的所有互动（Issues、Discussions、PR 评论）都需遵守 [GitHub 社区准则](https://docs.github.com/articles/github-community-guidelines)：尊重他人、不人身攻击、不发布垃圾信息、不传播侵权与误导性内容。维护者有权删除违规内容并限制参与。

---

## 五、许可 / License

- **代码**：依 [MIT License](LICENSE) 授权。提交 PR 即表示你同意以同一许可分发你的贡献。
- **用户创作内容（视频、提示词等）**：著作权归作者本人，项目仅按第 3.3 节的授权范围展示。
