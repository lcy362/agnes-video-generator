#!/usr/bin/env python3
"""
单场景回归测试执行器 — 提交任务 → 轮询等待 → 验证产物 → 返回 JSON 结果

用法:
  python scripts/scene_runner.py --scenario S1                # 执行 S1 场景
  python scripts/scene_runner.py --scenario C3 --poll 60      # 自定义轮询间隔
  python scripts/scene_runner.py --scenario M1 --timeout 3600  # 自定义超时
  python scripts/scene_runner.py --scenario C1 --resume        # 续传已有任务
  python scripts/scene_runner.py --list                        # 列出所有可用场景
  python scripts/scene_runner.py --validate-only --scenario S1 --dir <dir_name>  # 仅验证

机制:
  - 每个场景封装为独立子进程，主 agent 只需调用一次并读取 stdout JSON
  - 避免主 agent 内部大量轮询造成上下文爆炸
  - 输出格式: JSON（stdout），日志输出到 stderr
  - 退出码: 0=成功, 1=失败, 2=超时, 3=参数错误

输出 JSON 结构:
  {
    "scenario_id": "C3",
    "label": "带字幕+配音+关键帧",
    "status": "completed" | "failed" | "timeout",
    "task_id": "xxx",
    "dir_name": "xxx",
    "duration_s": 123.4,
    "checks": { ... },
    "errors": [ ... ],
    "error_detail": "具体错误信息（失败时）"
  }
"""

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests

# ═══════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKING_DIR = os.path.join(PROJECT_ROOT, ".working_dir")
SERVER_URL = "http://localhost:8765"
TEST_REF_IMAGE = os.path.join(PROJECT_ROOT, "test_ref.png")
TEST_END_IMAGE = os.path.join(PROJECT_ROOT, "test_end.png")

POLL_INTERVAL = 30
TIMEOUT_SIMPLE = 30 * 60
TIMEOUT_CREATIVE = 120 * 60
TIMEOUT_MANUSCRIPT = 60 * 60
TIMEOUT_ANCHOR = 60 * 60

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SceneRunner] %(message)s",
    stream=sys.stderr,  # 日志输出到 stderr，stdout 留给 JSON 结果
)
logger = logging.getLogger("SceneRunner")


# ═══════════════════════════════════════════════════
# 场景定义（与 regression_runner.py 保持一致）
# ═══════════════════════════════════════════════════

class ScenarioDef:
    def __init__(self, id: str, label: str, type_: str,
                 endpoint: str, params: dict, timeout: int,
                 requires_ref_image: bool = False,
                 requires_end_image: bool = False):
        self.id = id
        self.label = label
        self.type = type_
        self.endpoint = endpoint
        self.params = params
        self.timeout = timeout
        self.requires_ref_image = requires_ref_image
        self.requires_end_image = requires_end_image


