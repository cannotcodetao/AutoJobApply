#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AutoJobApply · 草稿解析与投递前校验。

草稿格式
--------
``drafts/`` 下每个 ``.txt`` 就是一封待发邮件。头部是 ``# KEY: value`` 形式的元信息，
以 ``# ---BODY---`` 为界，其后是邮件正文。

::

    # TO: hr@example.com
    # CC: hr2@example.com
    # SUBJECT: 应聘 2027 届校招·嵌入式软件工程师-{{姓名}}-{{学校}}-{{专业}}
    # ATTACH: attachments/resume.pdf ; attachments/resume.docx
    # COMPANY: 某某科技有限公司
    # ROLE: 嵌入式软件工程师
    # LOCATION: 深圳
    # VERIFIED: 企业官网招聘页原文「简历投递邮箱：hr@example.com」
    # ---BODY---

    尊敬的招聘老师：
    ……

必填五项（缺一即拒发）
----------------------
``COMPANY`` / ``ROLE`` / ``LOCATION`` / ``TO`` / ``VERIFIED``

为什么是这五项：它们分别防住一种真实的投错事故——投错主体、投错岗位序列、
投到不想去的城市、发给错误地址、以及把多校转载的二手邮箱当成已核实。
"""

from __future__ import annotations

import re
from pathlib import Path

from _config import REPO_ROOT

BODY_MARK = "# ---BODY---"

REQUIRED_FIELDS = ("COMPANY", "ROLE", "LOCATION", "TO", "VERIFIED")

FIELD_LABELS = {
    "COMPANY": "公司名称",
    "ROLE": "投递岗位",
    "LOCATION": "工作地点",
    "TO": "收件邮箱",
    "VERIFIED": "邮箱来源验证",
}

# 表示「还没核实完」的字样，命中即视为未核实
UNVERIFIED_MARKERS = ("待核实", "未核实", "待确认", "TODO", "unknown")

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

# 正文里需要人工复核的高风险表述 —— 只告警，不拦截
RISKY_PHRASES = [
    (re.compile(r"已(?:同步)?完成网申"), "断言已完成网申，除非真的提交过，否则改为「我会通过……提交网申」"),
    (re.compile(r"(?:头部|领军|龙头|顶尖|一流)企业"), "对企业地位的评价性断言，需有可引用的原始出处，否则删除"),
    (re.compile(r"(?:已|曾)?与贵司.{0,6}(?:深度)?合作"), "暗示既有合作关系，需确有其事"),
    (re.compile(r"贵司.{0,10}(?:唯一|首家|最大)"), "最高级断言，需有可引用的原始出处"),
]


# ---------------------------------------------------------------- 解析


def parse_draft(path) -> dict:
    """解析单个草稿文件，返回 ``{ID, FILE, PATH, <元信息大写键>, BODY}``。"""
    path = Path(path)
    text = path.read_text(encoding="utf-8")

    if BODY_MARK in text:
        head, body = text.split(BODY_MARK, 1)
    else:
        head, body = text, ""

    meta = {}
    for line in head.splitlines():
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        content = stripped.lstrip("#").strip()
        if ":" not in content:
            continue
        key, _, value = content.partition(":")
        key = key.strip().upper()
        if not key:
            continue
        meta[key] = value.strip()

    # ID 取文件名下划线前的部分：D1_某某公司.txt -> D1
    draft_id = path.stem.split("_", 1)[0]

    record = {"ID": draft_id, "FILE": path.name, "PATH": str(path), "BODY": body.strip()}
    record.update(meta)
    return record


def load_drafts(draft_dir) -> list:
    """读取目录下全部草稿，按 ID 排序。"""
    directory = Path(draft_dir)
    if not directory.is_dir():
        return []
    return [parse_draft(p) for p in sorted(directory.glob("*.txt")) if not p.name.startswith("_")]


# ---------------------------------------------------------------- 收件人


def parse_recipients(meta: dict) -> list:
    """合并 TO 与 CC，支持逗号或分号分隔，去重保序。"""
    result = []
    for key in ("TO", "CC"):
        raw = str(meta.get(key, "") or "")
        for item in re.split(r"[,;，；]", raw):
            address = item.strip()
            if address and address not in result:
                result.append(address)
    return result


def split_addresses(raw: str) -> list:
    """把一段地址文本拆成列表（用于分别校验 TO 与 CC）。"""
    return [item.strip() for item in re.split(r"[,;，；]", raw or "") if item.strip()]


# ---------------------------------------------------------------- 校验


def check(meta: dict, *, attach_root=None) -> list:
    """返回阻断性问题列表。空列表 = 可以发送。"""
    problems = []

    # ---- 1. 五项必填 ----
    for field in REQUIRED_FIELDS:
        value = str(meta.get(field, "") or "").strip()
        if not value:
            problems.append(f"缺少必填项 {FIELD_LABELS[field]}（{field}）")
        elif PLACEHOLDER_LEFT(value):
            problems.append(f"{FIELD_LABELS[field]}（{field}）仍是占位符：{value}")

    # ---- 2. 邮箱格式 ----
    for key in ("TO", "CC"):
        for address in split_addresses(str(meta.get(key, "") or "")):
            if not EMAIL_RE.match(address):
                problems.append(f"{key} 中的地址格式不合法：{address}")

    # ---- 3. TO 与 CC 查重 ----
    to_list = {a.lower() for a in split_addresses(str(meta.get("TO", "") or ""))}
    cc_list = {a.lower() for a in split_addresses(str(meta.get("CC", "") or ""))}
    overlap = to_list & cc_list
    if overlap:
        problems.append(f"同一地址同时出现在 TO 与 CC：{'、'.join(sorted(overlap))}")

    # ---- 4. 来源验证不能是「待核实」----
    verified = str(meta.get("VERIFIED", "") or "")
    for marker in UNVERIFIED_MARKERS:
        if marker.lower() in verified.lower():
            problems.append(f"邮箱来源仍标注为「{marker}」，未完成核实")
            break

    # ---- 5. 正文不能为空 ----
    if not str(meta.get("BODY", "") or "").strip():
        problems.append("正文为空")

    # ---- 6. 主题缺失（非阻断但必须提示）----
    if not str(meta.get("SUBJECT", "") or "").strip():
        problems.append("缺少 SUBJECT（邮件主题）")

    # ---- 7. 附件必须真实存在 ----
    attach_root = Path(attach_root) if attach_root else REPO_ROOT
    for item in str(meta.get("ATTACH", "") or "").split(";"):
        rel = item.strip()
        if not rel:
            continue
        candidate = Path(rel)
        if not candidate.is_absolute():
            candidate = attach_root / rel
        if not candidate.exists():
            problems.append(f"附件不存在：{rel}")

    return problems


def PLACEHOLDER_LEFT(value: str) -> bool:
    """值里是否还残留 ``{{占位符}}``。"""
    return bool(re.search(r"\{\{[A-Z0-9_]+\}\}", value or ""))


def warnings(meta: dict) -> list:
    """非阻断但值得人工复核的提示。"""
    notes = []
    body = str(meta.get("BODY", "") or "")

    for pattern, advice in RISKY_PHRASES:
        match = pattern.search(body)
        if match:
            notes.append(f"正文出现「{match.group(0)}」——{advice}")

    if len(body) > 0 and len(body) < 200:
        notes.append(f"正文仅 {len(body)} 字符，可能过于简短")

    if len(body) > 3000:
        notes.append(f"正文 {len(body)} 字符，HR 阅读成本偏高，建议压缩到 1500 字以内")

    return notes


def summary_line(meta: dict) -> str:
    """一行摘要，用于列表展示。"""
    company = meta.get("COMPANY", "（未填公司）")
    role = meta.get("ROLE", "（未填岗位）")
    location = meta.get("LOCATION", "（未填地点）")
    return f"{company} · {role} · {location}"
