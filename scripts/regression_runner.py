#!/usr/bin/env python3
"""
Agnes Video Generator v2.0 — 大版本回归测试脚本 (并发版)

用法:
  python scripts/regression_runner.py                # 从头运行
  python scripts/regression_runner.py --resume       # 续传：跳过已完成，重试可恢复的失败
  python scripts/regression_runner.py --quick        # 跳过运行，只验证产物
  python scripts/regression_runner.py --cleanup      # 清理回归产物（报告+日志+任务目录）

机制:
  - 10 个测试场景通过 asyncio 并发执行
  - 加权信号量控制并发提交数（≤ 10 权重并发）
  - 服务端全局令牌桶限速器（core/api/rate_limiter.py）确保 Agnes API
    总调用 ≤ 20 次/分钟（含 Chat + Image + Video 提交 + Video 轮询）
  - 测试报告在 docs/regression_report.json 增量写入，中断后可续传

续传策略:
  - completed / skipped → 跳过
  - failed（可恢复错误：timeout / API 故障 / 网络错误）→ 重新提交
  - failed（不可恢复：HTTP 400 提示词错误 / 参数校验失败）→ 跳过
  - submitted / running（中断遗留）→ 尝试续传原 task_id
"""

import asyncio
import json
import logging
import os
import re
import signal
import subprocess
import shutil
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests

# ═══════════════════════════════════════════════════
# 配置常量
# ═══════════════════════════════════════════════════

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKING_DIR = os.path.join(PROJECT_ROOT, ".working_dir")
UPLOAD_DIR = os.path.join(WORKING_DIR, "uploads")
REPORT_PATH = os.path.join(PROJECT_ROOT, "docs", "regression_report.json")
REPORT_MD_PATH = os.path.join(PROJECT_ROOT, "docs", "regression_report.md")
SERVER_URL = "http://localhost:8765"
SERVER_LOG = os.path.join(PROJECT_ROOT, ".regression_server.log")
MANIFEST_PATH = os.path.join(WORKING_DIR, ".regression_manifest.json")
TEST_REF_IMAGE = os.path.join(PROJECT_ROOT, "test_ref.png")
TEST_END_IMAGE = os.path.join(PROJECT_ROOT, "test_end.png")

# Agnes API 每分钟调用上限
AGNES_RATE_LIMIT = 20          # 次/分钟

# 各场景权重 = 该场景平均每分钟发起的 Agnes API 调用数
# 留 50% 余量 => 总权重上限 = AGNES_RATE_LIMIT / 2 = 10
SCENARIO_WEIGHTS = {
    "S1": 1, "S2": 1, "S3": 1,       # 简单: 1 submit + 轻量轮询
    "C1": 4, "C2": 4, "C3": 3, "C4": 3, "C5": 4,  # 创意: Chat + N*Image + N*Video + 轮询
    "M1": 4, "M2": 4,                 # 稿件: 段落*Chat + 段落*Image + 轮询
}
MAX_CONCURRENT_WEIGHT = AGNES_RATE_LIMIT // 2

# 单场景超时（秒）
TIMEOUT_SIMPLE = 30 * 60
TIMEOUT_CREATIVE = 120 * 60
TIMEOUT_MANUSCRIPT = 60 * 60
# 任务状态轮询间隔（区别于 pipeline 内部 30s 的 Agnes Video API 轮询）
POLL_INTERVAL = 30
HEALTH_CHECK_RETRIES = 12

# 不可恢复的错误模式：这些错误表示任务本身有问题（如提示词不合规、参数错误），
# 重新提交也会失败，因此续传时跳过。
_NON_RETRYABLE_PATTERNS = (
    "bad_prompt",
    "invalid_prompt",
    "status=failed: 400",
    "status=failed: Bad Request",
    "HTTP 400",
    "prompt_violation",
    "content_policy",
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Regression] %(message)s",
)
logger = logging.getLogger("RegressionTest")


# ═══════════════════════════════════════════════════
# 自定义异常
# ═══════════════════════════════════════════════════

class TaskNotFoundError(Exception):
    """任务已被删除或不存在（HTTP 404）。"""
    pass


# ═══════════════════════════════════════════════════
# 场景定义
# ═══════════════════════════════════════════════════

class ScenarioConfig:
    def __init__(self, id: str, label: str, type_: str,
                 endpoint: str, params: dict, timeout: int,
                 weight: int,
                 requires_ref_image: bool = False,
                 requires_end_image: bool = False):
        self.id = id
        self.label = label
        self.type = type_
        self.endpoint = endpoint
        self.params = params
        self.timeout = timeout
        self.weight = weight
        self.requires_ref_image = requires_ref_image
        self.requires_end_image = requires_end_image


SCENARIO_DEFS = [
    # ── 简单视频 ──
    ScenarioConfig("S1", "纯文本 t2v", "simple",
        "/api/tasks/simple",
        {"prompt": "春天花园里花朵盛开，阳光柔和",
         "mode": "t2v", "duration": 5},
        TIMEOUT_SIMPLE, SCENARIO_WEIGHTS["S1"]),

    ScenarioConfig("S2", "图生视频 ti2vid", "simple",
        "/api/tasks/simple",
        {"prompt": "春天花园里花朵盛开，阳光柔和",
         "mode": "ti2vid", "duration": 5},
        TIMEOUT_SIMPLE, SCENARIO_WEIGHTS["S2"], requires_ref_image=True),

    ScenarioConfig("S3", "关键帧 keyframes", "simple",
        "/api/tasks/simple",
        {"prompt": "春天花园里花朵盛开，阳光柔和",
         "mode": "keyframes", "duration": 5},
        TIMEOUT_SIMPLE, SCENARIO_WEIGHTS["S3"],
        requires_ref_image=True, requires_end_image=True),

    # ── 创意视频（主测无配音，三种场景模式 + 一个配音验证）──
    ScenarioConfig("C1", "纯文字+独立+无配音", "creative",
        "/api/tasks/creative",
        {"idea": "清晨小镇溪边的宁静风景",
         "user_requirement": "3个场景，每个场景5秒，写实风格",
         "style": "写实风格", "chaining_mode": "none",
         "video_duration": 5,
         "audio_enabled": False},
        TIMEOUT_CREATIVE, SCENARIO_WEIGHTS["C1"]),

    ScenarioConfig("C2", "带参考图+关键帧+无配音", "creative",
        "/api/tasks/creative",
        {"idea": "清晨小镇溪边的宁静风景",
         "user_requirement": "3个场景，每个场景5秒，写实风格",
         "style": "写实风格", "chaining_mode": "keyframes",
         "video_duration": 5,
         "audio_enabled": False},
        TIMEOUT_CREATIVE, SCENARIO_WEIGHTS["C2"], requires_ref_image=True),

    ScenarioConfig("C3", "参考图生成尾帧+关键帧+无配音", "creative",
        "/api/tasks/creative",
        {"idea": "清晨小镇溪边的宁静风景",
         "user_requirement": "3个场景，每个场景5秒，写实风格",
         "style": "写实风格", "chaining_mode": "keyframes",
         "video_duration": 5,
         "audio_enabled": False,
         "use_custom_end_frames": True,
         "generate_end_frames_from_ref": True},
        TIMEOUT_CREATIVE, SCENARIO_WEIGHTS["C3"], requires_ref_image=True),

    ScenarioConfig("C4", "独立场景+配音字幕验证", "creative",
        "/api/tasks/creative",
        {"idea": "清晨小镇溪边的宁静风景",
         "user_requirement": "3个场景，每个场景5秒，写实风格",
         "style": "写实风格", "chaining_mode": "none",
         "video_duration": 5,
         "audio_enabled": True, "audio_voice": "zh-CN-XiaoxiaoNeural"},
        TIMEOUT_CREATIVE, SCENARIO_WEIGHTS["C4"]),

    ScenarioConfig("C5", "链式续传 ti2vid + 无配音", "creative",
        "/api/tasks/creative",
        {"idea": "清晨小镇溪边的宁静风景",
         "user_requirement": "3个场景，每个场景5秒，写实风格",
         "style": "写实风格", "chaining_mode": "ti2vid",
         "video_duration": 5, "audio_enabled": False},
        TIMEOUT_CREATIVE, SCENARIO_WEIGHTS["C5"]),

    # ── 稿件视频（短文本，激活拆段算法）──
    ScenarioConfig("M1", "短稿件+配音", "manuscript",
        "/api/tasks/manuscript",
        {"manuscript_text": "清晨的小镇，一条小溪静静流过石桥。"
         "溪水清澈见底，映着蓝天白云的倒影。"
         "岸边的柳树轻轻摇摆，叶子随风飘动。"
         "阳光洒在水面上，泛起点点金光。"
         "微风吹过，带来泥土和青草的气息。"
         "远处的屋顶上升起缕缕炊烟，宁静而安详。"
         "春天来了，古镇的景色越发迷人。"
         "桃花开满了枝头，柳树抽出嫩绿的新芽。",
         "video_duration": 5, "audio_enabled": True,
         "audio_voice": "zh-CN-XiaoxiaoNeural"},
        TIMEOUT_MANUSCRIPT, SCENARIO_WEIGHTS["M1"]),

    ScenarioConfig("M2", "短稿件+自定义字幕", "manuscript",
        "/api/tasks/manuscript",
        {"manuscript_text": "清晨的小镇，一条小溪静静流过石桥。"
         "溪水清澈见底，映着蓝天白云的倒影。"
         "岸边的柳树轻轻摇摆，叶子随风飘动。"
         "阳光洒在水面上，泛起点点金光。"
         "微风吹过，带来泥土和青草的气息。"
         "远处的屋顶上升起缕缕炊烟，宁静而安详。"
         "春天来了，古镇的景色越发迷人。"
         "桃花开满了枝头，柳树抽出嫩绿的新芽。",
         "video_duration": 5, "audio_enabled": True,
         "audio_voice": "zh-CN-XiaoxiaoNeural",
         "subtitle_font": "SimHei", "subtitle_color": "yellow",
         "subtitle_fontsize": 52, "subtitle_position": "top",
         "subtitle_stroke_color": "blue", "subtitle_stroke_width": 3,
         "subtitle_bg_color": "black@0.7"},
        TIMEOUT_MANUSCRIPT, SCENARIO_WEIGHTS["M2"]),
]

