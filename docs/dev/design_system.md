# 前端视觉体系（Workbench）

> 适用：`frontend/src/**` 的所有界面改动。改样式前先读本文，避免回到「每个组件一套圆角阴影」的旧状态。
> 权威实现：`frontend/src/style.css`（token + 组件层）、`frontend/tailwind.config.js`（字体与圆角上限）。

## 一、设计语言

| 项 | 约定 |
|---|---|
| 世界 | 暗房工作台 / 仪表盘。近黑暖灰纸面 + 发丝级分隔线 + 单一琥珀强调色 |
| 承载 | 信息密度优先于留白；用线条与明度分层，不用阴影堆叠 |
| 强调色 | 琥珀 `--color-accent` **只**用于：主操作按钮、进行中/选中态、当前步骤指针 |
| 圆角 | ≤ 12px（`--r: 8px` 为默认，卡片 8、弹窗 12） |
| 阴影 | 除弹窗、抽屉、下拉面板外一律不用 |
| 动效 | 120–200ms，只做透明度 / 描边过渡；不使用位移与缩放入场 |
| 图标 | 24×24 线性 stroke（1.5–1.8），不新增表情符号；语言包自带的表情用 `stripEmoji()` 剥掉 |
| 数字/ID | 等宽字体（`.mono`、`tabular-nums`），编号统一两位数（01…04） |

## 二、Token

全部定义在 `style.css` 的 `:root`，亮色在 `[data-theme='light']` 同族反转（hue 60–70 暖灰家族）。

- 表面：`--color-paper`（页面）/ `--color-paper-2`（面板）/ `--color-paper-3`（悬停、开关底）
- 文字：`--color-ink`（标题）/ `--color-ink-2`（正文）/ `--color-muted`（元数据、label）
- 线：`--color-rule`（分隔线）/ `--color-rule-2`（控件描边）
- 语义：`--color-accent` / `--color-danger` / `--color-success` / `--color-warning` / `--color-focus`
- 几何：`--r-xs 3 / --r-sm 5 / --r 8 / --r-lg 12`、`--rail-w 236px`
- 字体：`--font-sans`（系统栈 + PingFang）、`--font-mono`（SF Mono / ui-monospace）

新增颜色先进 token，禁止在模板里写 `bg-blue-600`、`text-red-400` 这类原始色值（历史遗留点正在逐步收敛）。

## 三、组件层（直接用类名，不要重写一遍）

| 类 | 用途 |
|---|---|
| `.panel` / `.panel-head` / `.panel-body` / `.panel-title` | 唯一卡片形态。标题行 44px、下边框 1px |
| `.subpanel` | 卡片内的分组（模型选择、素材区、场景配置） |
| `.eyebrow` | 等宽大写小标签（10px / 0.18em），用于面板上的「栏目名」 |
| `.sec-title` / `.sec-num` | 区块标题（带向右延伸的发丝线）+ 序号 |
| `.label` / `.hint` | 表单标签 / 辅助说明 |
| `.field` | 所有 input / select / textarea；focus 有琥珀描边 + 3px 光晕 |
| `.check` | 复选框、单选，统一 `accent-color` |
| `.btn` + `-primary / -secondary / -ghost / -quiet / -danger`，`-sm / -xs / -block` | 按钮。primary 每屏最多 1–2 个 |
| `.chip` + `-accent / -danger / -success / -warning` | 状态徽标（等宽、大写、高 21px） |
| `.seg` / `.seg-item` | 分段控件（执行模式、生成类型）。按钮 `nowrap + flex:0 0 auto`，窄屏由 `.seg` 自身横向滚动（隐藏滚动条），禁止让按钮折行 |
| `.rail` / `.nav-item` / `.nav-num` | 左侧导航 |
| `.type-card` | 任务类型卡（选中态：琥珀左条 + 7% 底） |
| `.tl` / `.tl-item` / `.tl-dot` | 步骤时间线（is-done / is-running / is-awaiting） |
| `.meter` / `.meter-fill` / `.metric` | 进度轨与大号计量数字 |
| `.drawer` / `.drawer-head` / `.drawer-body` | 右侧抽屉（系统配置） |
| `.modal-backdrop` / `.modal` | 弹窗壳（居中、最大 85vh 内滚） |
| `.sidebar-card` | 侧栏信息块（进度页支持项目） |

兼容层：`.glass-card`、`.glass-input`、`.glow-btn`、`.tab-active/inactive` 已映射到新体系，旧代码不会断裂；新代码不要再用。

## 四、布局骨架

- **应用外壳**（`App.vue`）：`lg` 以上左侧固定导航（品牌 + 01–04 导航 + 设置 + 支持项目），内容区 `max-w-content (960px)` 居中；`lg` 以下为顶栏（品牌 + 设置）+ 横向导航条。
- **系统配置**：不再是创建页顶部的四张卡，而是右侧抽屉（`v-show` 常驻挂载，逻辑与挂载时机不变），入口为导航底部「设置」与移动端顶栏齿轮；未配置 Key 时入口带琥珀提示点。
- **进度页**（`ProgressPage.vue`）：左侧 220px 阶段时间线（sticky），右侧主栏：状态卡（44px 计量数字 + 2px 进度轨）→ 任务信息 → 按环节分组的产物 → 暂停审查 → 结果。
- **列表 / 画廊**：单一面板内用 1px 分隔线成行，不用「一行一卡」。

## 五、不要做的事

1. 不要给卡片加阴影、给按钮加渐变或发光。
2. 不要把主操作铺满一整屏（每屏一个 primary）。
3. 不要在同一个视图里混用两套状态色表达（状态一律走 `.chip-*` 语义）。
4. 不要为了好看改动交互逻辑：本次重构只动布局与样式，事件绑定、数据流、i18n key 一律保持原样。
5. 语言包新增文案要 22 种语言同步（见 `docs/dev/release_process.md`）。
