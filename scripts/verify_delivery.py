#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AutoJobApply · 投递送达核查器。

**送达是分级的，汇报时绝不能混为一谈。**

    ① SMTP 返回 250      = 我的发件服务器接受了这封信（最弱）
    ② 域名 MX 体检        = 对方域名当前能收信
    ③ 无退信 / RCPT 探测  = 地址很可能真实存在
    ④ HR 已读到           = 只能等回信，任何工具都测不出来

本脚本覆盖 ①~③，并把结论按级别分开呈现，避免「发出去了」被误读成「送到了」。

五部分
------
1. **发送日志明细** —— 发了什么、发到哪、日志里记录的送达状态
2. **MX 体检** —— 收件域名是否还能收信
3. **退信扫描** —— 收件箱 + 垃圾箱里的退信，并归因到具体收件地址
4. **「已发送」逐地址检索** —— 关键：**不看总数，按地址逐个查**
5. **RCPT 探测**（可选）—— 只探地址是否存在，不登录、不发信

用法
----
::

    python scripts/verify_delivery.py                 # 全量核查
    python scripts/verify_delivery.py --no-dns        # 跳过 MX（更快）
    python scripts/verify_delivery.py --log-only      # 只看本地日志
    python scripts/verify_delivery.py --days 30       # 只扫最近 30 天退信
    python scripts/verify_delivery.py --probe         # 额外做 RCPT 探测（慢）