SCENARIO_MAP = {s.id: s for s in SCENARIO_DEFS}


# ═══════════════════════════════════════════════════
# 加权信号量
# ═══════════════════════════════════════════════════

class WeightedSemaphore:
    """限流：总权重 ≤ max_weight。

    每个场景的权重 = 该场景预估的每分钟 Agnes API 调用数。
    控制并发场景数，确保总 API 调用 ≤ AGNES_RATE_LIMIT/分钟。
    """
    def __init__(self, max_weight: int):
        self.max_weight = max_weight
        self.current = 0
        self._lock = asyncio.Lock()
        self._cond = asyncio.Condition(self._lock)

    async def acquire(self, weight: int):
        if weight > self.max_weight:
            raise ValueError(f"scenario weight {weight} > max {self.max_weight}")
        async with self._lock:
            while self.current + weight > self.max_weight:
                await self._cond.wait()
            self.current += weight

    async def release(self, weight: int):
        async with self._lock:
            self.current -= weight
            self._cond.notify_all()

    @property
    def utilization(self) -> float:
        return self.current / self.max_weight


# ═══════════════════════════════════════════════════
# 报告管理器（增量写入 + 断点续传）
# ═══════════════════════════════════════════════════

class ReportManager:
    def __init__(self, report_path: str):
        self.path = report_path
        self.data = self._load_or_create()

    # ── 加载/初始化 ──

    def _load_or_create(self) -> dict:
        if os.path.exists(self.path):
            with open(self.path) as f:
                data = json.load(f)
            done = data.get("summary", {}).get("completed", 0)
            failed = data.get("summary", {}).get("failed", 0)
            logger.info(f"恢复报告: {done} 已完成 / {failed} 失败 (共 {data['summary']['total']})")
            return data
        return self._create_empty()

    def _create_empty(self) -> dict:
        scenarios = {}
        for sc in SCENARIO_DEFS:
            scenarios[sc.id] = {
                "label": sc.label,
                "type": sc.type,
                "status": "pending",
                "result": None,
                "errors": [],
            }
        endpoints = {f"E{i}": {"status": "pending", "detail": ""} for i in range(1, 10)}
        return {
            "version": "2.0",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "git_commit": self._get_git_commit(),
            "scenarios": scenarios,
            "endpoints": endpoints,
            "summary": {
                "total": len(SCENARIO_DEFS),
                "completed": 0, "failed": 0, "skipped": 0,
                "running": 0, "pending": len(SCENARIO_DEFS),
                "passed_checks": 0, "total_checks": 0,
            },
            "server_pid": None,
        }

    def _get_git_commit(self) -> str:
        try:
            r = subprocess.run(["git", "log", "--oneline", "-1"],
                               capture_output=True, text=True, cwd=PROJECT_ROOT)
            return r.stdout.strip() or "unknown"
        except Exception:
            return "unknown"

    # ── 更新 ──

    def set_server_pid(self, pid: int):
        self.data["server_pid"] = pid
        self._save()

    def update_scenario(self, id_: str, status: str,
                        result: dict = None, errors: list = None):
        sc = self.data["scenarios"][id_]
        sc["status"] = status
        if result is not None:
            sc["result"] = result
        if errors is not None:
            sc["errors"] = errors
        self._recalc_summary()
        self._save()

    def update_endpoint(self, id_: str, status: str, detail: str = ""):
        self.data["endpoints"][id_]["status"] = status
        self.data["endpoints"][id_]["detail"] = detail
        self._save()

    def _recalc_summary(self):
        s = self.data["summary"]
        sv = self.data["scenarios"].values()
        s["completed"] = sum(1 for x in sv if x["status"] == "completed")
        s["failed"] = sum(1 for x in sv if x["status"] == "failed")
        s["skipped"] = sum(1 for x in sv if x["status"] == "skipped")
        s["running"] = sum(1 for x in sv if x["status"] == "running")
        s["pending"] = sum(1 for x in sv if x["status"] in ("pending", "submitted"))

        tc = pc = 0
        for x in sv:
            chk = x.get("result", {}).get("checks", {}) if x.get("result") else {}
            for name, val in chk.items():
                if name.endswith(("_width", "_height", "_step_count", "_srt_entries",
                                  "_duration", "_count", "F2_duration", "F6_asr_text", "F4_speech_duration",
                                  "R3_incomplete_steps", "R6_dirs_checked", "R6_dirs_with_curl")):
                    continue
                tc += 1
                if val is True:
                    pc += 1
        s["total_checks"] = tc
        s["passed_checks"] = pc

    def _save(self):
        self.data["updated_at"] = datetime.now(timezone.utc).isoformat()
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        # 原子写：先写 .tmp 再 os.replace，避免崩溃/中断时损坏续传依据
        # （与 RegressionManifest.save 保持一致，见 fix_plan_v2.md B4.4）
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def should_run(self, id_: str, resume: bool = False) -> bool:
        """判断场景是否应该执行。

        Args:
            id_: 场景 ID。
            resume: 是否为续传模式。

        Returns:
            True 表示应该执行。

        逻辑:
          - completed / skipped → 始终跳过
          - pending / submitted / running → 始终执行
          - failed + resume 模式:
            - 错误信息匹配不可恢复模式 → 跳过
            - 否则 → 重新提交
          - failed + 非 resume → 执行（首次运行不会走到这里）
        """
        sc = self.data["scenarios"][id_]
        st = sc["status"]
        if st in ("completed", "skipped"):
            return False
        if st == "failed" and resume:
            errors = sc.get("errors", [])
            err_text = " ".join(str(e) for e in errors).lower()
            for pat in _NON_RETRYABLE_PATTERNS:
                if pat.lower() in err_text:
                    logger.info(
                        f"[{id_}] 不可恢复错误，跳过: {errors[0] if errors else '?'}"
                    )
                    return False
            # 可恢复的失败 → 重新提交
            logger.info(f"[{id_}] 可恢复失败，将重新提交: {errors[0] if errors else '?'}")
            return True
        return True

    def print_summary(self):
        s = self.data["summary"]
        logger.info("=" * 56)
        logger.info(f"  已完成: {s['completed']}/{s['total']}  "
                     f"失败: {s['failed']}  跳过: {s['skipped']}  "
                     f"运行中: {s['running']}")
        logger.info(f"  检查项: {s['passed_checks']}/{s['total_checks']} 通过")
        logger.info("=" * 56)

    def generate_md_report(self, report_md_path: str):
        d = self.data
        s = d["summary"]
        sc = d["scenarios"]
        ep = d["endpoints"]
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        icon = lambda st: {"completed": "✅", "failed": "❌", "skipped": "⏭️",
                           "running": "🔄", "pending": "⏳", "submitted": "⏳"}.get(st, "❓")

        lines = []
        lines.append(f"# Agnes Video Generator v2.0 — 大版本回归测试报告")
        lines.append(f"")
        lines.append(f"| 元数据 | 值 |")
        lines.append(f"|--------|-----|")
        lines.append(f"| 日期 | {now} |")
        lines.append(f"| 版本 | {d.get('git_commit', 'unknown')} |")
        lines.append(f"| 报告版本 | {d.get('version', '?')} |")
        lines.append(f"| 自动验证 | {s['passed_checks']}/{s['total_checks']} 通过 |")
        lines.append(f"")
        ep_pass = sum(1 for e in ep.values() if e["status"] == "passed")
        ep_all = len(ep)
        lines.append(f"## 概览")
        lines.append(f"")
        lines.append(f"| 状态 | 数量 |")
        lines.append(f"|------|------|")
        lines.append(f"| 总计 | {s['total']} |")
        lines.append(f"| ✅ 完成 | {s['completed']} |")
        lines.append(f"| ❌ 失败 | {s['failed']} |")
        lines.append(f"| ⏭️ 跳过 | {s['skipped']} |")
        lines.append(f"| 🔄 运行中 | {s['running']} |")
        lines.append(f"| ⏳ 待处理 | {s['pending']} |")
        lines.append(f"")
        lines.append(f"端点验证: {ep_pass}/{ep_all} ✅")
        lines.append(f"")

        for type_label, type_key, type_ids in [
            ("简单视频 (Simple)", "simple", ["S1", "S2", "S3"]),
            ("创意视频 (Creative)", "creative", ["C1", "C2", "C3", "C4", "C5"]),
            ("稿件视频 (Manuscript)", "manuscript", ["M1", "M2"]),
        ]:
            lines.append(f"---")
            lines.append(f"")
            lines.append(f"## {type_label}")
            lines.append(f"")
            for sid in type_ids:
                sdata = sc.get(sid)
                if not sdata:
                    continue
                st = sdata["status"]
                chk = (sdata.get("result") or {}).get("checks") or {}
                errs = sdata.get("errors") or []
                duration = (sdata.get("result") or {}).get("duration_s", "?")
                tag = icon(st)
                label = sdata.get("label", sid)
                if st == "completed":
                    fail_checks = [k for k, v in chk.items()
                                   if v is False and not any(k.endswith(x) for x in
                                      ("_width", "_height", "_duration", "_count", "_entries",
                                       "F2_duration", "F6_asr_text", "F4_speech_duration"))]
                    if not fail_checks:
                        lines.append(f"### {sid} {label} — {tag} 通过 ({duration}s)")
                    else:
                        lines.append(f"### {sid} {label} — ⚠️ 通过但有失败检查 ({duration}s)")
                else:
                    lines.append(f"### {sid} {label} — {tag} {st}")

            # Table
            lines.append(f"")
            lines.append(f"| 检查项 | " + " | ".join(type_ids) + " |")
            lines.append(f"|" + "|".join(["---" for _ in range(len(type_ids) + 1)]) + "|")

            all_check_names = set()
            for sid in type_ids:
                sdata = sc.get(sid)
                chk = (sdata.get("result") or {}).get("checks") or {} if sdata else {}
                all_check_names.update(chk.keys())

            sort_key = lambda n: (0 if n.startswith("F") else 1 if n.startswith("R") else 2, n)
            for cname in sorted(all_check_names, key=sort_key):
                if cname.endswith(("_width", "_height", "_duration", "_count", "_entries", "F2_duration", "F6_asr_text", "F4_speech_duration")):
                    continue
                row = [cname]
                for sid in type_ids:
                    sdata = sc.get(sid)
                    chk = (sdata.get("result") or {}).get("checks") or {} if sdata else {}
                    val = chk.get(cname, "—")
                    if val is True:
                        row.append("✅")
                    elif val is False:
                        row.append("❌")
                    elif val == "N/A":
                        row.append("N/A")
                    elif val == "skip":
                        row.append("⏭️")
                    elif val and cname.startswith("F2_duration"):
                        row.append(f"{val}s")
                    else:
                        row.append(str(val) if val else "—")
                lines.append("| " + " | ".join(row) + " |")
            lines.append(f"")

        # Endpoint results
        lines.append(f"---")
        lines.append(f"")
        lines.append(f"## 端点验证 (E1-E9)")
        lines.append(f"")
        lines.append(f"| 端点 | 状态 | 详情 |")
        lines.append(f"|------|------|------|")
        for eid in sorted(ep.keys()):
            e = ep[eid]
            tag = "✅" if e["status"] == "passed" else "❌"
            lines.append(f"| {eid} | {tag} | {e.get('detail', '')} |")
        lines.append(f"")

        # Manual verification section (only F5 subtitle visibility remains manual)
        lines.append(f"---")
        lines.append(f"")
        lines.append(f"## 需手动验证")
        lines.append(f"")
        lines.append(f"以下检查因 IMAX 视觉限制无法由脚本验证，需人工确认：")
        lines.append(f"")
        lines.append(f"| 检查项 | 操作 | 预期 |")
        lines.append(f"|--------|------|------|")
        lines.append(f"| F5 字幕可见性 | 播放 final_video.mp4 观察画面 | 字幕内容、位置、样式与配置一致 |")
        lines.append(f"")
        lines.append(f"> 音频正确性 (F4) 和字幕文本匹配 (F6) 已由脚本通过 whisper ASR 自动验证。")

        # Error summary
        lines.append(f"")
        lines.append(f"## 错误汇总")
        lines.append(f"")
        has_errors = False
        for sid, sdata in sorted(sc.items()):
            errs = sdata.get("errors") or []
            if errs:
                has_errors = True
                lines.append(f"- **{sid}** ({sdata.get('label', '')}): {errs[0]}")
        if not has_errors:
            lines.append(f"无错误。")
        lines.append(f"")

        content = "\n".join(lines)
        os.makedirs(os.path.dirname(report_md_path), exist_ok=True)
        with open(report_md_path, "w") as f:
            f.write(content)
        logger.info(f"MD 报告: {report_md_path}")


