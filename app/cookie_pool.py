#!/usr/bin/env python3
"""
Cookie 池 — 轮询真实皮皮虾 Cookie，规避单 IP / 单会话 频控
- 多个 Cookie 轮询使用
- 每个 Cookie 有冷却时间（避免单 Cookie 用太频繁被风控）
- 健康度追踪：失败 → 降级 → 临时禁用 → 恢复
- 存储: JSON 文件（轻量，后续可换 Redis）
"""
import json
import random
import time
from pathlib import Path
from threading import Lock
from typing import Optional

POOL_PATH = Path(__file__).parent.parent / "data" / "cookie_pool.json"


class CookiePool:
    def __init__(self, pool_path: Path = POOL_PATH):
        self.path = pool_path
        self.lock = Lock()
        self._load()

    def _load(self):
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.cookies = data.get("cookies", [])
        else:
            self.cookies = []
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._save()

    def _save(self):
        self.path.write_text(
            json.dumps({"cookies": self.cookies}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add_cookie(self, cookie_str: str, label: str = "", ua: str = ""):
        """
        添加一个 Cookie
        cookie_str 格式: 'name1=value1; name2=value2; ...'
        """
        with self.lock:
            self.cookies.append({
                "cookie": cookie_str,
                "label": label or f"cookie_{len(self.cookies)+1}",
                "ua": ua,
                "added_at": int(time.time()),
                "last_used_at": 0,
                "use_count": 0,
                "fail_count": 0,
                "cooldown_until": 0,
                "disabled": False,
            })
            self._save()

    def remove_cookie(self, label: str):
        with self.lock:
            self.cookies = [c for c in self.cookies if c["label"] != label]
            self._save()

    def get(self) -> Optional[dict]:
        """
        轮询取一个可用 Cookie。
        - 跳过 disabled
        - 跳过 cooldown 期间
        - 优先选 fail_count 低 + 冷却时间最早的
        """
        with self.lock:
            now = int(time.time())
            available = [
                c for c in self.cookies
                if not c.get("disabled") and c.get("cooldown_until", 0) <= now
            ]
            if not available:
                return None
            # 选失败次数最少、上次用得最久的（轮询均匀）
            available.sort(key=lambda c: (c["fail_count"], c["last_used_at"]))
            chosen = available[0]
            chosen["last_used_at"] = now
            chosen["use_count"] += 1
            self._save()
            return chosen

    def report_success(self, label: str):
        """用完 Cookie 后调用，标记成功（重置 fail 计数）"""
        with self.lock:
            for c in self.cookies:
                if c["label"] == label:
                    c["fail_count"] = 0
                    c["cooldown_until"] = 0
                    break
            self._save()

    def report_failure(self, label: str, cooldown_sec: int = 60):
        """用完 Cookie 后调用，标记失败（fail_count++，进入冷却）"""
        with self.lock:
            for c in self.cookies:
                if c["label"] == label:
                    c["fail_count"] += 1
                    # 失败 3 次以上 → 临时禁用 5 分钟
                    if c["fail_count"] >= 3:
                        c["cooldown_until"] = int(time.time()) + 300
                    else:
                        c["cooldown_until"] = int(time.time()) + cooldown_sec
                    break
            self._save()

    def status(self) -> dict:
        with self.lock:
            now = int(time.time())
            return {
                "total": len(self.cookies),
                "available": sum(
                    1 for c in self.cookies
                    if not c.get("disabled") and c.get("cooldown_until", 0) <= now
                ),
                "in_cooldown": sum(
                    1 for c in self.cookies
                    if c.get("cooldown_until", 0) > now
                ),
                "disabled": sum(1 for c in self.cookies if c.get("disabled")),
                "cookies": [
                    {
                        "label": c["label"],
                        "use_count": c["use_count"],
                        "fail_count": c["fail_count"],
                        "in_cooldown": c.get("cooldown_until", 0) > now,
                        "disabled": c.get("disabled", False),
                    }
                    for c in self.cookies
                ],
            }


# 全局单例
pool = CookiePool()


def parse_cookie_header(cookie_str: str) -> dict:
    """把 'a=1; b=2' 解析成 dict"""
    return dict(
        item.strip().split("=", 1)
        for item in cookie_str.split(";")
        if "=" in item
    )
