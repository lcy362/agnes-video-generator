"""全局测试夹具。

## 工作目录隔离（v8.0）

``core.task_manager`` / ``core.artifacts`` 在**模块导入时**就把
``core.config.get_working_dir`` 绑成了自己的模块级符号，因此测试里对
``core.config.get_working_dir`` 做 monkeypatch **不会生效**——``TaskManager``
落盘时用的仍是旧引用，于是测试数据会写进用户真实工作区
（如 ``~/generated-video``），在任务列表里留下 ``t_ts`` / ``t_diag`` 之类的
脏任务。

这里用 autouse 夹具把这两个模块的符号统一指向 ``tmp_path``：任何用例
（包括忘记自己打桩的用例）都不会再污染真实工作区。
"""

import pytest


@pytest.fixture(autouse=True)
def isolate_working_dir(tmp_path, monkeypatch):
    """把任务落盘目录隔离到当前用例的临时目录。"""
    import core.artifacts as artifacts_mod
    import core.task_manager as task_manager_mod

    target = str(tmp_path)
    monkeypatch.setattr(task_manager_mod, "get_working_dir", lambda: target, raising=False)
    monkeypatch.setattr(artifacts_mod, "get_working_dir", lambda: target, raising=False)
    return target