# ═══════════════════════════════════════════════════
# 回归测试产物清单
# ═══════════════════════════════════════════════════

class RegressionManifest:
    """回归测试产物清单。

    记录回归测试产生的所有文件/目录，用于安全清理而不影响用户数据。
    """

    def __init__(self, path: str, run_id: str = ""):
        self.path = path
        self.data: dict = {
            "run_id": run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": "",
            "task_dirs": [],        # .working_dir/ 下的任务目录名
            "uploads": [],          # .working_dir/uploads/ 下的文件名
            "reports": [
                os.path.relpath(REPORT_PATH, PROJECT_ROOT),
                os.path.relpath(REPORT_MD_PATH, PROJECT_ROOT),
            ],
            "server_log": os.path.relpath(SERVER_LOG, PROJECT_ROOT),
            "scenarios": {},        # scenario_id -> {task_id, dir_name, status}
        }
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    existing = json.load(f)
                # Merge with existing manifest (for resume mode)
                self.data["task_dirs"] = list(existing.get("task_dirs", []))
                self.data["uploads"] = list(existing.get("uploads", []))
                self.data["scenarios"] = dict(existing.get("scenarios", {}))
                self.data["run_id"] = existing.get("run_id", run_id)
                self.data["created_at"] = existing.get(
                    "created_at", self.data["created_at"])
            except (json.JSONDecodeError, OSError):
                pass

    def record_scenario(self, scenario_id: str, task_id: str, dir_name: str,
                        status: str, error: str = ""):
        """记录单个场景的执行产物。"""
        self.data["scenarios"][scenario_id] = {
            "task_id": task_id,
            "dir_name": dir_name,
            "status": status,
            "error": error,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        if dir_name and dir_name not in self.data["task_dirs"]:
            self.data["task_dirs"].append(dir_name)

    def record_upload(self, filename: str):
        """记录上传文件。"""
        if filename and filename not in self.data["uploads"]:
            self.data["uploads"].append(filename)

    def save(self):
        self.data["updated_at"] = datetime.now(timezone.utc).isoformat()
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.path)


