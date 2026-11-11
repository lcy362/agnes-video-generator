# SonarCloud 分析工作流（提交代码 → Sonar 分析）

> 最近更新：2026-11-11
> 本文档描述**从 push 代码到 SonarCloud 完成分析**的完整链路、触发条件、
> 关键配置与故障排查。配套文件：
> - 工作流定义：`.github/workflows/test.yml`
> - Sonar 分析配置：`sonar-project.properties`
> - 覆盖率/CI 评估：`docs/dev/test_coverage_and_ci.md`

---

## 一、端到端流程（时序图）

```
┌────────────┐   push   ┌──────────────────────┐  触发   ┌─────────────────────────┐
│  开发者提交  │ ───────→ │  GitHub Actions       │ ──────→ │  test.yml（4 个 job）     │
│  git push   │          │  test.yml 匹配分支     │         │  并行：i18n / test /     │
└────────────┘          └──────────────────────┘         │  frontend-build          │
                                                          └───────────┬─────────────┘
                                                                      │ test job（3.10/3.12 矩阵）
                                                          ┌───────────▼─────────────┐
                                                          │ 1. checkout（fetch-depth:0）│
                                                          │ 2. 装依赖（ruff / 前端）    │
                                                          │ 3. pytest --cov           │
                                                          │    → 生成 coverage.xml    │
                                                          │ 4. --cov-fail-under=55    │
                                                          │ 5. SonarQube Cloud Scan   │
                                                          │    （仅 3.12，读 coverage）│
                                                          └───────────┬─────────────┘
                                                                      │ 上传分析 + coverage.xml
                                                          ┌───────────▼─────────────┐
                                                          │ SonarCloud 服务端         │
                                                          │ · 关闭了 Automatic       │
                                                          │   Analysis（CI-based）    │
                                                          │ · 评估 Quality Gate       │
                                                          │   （新代码条件）           │
                                                          └───────────┬─────────────┘
                                                                      │ 结果回写 GitHub check
                                                          ┌───────────▼─────────────┐
                                                          │ GitHub commit → Checks   │
                                                          │  SonarCloud Code Analysis │
                                                          │  README 徽章实时反映       │
                                                          └─────────────────────────┘
```

---

## 二、触发条件

`test.yml` 的触发（`on:`）：

| 事件 | 触发 |
|------|------|
| `push` | **任意分支**（`branches: ["**"]`） |
| `pull_request` | 所有 PR |
| `workflow_dispatch` | 手动触发（仓库 Actions 页面） |

> 每次 push 都会触发完整 CI + Sonar 分析，无需额外操作。

---

## 三、CI 各 Job 职责

| Job | 职责 | 与 Sonar 的关系 |
|-----|------|-----------------|
| `i18n-check` | 多语言完整性前置检查（en 缺失硬阻断） | 无关 |
| `test` | Python 3.10/3.12 矩阵：依赖 → ruff → 前端测试 → `pytest --cov` → **Sonar 扫描** | **核心载体** |
| `frontend-build` | 校验 `frontend/` 源码 build 后与 `static/` 产物一致 | 无关 |

### test job 关键步骤（按顺序）

1. **Checkout**：`actions/checkout@11d5960a...`（固定 SHA），`fetch-depth: 0`
   > ⚠️ 必须完整 git 历史——SonarScanner 依赖它计算**新代码差异**（泄漏周期）。
2. **安装依赖**：`pip install -r requirements.txt -r requirements-dev.txt`
   > 不使用 `--only-binary :all:`：`srt` 包仅 sdist，会装不上（详见 sonar-project.properties S8541 豁免说明）。
3. **Lint (ruff)**：`ruff check core/ web/ utils/ models/ scripts/`
4. **前端**：`npm ci --ignore-scripts` + vitest + build
5. **Run tests with coverage**：
   ```bash
   python -m pytest tests/ \
     --cov=core --cov=models --cov=utils --cov=web \
     --cov-report=xml:coverage.xml \
     --cov-report=html:htmlcov \
     --cov-fail-under=55
   ```
   > - `--cov=web`：**必须包含路由层**（此前缺失导致 Sonar 中 web/ 覆盖率恒为 0）。
   > - `scripts/` 不纳入（一次性回归工具，sonar-project.properties 亦排除）。
