#!/usr/bin/env bash
# ============================================================
# Mock 回归测试 — 一键执行脚本
# ============================================================
# 用法:
#   ./scripts/run_mock_regression.sh           # 执行全部测试
#   ./scripts/run_mock_regression.sh simple    # 仅测试 SimpleVideo
#   ./scripts/run_mock_regression.sh creative  # 仅测试 CreativeVideo
#   ./scripts/run_mock_regression.sh clean     # 清理测试数据和报告
#   ./scripts/run_mock_regression.sh -h        # 帮助
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python"
VENV_PIP="$PROJECT_ROOT/.venv/bin/pip"
ASSTES_DIR="$PROJECT_ROOT/tests/mock_regression/assets"
FIXTURE_DIR="$PROJECT_ROOT/tests/mock_regression/fixture_data"
REPORT_DIR="$PROJECT_ROOT/tests/mock_regression/reports"
REPORT_HTML="$REPORT_DIR/report.html"

# 颜色
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }
log_step()  { echo -e "${CYAN}[STEP]${NC}  $*"; }

# ══════════════════════════════════════════════════════════════════════
# 帮助
# ══════════════════════════════════════════════════════════════════════

show_help() {
  cat << EOF
Mock 回归测试脚本 — 不调用外部接口，覆盖全流程

用法:
  $0 [command]

Commands:
  (无参数)      执行全部 mock 回归测试
  all          同上
  simple       仅测试 SimpleVideo pipeline
  creative     仅测试 CreativeVideo pipeline
  manuscript   仅测试 ManuscriptVideo pipeline
  anchor       仅测试 AnchorVideo pipeline
  resume       仅测试断点续传场景
  clean        清理所有测试生成的数据和报告（保留预制素材和 fixture）
  clean-all    清理所有测试数据 + 预制素材 + 报告
  check        检查环境（Python / ffmpeg / 依赖 / 素材）
  -h, --help   显示此帮助

示例:
  $0                          # 全量回归
  $0 creative                 # 只测创意视频
  $0 clean                    # 清理临时数据
EOF
}

# ══════════════════════════════════════════════════════════════════════
# 环境检查
# ══════════════════════════════════════════════════════════════════════