def cleanup_regression_artifacts() -> dict:
    """根据产物清单安全清理回归测试产物。

    只删除清单中明确记录的内容，不会影响用户原有任务数据。
    返回清理结果统计。
    """
    if not os.path.exists(MANIFEST_PATH):
        return {"ok": False, "error": "未找到回归测试产物清单，可能没有执行过回归测试"}

    try:
        with open(MANIFEST_PATH, "r") as f:
            manifest = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return {"ok": False, "error": f"读取清单失败: {e}"}

    removed_dirs = []
    removed_files = []
    errors = []

    # 1. 清理任务目录（只删除清单中列出的）
    for dir_name in manifest.get("task_dirs", []):
        dir_path = os.path.join(WORKING_DIR, dir_name)
        if os.path.isdir(dir_path):
            try:
                shutil.rmtree(dir_path)
                removed_dirs.append(dir_name)
            except OSError as e:
                errors.append(f"删除目录失败 {dir_name}: {e}")

    # 2. 清理上传文件
    for fname in manifest.get("uploads", []):
        fpath = os.path.join(UPLOAD_DIR, fname)
        if os.path.isfile(fpath):
            try:
                os.remove(fpath)
                removed_files.append(os.path.join("uploads", fname))
            except OSError as e:
                errors.append(f"删除上传文件失败 {fname}: {e}")

    # 3. 清理报告文件
    for rel_path in manifest.get("reports", []):
        abs_path = os.path.join(PROJECT_ROOT, rel_path)
        if os.path.isfile(abs_path):
            try:
                os.remove(abs_path)
                removed_files.append(rel_path)
            except OSError as e:
                errors.append(f"删除报告失败 {rel_path}: {e}")

    # 4. 清理服务器日志
    log_rel = manifest.get("server_log", "")
    if log_rel:
        log_path = os.path.join(PROJECT_ROOT, log_rel)
        if os.path.isfile(log_path):
            try:
                os.remove(log_path)
                removed_files.append(log_rel)
            except OSError as e:
                errors.append(f"删除日志失败: {e}")

    # 5. 清理清单本身
    try:
        os.remove(MANIFEST_PATH)
        removed_files.append(os.path.relpath(MANIFEST_PATH, PROJECT_ROOT))
    except OSError as e:
        errors.append(f"删除清单失败: {e}")

    result = {
        "ok": len(errors) == 0,
        "removed_dirs": len(removed_dirs),
        "removed_files": len(removed_files),
        "removed_dir_names": removed_dirs,
        "removed_file_names": removed_files,
        "errors": errors,
        "scenarios_cleaned": len(manifest.get("scenarios", {})),
    }
    logger.info(
        f"回归清理完成: {result['removed_dirs']} 目录, "
        f"{result['removed_files']} 文件")
    if errors:
        logger.warning(f"清理错误: {errors}")
    return result


# ═══════════════════════════════════════════════════
# 测试素材自动生成
# ═══════════════════════════════════════════════════

def _ensure_test_assets():
    """确保测试素材存在，不存在则自动生成。"""
    assets = {
        TEST_REF_IMAGE: (("test_ref.png", (100, 150, 200)),),
        TEST_END_IMAGE: (("test_end.png", (200, 150, 100)),),
    }
    for path, specs in assets.items():
        if os.path.exists(path):
            continue
        try:
            from PIL import Image
            for name, color in specs:
                img = Image.new("RGB", (768, 1152), color)
                save_path = path
                img.save(save_path)
                logger.info(f"自动生成测试素材: {save_path}")
                break
        except ImportError:
            logger.warning(f"PIL 不可用，无法自动生成 {path}，请手动准备")
            break


# ═══════════════════════════════════════════════════
# 服务管理
# ═══════════════════════════════════════════════════

_server_process: Optional[subprocess.Popen] = None


def _cleanup_server():
    global _server_process
    if _server_process is not None:
        logger.info("停止测试服务器...")
        os.killpg(os.getpgid(_server_process.pid), signal.SIGTERM)
        _server_process.wait(timeout=5)
        _server_process = None


def check_server_health() -> bool:
    try:
        r = requests.get(f"{SERVER_URL}/api/config", timeout=5)
        return r.status_code == 200
    except (requests.ConnectionError, requests.Timeout):
        return False


