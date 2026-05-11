#!/usr/bin/env python3
"""配置文件与状态管理"""
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
STATE_PATH = BASE_DIR / "session_state.json"

def default_config():
    return {
        "presets": {
            "cjk_serif": "SimSun",
            "cjk_sans": "SimHei",
            "cjk_mono": "SimSun",
            "en_serif": "Times New Roman",
            "en_sans": "Arial",
            "en_mono": "Consolas",
            "font_size": 12,
            "cover": False,
            "header_enabled": False
        },
        "usage_stats": {},
        "feedback_history": []
    }

def load_config():
    if CONFIG_PATH.is_file():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except:
                return default_config()
    else:
        config = default_config()
        save_config(config)
        return config

def save_config(config):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

# ---------- 使用统计与反馈 ----------
def update_usage_stats(config, selected_config):
    stats = config.setdefault("usage_stats", {})
    for key in ["cjk_serif", "cjk_sans", "cjk_mono", "en_serif", "en_sans", "en_mono",
                "font_size", "cover", "header_enabled"]:
        val = selected_config.get(key)
        if val is not None:
            val_str = str(val)
            if key not in stats:
                stats[key] = {}
            stats[key][val_str] = stats[key].get(val_str, 0) + 1

def get_personalized_preset(config):
    stats = config.get("usage_stats", {})
    if not stats:
        return None
    preset = {}
    for font_key in ["cjk_serif", "cjk_sans", "cjk_mono", "en_serif", "en_sans", "en_mono"]:
        item = stats.get(font_key, {})
        if item:
            best = max(item, key=item.get)
            preset[font_key] = best if item[best] >= 2 else default_config()["presets"][font_key]
        else:
            preset[font_key] = default_config()["presets"][font_key]
    fs = stats.get("font_size", {})
    if fs:
        best_fs = max(fs, key=fs.get)
        preset["font_size"] = int(best_fs) if fs[best_fs] >= 2 else 12
    else:
        preset["font_size"] = 12
    cov = stats.get("cover", {})
    if cov:
        best_cov = max(cov, key=cov.get)
        preset["cover"] = (best_cov == "True") if cov[best_cov] >= 2 else False
    else:
        preset["cover"] = False
    head = stats.get("header_enabled", {})
    if head:
        best_head = max(head, key=head.get)
        preset["header_enabled"] = (best_head == "True") if head[best_head] >= 2 else False
    else:
        preset["header_enabled"] = False
    return preset

def add_feedback(config, score, comment):
    history = config.setdefault("feedback_history", [])
    history.append({"score": score, "comment": comment})
    if len(history) > 5:
        history.pop(0)

def get_recent_feedback(config):
    history = config.get("feedback_history", [])
    useful = [fb["comment"] for fb in history if fb.get("score", 0) >= 3 and fb["comment"].strip()]
    return useful[-3:]

def update_subject_stats(config, subject):
    stats = config.setdefault("usage_stats", {})
    subj = stats.setdefault("subject", {})
    subj[subject] = subj.get(subject, 0) + 1

# ---------- 会话状态持久化 ----------
def save_session_state(state_data):
    """保存当前会话状态到 session_state.json"""
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state_data, f, ensure_ascii=False, indent=2)

def load_session_state():
    """读取会话状态，若文件不存在返回 None"""
    if STATE_PATH.is_file():
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except:
                return None
    return None

def clear_session_state():
    """删除会话状态文件"""
    if STATE_PATH.exists():
        STATE_PATH.unlink()