本脚本**只读**：不修改日志、不发送任何邮件。
"""

from __future__ import annotations

import argparse
import email
import imaplib
import json
import re
import socket
import sys
from datetime import datetime, timedelta
from email.header import decode_header, make_header
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _config

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

BOUNCE_HINTS = (
    "退信", "无法送达", "投递失败", "未能送达", "退回",
    "undelivered", "undeliverable", "delivery status", "delivery failed",
    "mail delivery", "returned mail", "failure notice",
)

# 这些不是真实收件人，从 DSN 里提取时一律忽略
NOISE_LOCALPARTS = (
    "postmaster", "mailer-daemon", "mailerdaemon", "no-reply", "noreply",
    "localhost", "tencent_", "system",
)


def line(char="=", width=78) -> None:
    print(char * width)


def head(title: str) -> None:
    print()
    line()
    print(title)
    line()


# ---------------------------------------------------------------- 一、日志


def load_log(cfg) -> dict:
    path = _config.path_of(cfg, "paths.send_log", "state/send_log.json")
    if not path.exists():
        return {"sends": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"sends": []}


def show_log(records) -> None:
    head("第一部分：发送日志明细")

    if not records:
        print("日志为空：还没有任何发送记录。")
        return

    print(f"{'ID':<6}{'发送时间':<18}{'地点':<12}{'公司':<26}{'送达状态'}")
    line("-")

    for record in records:
        delivery = record.get("delivery", "pending")
        icon = {
            "pending": "待核查",
            "no_bounce_observed": "未见退信",
            "bounced": "已退信",
            "replied": "已回信",
        }.get(delivery, delivery)

        sent_at = str(record.get("sent_at", ""))[:16].replace("T", " ")
        print(
            f"{record.get('id', ''):<6}"
            f"{sent_at:<18}"
            f"{str(record.get('location', '—'))[:11]:<12}"
            f"{str(record.get('company', '—'))[:24]:<26}"
            f"{icon}"
        )

    print()
    print(f"合计 {len(records)} 封。发送成功不等于送达，请看下面三部分。")


def known_recipients(records) -> set:
    """日志里出现过的全部收件地址（含抄送），小写去重。"""
    result = set()
    for record in records:
        for key in ("to", "cc"):
            raw = str(record.get(key, "") or "")
            for item in re.split(r"[,;，；]", raw):
                address = item.strip().lower()
                if "@" in address:
                    result.add(address)
    return result


# ---------------------------------------------------------------- 二、MX


def show_mx(records) -> dict:
    head("第二部分：收件域名 MX 体检")

    domains = sorted({a.split("@", 1)[1] for a in known_recipients(records)})
    if not domains:
        print("没有收件域名可检查。")
        return {}

    import preflight  # 复用同一套实现，避免两处逻辑漂移

    result = preflight.mx_check(domains)
    for domain, (status, detail) in result.items():
        icon = "✅" if status == "正常" else "❌"
        print(f"  {icon} {domain:<34} {status}　{detail}")

    bad = [d for d, (s, _) in result.items() if s != "正常"]
    if bad:
        print()
        print(f"⚠️  {len(bad)} 个域名当前无法正常收信：{'、'.join(bad)}")
        print("   MX 记录可能指向了不存在的主机。这类域名的邮件一定会被退回。")
    return result


# ---------------------------------------------------------------- 三、退信


def decode_header_safe(raw) -> str:
    """解码邮件头。unknown-8bit 等非标准编码会让 make_header 抛异常。"""
    try:
        return str(make_header(decode_header(raw or "")))
    except Exception:  # noqa: BLE001
        try:
            return (raw or "").encode("utf-8", "ignore").decode("utf-8", "ignore")
        except Exception:  # noqa: BLE001
            return raw or ""


def scan_bounces(cfg, records, *, days: int = 0) -> dict:
    """扫描收件箱与垃圾箱，提取退信里提到的失败地址。"""
    head("第三部分：退信扫描（收件箱 + 垃圾箱）")

    try:
        code = _config.authcode(cfg, required=False)
    except _config.ConfigError:
        code = ""
    if not code:
        print("[跳过] 未设置授权码环境变量，无法登录 IMAP 扫描退信。")
        return {}

    sender = str(_config.get(cfg, "sender.email", "") or "")
    host = _config.get(cfg, "sender.imap_host", "imap.qq.com")
    port = int(_config.get(cfg, "sender.imap_port", 993))

    try:
        conn = imaplib.IMAP4_SSL(host, port)
        conn.login(sender, code)
    except Exception as exc:  # noqa: BLE001
        print(f"[跳过] IMAP 登录失败：{exc}")
        return {}

    since = ""
    if days > 0:
        since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")

    known = known_recipients(records)
    findings = {}
    considered = 0

    for mailbox in _candidate_mailboxes(conn, ("INBOX", "Junk", "Spam", "垃圾邮件")):
        try:
            status, _ = conn.select(mailbox, readonly=True)
            if status != "OK":
                continue
        except Exception:  # noqa: BLE001
            continue

        try:
            criteria = ("SINCE", since) if since else ("ALL",)
            status, data = conn.search(None, *criteria)
            if status != "OK":
                continue
            ids = data[0].split()
        except Exception:  # noqa: BLE001
            continue

        ids = ids[-300:]  # 只看最近 300 封，避免超时
        for msg_id in ids:
            try:
                status, parts = conn.fetch(
                    msg_id, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)] BODY.PEEK[TEXT])"
                )
                if status != "OK":
                    continue
                raw = b"".join(p[1] for p in parts if isinstance(p, tuple))
                message = email.message_from_bytes(raw)

                subject = decode_header_safe(message.get("Subject"))
                sender_hdr = decode_header_safe(message.get("From")).lower()
                text = raw.decode("utf-8", "ignore")

                is_bounce = (
                    any(hint in subject.lower() for hint in BOUNCE_HINTS)
                    or "postmaster" in sender_hdr
                    or "mailer-daemon" in sender_hdr
                )
                if not is_bounce:
                    continue

                considered += 1
                addresses = {a.lower() for a in EMAIL_RE.findall(text)}
                for address in addresses & known:
                    entry = findings.setdefault(address, {
                        "subject": subject[:70],
                        "date": str(message.get("Date", ""))[:31],
                        "mailbox": mailbox,
                    })
                    entry.setdefault("count", 0)
                    entry["count"] += 1
            except Exception:  # noqa: BLE001
                continue

    try:
        conn.logout()
    except Exception:  # noqa: BLE001
        pass

    if not findings:
        print(f"扫描了 {considered} 封疑似退信/系统邮件，")
        print("未发现指向本次投递收件地址的退信。✅")
        return {}

    print(f"发现 {len(findings)} 个地址存在退信记录：\n")
    for address, info in sorted(findings.items()):
        print(f"  ❌ {address}")
        print(f"     所在文件夹：{info['mailbox']}　时间：{info['date']}")
        print(f"     退信主题：{info['subject']}")
        print()

    print("提示：退信只说明这一个地址没收到。同公司的其他地址（尤其是抄送）可能正常，")
    print("      换地址重投前建议先用 --probe 做一次 RCPT 探测。")
    return findings


# ---------------------------------------------------------------- 四、已发送


def show_sent_folder(cfg, records) -> None:
    head("第四部分：邮箱「已发送」逐地址检索")

    try:
        code = _config.authcode(cfg, required=False)
    except _config.ConfigError:
        code = ""
    if not code:
        print("[跳过] 未设置授权码环境变量，无法登录 IMAP。")
        return

    sender = str(_config.get(cfg, "sender.email", "") or "")
    host = _config.get(cfg, "sender.imap_host", "imap.qq.com")
    port = int(_config.get(cfg, "sender.imap_port", 993))

    try:
        conn = imaplib.IMAP4_SSL(host, port)
        conn.login(sender, code)
    except Exception as exc:  # noqa: BLE001
        print(f"[跳过] IMAP 登录失败：{exc}")
        return

    mailboxes = [m for m in ("Sent Messages", "Sent", "&XfJT0ZAB-", "已发送") if m]
    selected = None
    for mailbox in mailboxes:
        try:
            status, _ = conn.select(mailbox, readonly=True)
            if status == "OK":
                selected = mailbox
                break
        except Exception:  # noqa: BLE001
            continue

    if not selected:
        print("[跳过] 找不到「已发送」文件夹（不同邮箱命名不同，可自行改脚本里的候选列表）。")
        conn.logout()
        return

    try:
        status, data = conn.search(None, "ALL")
        total = len(data[0].split()) if status == "OK" and data and data[0] else 0
        status, data = conn.search(None, "SINCE", datetime.now().strftime("%d-%b-%Y"))
        today = len(data[0].split()) if status == "OK" and data and data[0] else 0
        print(f"  [{selected}] 邮件总数：{total}　今日：{today}")
    except Exception:  # noqa: BLE001
        print(f"  [{selected}] 统计失败")

    addresses = sorted(known_recipients(records))
    if not addresses:
        print("\n日志里没有收件地址可检索。")
        conn.logout()
        return

    print()
    print("  按投递记录逐地址检索（命中 = 该封确有「已发送」副本）：")
    hits = 0
    for address in addresses:
        try:
            status, data = conn.search(None, "TO", address)
            count = len(data[0].split()) if status == "OK" and data and data[0] else 0
        except Exception:  # noqa: BLE001
            count = 0
        mark = "✅" if count else "— "
        hits += 1 if count else 0
        print(f"    {mark} {address:<38} {count} 封")

    print()
    print(f"  合计命中 {hits} / {len(addresses)} 个地址")
    print("  （未命中 ≠ 投递失败：若「SMTP 发信保存到服务器」开关是后开的，")
    print("    它不会补录开启之前发出的历史邮件）")

    conn.logout()


def _candidate_mailboxes(conn, wanted):
    """把候选文件夹名与实际存在的中文/编码名对上。"""
    try:
        status, data = conn.list()
        existing = b" ".join(data).decode("utf-8", "ignore") if status == "OK" else ""
    except Exception:  # noqa: BLE001
        existing = ""
    return [name for name in wanted if name.lower() in existing.lower()] or list(wanted[:1])


# ---------------------------------------------------------------- 五、RCPT


def probe_addresses(records) -> None:
    head("第五部分：SMTP RCPT 探测（只探地址存在，不发信）")

    addresses = sorted(known_recipients(records))
    if not addresses:
        print("没有可探测的地址。")
        return

    print("说明：连到对方 MX 的 25 端口做 EHLO/MAIL FROM/RCPT TO，不登录、不发正文。")
    print("      很多公司与云主机封了 25 端口出站，超时属正常现象，不代表地址不存在。\n")

    for address in addresses:
        domain = address.split("@", 1)[1]
        hosts, error = _mx_hosts(domain)
        if error:
            print(f"  ❌ {address:<38} {error}")
            continue

        verdict = "无法判定（连接失败）"
        for host in hosts:
            try:
                with socket.create_connection((host, 25), timeout=8) as sock:
                    sock.settimeout(8)
                    banner = sock.recv(1024).decode("utf-8", "ignore")
                    if not banner.startswith("220"):
                        continue
                    for command in (b"EHLO preflight.local\r\n", b"MAIL FROM:<>\r\n",
                                    f"RCPT TO:<{address}>\r\n".encode()):
                        sock.sendall(command)
                        reply = sock.recv(1024).decode("utf-8", "ignore")
                    if reply.startswith("250") or reply.startswith("251"):
                        verdict = "地址存在（250）"
                    elif reply.startswith("550") or reply.startswith("551"):
                        verdict = "地址不存在（5xx）"
                    else:
                        verdict = f"不确定（{reply[:40].strip()}）"
                    break
            except Exception:  # noqa: BLE001
                continue

        print(f"  · {address:<38} {verdict}")


def _mx_hosts(domain):
    import preflight

    return preflight.get_mx_hosts(domain)


# ---------------------------------------------------------------- 入口


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="投递送达核查（只读）")
    parser.add_argument("--no-dns", action="store_true", help="跳过 MX 体检")
    parser.add_argument("--log-only", action="store_true", help="只看本地发送日志")
    parser.add_argument("--probe", action="store_true", help="额外做 SMTP RCPT 探测（慢）")
    parser.add_argument("--days", type=int, default=0, help="只扫最近 N 天的退信")
    parser.add_argument("--config", default="", help="指定配置文件")
    args = parser.parse_args(argv)

    try:
        cfg = _config.load_config(args.config or None)
    except _config.ConfigError as exc:
        return _config.fail(exc)

    records = load_log(cfg).get("sends", [])

    show_log(records)

    if args.log_only:
        print("\n（--log-only：已跳过网络检查）")
        return 0

    bounces = {}
    if not args.no_dns:
        show_mx(records)

    bounces = scan_bounces(cfg, records, days=args.days)
    show_sent_folder(cfg, records)

    if args.probe:
        probe_addresses(records)

    # ---- 总结 ----
    head("总结")
    print(f"  SMTP 发送：成功 {len(records)} 封")
    if bounces:
        print(f"  已确认退信：{len(bounces)} 个地址　→　{'、'.join(sorted(bounces))}")
    else:
        print("  已确认退信：0 个地址")

    print()
    print("  能确认到什么程度（分级，不要混为一谈）：")
    print("    ① 邮件已被发件服务器接收（日志）      —— 最弱")
    print("    ② 收件域名 MX 正常（体检）            —— 域名能收信")
    print("    ③ 无退信 / RCPT 返回 250（扫描/探测） —— 地址很可能存在")
    print("    ④ HR 已读到                           —— 只能等回信，任何工具都测不出来")
    print()
    print("  再次提醒：SMTP 返回成功 ≠ 邮件已送达。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
