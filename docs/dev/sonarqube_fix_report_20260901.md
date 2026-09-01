# SonarQube 配置补齐与问题清理报告

**日期**：2026-09-01
**项目**：agnes-video-generator（SonarCloud 组织 `sandgrid`，项目 key `lcy362_agnes-video-generator`）

---

## 一、背景与诊断

- SonarCloud 通过 GitHub App **自动分析（Automatic Analysis）** 集成，配置在 SonarCloud 服务端，**仓库内原本没有任何 sonar 配置**，这是之前"找不到配置"的原因。
- 提交 `b29edba` 触发的 `SonarCloud Code Analysis` **Quality Gate 失败**：唯一失败条件 `new_reliability_rating = 3`（新代码可靠性评级 C，要求 A）。
- 泄漏周期内共 6 个新代码问题，分布在 `config_routes.py` 与 `ConfigPanel.vue`。
- 存量问题 **763 个**（BUG 115 / VULNERABILITY 72 / CODE_SMELL 576），修复总工时约 125.8h。
- **覆盖率从未上报**：SonarCloud 上 `coverage` 指标为空（CI 虽产出 `coverage.xml`，但从未上传）。

## 二、配置补齐（本次新增）

| 文件 | 变更 | 说明 |
|------|------|------|
| `sonar-project.properties` | **新增** | 定义 projectKey/org、分析范围（core/web/models/utils/scripts/server.py）、排除项（node_modules/static/htmlcov/tests 等）、`sonar.python.coverage.reportPaths=coverage.xml`、编码与重复代码阈值 |
| `.github/workflows/test.yml` | 修改 | 新增 `Publish coverage to SonarCloud` 步骤：用 `sonarcloud/publish-coverage@v3` 上传 `coverage.xml`；`SONAR_TOKEN` 提升为 job 级 env（未配置时自动跳过，不影响现有 CI） |

> **待用户操作**：在 GitHub 仓库 Settings → Secrets 添加 `SONAR_TOKEN`（SonarCloud 个人 Token）后，下次 push 的自动分析即会合并覆盖率数据。

## 三、新代码问题修复（Quality Gate 直接原因，6/6）

| 文件 | 规则 | 问题 | 修复 |
|------|------|------|------|
| `config_routes.py` | S1192 (CRITICAL) | `"Key 不存在"` 重复 3 次 | 提取模块常量 `_MSG_KEY_NOT_FOUND` |
| `config_routes.py` | S5806 (MAJOR) | 变量 `id` 遮蔽内建函数 | 参数改名 `key_id` + `alias="id"` 保持 API 契约 |
| `config_routes.py` | S8415 ×3 (MAJOR) | HTTPException 状态码未在路由声明 | 两个路由装饰器补充 `responses={400/404/422}` |
| `ConfigPanel.vue` | InputWithoutLabelCheck (BUG) | 域名 select 缺 label 关联 | 添加 `<label :for>` + `:id` + `aria-label`（`sr-only` 类已有先例） |

## 四、BLOCKER 修复（5/5）

| 文件 | 规则 | 问题 | 修复 |
|------|------|------|------|
| `image_routes.py` | S2083 (VULNERABILITY) | 路径遍历：`ext` 来自用户文件名 | 扩展名白名单 `_ALLOWED_UPLOAD_EXTS` + `safe_join()` |
| `task_creation_routes.py` | S2083 (VULNERABILITY) | 同上（上传文件保存） | 扩展名白名单 + `safe_join()` |
| `regression_runner.py` | S2083 (VULNERABILITY) | `tmp_audio` 由外部路径拼接 | 改用 `tempfile.mkstemp` 系统临时目录 |
| `concat.py` | S3516 (CODE_SMELL) | "总是返回相同值" | 经比对为**旧版本代码**（08-31 已更新，当前含动态返回值），重新分析后自动标记 FIXED |
| `watermark.py` | S3516 (CODE_SMELL) | 同上 | 同上 |

