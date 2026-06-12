import json
import os

CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".agnes_config")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")


def _ensure_config_dir():
    os.makedirs(CONFIG_DIR, exist_ok=True)


def load_config() -> dict:
    _ensure_config_dir()
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}


def save_config(config: dict):
    _ensure_config_dir()
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def get_api_key() -> str:
    env_key = os.environ.get("AGNES_API_KEY", "")
    if env_key:
        return env_key
    config = load_config()
    return config.get("api_key", "")


def set_api_key(key: str):
    config = load_config()
    config["api_key"] = key
    save_config(config)


def get_working_dir() -> str:
    return os.path.join(os.getcwd(), ".working_dir")


def get_task_dir(task_id: str) -> str:
    return os.path.join(get_working_dir(), task_id)