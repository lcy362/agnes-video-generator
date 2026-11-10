/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          '-apple-system',
          'BlinkMacSystemFont',
          'Segoe UI',
          'PingFang SC',
          'Hiragino Sans GB',
          'Microsoft YaHei',
          'system-ui',
          'sans-serif',
        ],
        mono: [
          'SF Mono',
          'ui-monospace',
          'JetBrains Mono',
          'Menlo',
          'Consolas',
          'Liberation Mono',
          'monospace',
        ],
      },
      borderRadius: {
        // 新体系：圆角收敛，最大 12px
        DEFAULT: '8px',
        lg: '12px',
        xl: '12px',
        '2xl': '12px',
      },
      maxWidth: {
        content: '960px',
      },
    },
  },
  plugins: [],
}