## 五、CI / Docker 安全漏洞清理（25 处）

| 文件 | 规则 | 修复 |
|------|------|------|
| `release.yml` | S8233 ×2 | workflow 级写权限 → 收敛为 `contents: read`，仅 `build-and-push` job 授予 `write` |
| `release.yml` | S7637 ×12 | 全部 action 固定到完整 commit SHA（checkout/qemu/buildx/build-push/login/metadata/gh-release/setup-node） |
| `release.yml` | S7636 ×2 | release body heredoc 内 secrets 展开 → `env` 注入 + 占位符 `__DH_USERNAME__` + sed 替换 |
| `sync-to-gitee.yml` | S7636 ×2 | run 块内联 `GITEE_TOKEN` → `env` 注入引用 |
| `test.yml` | S8541/S8544 | pip 安装加 `--only-binary :all:`（已验证全依赖有 wheel） |
| `test.yml` | S6505/S8543 | `npm install` → `npm ci --ignore-scripts`（锁版本 + 禁生命周期脚本） |
| `test.yml` | S6505 | frontend-build 的 `npm ci` 加 `--ignore-scripts` |
| `Dockerfile` | S6471 (VULNERABILITY) | root 运行 → 新建 `appuser` 非 root 用户 + 授权写目录 |
| `Dockerfile` | S7031 / S7020 | 合并连续 RUN + 拆分超长行 |
| `Dockerfile` | S6470 | `COPY . .` → 改为显式拷贝运行所需目录（配合已有 .dockerignore） |
| `Dockerfile` | S8541/S8544 | ⚠️ 无法加 `--only-binary`：`srt` 包仅 sdist 无 wheel（已验证），需 lock 文件或接受现状 |

## 六、Python 核心高价值问题修复

| 文件 | 规则 | 问题 | 修复 |
|------|------|------|------|
| `agnes_video.py` | S7493 (BUG) ×2 | async 函数内同步 `open()` | 提取 `_read_json_cache`/`_write_json_cache`，`asyncio.to_thread` 包装 |
| `agnes_image.py` | S5145 (VULNERABILITY) | 日志记录用户 prompt | 改为只记录模式 + prompt 长度 |
| `agnes_chat.py` | S5713 (CODE_SMELL) ×2 | `json.JSONDecodeError` 冗余捕获（其是 `ValueError` 子类） | 收敛为 `except ValueError` |

## 七、自验结果

| 检查 | 结果 |
|------|------|
| `py_compile` 全部改动文件 | ✅ 通过 |
| `ruff check` 全部改动文件 | ✅ 通过 |
| 完整测试套件 `pytest tests/` | ✅ **367 用例全通过**（无失败） |
| 前端 `vitest` | ✅ 4/4 通过 |
| 前端 `npm run build` | ✅ 构建成功（`static/` 产物已同步，满足 CI 一致性检查） |
| 三个 workflow YAML 语法 | ✅ 全部有效 |
| FastAPI 路由注册（含 responses） | ✅ 正常 |
| i18n 完整性检查 | ✅ 通过 |

## 八、遗留与建议

1. **待配置**：GitHub Secrets 添加 `SONAR_TOKEN`，否则覆盖率上传步骤会跳过。
2. **存量 CRITICAL 复杂度问题**（S3776：`agnes_image.py` 46 分、`agnes_video.py` 20-29 分等）未动——重构风险高、收益低，建议专项排期。
3. **`Dockerfile` S8544**（依赖未锁定）：如需彻底解决，需引入 pip lock 文件（`pip-tools` compile），但会改变现有"版本范围"维护策略，需确认。
4. **Workflow S8544**（`requirements.txt` 未锁版本）：同上，属供应链加固项，建议后续用 `pip-compile` 生成锁定文件。
5. **存量 763 问题中约 1/3 为外部 API 客户端**（有意不单测）与 CRITICAL 复杂度，其余 MAJOR 级 issue 建议按模块分批清理。
