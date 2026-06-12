#!/usr/bin/env python3
import json, sys, os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
with open('.working_dir/67c01fcf7e7d/task_state.json', 'r') as f:
    data = json.load(f)
data['status'] = 'pending'
with open('.working_dir/67c01fcf7e7d/task_state.json', 'w') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print('OK: Status reset to pending')
print('step_video_generation:', data.get('step_video_generation'))
print('step_end_frame_generation:', data.get('step_end_frame_generation'))
