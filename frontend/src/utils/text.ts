// 文案工具：语言包里不少标签带前导表情（如「⚡ 一键创作」「⭐ 给个 Star」）。
// 新视觉体系用同一套线性图标接手图标位，这里统一剥掉前导符号，避免与图标重复或
// 在缺少彩色表情字体的系统上渲染成方框。
export function stripEmoji(value: string | undefined | null): string {
  if (!value) return ''
  return value.replace(/^[^\p{L}\p{N}]+/u, '').trim()
}