SCENARIO_DEFS = [
    ScenarioDef("S1", "关键帧 keyframes", "simple",
        "/api/tasks/simple",
        {"prompt": "春天花园里花朵盛开，阳光柔和",
         "mode": "keyframes", "duration": 5},
        TIMEOUT_SIMPLE,
        requires_ref_image=True, requires_end_image=True),

    ScenarioDef("C1", "带参考图+关键帧+无配音", "creative",
        "/api/tasks/creative",
        {"idea": "清晨小镇溪边的宁静风景",
         "user_requirement": "3个场景，每个场景5秒，写实风格",
         "style": "写实风格", "chaining_mode": "keyframes",
         "video_duration": 5,
         "audio_enabled": False},
        TIMEOUT_CREATIVE, requires_ref_image=True),

    ScenarioDef("C2", "参考图生成尾帧+关键帧+无配音", "creative",
        "/api/tasks/creative",
        {"idea": "清晨小镇溪边的宁静风景",
         "user_requirement": "3个场景，每个场景5秒，写实风格",
         "style": "写实风格", "chaining_mode": "keyframes",
         "video_duration": 5,
         "audio_enabled": False,
         "use_custom_end_frames": True,
         "generate_end_frames_from_ref": True},
        TIMEOUT_CREATIVE, requires_ref_image=True),

    ScenarioDef("C3", "带字幕+配音+关键帧", "creative",
        "/api/tasks/creative",
        {"idea": "一只橘猫在阳光下的客厅里打盹",
         "user_requirement": "2个场景，每个场景5秒，温馨治愈风格",
         "style": "温馨写实风格", "chaining_mode": "keyframes",
         "video_duration": 5,
         "audio_enabled": True,
         "audio_voice": "zh-CN-XiaoxiaoNeural",
         "subtitle_enabled": True},
        TIMEOUT_CREATIVE),

    ScenarioDef("M1", "短稿件+配音", "manuscript",
        "/api/tasks/manuscript",
        {"manuscript_text": "今天天气真好，阳光暖暖地照在大地上。"
         "公园里的花开了，红的黄的紫的，五颜六色。"
         "小鸟在枝头唱歌，叽叽喳喳真好听。"
         "孩子们在草地上奔跑，笑声传得很远。"
         "老爷爷在长椅上看报纸，偶尔喝一口茶。"
         "小狗在主人脚边转来转去，摇着小尾巴。"
         "远处的喷泉哗啦啦地响着，水花闪闪发亮。"
         "这就是一个普通的周末，简单又快乐。",
         "video_duration": 5, "audio_enabled": True,
         "audio_voice": "zh-CN-XiaoxiaoNeural"},
        TIMEOUT_MANUSCRIPT),

    ScenarioDef("M2", "短稿件+自定义字幕", "manuscript",
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
        TIMEOUT_MANUSCRIPT),

    ScenarioDef("A1", "数字人+后拼接音频", "anchor",
        "/api/tasks/anchor",
        {"anchor_prompt": "一位专业的新闻主播，穿着正式西装，坐在现代化的新闻演播室中",
         "script_text": "大家好，欢迎收看今天的新闻联播。"
         "今天的主要内容有：科技创新取得重大突破，"
         "人工智能领域又有新进展。"
         "国内外众多专家齐聚一堂，共同探讨未来发展。"
         "感谢您的收看，我们下期节目再见。",
         "audio_source": "post_stitch",
         "audio_enabled": True,
         "audio_voice": "zh-CN-XiaoxiaoNeural"},
        TIMEOUT_ANCHOR),

    ScenarioDef("A2", "数字人+模型音频", "anchor",
        "/api/tasks/anchor",
        {"anchor_prompt": "一位专业的新闻主播，穿着正式西装，坐在现代化的新闻演播室中",
         "script_text": "大家好，欢迎收看今天的新闻联播。"
         "今天的主要内容有：科技创新取得重大突破，"
         "人工智能领域又有新进展。"
         "感谢您的收看，我们下期节目再见。",
         "audio_source": "model",
         "audio_enabled": False},
        TIMEOUT_ANCHOR),
]

SCENARIO_MAP = {s.id: s for s in SCENARIO_DEFS}


# ═══════════════════════════════════════════════════
# HTTP 调用
# ═══════════════════════════════════════════════════

def submit_task(sc: ScenarioDef) -> dict:
    """提交任务到服务端，返回 {task_id, dir_name}。"""
    url = f"{SERVER_URL}{sc.endpoint}"
    data = sc.params.copy()
    files = {}

    if sc.requires_ref_image and os.path.exists(TEST_REF_IMAGE):
        with open(TEST_REF_IMAGE, "rb") as f:
            files["reference_image"] = ("ref.png", f.read(), "image/png")
    if sc.requires_end_image and os.path.exists(TEST_END_IMAGE):
        if sc.type == "simple":
            with open(TEST_END_IMAGE, "rb") as f:
                files["end_frame_image"] = ("end.png", f.read(), "image/png")

    r = requests.post(url, data=data, files=files if files else None, timeout=30)
    r.raise_for_status()
    result = r.json()
    if not result.get("ok"):
        raise RuntimeError(f"提交失败: {result}")
    return result


def get_task_status(task_id: str) -> dict:
    """获取任务状态。"""
    r = requests.get(f"{SERVER_URL}/api/tasks/{task_id}", timeout=10)
    if r.status_code == 404:
        raise FileNotFoundError(f"Task {task_id} not found (404)")
    r.raise_for_status()
    return r.json()


