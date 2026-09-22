"""stability_hardening P2（M3）：稿件场景 prompt 单段失败隔离测试。

构造 A/B/C 三段稿件，注入不同的失败形态，验证 _generate_scene_prompts：
- 单段业务失败 → 任务不 FAILED，A/C 保留 prompt，B 段留空被下游跳过；
- 全段失败 → 显式 raise（异常链含首个失败段落 index）；
- 中止类失败（PipelineShutdown）→ 向上传播，不被当作"失败段"；
- 返回值防御：None 也归一化为空串。
"""
from types import SimpleNamespace

import pytest

from core.pipelines import CheckpointPause, PipelineShutdown
from core.pipelines.manuscript_video import ManuscriptVideoPipeline
from models.task import ManuscriptParagraph


def _para(idx, text="para", scene_prompt=""):
    return ManuscriptParagraph(index=idx, text=text, scene_prompt=scene_prompt)


def _make_pipeline(screenwriter, update_state=None):
    p = object.__new__(ManuscriptVideoPipeline)  # 绕过 __init__
    p._state = SimpleNamespace(style="测试风格")
    p.screenwriter = screenwriter
    p.task_manager = SimpleNamespace(
        update_state=update_state if update_state is not None else (lambda **kw: None)
    )
    p._emit_calls = []

    async def _emit(step, status, message, progress):
        p._emit_calls.append((step, status, message))

    p._emit = _emit
    p._check_shutdown = lambda: None
    p.save_prompts = lambda data: None
    return p


async def test_single_failure_isolated():
    """单段失败：任务继续，失败段留空，其余保留。"""
    calls = {"n": 0}

    def fake_screenwriter(para_text, style):
        calls["n"] += 1
        # 与段落 index 缓冲区一一对应（A/B/C）
        if para_text == "B":
            raise RuntimeError("LLM boom: paragraph B")
        return f"prompt-for-{para_text}"

    screenwriter = SimpleNamespace(generate_scene_prompt_for_paragraph=fake_screenwriter)
    p = _make_pipeline(screenwriter)

    paras = [_para(0, "A"), _para(1, "B"), _para(2, "C")]
    # 不抛异常 → 部分失败被隔离
    await p._generate_scene_prompts(paras)

    assert paras[0].scene_prompt == "prompt-for-A"
    assert paras[1].scene_prompt == "", "B 段失败应留空"
    assert paras[2].scene_prompt == "prompt-for-C"
    # 进度文案含成功/失败计数（部分失败：2/3 成功，1 段失败）
    assert any("2/3" in m and "段失败" in m for _, _, m in p._emit_calls)
    assert calls["n"] == 3


async def test_all_raised_when_every_paragraph_fails():
    """全段失败：显式 raise，异常信息含首个失败段落 index。"""
    def fake_screenwriter(para_text, style):
        raise RuntimeError("all down")

    p = _make_pipeline(SimpleNamespace(generate_scene_prompt_for_paragraph=fake_screenwriter))
    paras = [_para(0, "A"), _para(1, "B"), _para(2, "C")]
    with pytest.raises(RuntimeError) as ei:
        await p._generate_scene_prompts(paras)
    assert "全部失败" in str(ei.value)
    assert "index=0" in str(ei.value)
    assert "all down" in str(ei.value)


async def test_null_prompt_normalized_to_empty():
    """返回值 None 归一化为空串（正常完成路径，不算失败，不抛异常）。"""
    def fake_screenwriter(para_text, style):
        return None

    p = _make_pipeline(SimpleNamespace(generate_scene_prompt_for_paragraph=fake_screenwriter))
    paras = [_para(0, "A")]
    await p._generate_scene_prompts(paras)  # None 是正常值，不触发失败分支
    assert paras[0].scene_prompt == ""


@pytest.mark.parametrize(
    "exc", [PipelineShutdown("stop"), CheckpointPause("audio", "pause again")],
)
async def test_control_flow_exception_propagates(exc):
    """中止类异常穿透，不被当作失败段隔离。"""
    def fake_screenwriter(para_text, style):
        raise exc

    p = _make_pipeline(SimpleNamespace(generate_scene_prompt_for_paragraph=fake_screenwriter))
    paras = [_para(0, "A"), _para(1, "B")]
    with pytest.raises(type(exc)):
        await p._generate_scene_prompts(paras)
    # 中止异常不应触发"部分/全部失败"分支：保持原样
    assert paras[0].scene_prompt == ""