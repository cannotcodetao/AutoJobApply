#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AutoJobApply · 简历邮件投递器。

安全设计（全部是硬约束，不是建议）
----------------------------------
1. **默认干跑。** 不加 ``--send`` 只打印预览，绝不连接 SMTP。
2. **双重确认。** ``--send`` 必须同时带 ``--approved`` 才会真实发送，否则打印核对表
   并以**退出码 3** 拦截。``--approved`` 的语义是：**用户已逐行确认过核对表**。
3. **五项缺一不可。** 公司 / 岗位 / 地点 / 收件人 / 来源验证，任一缺失即拒发该目标。
4. **幂等。** 已成功发送的目标记录在发送日志里，重跑自动跳过；``--force`` 才重发。
5. **附件缺失即拒发**，绝不发出没有简历的邮件。
6. **凭据只来自环境变量**，不落盘。
7. 每个收件人之间有间隔，降低被邮件服务商风控的概率。

用法
----
::

    python scripts/send_resume.py                          # 预览（干跑）
    python scripts/send_resume.py --list                   # 只列状态
    python scripts/send_resume.py --send                   # 会被拦截（缺 --approved）
    python scripts/send_resume.py --send --approved        # 真实发送
    python scripts/send_resume.py --send --approved --only D1
    python scripts/send_resume.py --send --approved --force # 忽略日志强制重发