def resume_task(task_id: str) -> dict:
    """续传任务。"""
    r = requests.post(f"{SERVER_URL}/api/tasks/{task_id}/resume", timeout=10)
    return r.json()


# ═══════════════════════════════════════════════════
# 产物验证（从 regression_runner.py 抽取核心逻辑）
# ═══════════════════════════════════════════════════

def _compute_expected_duration(task_state: dict, sc: ScenarioDef) -> Optional[float]:
    """从 task_state 计算期望视频总时长。"""
    if sc.type == "simple":
        dur = task_state.get("duration")
        return float(dur) if dur else None

    if sc.type == "anchor":
        audio = task_state.get("combined_audio", "")
        if audio and os.path.exists(audio):
            try:
                r = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", audio],
                    capture_output=True, text=True, timeout=10,
                    stdin=subprocess.DEVNULL,
                )
                return float(r.stdout.strip())
            except Exception:
                pass
        return None

    if sc.type in ("creative", "manuscript"):
        video_dur = task_state.get("video_duration", 5)
        if sc.type == "creative":
            scenes = task_state.get("scenes", [])
            count = len(scenes) if scenes else task_state.get("scene_count", 0)
            if not count:
                return None
            expected = count * video_dur
        else:
            paras = task_state.get("paragraphs", [])
            if not paras:
                return None
            expected = sum(max(-(-len(p.get("text", "")) // 4), 3) for p in paras)

        combined = task_state.get("combined_audio", "")
        if combined and os.path.exists(combined):
            try:
                r = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", combined],
                    capture_output=True, text=True, timeout=10,
                    stdin=subprocess.DEVNULL,
                )
                audio_dur = float(r.stdout.strip())
                expected = max(expected, audio_dur)
            except Exception:
                pass
        return float(expected)

    return None


_VIDEO_ID_RE = re.compile(r"agnesapi\?\S*video_id=|mode=\S*&video_id=")


def _curl_has_valid_video_id(path: str) -> bool:
    """严格匹配：要求 agnesapi?..video_id= 或 mode=..&video_id= 模式。"""
    if not os.path.exists(path):
        return False
    with open(path) as f:
        return bool(_VIDEO_ID_RE.search(f.read()))


def validate_artifacts(dir_name: str, sc: ScenarioDef) -> dict:
    """验证任务产物，返回 checks dict。

    与 regression_runner.py 的 _validate_sync 保持一致的检查项，
    包括 F1-F7（最终产物）、R1-R6（断点续传）、R7-R10（音频/字幕）。
    """
    task_dir = os.path.join(WORKING_DIR, dir_name)
    checks: dict[str, Any] = {}

    # ── 防御：任务目录不存在 ──
    if not os.path.isdir(task_dir):
        checks["F1_final_video_exists"] = False
        checks["F1_final_video_nonempty"] = False
        checks["F2_duration"] = 0
        checks["F2_duration_gt_0"] = False
        checks["F4_has_audio_stream"] = False
        checks["F4_has_speech"] = "N/A"
        checks["F6_text_match"] = "N/A"
        checks["F7_duration_reasonable"] = False
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

    # ── 加载 task_state ──
    ts_path = os.path.join(task_dir, "task_state.json")
    sd: dict = {}
    if os.path.exists(ts_path):
        try:
            with open(ts_path) as f:
                sd = json.load(f)
        except Exception:
            pass

    # ── F2-F7: 视频元数据 ──
    if ve:
        try:
            from moviepy import VideoFileClip
            clip = VideoFileClip(video)
            checks["F2_duration"] = round(clip.duration, 2)
            checks["F2_duration_gt_0"] = clip.duration > 0
            exp_w = sd.get("video_width", sc.params.get("video_width", 768))
            exp_h = sd.get("video_height", sc.params.get("video_height", 1152))
            checks["F3_width"] = clip.w
            checks["F3_height"] = clip.h
            w_ok = abs(clip.w - exp_w) / max(exp_w, 1) <= 0.15
            h_ok = abs(clip.h - exp_h) / max(exp_h, 1) <= 0.15
            checks["F3_resolution_matches"] = w_ok and h_ok
            checks["F4_has_audio_stream"] = clip.audio is not None
            expected_dur = _compute_expected_duration(sd, sc)
            if expected_dur:
                checks["F7_expected_duration"] = round(expected_dur, 2)
                checks["F7_duration_reasonable"] = (
                    abs(clip.duration - expected_dur) / expected_dur <= 0.15
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
            checks["F3_resolution_matches"] = "skip"
            checks["F4_has_audio_stream"] = "skip"
            checks["F7_duration_reasonable"] = "skip"
        except Exception as e:
            checks["F2_duration"] = f"err:{e}"
            checks["F2_duration_gt_0"] = False
            checks["F4_has_audio_stream"] = False
            checks["F7_duration_reasonable"] = False

        # ASR 验证（scene_runner 不加载 whisper，标记为 skip）
        audio_enabled = sc.params.get("audio_enabled", True)
        is_simple = sd.get("task_type") == "simple"
        asr_eligible = (
            ve
            and checks.get("F4_has_audio_stream") is True
            and audio_enabled
            and not is_simple
        )
        if asr_eligible:
            checks["F4_has_speech"] = "skip"  # whisper 验证留给主回归脚本
            checks["F6_text_match"] = "skip"
        else:
            checks["F4_has_speech"] = "N/A"
            checks["F6_text_match"] = "N/A"
    else:
        checks["F2_duration"] = 0
        checks["F2_duration_gt_0"] = False
        checks["F4_has_audio_stream"] = False
        checks["F7_duration_reasonable"] = False
        checks["F4_has_speech"] = "N/A"
        checks["F6_text_match"] = "N/A"

    # ── R1-R4: task_state.json ──
    if sd:
        checks["R1_task_state_valid"] = True
        checks["R2_task_type"] = sd.get("task_type", "?")
        checks["R2_task_type_matches"] = sd.get("task_type") == sc.type

        # R3: step completion（含可跳过步骤逻辑）
        steps = {k: v for k, v in sd.items() if k.startswith("step_")}
        checks["R3_step_count"] = len(steps)

        if sc.type == "simple":
            # simple 任务无 step_* 字段，用顶层 status 判断
            checks["R3_all_completed"] = sd.get("status") == "completed"
            checks["R3_incomplete_steps"] = (
                "" if checks["R3_all_completed"]
                else "status=" + sd.get("status", "?")
            )
        elif sc.type == "anchor":
            # anchor: 根据 audio_source 决定哪些 step 必须完成
            audio_source = sd.get("audio_source", "post_stitch")
            _skippable = set()
            if audio_source == "model":
                # 模型音频模式：跳过 audio/subtitle/concatenation 步骤
                _skippable = {"step_subtitle", "step_concatenation"}
            active_steps = {k: v for k, v in steps.items() if k not in _skippable}
            incomplete = [k for k, v in active_steps.items() if v != "completed"]
            checks["R3_all_completed"] = not incomplete if active_steps else "N/A"
            checks["R3_incomplete_steps"] = ",".join(incomplete) if incomplete else ""
        else:
            # creative: 非 keyframes 模式下 end_frame 步骤可跳过
            chaining_mode = sd.get("chaining_mode", "none")
            _skippable = set()
            if sc.type == "creative" and chaining_mode not in ("keyframes",):
                _skippable = {"step_end_frame_prompts", "step_end_frame_generation"}
            active_steps = {k: v for k, v in steps.items() if k not in _skippable}
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

    # ── R5: task.json（含 video_id） ──
    # 创意任务在 scene_N/ 子目录，稿件任务在 para_N/ 子目录
    # 简单视频任务在根目录，数字人在 clip/ 子目录
    _task_json_found = False
    _has_video_id = False

    tj_root = os.path.join(task_dir, "task.json")
    if os.path.exists(tj_root):
        _task_json_found = True
        try:
            with open(tj_root) as f:
                tjd = json.load(f)
            _has_video_id = bool(tjd.get("video_id") or tjd.get("id"))
        except Exception:
            pass

    # 检查子目录
    if sc.type in ("creative", "manuscript", "anchor"):
        subdir_prefix = {
            "creative": "scene_", "manuscript": "para_", "anchor": "clip"
        }.get(sc.type)
        subdir_is_exact = sc.type == "anchor"
        for entry in os.listdir(task_dir):
            match = entry == subdir_prefix if subdir_is_exact else entry.startswith(subdir_prefix)
            if match:
                sd_path = os.path.join(task_dir, entry)
                if os.path.isdir(sd_path):
                    tj_sub = os.path.join(sd_path, "task.json")
                    if os.path.exists(tj_sub):
                        _task_json_found = True
                        if not _has_video_id:
                            try:
                                with open(tj_sub) as f:
                                    tjd = json.load(f)
                                _has_video_id = bool(tjd.get("video_id") or tjd.get("id"))
                            except Exception:
                                pass

    checks["R5_task_json"] = _task_json_found
    checks["R5_has_video_id"] = _has_video_id

    # ── R6: curl.sh（含 video_id） ──
    _curl_dirs_checked = 0
    _curl_dirs_with_valid_id = 0

    cs_root = os.path.join(task_dir, "curl.sh")
    if os.path.exists(cs_root):
        _curl_dirs_checked += 1
        if _curl_has_valid_video_id(cs_root):
            _curl_dirs_with_valid_id += 1

    if sc.type in ("creative", "manuscript", "anchor"):
        subdir_prefix = {
            "creative": "scene_", "manuscript": "para_", "anchor": "clip"
        }.get(sc.type)
        subdir_is_exact = sc.type == "anchor"
        for entry in os.listdir(task_dir):
            match = entry == subdir_prefix if subdir_is_exact else entry.startswith(subdir_prefix)
            if match:
                sd_path = os.path.join(task_dir, entry)
                if os.path.isdir(sd_path):
                    cs_sub = os.path.join(sd_path, "curl.sh")
                    if os.path.exists(cs_sub):
                        _curl_dirs_checked += 1
                        if _curl_has_valid_video_id(cs_sub):
                            _curl_dirs_with_valid_id += 1

    checks["R6_curl_sh"] = _curl_dirs_checked > 0
    checks["R6_has_video_id_in_curl"] = _curl_dirs_with_valid_id > 0
    checks["R6_dirs_checked"] = _curl_dirs_checked
    checks["R6_dirs_with_curl"] = _curl_dirs_with_valid_id

    # ── R7-R8: 子目录 + 音频/字幕文件 ──
    audio_enabled = sc.params.get("audio_enabled", True)
    if sc.type in ("creative", "manuscript", "anchor"):
        # R7: 子目录存在性
        if sc.type == "anchor":
            dirs_exist = os.path.isdir(os.path.join(task_dir, "clip"))
        else:
            prefix = "scene_" if sc.type == "creative" else "para_"
            dirs_exist = any(
                e.startswith(prefix) and os.path.isdir(os.path.join(task_dir, e))
                for e in os.listdir(task_dir)
            )
        checks["R7_sub_dirs_exist"] = dirs_exist

        if audio_enabled:
            audio_found = srt_found = False
            for root, _dirs, files in os.walk(task_dir):
                for fn in files:
                    if fn in ("narration.mp3", "full_narration.mp3",
                              "narration.wav", "combined_narration.mp3"):
                        audio_found = True
                    if fn.endswith(".srt"):
                        srt_found = True
            checks["R7_audio_files"] = audio_found
            checks["R8_subtitle_srt"] = srt_found
        else:
            checks["R7_audio_files"] = "N/A"
            checks["R8_subtitle_srt"] = "N/A"
    else:
        checks["R7_sub_dirs_exist"] = "N/A"
        checks["R7_audio_files"] = "N/A"
        checks["R8_subtitle_srt"] = "N/A"

    # ── R9-R10: 合稿产物（稿件/数字人后拼接音频） ──
    has_combined = sc.type in ("manuscript", "anchor")
    if has_combined and audio_enabled:
        fn9 = os.path.join(task_dir, "full_narration.mp3")
        checks["R9_full_narration"] = os.path.exists(fn9) and os.path.getsize(fn9) > 0
        fn10 = os.path.join(task_dir, "full_subtitle.srt")
        checks["R10_full_subtitle"] = os.path.exists(fn10)
        if os.path.exists(fn10):
            with open(fn10) as f:
                srt_content = f.read()
            checks["R10_srt_entries"] = (
                srt_content.count("\n\n") + 1 if "\n\n" in srt_content else 1
            )
        else:
            checks["R10_srt_entries"] = 0
    elif has_combined:
        checks["R9_full_narration"] = "N/A"
        checks["R10_full_subtitle"] = "N/A"
        checks["R10_srt_entries"] = "N/A"
    else:
        checks["R9_full_narration"] = "N/A"
        checks["R10_full_subtitle"] = "N/A"
        checks["R10_srt_entries"] = "N/A"

    return checks


# ═══════════════════════════════════════════════════
# 单场景执行主流程
# ═══════════════════════════════════════════════════

def run_scenario(sc: ScenarioDef, poll_interval: int = POLL_INTERVAL,
                 timeout_override: int = None,
                 existing_task_id: str = None,
                 existing_dir: str = None) -> dict:
    """执行单个场景的完整流程：提交 → 轮询 → 验证 → 返回结果。"""
    start = time.monotonic()
    timeout = timeout_override or sc.timeout
    task_id = existing_task_id
    dir_name = existing_dir

    result = {
        "scenario_id": sc.id,
        "label": sc.label,
        "type": sc.type,
        "status": "pending",
        "task_id": None,
        "dir_name": None,
        "duration_s": 0,
        "checks": {},
        "errors": [],
        "error_detail": "",
        "started_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        # ── 提交阶段 ──
        if not task_id:
            logger.info(f"[{sc.id}] 提交任务: {sc.label}")
            submit_result = submit_task(sc)
            task_id = submit_result["task_id"]
            dir_name = submit_result.get("dir_name", task_id)
            logger.info(f"[{sc.id}] 已提交 → task_id={task_id[:12]}, dir={dir_name}")
        else:
            logger.info(f"[{sc.id}] 续传已有任务: {task_id[:12]}")

        result["task_id"] = task_id
        result["dir_name"] = dir_name
        result["status"] = "submitted"

        # ── 轮询阶段 ──
        deadline = time.monotonic() + timeout
        max_retries = 2
        retry_count = 0
        final_status = None

        while time.monotonic() < deadline:
            time.sleep(poll_interval)
            try:
                state = get_task_status(task_id)
                st = state.get("status", "")
                elapsed = round(time.monotonic() - start, 1)

                if st == "completed":
                    final_status = "completed"
                    logger.info(f"[{sc.id}] ✅ 任务完成 ({elapsed}s)")
                    break
                elif st in ("failed", "error"):
                    if retry_count < max_retries:
                        retry_count += 1
                        logger.info(f"[{sc.id}] 任务失败，尝试续传 ({retry_count}/{max_retries})")
                        try:
                            resume_task(task_id)
                            time.sleep(10)
                            continue
                        except Exception as re:
                            logger.warning(f"[{sc.id}] 续传失败: {re}")
                    final_status = f"failed: {state.get('error', '?')}"
                    logger.warning(f"[{sc.id}] ❌ {final_status}")
                    break
                elif st == "running":
                    fvf = state.get("final_video_file", "")
                    if fvf:
                        logger.info(f"[{sc.id}] running, video={os.path.basename(fvf)}")
                else:
                    logger.info(f"[{sc.id}] status={st}")

            except FileNotFoundError:
                logger.warning(f"[{sc.id}] 任务不存在 (404)")
                final_status = "task_not_found"
                break
            except Exception as e:
                logger.warning(f"[{sc.id}] 轮询异常: {e}")
                time.sleep(5)
        else:
            final_status = f"timeout (>{timeout}s)"
            logger.warning(f"[{sc.id}] ⏰ 超时 ({timeout}s)")

        # ── 验证阶段 ──
        elapsed = round(time.monotonic() - start, 1)
        result["duration_s"] = elapsed

        if final_status == "completed" and dir_name:
            logger.info(f"[{sc.id}] 验证产物...")
            checks = validate_artifacts(dir_name, sc)
            result["checks"] = checks

            failed_checks = [
                k for k, v in checks.items()
                if v is False and not any(
                    k.endswith(x) for x in
                    ("_width", "_height", "_duration", "_count",
                     "_entries", "F2_duration", "F6_asr_text",
                     "F4_speech_duration", "R3_incomplete_steps",
                     "R6_dirs_checked", "R6_dirs_with_curl",
                     "R10_srt_entries", "F7_expected_duration")
                )
            ]
            result["errors"] = failed_checks

            if failed_checks:
                result["status"] = "completed_with_issues"
                result["error_detail"] = f"检查失败: {', '.join(failed_checks)}"
                logger.warning(f"[{sc.id}] ⚠️ 完成但有 {len(failed_checks)} 项检查失败")
            else:
                result["status"] = "completed"
                logger.info(f"[{sc.id}] ✅ 全部检查通过 ({elapsed}s)")
        else:
            result["status"] = "failed"
            result["error_detail"] = final_status or "unknown"

    except requests.ConnectionError as e:
        result["status"] = "failed"
        result["error_detail"] = f"服务不可用: {e}"
        logger.error(f"[{sc.id}] 服务不可用: {e}")
    except Exception as e:
        result["status"] = "failed"
        result["error_detail"] = str(e)
        logger.error(f"[{sc.id}] 异常: {e}")

    result["completed_at"] = datetime.now(timezone.utc).isoformat()
    return result


# ═══════════════════════════════════════════════════
# 端点验证（独立运行）
# ═══════════════════════════════════════════════════

def verify_endpoints() -> dict:
    """验证所有服务端点，返回 {E1: {status, detail}, ...}。"""
    results = {}

    def check(eid: str, desc: str, fn):
        try:
            ok, detail = fn()
            results[eid] = {"status": "passed" if ok else "failed", "detail": str(detail)}
            tag = "✅" if ok else "❌"
            logger.info(f"  {tag} {eid}: {desc}" + (f" -> {detail}" if not ok else ""))
        except Exception as e:
            results[eid] = {"status": "failed", "detail": str(e)}
            logger.info(f"  ❌ {eid}: {desc} -> {e}")

    def _200(path, check_text=""):
        r = requests.get(f"{SERVER_URL}{path}", timeout=10)
        if check_text:
            return r.status_code == 200 and check_text in r.text, r.status_code
        return r.status_code == 200, r.status_code

    def _post_ok(path, data):
        r = requests.post(f"{SERVER_URL}{path}", data=data, timeout=15)
        return r.status_code in (200, 201), r.status_code

    logger.info("端点验证 E1-E10")
    check("E1", "GET / → 200", lambda: _200("/", "Agnes Video Generator"))
    check("E2", "GET /api/config → 200", lambda: _200("/api/config"))
    check("E3", "POST /api/tasks/simple → 200",
          lambda: _post_ok("/api/tasks/simple", {"prompt": "test", "mode": "t2v", "duration": 5}))
    check("E4", "POST /api/tasks/creative → 200",
          lambda: _post_ok("/api/tasks/creative",
                           {"idea": "__ep_probe__", "user_requirement": "1个场景，5秒",
                            "audio_enabled": "false", "creative_name": "__ep_probe__"}))
    check("E5", "POST /api/tasks/manuscript → 200",
          lambda: _post_ok("/api/tasks/manuscript",
                           {"manuscript_text": "__ep_probe__。第二句。",
                            "audio_enabled": "false", "creative_name": "__ep_probe__"}))
    check("E6", "GET /api/tasks → list", lambda: _200("/api/tasks"))
    check("E7", "GET /api/tasks/{id} → task_type", _e7_check)
    check("E8", "POST /api/tasks/{id}/resume", lambda: _e8_e9_check("resume"))
    check("E9", "POST /api/tasks/{id}/stop", lambda: _e8_e9_check("stop"))
    check("E10", "POST /api/tasks/anchor → 200",
          lambda: _post_ok("/api/tasks/anchor",
                           {"script_text": "E10探针测试。", "audio_source": "post_stitch",
                            "audio_enabled": "false", "creative_name": "__ep_probe__"}))

    return results


def _e7_check():
    try:
        r = requests.get(f"{SERVER_URL}/api/tasks", timeout=10)
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}"
        tasks = r.json().get("tasks", [])
        if not tasks:
            return True, "no tasks (skip)"
        tid = tasks[0]["task_id"]
        r2 = requests.get(f"{SERVER_URL}/api/tasks/{tid}", timeout=10)
        ok = r2.status_code == 200 and "task_type" in r2.json()
        return ok, f"{tid} type={r2.json().get('task_type','?')}" if ok else f"HTTP {r2.status_code}"
    except Exception as e:
        return False, str(e)


def _e8_e9_check(action):
    try:
        r = requests.get(f"{SERVER_URL}/api/tasks", timeout=10)
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
        r2 = requests.post(f"{SERVER_URL}/api/tasks/{tid}/{action}", timeout=15)
        return r2.status_code == 200, f"{tid} {r2.status_code}"
    except Exception as e:
        return False, str(e)


# ═══════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="单场景回归测试执行器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    parser.add_argument("--scenario", "-s", type=str, help="场景 ID（如 S1, C1, C3, M1）")
    parser.add_argument("--poll", type=int, default=POLL_INTERVAL, help=f"轮询间隔秒数（默认 {POLL_INTERVAL}）")
    parser.add_argument("--timeout", type=int, default=None, help="超时秒数（覆盖场景默认值）")
    parser.add_argument("--resume", action="store_true", help="续传已有任务（需配合 --task-id）")
    parser.add_argument("--task-id", type=str, help="已有任务 ID（续传模式）")
    parser.add_argument("--dir", type=str, help="任务目录名（仅验证模式）")
    parser.add_argument("--validate-only", action="store_true", help="仅验证产物，不提交/轮询")
    parser.add_argument("--endpoints", action="store_true", help="执行端点验证 E1-E10")
    parser.add_argument("--list", action="store_true", help="列出所有可用场景")
    parser.add_argument("--json", action="store_true", help="输出 JSON 到 stdout（默认）")

    args = parser.parse_args()

    # 列出场景
    if args.list:
        for sc in SCENARIO_DEFS:
            print(f"  {sc.id:4s}  {sc.type:12s}  {sc.label:30s}  超时={sc.timeout//60}m")
        return 0

    # 端点验证
    if args.endpoints:
        results = verify_endpoints()
        output = {"type": "endpoints", "results": results}
        print(json.dumps(output, ensure_ascii=False, indent=2))
        passed = sum(1 for v in results.values() if v["status"] == "passed")
        return 0 if passed == len(results) else 1

    # 需要 scenario 参数
    if not args.scenario:
        parser.error("请指定 --scenario 或使用 --list 查看可用场景")

    sc_id = args.scenario.upper()
    if sc_id not in SCENARIO_MAP:
        logger.error(f"未知场景: {sc_id}，可用场景: {', '.join(SCENARIO_MAP.keys())}")
        return 3

    sc = SCENARIO_MAP[sc_id]

    # 仅验证模式
    if args.validate_only:
        if not args.dir:
            logger.error("仅验证模式需要 --dir 参数")
            return 3
        checks = validate_artifacts(args.dir, sc)
        output = {
            "scenario_id": sc.id,
            "label": sc.label,
            "status": "validate_only",
            "dir_name": args.dir,
            "checks": checks,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0

    # 执行场景
    result = run_scenario(
        sc,
        poll_interval=args.poll,
        timeout_override=args.timeout,
        existing_task_id=args.task_id if args.resume else None,
        existing_dir=args.dir if args.resume else None,
    )

    # 输出 JSON 结果到 stdout
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # 退出码
    if result["status"] == "completed":
        return 0
    elif result["status"] == "completed_with_issues":
        return 1
    elif "timeout" in (result.get("error_detail") or ""):
        return 2
    else:
        return 1


if __name__ == "__main__":
    sys.exit(main())
