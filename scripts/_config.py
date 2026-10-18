#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AutoJobApply · 统一配置加载与校验。

设计原则
--------
1. **配置与凭据分离。** config.json 只放非敏感配置；邮箱授权码/密码**只从环境变量读取**，
   永不落盘，因此仓库里不可能存在可被 commit 的密码。
2. **占位符即错误。** config.example.json 里的 ``{{...}}`` 若未替换，加载时直接失败并列出
   全部未填项，避免「拿模板配置当真配置」把邮件发到占位符地址这类事故。
3. **路径与工作目录解耦。** 配置里的相对路径一律相对**仓库根**解析，脚本从任何工作目录
   调用都能正常跑。

环境变量
--------
``AUTOJOB_CONFIG``   指定配置文件路径（默认 ``config/config.json``）
``AUTOJOB_AUTHCODE`` 邮箱 SMTP/IMAP 授权码（**必填**，或改用 config 中 ``authcode_env`` 指定的变量名）
``AUTOJOB_DRY_RUN``  设为 ``1`` 时强制全局干跑，任何脚本都不会真实发信
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------- 基础路径

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_CONFIG = REPO_ROOT / "config" / "config.json"
EXAMPLE_CONFIG = REPO_ROOT / "config" / "config.example.json"

# 占位符形如 {{NAME}} 或 {{姓名}}——必须允许非 ASCII，
# 否则用中文写的占位符会被漏检，模板就可能在未填写的情况下被当成真配置使用。
PLACEHOLDER_RE = re.compile(r"\{\{[^{}\n]+\}\}")

# 敏感字段名（出现在 config.json 里就报警，提示改用环境变量）
SENSITIVE_KEYS = {"authcode", "password", "passwd", "smtp_password", "token", "secret"}


class ConfigError(RuntimeError):
    """配置不可用。调用方应捕获后原样退出，不要吞掉。"""


# ---------------------------------------------------------------- 占位符检测


def find_placeholders(node, trail: str = "") -> list:
    """递归找出所有未替换的 ``{{占位符}}``，返回 ``路径 -> 占位符`` 的可读列表。

    以 ``_`` 开头的键视为注释（如 ``_comment``），整棵子树跳过——
    注释里经常会写 ``{{...}}`` 作为示例，不能当成未填项报出来。
    """
    found = []

    if isinstance(node, dict):
        for key, value in node.items():
            if str(key).startswith("_"):
                continue
            found.extend(find_placeholders(value, f"{trail}.{key}" if trail else str(key)))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(find_placeholders(value, f"{trail}[{index}]"))
    elif isinstance(node, str):
        for match in PLACEHOLDER_RE.findall(node):
            found.append(f"{trail or '(根)'} -> {match}")

    return found


# ---------------------------------------------------------------- 配置加载


def config_path() -> Path:
    """当前生效的配置文件路径。"""
    override = os.environ.get("AUTOJOB_CONFIG", "").strip()
    return Path(override).expanduser().resolve() if override else DEFAULT_CONFIG


def load_config(path=None, *, strict: bool = True, quiet: bool = False) -> dict:
    """加载并校验配置。

    参数
    ----
    path   : 配置文件路径；默认取 ``AUTOJOB_CONFIG`` 或 ``config/config.json``
    strict : True 时，未填占位符 / 缺凭据即抛 ConfigError；False 时只告警
    quiet  : True 时不打印加载提示

    返回符合 config.example.json 结构的 dict。
    """
    target = Path(path).expanduser().resolve() if path else config_path()

    if not target.exists():
        raise ConfigError(
            f"配置文件不存在：{target}\n"
            f"请先复制模板：cp \"{EXAMPLE_CONFIG}\" \"{target}\"\n"
            f"然后按 config/README.md 填写（或保留占位符，脚本会在校验阶段报错提示具体项）。"
        )

    try:
        raw = target.read_text(encoding="utf-8")
        cfg = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"配置文件不是合法 JSON：{target}\n  第 {exc.lineno} 行：{exc.msg}") from exc

    # ---- 占位符未替换 ----
    holes = find_placeholders(cfg)
    if holes:
        listing = "\n".join(f"  · {item}" for item in holes)
        message = (
            f"配置里还有 {len(holes)} 项占位符未填写：\n{listing}\n"
            f"请在 {target} 中替换后再运行。"
        )
        if strict:
            raise ConfigError(message)
        if not quiet:
            print(f"[警告] {message}", file=sys.stderr)

    # ---- 敏感信息不该出现在配置文件里 ----
    leaked = [key for key in _all_keys(cfg) if key.lower() in SENSITIVE_KEYS]
    if leaked:
        message = (
            "配置文件中出现了疑似敏感字段："
            + "、".join(sorted(set(leaked)))
            + "\n请改用环境变量（见 config/README.md），不要把密码写进配置文件。"
        )
        if strict:
            raise ConfigError(message)
        if not quiet:
            print(f"[警告] {message}", file=sys.stderr)

    if not quiet:
        print(f"[配置] {target}")
    return cfg