check_env() {
  log_step "检查环境..."
  local ok=true

  if ! "$VENV_PYTHON" --version &>/dev/null; then
    log_error "venv Python 不可用: $VENV_PYTHON"
    ok=false
  else
    log_info "Python: $("$VENV_PYTHON" --version 2>&1)"
  fi

  if command -v ffmpeg &>/dev/null; then
    log_info "ffmpeg: $(ffmpeg -version 2>&1 | head -1)"
  else
    log_error "ffmpeg 未安装"
    ok=false
  fi

  for pkg in pytest pytest_asyncio pytest_html; do
    if ! "$VENV_PYTHON" -c "import ${pkg}" &>/dev/null; then
      log_warn "${pkg} 未安装，正在安装..."
      "$VENV_PIP" install "${pkg//_/-}" -q
    fi
  done
  log_info "pytest 相关依赖: OK"

  for asset in test_video_5s.mp4 test_image.png; do
    if [ -f "$ASSTES_DIR/$asset" ]; then
      log_info "素材: $asset ($(wc -c < "$ASSTES_DIR/$asset" | tr -d ' ') bytes)"
    else
      log_error "素材缺失: $asset"
      ok=false
    fi
  done

  local f_count=$(ls "$FIXTURE_DIR"/*.{json,txt} 2>/dev/null | wc -l | tr -d ' ')
  if [ "$f_count" -ge 8 ]; then
    log_info "Fixture: ${f_count} 个文件"
  else
    log_error "Fixture 不足: ${f_count} (>= 8)"
    ok=false
  fi

  if $ok; then
    log_info "✅ 环境检查通过"
  else
    log_error "❌ 环境检查未通过"
    exit 1
  fi
}

# ══════════════════════════════════════════════════════════════════════
# 生成预制素材
# ══════════════════════════════════════════════════════════════════════

generate_assets() {
  log_step "检查预制素材..."

  if [ ! -f "$ASSTES_DIR/test_video_5s.mp4" ]; then
    log_warn "生成 test_video_5s.mp4..."
    ffmpeg -y -f lavfi -i "testsrc=duration=5:size=768x1152:rate=30" \
      -f mp4 "$ASSTES_DIR/test_video_5s.mp4" 2>/dev/null
  fi

  if [ ! -f "$ASSTES_DIR/test_image.png" ]; then
    log_warn "生成 test_image.png..."
    if [ -f "$PROJECT_ROOT/test_ref.png" ]; then
      cp "$PROJECT_ROOT/test_ref.png" "$ASSTES_DIR/test_image.png"
    else
      ffmpeg -y -f lavfi -i "color=c=blue:size=768x1152:r=1" \
        -frames:v 1 "$ASSTES_DIR/test_image.png" 2>/dev/null
    fi
  fi

  log_info "✅ 预制素材就绪"
}

# ══════════════════════════════════════════════════════════════════════
# 执行测试
# ══════════════════════════════════════════════════════════════════════

run_tests() {
  local filter="${1:-all}"
  local test_path="$PROJECT_ROOT/tests/mock_regression/test_pipelines.py"

  mkdir -p "$REPORT_DIR"

  # 构建 pytest 参数
  local pytest_args=(
    "$test_path"
    "-o" "addopts=-ra -q"
    -v --tb=short --color=yes
    "--html=$REPORT_HTML" "--self-contained-html"
    "-p" "no:warnings"
  )

  case "$filter" in
    all)      ;;
    simple)   pytest_args+=(-k "TestSimpleVideoPipeline") ;;
    creative) pytest_args+=(-k "TestCreativeVideoPipeline") ;;
    manuscript) pytest_args+=(-k "TestManuscriptVideoPipeline") ;;
    anchor)   pytest_args+=(-k "TestAnchorVideoPipeline") ;;
    poetry)   pytest_args+=(-k "TestPoetryVideoPipeline") ;;
    resume)   pytest_args+=(-k "TestPipelineResume") ;;
    *)        log_warn "未知过滤: $filter，执行全部";;
  esac

  log_step "执行 Mock 回归测试..."
  echo ""

  cd "$PROJECT_ROOT"
  local start_time=$(date +%s)

  if "$VENV_PYTHON" -m pytest "${pytest_args[@]}" 2>&1; then
    local end_time=$(date +%s)
    local elapsed=$((end_time - start_time))
    echo ""
    log_info "============================================="
    log_info "  ✅ 全部测试通过!  耗时: ${elapsed}s"
    log_info "  📊 HTML 报告: $REPORT_HTML"
    log_info "============================================="
    return 0
  else
    local end_time=$(date +%s)
    local elapsed=$((end_time - start_time))
    echo ""
    log_error "============================================="
    log_error "  ❌ 测试失败!  耗时: ${elapsed}s"
    log_error "  📊 HTML 报告: $REPORT_HTML"
    log_error "============================================="
    return 1
  fi
}

# ══════════════════════════════════════════════════════════════════════
# 清理
# ══════════════════════════════════════════════════════════════════════

clean_data() {
  log_step "清理测试数据和报告..."

  # 清理报告
  if [ -d "$REPORT_DIR" ]; then
    rm -rf "$REPORT_DIR"
    log_info "已清理: $REPORT_DIR"
  fi

  # 清理 __pycache__
  find "$PROJECT_ROOT/tests/mock_regression" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
  log_info "已清理: __pycache__"

  # 清理 .pytest_cache
  if [ -d "$PROJECT_ROOT/.pytest_cache" ]; then
    rm -rf "$PROJECT_ROOT/.pytest_cache"
    log_info "已清理: .pytest_cache"
  fi

  log_info "✅ 清理完成（预制素材和 fixture 已保留）"
}

clean_all() {
  log_warn "⚠️  此操作将删除所有预制素材和 fixture 数据!"
  read -rp "确认删除? (y/N) " confirm
  if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
    log_info "已取消"
    return
  fi

  clean_data

  if [ -d "$ASSTES_DIR" ]; then
    rm -rf "$ASSTES_DIR"/*
    log_info "已清理: $ASSTES_DIR"
  fi
  if [ -d "$FIXTURE_DIR" ]; then
    rm -rf "$FIXTURE_DIR"/*
    log_info "已清理: $FIXTURE_DIR"
  fi
  if [ -d "$REPORT_DIR" ]; then
    rm -rf "$REPORT_DIR"
    log_info "已清理: $REPORT_DIR"
  fi

  log_info "✅ 全部清理完成"
}

# ══════════════════════════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════════════════════════

main() {
  local cmd="${1:-all}"

  case "$cmd" in
    -h|--help)
      show_help
      ;;
    check)
      generate_assets
      check_env
      ;;
    clean)
      clean_data
      ;;
    clean-all)
      clean_all
      ;;
    all|simple|creative|manuscript|anchor|poetry|resume)
      generate_assets
      check_env
      run_tests "$cmd"
      ;;
    *)
      log_error "未知命令: $cmd"
      show_help
      exit 1
      ;;
  esac
}

main "$@"