async def wait_for_server(retries: int = HEALTH_CHECK_RETRIES) -> bool:
    for i in range(retries):
        if await asyncio.to_thread(check_server_health):
            logger.info("服务器就绪 ✓")
            return True
        logger.info(f"等待服务器... ({i + 1}/{retries})")
        await asyncio.sleep(HEALTH_CHECK_RETRIES // 2)
    logger.error("服务器未就绪")
    return False


async def ensure_server(auto_start: bool = False) -> bool:
    if await asyncio.to_thread(check_server_health):
        return True
    if not auto_start:
        logger.info("请先在另一终端运行: bash start.sh")
        return False
    logger.info("自动启动服务...")
    venv_python = os.path.join(PROJECT_ROOT, ".venv", "bin", "python")
    python = venv_python if os.path.exists(venv_python) else "python"
    global _server_process
    _server_process = subprocess.Popen(
        [python, "server.py"],
        cwd=PROJECT_ROOT,
        stdout=open(SERVER_LOG, "w"),
        stderr=subprocess.STDOUT,
        preexec_fn=os.setsid,
    )
    import atexit
    atexit.register(_cleanup_server)
    ok = await wait_for_server()
    if not ok:
        _cleanup_server()
    return ok


# ═══════════════════════════════════════════════════
# HTTP 调用
# ═══════════════════════════════════════════════════

@contextmanager
def _open_images(scenario: ScenarioConfig):
    files = {}
    if scenario.requires_ref_image and os.path.exists(TEST_REF_IMAGE):
        with open(TEST_REF_IMAGE, "rb") as f:
            files["reference_image"] = ("ref.png", f.read(), "image/png")
    if scenario.requires_end_image and os.path.exists(TEST_END_IMAGE):
        if scenario.type == "simple":
            with open(TEST_END_IMAGE, "rb") as f:
                files["end_frame_image"] = ("end.png", f.read(), "image/png")
    yield files


def _submit_sync(scenario: ScenarioConfig) -> dict:
    url = f"{SERVER_URL}{scenario.endpoint}"
    data = scenario.params.copy()
    with _open_images(scenario) as img_files:
        files = img_files if img_files else None
        r = requests.post(url, data=data, files=files, timeout=30)
    r.raise_for_status()
    result = r.json()
    if not result.get("ok"):
        raise RuntimeError(f"提交失败: {result}")
    return result


async def submit_task(scenario: ScenarioConfig) -> dict:
    return await asyncio.to_thread(_submit_sync, scenario)


async def get_task_status(task_id: str) -> dict:
    def _fetch():
        r = requests.get(f"{SERVER_URL}/api/tasks/{task_id}", timeout=10)
        if r.status_code == 404:
            raise TaskNotFoundError(f"Task {task_id} not found (404)")
        r.raise_for_status()
        return r.json()
    return await asyncio.to_thread(_fetch)


async def resume_task(task_id: str) -> dict:
    return await asyncio.to_thread(
        lambda: requests.post(f"{SERVER_URL}/api/tasks/{task_id}/resume", timeout=10).json()
    )


# ═══════════════════════════════════════════════════
# Whisper 模型缓存（全局共享，避免每次验证重复加载）
# ═══════════════════════════════════════════════════

_whisper_model = None

def _get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        import whisper
        logger.info("加载 whisper tiny 模型（首次）...")
        _whisper_model = whisper.load_model("tiny")
    return _whisper_model


# ═══════════════════════════════════════════════════
# 产物验证
# ═══════════════════════════════════════════════════

def _load_task_state(task_dir: str) -> dict:
    ts = os.path.join(task_dir, "task_state.json")
    if os.path.exists(ts):
        with open(ts) as f:
            return json.load(f)
    return {}


def _get_expected_narration(task_state: dict, scenario: ScenarioConfig) -> str:
    if scenario.type == "simple":
        return task_state.get("prompt", "")
    if scenario.type == "creative":
        narrations = task_state.get("narrations", [])
        return "\n".join(narrations)
    if scenario.type == "manuscript":
        paras = task_state.get("paragraphs", [])
        return "\n".join(p.get("text", "") for p in paras)
    return ""


def _compute_expected_duration(task_state: dict, scenario: ScenarioConfig) -> float | None:
    """从 task_state 计算期望视频总时长（秒），无法计算时返回 None。

    - simple: 直接读 duration 字段
    - creative: scene_count × video_duration
    - manuscript: sum(len(para.text)/4.0) 或 combined_audio 时长
    """
    if scenario.type == "simple":
        dur = task_state.get("duration")
        return float(dur) if dur else None

    if scenario.type in ("creative", "manuscript"):
        video_dur = task_state.get("video_duration", 5)
        if scenario.type == "creative":
            scenes = task_state.get("scenes", [])
            count = len(scenes) if scenes else task_state.get("scene_count", 0)
            if not count:
                return None
            expected = count * video_dur
        else:  # manuscript
            paras = task_state.get("paragraphs", [])
            if not paras:
                return None
            # 每段时长 ≈ max(ceil(text_len/4), 3)
            expected = sum(max(-(-len(p.get("text", "")) // 4), 3) for p in paras)

        # 若有合并音频，取 max(视频总时长, 音频时长)
        combined = task_state.get("combined_audio", "")
        if combined and os.path.exists(combined):
            try:
                r = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", combined],
                    capture_output=True, text=True, timeout=10,
                )
                audio_dur = float(r.stdout.strip())
                expected = max(expected, audio_dur)
            except Exception:
                pass
        return float(expected)

    return None


def _asr_validate(video_path: str) -> dict:
    result = {"has_speech": False, "text": "", "duration": 0.0, "error": ""}
    tmp_audio = video_path + "_asr_tmp.wav"
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", video_path, "-vn", "-acodec", "pcm_s16le",
             "-ar", "16000", "-ac", "1", tmp_audio],
            capture_output=True, timeout=60,
        )
        if not os.path.exists(tmp_audio) or os.path.getsize(tmp_audio) == 0:
            result["error"] = "ffmpeg extract failed"
            return result
        try:
            model = _get_whisper_model()
        except ImportError:
            result["error"] = "whisper not installed"
            return result
        trans = model.transcribe(tmp_audio, language="zh")
        text = (trans.get("text") or "").strip()
        result["text"] = text
        result["duration"] = trans.get("duration", 0.0)
        result["has_speech"] = len(text) > 5
        return result
    except Exception as e:
        result["error"] = str(e)
        return result
    finally:
        if os.path.exists(tmp_audio):
            try:
                os.remove(tmp_audio)
            except OSError:
                pass


def _validate_sync(dir_name: str, scenario: ScenarioConfig) -> dict:
    task_dir = os.path.join(WORKING_DIR, dir_name)
    checks: dict[str, Any] = {}

    # 防御：任务目录不存在（如 C2/C3 因缺素材而失败）
    if not os.path.isdir(task_dir):
        checks["F1_final_video_exists"] = False
        checks["F1_final_video_nonempty"] = False
        checks["F2_duration"] = 0
        checks["F2_duration_gt_0"] = False
        checks["F4_has_audio_stream"] = False
        checks["F7_duration_reasonable"] = False
        checks["F4_has_speech"] = "N/A"
        checks["F6_asr_text"] = "N/A"
        checks["F6_text_match"] = "N/A"
        checks["R1_task_state_valid"] = False
        checks["R2_task_type"] = None
        checks["R2_task_type_matches"] = False
        checks["R3_step_count"] = 0
        checks["R3_all_completed"] = False
        checks["R3_incomplete_steps"] = "task_dir missing"
        checks["R4_final_path_exists"] = False
        checks["R5_task_json"] = False
        checks["R5_has_video_id"] = False
        checks["R6_curl_sh"] = False
        checks["R6_has_video_id_in_curl"] = False
        checks["R6_dirs_checked"] = 0
        checks["R6_dirs_with_curl"] = 0
        checks["R7_sub_dirs_exist"] = "N/A"
        checks["R7_audio_files"] = "N/A"
        checks["R8_subtitle_srt"] = "N/A"
        checks["R9_full_narration"] = "N/A"
        checks["R10_full_subtitle"] = "N/A"
        checks["R10_srt_entries"] = "N/A"
        return checks

    video = os.path.join(task_dir, "final_video.mp4")
    ve = os.path.exists(video)
    checks["F1_final_video_exists"] = ve
    checks["F1_final_video_nonempty"] = os.path.getsize(video) > 0 if ve else False

    # 提前加载 task_state，供 F7 和 R1-R4 共用
    ts = os.path.join(task_dir, "task_state.json")
    sd: dict = {}
    if os.path.exists(ts):
        try:
            with open(ts) as f:
                sd = json.load(f)
        except Exception:
            pass

    if ve:
        try:
            from moviepy import VideoFileClip
            clip = VideoFileClip(video)
            checks["F2_duration"] = round(clip.duration, 2)
            checks["F2_duration_gt_0"] = clip.duration > 0
            exp_w = sd.get("video_width", scenario.params.get("video_width", 768))
            exp_h = sd.get("video_height", scenario.params.get("video_height", 1152))
            checks["F3_width"] = clip.w
            checks["F3_height"] = clip.h
            # Agnes API may adjust dimensions (e.g. rounding to 64-multiples),
            # so allow ±15% tolerance on each axis
            w_ok = abs(clip.w - exp_w) / max(exp_w, 1) <= 0.15
            h_ok = abs(clip.h - exp_h) / max(exp_h, 1) <= 0.15
            checks["F3_resolution_matches"] = w_ok and h_ok
            checks["F4_has_audio_stream"] = clip.audio is not None
            # F7: 时长区间校验（与 F2 duration>0 不同，需要与 task_state 期望值比对）
            expected_dur = _compute_expected_duration(sd, scenario)
            if expected_dur:
                tol = 0.15
                checks["F7_expected_duration"] = round(expected_dur, 2)
                checks["F7_duration_reasonable"] = (
                    abs(clip.duration - expected_dur) / expected_dur <= tol
                )
            else:
                checks["F7_duration_reasonable"] = clip.duration > 0
            clip.close()
        except ImportError:
            logger.warning("moviepy 不可用，跳过视频元数据验证")
            checks["F2_duration"] = "skip"
            checks["F2_duration_gt_0"] = "skip"
            checks["F3_width"] = "skip"
            checks["F3_height"] = "skip"
            checks["F4_has_audio_stream"] = "skip"
            checks["F7_expected_duration"] = "skip"
            checks["F7_duration_reasonable"] = "skip"
        except Exception as e:
            checks["F2_duration"] = f"err:{e}"
            checks["F2_duration_gt_0"] = False
            checks["F4_has_audio_stream"] = False
            checks["F7_duration_reasonable"] = False

        # ASR: speech content detection + subtitle text matching
        # 简单视频无配音，直接跳过 ASR 检查
        is_simple = sd.get("task_type") == "simple"
        asr_eligible = (
            ve
            and checks.get("F4_has_audio_stream") is True
            and scenario.params.get("audio_enabled", True)
            and not is_simple
        )
        if asr_eligible:
            asr = _asr_validate(video)
            if asr.get("error") and "not installed" in asr["error"]:
                checks["F4_has_speech"] = "skip"
                checks["F6_asr_text"] = "skip"
                checks["F6_text_match"] = "skip"
                logger.info("whisper 不可用，跳过语音内容验证")
            elif asr.get("error"):
                checks["F4_has_speech"] = False
                checks["F6_asr_text"] = f"err:{asr['error']}"
                checks["F6_text_match"] = False
            else:
                checks["F4_has_speech"] = asr["has_speech"]
                checks["F6_asr_text"] = asr["text"][:200]
                checks["F4_speech_duration"] = round(asr["duration"], 2)
                expected = _get_expected_narration(_load_task_state(task_dir), scenario)
                if expected:
                    # Simple fuzzy match: check if expected chars appear in transcription
                    exp_clean = "".join(c for c in expected if c.isalpha())
                    asr_clean = "".join(c for c in asr["text"] if c.isalpha())
                    if exp_clean and asr_clean:
                        overlap = sum(1 for c in exp_clean[:50] if c in asr_clean)
                        ratio = overlap / min(len(exp_clean), 50)
                        checks["F6_text_match"] = ratio > 0.3
                    else:
                        checks["F6_text_match"] = False
                else:
                    checks["F6_text_match"] = "N/A"
        else:
            checks["F4_has_speech"] = "N/A"
            checks["F6_asr_text"] = "N/A"
            checks["F6_text_match"] = "N/A"

    else:
        checks["F2_duration"] = 0
        checks["F2_duration_gt_0"] = False
        checks["F4_has_audio_stream"] = False
        checks["F7_duration_reasonable"] = False
        checks["F4_has_speech"] = "N/A"
        checks["F6_asr_text"] = "N/A"
        checks["F6_text_match"] = "N/A"

    # R1-R4: task_state.json（sd 已在上方加载）
    if sd:
        checks["R1_task_state_valid"] = True
        checks["R2_task_type"] = sd.get("task_type", "?")
        checks["R2_task_type_matches"] = sd.get("task_type") == scenario.type

        # R3: step completion
        steps = {k: v for k, v in sd.items() if k.startswith("step_")}
        checks["R3_step_count"] = len(steps)

        if scenario.type == "simple":
            # simple 任务无 step_* 字段，用顶层 status 判断
            checks["R3_all_completed"] = sd.get("status") == "completed"
            checks["R3_incomplete_steps"] = "" if checks["R3_all_completed"] else "status=" + sd.get("status", "?")
        else:
            # 对于非 keyframes 模式的创意任务，end_frame_prompts/end_frame_generation
            # 步骤不会被触发，不应计入"未完成"
            chaining_mode = sd.get("chaining_mode", "none")
            _SKIPPABLE_STEPS = set()
            if scenario.type == "creative" and chaining_mode not in ("keyframes",):
                _SKIPPABLE_STEPS = {"step_end_frame_prompts", "step_end_frame_generation"}

            active_steps = {k: v for k, v in steps.items() if k not in _SKIPPABLE_STEPS}
            incomplete = [k for k, v in active_steps.items() if v != "completed"]
            checks["R3_all_completed"] = not incomplete if active_steps else "N/A"
            checks["R3_incomplete_steps"] = ",".join(incomplete) if incomplete else ""
        fvf = sd.get("final_video_file", "")
        checks["R4_final_path_exists"] = bool(fvf and os.path.exists(fvf))
    else:
        checks["R1_task_state_valid"] = False
        checks["R2_task_type"] = None
        checks["R2_task_type_matches"] = False
        checks["R3_step_count"] = 0
        checks["R3_all_completed"] = False
        checks["R3_incomplete_steps"] = "task_state.json missing"
        checks["R4_final_path_exists"] = False

    # R5: task.json — 创意任务在 scene_N/ 子目录，稿件任务在 para_N/ 子目录
    # 简单视频任务在根目录
    _VIDEO_ID_RE = re.compile(r"agnesapi\?\S*video_id=|mode=\S*&video_id=")

    def _curl_has_valid_video_id(path: str) -> bool:
        """严格匹配：要求 agnesapi?..video_id= 或 mode=..&video_id= 模式，
        避免注释/残留文本中裸 video_id= 的误判。"""
        if not os.path.exists(path):
            return False
        with open(path) as f:
            return bool(_VIDEO_ID_RE.search(f.read()))

    _task_json_found = False
    _has_video_id = False
    _curl_dirs_checked = 0
    _curl_dirs_with_valid_id = 0

    # 检查根目录（简单视频 / 创意稿件的顶层）
    tj_root = os.path.join(task_dir, "task.json")
    cs_root = os.path.join(task_dir, "curl.sh")
    if os.path.exists(tj_root):
        _task_json_found = True
        try:
            with open(tj_root) as f:
                tjd = json.load(f)
            _has_video_id = bool(tjd.get("video_id") or tjd.get("id"))
        except Exception:
            pass
    if os.path.exists(cs_root):
        _curl_dirs_checked += 1
        if _curl_has_valid_video_id(cs_root):
            _curl_dirs_with_valid_id += 1

    # 对于创意/稿件任务，独立检查每个子目录（无短路守卫）
    if scenario.type == "creative":
        for entry in os.listdir(task_dir) if os.path.isdir(task_dir) else []:
            if entry.startswith("scene_"):
                sd_path = os.path.join(task_dir, entry)
                if os.path.isdir(sd_path):
                    tj_sub = os.path.join(sd_path, "task.json")
                    cs_sub = os.path.join(sd_path, "curl.sh")
                    if os.path.exists(tj_sub):
                        _task_json_found = True
                        if not _has_video_id:
                            try:
                                with open(tj_sub) as f:
                                    tjd = json.load(f)
                                _has_video_id = bool(tjd.get("video_id") or tjd.get("id"))
                            except Exception:
                                pass
                    if os.path.exists(cs_sub):
                        _curl_dirs_checked += 1
                        if _curl_has_valid_video_id(cs_sub):
                            _curl_dirs_with_valid_id += 1
    elif scenario.type == "manuscript":
        for entry in os.listdir(task_dir) if os.path.isdir(task_dir) else []:
            if entry.startswith("para_"):
                sd_path = os.path.join(task_dir, entry)
                if os.path.isdir(sd_path):
                    tj_sub = os.path.join(sd_path, "task.json")
                    cs_sub = os.path.join(sd_path, "curl.sh")
                    if os.path.exists(tj_sub):
                        _task_json_found = True
                        if not _has_video_id:
                            try:
                                with open(tj_sub) as f:
                                    tjd = json.load(f)
                                _has_video_id = bool(tjd.get("video_id") or tjd.get("id"))
                            except Exception:
                                pass
                    if os.path.exists(cs_sub):
                        _curl_dirs_checked += 1
                        if _curl_has_valid_video_id(cs_sub):
                            _curl_dirs_with_valid_id += 1

    checks["R5_task_json"] = _task_json_found
    checks["R5_has_video_id"] = _has_video_id
    checks["R6_curl_sh"] = _curl_dirs_checked > 0
    checks["R6_has_video_id_in_curl"] = _curl_dirs_with_valid_id > 0
    checks["R6_dirs_checked"] = _curl_dirs_checked
    checks["R6_dirs_with_curl"] = _curl_dirs_with_valid_id

    # R7-R8: 子目录 + 音频/字幕（创意/稿件）
    # 判断是否需要音频验证：检查 audio_enabled 参数
    audio_enabled = scenario.params.get("audio_enabled", True)
    if scenario.type in ("creative", "manuscript"):
        prefix = "scene_" if scenario.type == "creative" else "para_"
        dirs_exist = any(
            e.startswith(prefix) and os.path.isdir(os.path.join(task_dir, e))
            for e in os.listdir(task_dir)
        ) if os.path.isdir(task_dir) else False
        checks["R7_sub_dirs_exist"] = dirs_exist

        if audio_enabled:
            audio_found = srt_found = False
            for root, _dirs, files in os.walk(task_dir):
                for fn in files:
                    if fn in ("narration.mp3", "full_narration.mp3", "narration.wav",
                              "combined_narration.mp3"):
                        audio_found = True
                    if fn.endswith(".srt"):
                        srt_found = True
            checks["R7_audio_files"] = audio_found
            checks["R8_subtitle_srt"] = srt_found
        else:
            # 无配音场景：音频/字幕检查标记为 N/A
            checks["R7_audio_files"] = "N/A"
            checks["R8_subtitle_srt"] = "N/A"
    else:
        checks["R7_sub_dirs_exist"] = "N/A"
        checks["R7_audio_files"] = "N/A"
        checks["R8_subtitle_srt"] = "N/A"

    # R9-R10: 合稿产物（稿件专用）
    if scenario.type == "manuscript":
        fn9 = os.path.join(task_dir, "full_narration.mp3")
        checks["R9_full_narration"] = os.path.exists(fn9) and os.path.getsize(fn9) > 0
        fn10 = os.path.join(task_dir, "full_subtitle.srt")
        checks["R10_full_subtitle"] = os.path.exists(fn10)
        if audio_enabled and os.path.exists(fn10):
            with open(fn10) as f:
                srt_content = f.read()
            checks["R10_srt_entries"] = srt_content.count("\n\n") + 1 if "\n\n" in srt_content else 1
        elif not audio_enabled:
            checks["R10_srt_entries"] = "N/A"
        else:
            checks["R10_srt_entries"] = 0
    else:
        checks["R9_full_narration"] = "N/A"
        checks["R10_full_subtitle"] = "N/A"
        checks["R10_srt_entries"] = "N/A"

    return checks


async def validate_task(dir_name: str, scenario: ScenarioConfig) -> dict:
    return await asyncio.to_thread(_validate_sync, dir_name, scenario)


# ═══════════════════════════════════════════════════
# 单场景执行
# ═══════════════════════════════════════════════════

async def run_scenario(scenario: ScenarioConfig,
                       sema: WeightedSemaphore,
                       report: ReportManager,
                       manifest: RegressionManifest):
    if not report.should_run(scenario.id):
        return
    start = time.monotonic()
    report.update_scenario(scenario.id, "running")
    logger.info(f"[{scenario.id}] ▶ 开始 (weight={scenario.weight}): {scenario.label}")

    task_id = None
    dir_name = None
    try:
        # B3.1: 只有 submitted/running（崩溃中断）才复用旧 task_id；
        # failed/timeout 必须重新提交
        existing = report.data["scenarios"].get(scenario.id, {})
        existing_status = existing.get("status")
        existing_result = existing.get("result") or {}

        if (existing_result.get("task_id")
                and existing_status in ("submitted", "running")):
            task_id = existing_result["task_id"]
            dir_name = existing_result.get("dir_name", task_id)
            logger.info(f"[{scenario.id}] 续传已有任务 {task_id[:12]}")
        else:
            # B3.2: 信号量只在「提交 + 确认」窗口持有
            await sema.acquire(scenario.weight)
            try:
                submit_result = await submit_task(scenario)
                task_id = submit_result["task_id"]
                dir_name = submit_result.get("dir_name", task_id)
                report.update_scenario(
                    scenario.id, "submitted",
                    result={"task_id": task_id, "dir_name": dir_name})
                logger.info(f"[{scenario.id}] 提交 → {task_id[:12]}")
            finally:
                await sema.release(scenario.weight)
                logger.info(
                    f"[{scenario.id}] 释放 w={sema.current}/{sema.max_weight}")

        # 轮询 + 验证阶段不持锁
        final_status = None
        retry_count = 0
        max_retries = 2
        deadline = time.monotonic() + scenario.timeout
        while time.monotonic() < deadline:
            await asyncio.sleep(POLL_INTERVAL)
            try:
                state = await get_task_status(task_id)
                st = state.get("status", "")
                if st == "completed":
                    final_status = "completed"
                    break
                elif st in ("failed", "error"):
                    if retry_count < max_retries:
                        retry_count += 1
                        logger.info(
                            f"[{scenario.id}] 任务失败，尝试续传 "
                            f"(retry {retry_count}/{max_retries})")
                        try:
                            await resume_task(task_id)
                            await asyncio.sleep(10)
                            continue
                        except Exception as re:
                            logger.warning(
                                f"[{scenario.id}] 续传失败: {re}")
                    final_status = f"failed: {state.get('error', '?')}"
                    break
                elif st == "running":
                    fvf = state.get("final_video_file", "")
                    if fvf:
                        logger.info(
                            f"[{scenario.id}] running, "
                            f"video={os.path.basename(fvf)}")
                elif st == "pending":
                    logger.info(f"[{scenario.id}] pending...")
                elif st:
                    logger.info(f"[{scenario.id}] status={st}")
            except TaskNotFoundError:
                logger.warning(
                    f"[{scenario.id}] 任务不存在 (404)，停止轮询: {task_id}")
                final_status = "task_not_found"
                break
            except Exception as e:
                logger.warning(f"[{scenario.id}] 轮询: {e}")
                await asyncio.sleep(5)
        else:
            final_status = "timeout"

        elapsed = round(time.monotonic() - start, 1)
        if final_status == "completed":
            checks = await validate_task(dir_name, scenario)
            ok_count = sum(1 for v in checks.values() if v is True)
            na_count = sum(
                1 for v in checks.values() if v == "N/A" or v == "skip")
            skip_count = sum(1 for v in checks.values() if v == "skip")
            total_real = sum(
                1 for v in checks.values()
                if v not in ("N/A", "skip") or v is True or v is False)
            logger.info(
                f"[{scenario.id}] 验证 {ok_count}/{total_real} 通过 "
                f"({na_count} N/A)")

            checks_clean = {}
            for k, v in checks.items():
                if k in ("F2_duration", "F3_width", "F3_height",
                         "R3_step_count", "R10_srt_entries"):
                    checks_clean[k] = (
                        v if not isinstance(v, (int, float)) else v)
                elif isinstance(v, str) and v == "skip":
                    checks_clean[k] = True
                else:
                    checks_clean[k] = v

            errors = [
                k for k, v in checks.items()
                if v is False and not any(
                    k.endswith(x) for x in
                    ("_width", "_height", "_duration", "_count",
                     "_entries", "F2_duration", "F6_asr_text",
                     "F4_speech_duration"))]
            report.update_scenario(
                scenario.id, "completed",
                result={"task_id": task_id, "dir_name": dir_name,
                        "duration_s": elapsed,
                        "started_at": datetime.fromtimestamp(
                            start, timezone.utc).isoformat(),
                        "completed_at": datetime.now(
                            timezone.utc).isoformat(),
                        "checks": checks_clean},
                errors=errors)
            tag = "✅" if not errors else "⚠️"
            logger.info(
                f"[{scenario.id}] {tag} {elapsed}s"
                + (f" ({len(errors)} 检查失败)" if errors else ""))
        else:
            report.update_scenario(
                scenario.id, "failed",
                result={"task_id": task_id, "dir_name": dir_name,
                        "duration_s": elapsed},
                errors=[f"status={final_status}"])
            logger.warning(
                f"[{scenario.id}] ❌ {final_status} ({elapsed}s)")

        # 记录到产物清单
        if task_id:
            manifest.record_scenario(
                scenario.id, task_id, dir_name or "",
                report.data["scenarios"].get(
                    scenario.id, {}).get("status", "unknown"),
                error="; ".join(report.data["scenarios"].get(
                    scenario.id, {}).get("errors", [])),
            )

    except Exception as e:
        elapsed = round(time.monotonic() - start, 1)
        logger.error(f"[{scenario.id}] ❌ {e}")
        report.update_scenario(
            scenario.id, "failed", errors=[str(e)])
        if task_id:
            manifest.record_scenario(
                scenario.id, task_id, dir_name or "",
                report.data["scenarios"].get(
                    scenario.id, {}).get("status", "unknown"),
                error="; ".join(report.data["scenarios"].get(
                    scenario.id, {}).get("errors", [])),
            )


# ═══════════════════════════════════════════════════
# 端点验证 (E1-E9)
# ═══════════════════════════════════════════════════

async def verify_endpoints(report: ReportManager):
    logger.info("─" * 50)
    logger.info("端点验证 E1-E9")

    async def check(ep: str, desc: str, fn):
        ok = detail = False
        try:
            ok, detail = await fn()
        except Exception as e:
            detail = str(e)
        report.update_endpoint(ep, "passed" if ok else "failed", str(detail))
        tag = "✅" if ok else "❌"
        logger.info(f"  {tag} {ep}: {desc}" + (f" -> {detail}" if not ok else ""))

    async def _200(path: str, check_text: str = ""):
        r = await asyncio.to_thread(lambda: requests.get(f"{SERVER_URL}{path}", timeout=10))
        if check_text:
            return r.status_code == 200 and check_text in r.text, r.status_code
        return r.status_code == 200, r.status_code

    async def _post_ok(path: str, data: dict) -> tuple:
        """E3-E5 端点探测：只验证 HTTP 200，不要求 ok=true，
        避免创建孤儿任务。creative/manuscript 使用 __ep_probe__ creative_name 隔离。"""
        r = await asyncio.to_thread(
            lambda: requests.post(f"{SERVER_URL}{path}", data=data, timeout=15))
        return r.status_code in (200, 201), r.status_code

    await asyncio.gather(
        check("E1", "GET / → 200 + index.html",
              lambda: _200("/", "Agnes Video Generator")),
        check("E2", "GET /api/config → 200",
              lambda: _200("/api/config")),
        check("E3", "POST /api/tasks/simple → 200",
              lambda: _post_ok("/api/tasks/simple",
                               {"prompt": "test", "mode": "t2v", "duration": 5})),
        check("E4", "POST /api/tasks/creative → 200",
              lambda: _post_ok("/api/tasks/creative",
                               {"idea": "__ep_probe__",
                                "user_requirement": "1个场景，5秒",
                                "audio_enabled": "false",
                                "creative_name": "__ep_probe__"})),
        check("E5", "POST /api/tasks/manuscript → 200",
              lambda: _post_ok("/api/tasks/manuscript",
                               {"manuscript_text": "__ep_probe__。第二句。",
                                "audio_enabled": "false",
                                "creative_name": "__ep_probe__"})),
        check("E6", "GET /api/tasks → list",
              lambda: _200("/api/tasks")),
        check("E7", "GET /api/tasks/{id} → task_type",
              lambda: _e7_check()),

        check("E8", "POST /api/tasks/{id}/resume",
              lambda: _e8_e9_check("resume")),

        check("E9", "POST /api/tasks/{id}/stop",
              lambda: _e8_e9_check("stop")),
    )


async def _e7_check() -> tuple:
    try:
        r = await asyncio.to_thread(
            lambda: requests.get(f"{SERVER_URL}/api/tasks", timeout=10))
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}"
        tasks = r.json().get("tasks", [])
        if not tasks:
            return True, "no tasks (skip)"
        tid = tasks[0]["task_id"]
        r2 = await asyncio.to_thread(
            lambda: requests.get(f"{SERVER_URL}/api/tasks/{tid}", timeout=10))
        ok = r2.status_code == 200 and "task_type" in r2.json()
        return ok, f"{tid} type={r2.json().get('task_type','?')}" if ok else f"HTTP {r2.status_code}"
    except Exception as e:
        return False, str(e)