def _all_keys(node):
    """递归收集所有 dict 的键名（跳过 ``_`` 注释键）。"""
    if isinstance(node, dict):
        for key, value in node.items():
            if str(key).startswith("_"):
                continue
            yield str(key)
            yield from _all_keys(value)
    elif isinstance(node, list):
        for value in node:
            yield from _all_keys(value)


# ---------------------------------------------------------------- 取值辅助


def get(cfg: dict, dotted: str, default=None):
    """按点号路径取值：``get(cfg, "sender.smtp_host")``。"""
    node = cfg
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def path_of(cfg: dict, dotted: str, default_rel: str = "") -> Path:
    """按点号路径取路径值，相对仓库根解析为绝对路径。"""
    rel = get(cfg, dotted, default_rel) or default_rel
    candidate = Path(str(rel))
    return candidate if candidate.is_absolute() else (REPO_ROOT / candidate).resolve()


# ---------------------------------------------------------------- 凭据


def authcode(cfg: dict, *, required: bool = True) -> str:
    """取邮箱授权码。只认环境变量。

    config 中的 ``sender.authcode_env`` 用于自定义变量名（默认 ``AUTOJOB_AUTHCODE``），
    这样同一个账号可以有多个环境变量并存，也方便 CI 注入。
    """
    env_name = get(cfg, "sender.authcode_env", "AUTOJOB_AUTHCODE") or "AUTOJOB_AUTHCODE"
    value = os.environ.get(env_name, "").strip()

    if not value and required:
        raise ConfigError(
            f"缺少邮箱授权码：环境变量 {env_name} 未设置。\n"
            "  设置方法（任选其一）：\n"
            f"    · 当前终端：export {env_name}='你的授权码'\n"
            f"    · Windows PowerShell：$env:{env_name}='你的授权码'\n"
            "  注意：是邮箱的「SMTP/IMAP 授权码」，不是登录密码。\n"
            "  QQ 邮箱开启路径：设置 → 账号 → POP3/IMAP/SMTP 服务 → 生成授权码"
        )
    return value


def force_dry_run() -> bool:
    """``AUTOJOB_DRY_RUN=1`` 是全局干跑开关，优先级高于命令行参数。"""
    return os.environ.get("AUTOJOB_DRY_RUN", "").strip() in {"1", "true", "TRUE", "yes"}


# ---------------------------------------------------------------- CLI 引导


def fail(exc: Exception, exit_code: int = 2) -> int:
    """统一把 ConfigError 打印成人类可读的错误，返回退出码。"""
    print()
    print("!" * 78)
    print(f"无法继续：{exc}")
    print("!" * 78)
    return exit_code


def bootstrap(argv=None):
    """供各脚本共用的入口包装：解析 --config，加载配置，异常转退出码。

    用法::

        cfg = bootstrap()          # 直接拿配置
        if cfg is None: sys.exit(2)
    """
    import argparse

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--config", default="", help="指定配置文件（默认 config/config.json）")
    args, _rest = parser.parse_known_args(argv)

    try:
        return load_config(args.config or None)
    except ConfigError as exc:
        fail(exc)
        return None
