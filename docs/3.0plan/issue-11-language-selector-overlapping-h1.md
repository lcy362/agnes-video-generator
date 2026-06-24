# Bug Fix: Issue #11 — 语言选择器被 h1 遮挡

## 修复内容

在 `static/index.html` 中修复 Firefox 上语言选择器被 `<h1>` 标题遮挡无法点击的问题。

| 修改位置 | 变更 | 作用 |
|----------|------|------|
| 第 113 行 `<div class="absolute right-0 top-0">` | 添加 `style="z-index: 10;"` | 将选择器提升到最高层 |
| 第 124 行 `<h1>` | style 中添加 `position: relative; z-index: 0;` | 使 h1 参与 z-index 层叠，置于选择器下方 |

## 提交信息

- **Commit**: `edd4e3f` on `v3.0-dev`
- **Issue**: 已关闭 [#11](https://github.com/lcy362/agnes-video-generator/issues/11)