6. **SonarQube Cloud Scan**（步骤核心）：
   ```yaml
   if: ${{ matrix.python-version == '3.12' && env.SONAR_TOKEN != '' }}
   uses: SonarSource/sonarqube-scan-action@c7ee0f9df90b7aa20e8dcf9695dcfe2e7da5b4f2  # v7
   env:
     SONAR_TOKEN: ${{ env.SONAR_TOKEN }}
   ```
   - **仅 Python 3.12 执行一次**，避免矩阵重复分析。
   - 未配置 `SONAR_TOKEN` 时自动跳过（不影响其余 CI）。
   - SonarScanner 自动读取 `sonar-project.properties` + 同目录 `coverage.xml`。

---

## 四、Sonar 分析配置（sonar-project.properties）

| 配置项 | 值 | 说明 |
|--------|-----|------|
| `sonar.projectKey` | `lcy362_agnes-video-generator` | SonarCloud 项目标识 |
| `sonar.organization` | `sandgrid` | SonarCloud 组织 |
| `sonar.sources` | `core,web,models,utils,server.py` | 分析范围（**不含 scripts/**） |
| `sonar.exclusions` | node_modules/static/htmlcov/tests 等 | 排除构建产物/测试/脚本 |
| `sonar.coverage.exclusions` | `**/tests/**` 等 | 测试代码不计入覆盖率分母 |
| `sonar.python.coverage.reportPaths` | `coverage.xml` | **CI 生成的覆盖率报告路径** |
| `sonar.cpd.python.minimumTokens` | 100 | 重复代码阈值 |

**Issue 豁免**：`githubactions:S8541` / `S8544`（pip 安装相关）——
`--only-binary` 会因 `srt` 无 wheel 失败、全量锁版本超出当前维护策略，故豁免。

---

## 五、Quality Gate（门禁条件）

项目使用 SonarCloud **内置 `Sonar way` 门禁**（Free 计划**无法**修改门禁值、
也无法将自定义门禁关联到项目——UI 明确提示需升级）。默认条件（**新代码**）：

| 条件 | 阈值 | 当前状态（2026-09-22 复核） |
|------|------|---------|
| `new_coverage`（新代码覆盖率） | ≥ 80% | ✅ 91.7% |
| `new_reliability_rating`（可靠性） | = A | ✅ 1 |
| `new_security_rating`（安全） | = A | ✅ 1 |
| `new_maintainability_rating`（可维护性） | = A | ✅ 1 |
| `new_duplicated_lines_density`（重复行） | ≤ 3% | ✅ 1.5% |
| `new_security_hotspots_reviewed`（安全热点） | 100% | ✅ 100% |

> **关键约束**：Free 计划下门禁只看「新代码」（previous_version 以来的改动），
> 存量问题不阻塞门禁。门禁值不可调整，只能通过**补测试提升新代码覆盖率**达标。
>
> **2026-09-22 修复记录**（画廊 P1 新代码引入）：门禁曾因
> `new_security_rating = 5`（2 个漏洞）+ `new_coverage = 75.9%` 判红。
> 漏洞为 `pythonsecurity:S2083`（`gallery_routes.py` 缩略图路径穿越）与
> `pythonsecurity:S6350`（`gallery_cache.py` ffmpeg 参数注入），根因同一条污点
> 链路：URL 路径参数 `task_id` → 缓存文件名/成片路径。修复方式见 §7；
> 覆盖率经 `tests/test_gallery_routes.py` + `tests/test_presets.py` 补测后
> 由 75.9% → 91.7%。
>
> **2026-09-24 修复记录**（i18n 收尾批次引入）：门禁 `new_security_rating = 2`
> 判红，2 个 `pythonsecurity:S5145`（日志注入，MINOR）。链路：用户表单语言代码 →
> `web/helpers.py::_lang_label` 拼接 `translate(f"voice_compat.label.{code}")` →
> 未知 code 命中 `translate()` 的 `logger.warning("Missing catalog key: %s", key)`
> sink。教训：**后端 i18n 的 key 必须是模块级常量**，动态拼接用户输入的 key 会把
> 不可信值送进 i18n 运行时的诊断日志。修复：语言标签改走静态英文表 +
> `PROJECT_LANGUAGES` 自名表（用户输入只作查表键、不进任何 sink），删除 22 个
> `voice_compat.label.*` 动态 key，补 6 条回归测试（commit `7461a41`）。
>
> **2026-10-17 修复记录**（issue #88 尾帧映射补丁引入）：门禁 `new_security_rating = 3`
> 判红，1 个 `pythonsecurity:S6639`（Memory Allocation DoS，MAJOR）。链路：表单字段
> `end_frame_indices_json` → `json.loads` → `max(ef_indices) + 1` →
> `[""] * slots`（尾帧槽位列表）——该值此前只过了「list[int]」形态校验，
> `[999999999]` 即可让进程分配约 8 GB 列表。修复思路与 §7 的 Python 引擎经验一致：
> **自定义校验函数不被识别为净化器**，故不让用户可控值进入分配大小的构造——
> 落盘结果先按「场景 index → 路径」收进 dict（分配量只与上传文件数有关），
> 再物化成**长度只由常量 `_MAX_SCENE_COUNT`（30）决定**的占位列表；同时把
> `end_frame_indices_json` 的解析收拢为 `_parse_end_frame_indices()`，与
> `scene_count` 共用同一常量上界。补 2 条回归测试（越界 422 / 上界 29 正常落盘）。
>
> **2026-11-11 修复记录**（v8.0 收尾批次引入）：门禁 `new_security_rating = 4`
> 判红，1 个 `python:S2053`（Make this salt unpredictable，CRITICAL）。链路：
> `core/api/key_manager.py::key_fingerprint` 把模块级常量 `_KEY_FP_SALT` 当作
> PBKDF2 盐 → 静态扫描判定「盐可预测」。修复：改为**每安装随机盐**——首次调用
> `secrets.token_bytes(32)` 生成，以 0600 原子写入 `<CONFIG_DIR>/key_fingerprint_salt`
> （`O_CREAT|O_EXCL`，并发首启读回先写入者的值），只读文件系统退化为进程内随机盐。
> 盐随安装持久化，因此指纹跨重启稳定，`video_key_hints` 的回查语义不变。
> 同批次一并清理 v8.0 新代码的 12 条代码味道（S3776 ×4 / S8415 ×4 / S107 /
> S1192 / S3358 / S5869），涉及 `simple_video.py`、`agnes_video.py`、
> `task_creation_routes.py`、`config.py`。

---

## 六、凭据与访问

| 项 | 值 | 说明 |
|----|-----|------|
| GitHub secret | `SONAR_TOKEN` | SonarCloud 个人 token，**长期有效（No expiration）** |
| Token 名称 | `github-ci` | SonarCloud My Account → Access Tokens 生成 |
| 分析模式 | **CI-based analysis** | Automatic Analysis 已关闭（它无法读取 CI 生成的 coverage.xml） |
| 徽章 | `img.shields.io/sonar/quality_gate/...` | README 顶部，实时反映门禁与覆盖率 |

---

## 七、故障排查（按症状）

| 症状 | 根因 | 解决 |
|------|------|------|
| Sonar 步骤 `EXECUTION FAILURE`，`analysis/jres` 返回 **403** | `SONAR_TOKEN` 无效/被删 | 在 SonarCloud 重新生成 token（长期 No expiration），用 `gh secret set SONAR_TOKEN` 更新 |
| Sonar 中 `web/` 覆盖率恒为 **0%** | CI `--cov` 命令漏掉 `--cov=web` | 检查 test.yml 的 pytest 命令包含 `--cov=web` |
| `new_coverage` 不达标（< 80%） | 泄漏周期内新代码测试不足 | 补单测；可用 Sonar API 定位未覆盖文件（见下） |
| `new_security_rating` 不达标（= C/E） | 新代码中存在 `pythonsecurity:*` 漏洞 | 先拉污点链路定位（见下），再在**数据流源头**切断用户输入 |
| `new_security_rating = 3`，规则 `pythonsecurity:S6639`（Memory Allocation DoS） | 用户可控数值进入了 `[""] * n` / `range(n)` / `dict` 预分配等**内存分配大小**的构造 | 让分配长度只由模块级常量决定（先按 key 收进 dict 再物化），并给该数值加常量上界的解析函数；详见 §5 2026-10-17 记录 |
| Quality Gate 无法修改 | Free 计划限制 | 只能补测试；内置门禁不可改 |
| 非主分支数据看不到 | Free 计划仅主分支可查 | 用 GitHub check 看结果，或用 master 分支查询 |

### 定位安全漏洞的污点链路（`pythonsecurity:*`）

`additionalFields=_all` 会返回 `flows`（Source → 中间传播点 → Sink 的完整行号链路），
据此判断该在**哪一行**切断不可信数据，而不是盲目加校验：

```bash
# 1. 列出新代码中的漏洞及其 issue key
curl -s "https://sonarcloud.io/api/issues/search?componentKeys=lcy362_agnes-video-generator&resolved=false&inNewCodePeriod=true&ps=100" \
  | python3 -c 'import json,sys; [print(i["key"], i["rule"], i["component"], i.get("line"), i["message"]) for i in json.load(sys.stdin)["issues"] if i["type"]=="VULNERABILITY"]'

# 2. 拉取某条 issue 的完整污点链路（Source/Sink 行号）
curl -s "https://sonarcloud.io/api/issues/search?issues=<issue_key>&additionalFields=_all" \
  | python3 -c 'import json,sys; [print(l["component"], (l.get("textRange") or {}).get("startLine"), l.get("msg")) for fl in json.load(sys.stdin)["issues"][0]["flows"] for l in fl["locations"]]'
```

> **经验（Python 引擎行为）**：任意函数调用都会把实参污点传播到返回值
> （链路里会出现「This invocation can propagate malicious content to its return value」），
> 因此把不可信值交给自定义校验函数**不能**消除告警，`safe_join` 这类自定义
> 净化函数同样不被识别。可靠做法是让不可信值**不进入路径/参数构造**：
> 例如画廊缩略图端点只用 URL 上的 `task_id` 与工作区扫描结果做**相等比较**，
> 路径与文件名一律取自扫描到的可信标识（磁盘数据）；配合
> `_TASK_ID_RE` 白名单形态校验 + `safe_join` / `safe_workspace_path` 做纵深防御。

### 定位泄漏周期内未覆盖文件

```bash
# 主分支（Free 计划可访问）
curl -s "https://sonarcloud.io/api/measures/component_tree?component=lcy362_agnes-video-generator&metricKeys=new_lines_to_cover,new_uncovered_lines&qualifiers=FIL&ps=50&strategy=leaves"
```

---

## 八、本地快速验证

```bash
# 1. 完整测试 + 覆盖率（与 CI 同参数）
.venv/bin/python -m pytest tests/ --cov=core --cov=models --cov=utils --cov=web --cov-report=term-missing

# 2. 检查 sonar-project.properties 语法（YAML 仅为 workflow 需校验）
.venv/bin/python -c "import yaml; yaml.safe_load(open('.github/workflows/test.yml')); print('OK')"

# 3. 验证 token 对 Sonar 有效
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $SONAR_TOKEN" \
  "https://sonarcloud.io/analysis/jres?os=linux&arch=x86_64"   # 期望 200
```
