"""临时复现：快速模式 attempts 是否真的每秒落盘、新实例能否读到。"""
import os
import tempfile
import time
from datetime import datetime

import core.task_manager as tm_mod
from core.pipelines import _PipelineFastRetryHook
from models.task import SimpleVideoTask

WORK = tempfile.mkdtemp(prefix="fastretry_probe_")
tm_mod.get_working_dir = lambda: WORK


class P:
    def __init__(self, state, tm):
        self.task_id = state.task_id
        self._state = state
        self.task_manager = tm
        self.emits = []

    def _save_fast_retry(self):
        self.task_manager.update_state()

    def _emit_fast_retry(self, key, params):
        self.emits.append((key, params))


state = SimpleVideoTask(task_id="t_probe")
state.fast_retry.enabled = True
state.fast_retry.per_minute = 120
state.fast_retry.minutes = 3
state.fast_retry.started_at = datetime.now().isoformat(timespec="seconds")

tm = tm_mod.TaskManager("t_probe")
tm.create(state)

p = P(state, tm)
hook = _PipelineFastRetryHook(p)

for n in range(1, 9):
    interval = hook.decide(0, {"status": 503, "code": "video_queue_full",
                               "attempt": 0, "waited_s": 0.0, "probe": n})
    loaded = tm_mod.TaskManager("t_probe").load()
    print(f"probe={n} interval={interval} mem_attempts={state.fast_retry.attempts} "
          f"file_attempts={loaded.fast_retry.attempts}")
    time.sleep(0.35)

print("state file:", os.path.join(WORK, "t_probe", "task_state.json"))