"""

from __future__ import annotations

import argparse
import hashlib
import json
import smtplib
import ssl
import sys
import time
from datetime import datetime
from email.header import Header
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _config
import _draft


# ---------------------------------------------------------------- 日志


def load_log(cfg) -> dict:
    path = _config.path_of(cfg, "paths.send_log", "state/send_log.json")
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "sends" in data:
                return data
        except Exception:  # noqa: BLE001
            pass
    return {"version": 1, "sends": []}


def save_log(cfg, log: dict) -> Path:
    path = _config.path_of(cfg, "paths.send_log", "state/send_log.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------- 附件


def resolve_attachments(cfg, meta: dict) -> list:
    attach_root = _config.path_of(cfg, "paths.attachments", "attachments")
    base = attach_root.parent  # 允许草稿里写 attachments/xxx 或绝对路径
    paths = []
    for item in str(meta.get("ATTACH", "") or "").split(";"):
        rel = item.strip()
        if not rel:
            continue
        candidate = Path(rel)
        if not candidate.is_absolute():
            candidate = base / rel
        paths.append(candidate.resolve())
    return paths


def file_digest(paths) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


# ---------------------------------------------------------------- 组信


def build_message(cfg, meta: dict, attachments, sender_email: str):
    msg = MIMEMultipart()

    from_name = _config.get(cfg, "sender.from_name", "") or ""
    msg["From"] = formataddr((str(Header(from_name, "utf-8")), sender_email)) if from_name else sender_email
    msg["To"] = str(meta.get("TO", ""))
    if meta.get("CC"):
        msg["Cc"] = str(meta["CC"])
    msg["Subject"] = Header(str(meta.get("SUBJECT", "")), "utf-8")

    body = str(meta.get("BODY", "") or "")
    msg.attach(MIMEText(body, "plain", "utf-8"))

    for path in attachments:
        part = MIMEApplication(path.read_bytes(), Name=path.name)
        part.add_header(
            "Content-Disposition",
            "attachment",
            filename=("utf-8", "", path.name),
        )
        msg.attach(part)

    return msg


# ---------------------------------------------------------------- 发送


def send_one(cfg, meta: dict, attachments, sender_email: str, authcode: str) -> None:
    host = _config.get(cfg, "sender.smtp_host", "smtp.qq.com")
    port = int(_config.get(cfg, "sender.smtp_port", 465))
    recipients = _draft.parse_recipients(meta)

    msg = build_message(cfg, meta, attachments, sender_email)

    context = ssl.create_default_context()
    if port == 465:
        server = smtplib.SMTP_SSL(host, port, context=context, timeout=45)
    else:
        server = smtplib.SMTP(host, port, timeout=45)
        server.starttls(context=context)

    try:
        server.login(sender_email, authcode)
        server.sendmail(sender_email, recipients, msg.as_string())
    finally:
        try:
            server.quit()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------- 主流程


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="简历邮件投递（默认干跑）")
    parser.add_argument("--send", action="store_true", help="真实发送（默认只预览）")
    parser.add_argument("--approved", action="store_true",
                        help="确认已取得用户对核对表的批准（--send 的必备配套）")
    parser.add_argument("--only", default="", help="只处理指定 ID，逗号分隔")
    parser.add_argument("--force", action="store_true", help="忽略发送日志，强制重发")
    parser.add_argument("--list", action="store_true", help="只列状态，不做任何事")
    parser.add_argument("--include-unverified", action="store_true",
                        help="连来源未核实的目标也纳入（不推荐）")
    parser.add_argument("--limit", type=int, default=0, help="本次最多发送几封")
    parser.add_argument("--config", default="", help="指定配置文件")
    args = parser.parse_args(argv)

    # ---- 配置 ----
    try:
        cfg = _config.load_config(args.config or None)
    except _config.ConfigError as exc:
        return _config.fail(exc)

    sender_email = str(_config.get(cfg, "sender.email", "") or "")
    if not sender_email or "@" not in sender_email:
        return _config.fail(_config.ConfigError("sender.email 未正确配置"))

    # ---- 草稿 ----
    draft_dir = _config.path_of(cfg, "paths.drafts", "drafts")
    drafts = _draft.load_drafts(draft_dir)
    if not drafts:
        print(f"在 {draft_dir} 下没有找到任何草稿。")
        return 0

    only = {item.strip().upper() for item in args.only.split(",") if item.strip()}
    if only:
        drafts = [d for d in drafts if d["ID"].upper() in only]
        if not drafts:
            print(f"没有匹配 ID {args.only} 的草稿。")
            return 0

    log = load_log(cfg)
    sent = {record.get("id"): record for record in log.get("sends", [])}
    max_per_run = int(_config.get(cfg, "safety.max_sends_per_run", 10) or 10)

    # ---- 逐个判定 ----
    plan = []
    for meta in drafts:
        draft_id = meta["ID"]
        problems = _draft.check(meta)

        if draft_id in sent and not args.force:
            plan.append((meta, "SKIP", f"已于 {_short_time(sent[draft_id].get('sent_at'))} 发送，跳过"))
            continue

        if problems:
            plan.append((meta, "BLOCK", "；".join(problems)))
            continue

        verified = str(meta.get("VERIFIED", "") or "")
        if _looks_unverified(verified) and not args.include_unverified:
            plan.append((meta, "BLOCK", "邮箱来源未完成核实，加 --include-unverified 可强行纳入"))
            continue

        plan.append((meta, "READY", ""))

    ready = [item for item in plan if item[1] == "READY"]

    # ---- --list ----
    if args.list:
        _print_plan(cfg, plan, sent)
        return 0

    # ---- 预览 ----
    _print_plan(cfg, plan, sent, verbose=True)

    if not args.send:
        print("\n当前为预览模式，未发送任何邮件。")
        print("确认无误后，把上面的就绪项加上 --send --approved 重新运行：")
        print("    python scripts/send_resume.py --send --approved")
        return 0

    # ---- 用户确认闸门 ----
    if _config.force_dry_run():
        print("\n环境变量 AUTOJOB_DRY_RUN=1 生效，本次不真实发送。")
        return 0

    if not args.approved:
        print()
        print("!" * 78)
        print("已拦截：--send 未附带 --approved —— 尚未取得用户对核对表的确认。")
        print("!" * 78)
        if ready:
            print("先执行核对表并把结果交给用户过目：")
            print("    python scripts/preflight.py --dns --html")
            print("用户明确确认后，再执行：")
            print("    python scripts/send_resume.py --send --approved")
        print()
        return 3

    if not ready:
        print("\n没有可发送的目标，结束。")
        return 0

    if args.limit and len(ready) > args.limit:
        print(f"\n本次限制发送 {args.limit} 封（共 {len(ready)} 封就绪），其余下次再发。")
        ready = ready[: args.limit]

    # ---- 发送前 MX 复核 ----
    # 「SMTP 返回 250」只说明我的发件服务器接受了这封信。若收件域名的 MX
    # 指向一台不存在的主机，这封信会在几秒后被退回——曾经真实发生过。
    # 所以在真正投出去之前，再确认一次对方域名还活着。
    if _config.get(cfg, "safety.verify_mx_before_send", True):
        ready = _mx_gate(ready)
        if not ready:
            print("\n所有目标的收件域名都无法收信，已全部拦下，一封都没发。")
            return 4

    # ---- 凭据 ----
    try:
        code = _config.authcode(cfg)
    except _config.ConfigError as exc:
        return _config.fail(exc)

    # ---- 真正发送 ----
    interval = int(_config.get(cfg, "sender.interval_sec", 25) or 25)
    print()
    print(f"发件邮箱：{sender_email}")
    print(f"发送间隔：{interval} 秒")
    print()

    ok = failed = 0
    for index, (meta, _status, _reason) in enumerate(ready, start=1):
        attachments = resolve_attachments(cfg, meta)
        label = meta.get("COMPANY", meta["FILE"])
        recipients = _draft.parse_recipients(meta)

        print(f"[{index}/{len(ready)}] 发送中 -> {label} <{', '.join(recipients)}> … ", end="", flush=True)
        try:
            send_one(cfg, meta, attachments, sender_email, code)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"失败：{exc}")
            continue

        ok += 1
        print("成功")

        log["sends"].append({
            "id": meta["ID"],
            "company": meta.get("COMPANY", ""),
            "role": meta.get("ROLE", ""),
            "location": meta.get("LOCATION", ""),
            "location_alt": meta.get("LOCATION_ALT", ""),
            "to": meta.get("TO", ""),
            "cc": meta.get("CC", ""),
            "subject": meta.get("SUBJECT", ""),
            "attachments": [p.name for p in attachments],
            "digest": file_digest(attachments) if attachments else "",
            "verified_source": meta.get("VERIFIED", ""),
            "sent_at": datetime.now().isoformat(timespec="seconds"),
            "sender": sender_email,
            "delivery": "pending",
        })
        save_log(cfg, log)

        if index < len(ready) and interval > 0:
            time.sleep(interval)

    print()
    print("=" * 78)
    print(f"完成：成功 {ok} 封，失败 {failed} 封。日志：{save_log(cfg, log)}")
    print("=" * 78)

    if ok:
        print("\n别忘了：发送成功 ≠ 已送达。稍后跑一次核查：")
        print("    python scripts/verify_delivery.py")
    return 0


def _short_time(value) -> str:
    if not value:
        return "未知时间"
    try:
        return datetime.fromisoformat(str(value)).strftime("%m-%d %H:%M")
    except Exception:  # noqa: BLE001
        return str(value)


def _looks_unverified(text: str) -> bool:
    return any(marker.lower() in (text or "").lower() for marker in _draft.UNVERIFIED_MARKERS)


def _mx_gate(ready):
    """发送前的最后一道 MX 复核。返回仍然可发的目标列表。"""
    import preflight  # 同目录，复用同一套 MX 实现，避免两处逻辑漂移

    domains = sorted({
        address.split("@", 1)[1].lower()
        for meta, _status, _reason in ready
        for address in _draft.parse_recipients(meta)
        if "@" in address
    })
    if not domains:
        return ready

    print()
    print(f"[MX 复核] 检查 {len(domains)} 个收件域名 …")
    result = preflight.mx_check(domains)

    kept = []
    for meta, status, reason in ready:
        dead = []
        for address in _draft.parse_recipients(meta):
            if "@" not in address:
                continue
            domain = address.split("@", 1)[1].lower()
            state, detail = result.get(domain, ("未知", ""))
            # 只拦「MX 确实不可用」；本地 nslookup 跑不起来属于环境问题，放行并提示
            if state == "异常" and "nslookup" not in detail:
                dead.append(f"{domain}（{detail}）")

        if dead:
            print(f"  ❌ {meta['ID']} {meta.get('COMPANY', '')} —— 收件域名不可用：{'；'.join(dead)}")
            print("     已跳过。请改用其他有效地址重投，或直接走网申。")
            continue

        print(f"  ✅ {meta['ID']} {meta.get('COMPANY', '')}")
        kept.append((meta, status, reason))

    return kept


def _print_plan(cfg, plan, sent, *, verbose: bool = False) -> None:
    print("=" * 78)
    print("简历邮件投递 | " + ("预览（未发送）" if verbose else "目标状态"))
    print("=" * 78)

    marks = {"READY": "[就绪]", "SKIP": "[跳过]", "BLOCK": "[阻断]"}
    for meta, status, reason in plan:
        print()
        print(f"{marks[status]} {meta['ID']}  {meta.get('COMPANY', meta['FILE'])}")
        if status == "SKIP" and not verbose:
            print(f"       {reason}")
            continue

        print(f"       岗位   : {meta.get('ROLE', '（未填）')}")
        print(f"       地点   : {meta.get('LOCATION', '（未填）')}")
        print(f"       收件人 : {meta.get('TO', '（未填）')}")
        if meta.get("CC"):
            print(f"       抄送   : {meta['CC']}")
        print(f"       主题   : {meta.get('SUBJECT', '（未填）')}")

        attach_root = _config.path_of(cfg, "paths.attachments", "attachments").parent
        attachments = []
        for item in str(meta.get("ATTACH", "") or "").split(";"):
            rel = item.strip()
            if not rel:
                continue
            candidate = Path(rel) if Path(rel).is_absolute() else attach_root / rel
            attachments.append(candidate.name)
        print(f"       附件   : {', '.join(attachments) or '（无）'}")

        if status == "BLOCK":
            print(f"       阻断原因：{reason}")
        elif status == "SKIP":
            print(f"       跳过原因：{reason}")

    counts = {key: sum(1 for item in plan if item[1] == key) for key in ("READY", "SKIP", "BLOCK")}
    print()
    print("-" * 78)
    print(f"就绪 {counts['READY']} 封，跳过 {counts['SKIP']} 封，阻断 {counts['BLOCK']} 封")
    print("-" * 78)


if __name__ == "__main__":
    sys.exit(main())