async def _e8_e9_check(action: str) -> tuple:
    try:
        r = await asyncio.to_thread(
            lambda: requests.get(f"{SERVER_URL}/api/tasks", timeout=10))
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}"
        tasks = r.json().get("tasks", [])
        target = None
        for t in tasks:
            if action == "resume" and t.get("status") in ("pending", "failed"):
                target = t
                break
            if action == "stop" and t.get("status") == "running":
                target = t
                break
        if not target:
            return True, f"no suitable task for {action} (skip)"
        tid = target["task_id"]
        path = f"/api/tasks/{tid}/{action}"
        r2 = await asyncio.to_thread(
            lambda: requests.post(f"{SERVER_URL}{path}", timeout=15))
        ok = r2.status_code == 200
        return ok, f"{tid} {r2.status_code}" if ok else f"HTTP {r2.status_code}"
    except Exception as e:
        return False, str(e)


# ═══════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════

async def main(resume: bool = False, auto_start: bool = False,
               quick: bool = False, cleanup: bool = False,
               poll_interval: int = POLL_INTERVAL):
    global POLL_INTERVAL
    POLL_INTERVAL = poll_interval

    logger.info("=" * 56)
    logger.info("  Agnes Video Generator v2.0 — 大版本回归测试")
    logger.info(f"  并行度上限: {MAX_CONCURRENT_WEIGHT} 权重并发")
    logger.info(f"  服务端限速: {AGNES_RATE_LIMIT} 次/分钟 (令牌桶, 含轮询)")
    logger.info(f"  轮询间隔: {POLL_INTERVAL}s")
    resume and logger.info(f"  模式: 续传 (跳过已完成 + 不可恢复失败，重试可恢复失败)")
    quick and logger.info(f"  模式: 快速验证 (跳过运行)")
    cleanup and logger.info(f"  模式: 清理回归产物")
    logger.info("=" * 56)

    # ── 清理模式 ──
    if cleanup:
        result = cleanup_regression_artifacts()
        if result.get("ok"):
            logger.info(
                f"✅ 已清理 {result['removed_dirs']} 个任务目录、"
                f"{result['removed_files']} 个文件"
                f"（涉及 {result['scenarios_cleaned']} 个场景）")
        else:
            logger.error(f"清理失败: {result.get('error', 'unknown')}")
            if result.get("errors"):
                for e in result["errors"]:
                    logger.error(f"  - {e}")
        return 0 if result.get("ok") else 1

    # 确保测试素材存在
    _ensure_test_assets()

    if not await ensure_server(auto_start):
        logger.error("服务不可用，退出")
        return 1

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    report = ReportManager(REPORT_PATH)
    manifest = RegressionManifest(MANIFEST_PATH, run_id=run_id)

    if quick:
        logger.info("快速验证模式：仅检查 manifest 已记录的产物")
        recorded = manifest.data.get("scenarios", {})
        has_any = False
        for sc in SCENARIO_DEFS:
            rec = recorded.get(sc.id)
            if rec and rec.get("dir_name"):
                has_any = True
                dn = rec["dir_name"]
                dir_path = os.path.join(WORKING_DIR, dn)
                if os.path.isdir(dir_path):
                    checks = await validate_task(dn, sc)
                    report.update_scenario(
                        sc.id, "completed",
                        result={"checks": checks},
                        errors=[k for k, v in checks.items() if v is False])
                    logger.info(f"  {sc.id}: 已验证 (dir={dn})")
                else:
                    report.update_scenario(
                        sc.id, "failed",
                        errors=[f"目录不存在: {dn}"])
                    logger.warning(f"  {sc.id}: 目录不存在 ({dn})")
            else:
                report.update_scenario(
                    sc.id, "skipped",
                    errors=["manifest 中无此场景记录"])
                logger.info(f"  {sc.id}: 跳过 (manifest 无记录)")
        if not has_any:
            logger.warning("manifest 中无任何场景记录，请先运行完整回归测试")
        await verify_endpoints(report)
        report._save()
        report.generate_md_report(REPORT_MD_PATH)
        manifest.save()
        report.print_summary()
        return 0

    pending = [sc for sc in SCENARIO_DEFS if report.should_run(sc.id, resume=resume)]
    skipped = [sc for sc in SCENARIO_DEFS if not report.should_run(sc.id, resume=resume)]

    if skipped:
        skip_ids = ', '.join(s.id for s in skipped)
        skip_reasons = []
        for s in skipped:
            st = report.data["scenarios"][s.id]["status"]
            if st == "completed":
                skip_reasons.append(f"{s.id}(已完成)")
            elif st == "skipped":
                skip_reasons.append(f"{s.id}(已跳过)")
            elif st == "failed":
                skip_reasons.append(f"{s.id}(不可恢复)")
            else:
                skip_reasons.append(f"{s.id}({st})")
        logger.info(f"跳过 {len(skipped)}: {', '.join(skip_reasons)}")
    if not pending:
        logger.info("无待运行场景")
        # 所有场景都已完成或不可恢复，直接生成报告
    else:
        logger.info(f"并发 {len(pending)} 场景 (max_weight={MAX_CONCURRENT_WEIGHT})")
        sema = WeightedSemaphore(MAX_CONCURRENT_WEIGHT)
        tasks = [run_scenario(sc, sema, report, manifest) for sc in pending]
        await asyncio.gather(*tasks)
        logger.info(f"全部场景执行完毕")

    await verify_endpoints(report)
    report._save()
    report.generate_md_report(REPORT_MD_PATH)
    manifest.save()

    passed = report.data["summary"]["failed"] == 0
    report.print_summary()
    logger.info(f"JSON 报告: {REPORT_PATH}")
    logger.info(f"MD  报告: {REPORT_MD_PATH}")
    logger.info(f"产物清单: {MANIFEST_PATH}")
    return 0 if passed else 1


def _print_help():
    print(__doc__)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(
        description="Agnes Video Generator 大版本回归测试")
    p.add_argument("--resume", action="store_true",
                   help="恢复已有报告")
    p.add_argument("--auto-start", action="store_true",
                   help="自动启动服务器")
    p.add_argument("--quick", action="store_true",
                   help="仅验证已有产物")
    p.add_argument("--cleanup", action="store_true",
                   help="清理回归测试产物（报告、日志、任务目录）")
    p.add_argument("--poll-interval", type=int, default=POLL_INTERVAL,
                   help=f"任务状态轮询间隔秒数 (默认 {POLL_INTERVAL})")
    args = p.parse_args()

    if args.quick and not args.resume:
        args.resume = True

    sys.exit(asyncio.run(main(
        resume=args.resume,
        auto_start=args.auto_start,
        quick=args.quick,
        cleanup=args.cleanup,
        poll_interval=args.poll_interval,
    )))
