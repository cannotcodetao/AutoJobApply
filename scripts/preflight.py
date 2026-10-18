#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AutoJobApply · 投递前核对表生成器。

**这是整套流程里最重要的一道闸门。**

它把每一封待发邮件的五个关键事实摊开给人看：

    公司名称 / 投递岗位 / 工作地点 / 收件邮箱 / 邮箱来源验证

五项任一缺失或可疑，该目标即被标为「阻断」，不允许发送。这样做的原因很实际：
「邮箱可信」不等于「能送达」，也不等于「该投」。这些信息只有摊开给人看，
人才有办法拍板。

用法
----
::

    python scripts/preflight.py                 # 只列待投目标
    python scripts/preflight.py --all           # 连已投递的一起列
    python scripts/preflight.py --dns           # 额外做收件域名 MX 体检（较慢）
    python scripts/preflight.py --md --html     # 导出 Markdown 与 HTML
    python scripts/preflight.py --only D1,D2    # 只看指定目标

本脚本**只读**：不发信、不改日志、不动草稿。
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import socket
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _config
import _draft


# ---------------------------------------------------------------- MX 体检


def _nslookup(args) -> str:
    """执行 nslookup 并返回文本。

    Windows 下 nslookup 的输出是本地代码页（简体中文系统为 GBK），直接用
    ``text=True`` 会抛 UnicodeDecodeError。这里按字节捕获后容错解码——
    我们只关心 MX 主机名与 IP，都是 ASCII，中文乱码不影响判断。
    """
    try:
        proc = subprocess.run(args, capture_output=True, timeout=25)
    except Exception:  # noqa: BLE001
        return ""
    return proc.stdout.decode("utf-8", "ignore")


def get_mx_hosts(domain: str) -> tuple:
    """返回 ``(hosts, error)``。hosts 为 MX 主机名列表。"""
    output = _nslookup(["nslookup", "-type=mx", domain])
    if not output:
        return [], "nslookup 执行失败（可能未安装或无法联网）"

    hosts = []
    for line in output.splitlines():
        if "mail exchanger" not in line.lower():
            continue
        # Windows: MX preference = 5, mail exchanger = mx1.example.com
        # Linux  : example.com  mail exchanger = 5 mx1.example.com.
        tail = line.lower().split("mail exchanger")[-1]
        for token in re.findall(r"[a-z0-9][a-z0-9.\-]*\.[a-z]{2,}\.?", tail):
            host = token.rstrip(".")
            if host and host not in hosts:
                hosts.append(host)

    if not hosts:
        return [], "无 MX 记录"
    return hosts, ""


def host_has_ipv4(host: str) -> bool:
    """MX 主机能否解析出 IPv4。

    用 ``getaddrinfo`` 而不是 ``nslookup``：既避开编码问题，也避开
    「nslookup 先打印 IPv6 导致正则误判为无 IP」这个坑。
    """
    try:
        infos = socket.getaddrinfo(host, 25, socket.AF_INET, socket.SOCK_STREAM)
        return bool(infos)
    except Exception:  # noqa: BLE001
        return False


def mx_check(domains) -> dict:
    """对一组域名做 MX 体检，返回 ``域名 -> (状态, 说明)``。"""
    result = {}
    for domain in domains:
        hosts, error = get_mx_hosts(domain)
        if error:
            result[domain] = ("异常", error)
            continue

        alive = [h for h in hosts if host_has_ipv4(h)]
        if alive:
            result[domain] = ("正常", ", ".join(alive))
        else:
            result[domain] = ("异常", f"MX 主机 {'/'.join(hosts)} 无法解析出 IPv4")
    return result


def collect_domains(drafts) -> set:
    domains = set()
    for meta in drafts:
        for address in _draft.parse_recipients(meta):
            if "@" in address:
                domains.add(address.split("@", 1)[1].lower())
    return domains


# ---------------------------------------------------------------- 汇总


def build_rows(drafts, *, mx_map=None) -> list:
    rows = []
    for meta in drafts:
        problems = _draft.check(meta)
        notes = _draft.warnings(meta)

        domains = {a.split("@", 1)[1].lower() for a in _draft.parse_recipients(meta) if "@" in a}
        mx_info = []
        for domain in sorted(domains):
            if mx_map and domain in mx_map:
                status, detail = mx_map[domain]
                mx_info.append((domain, status, detail))

                # MX 查得到但不可用 = 这封信一定进不去。
                # 这不是建议，是阻断：曾经真实发生过「SMTP 返回成功、随后被退回」，
                # 原因就是收件域名的 MX 指向了一台不存在的主机。
                # 但「nslookup 本身跑不起来」属于本地环境问题，只警告不阻断。
                if status == "异常" and "nslookup" not in detail:
                    problems.append(
                        f"收件域名 {domain} 的 MX 不可用（{detail}）——该地址一定收不到信"
                    )
            else:
                mx_info.append((domain, "未检查", ""))

        rows.append({"meta": meta, "problems": problems, "notes": notes, "mx": mx_info})
    return rows


def is_blocked(row) -> bool:
    return bool(row["problems"])


# ---------------------------------------------------------------- 终端输出


LINE = "-" * 118


def render_terminal(rows, *, show_notes: bool = True) -> None:
    print("=" * 118)
    print("投递前核对表  ——  请逐行确认：公司名称 / 投递岗位 / 工作地点 / 收件邮箱 / 邮箱来源验证")
    print(f"生成时间：{dt.datetime.now():%Y-%m-%d %H:%M:%S}")
    print("=" * 118)

    if not rows:
        print("\n没有待核对的目标。")
        return

    ready = blocked = 0
    for row in rows:
        meta = row["meta"]
        if is_blocked(row):
            blocked += 1
            mark = "🔴 [阻断]"
        else:
            ready += 1
            mark = "🟢 [就绪]"

        print()
        print(f"{mark} {meta['ID']}　{meta.get('COMPANY', '（未填公司）')}")
        print(f"   岗位：{meta.get('ROLE', '（未填）')}")
        print(f"   地点：{meta.get('LOCATION', '（未填）')}")
        alt = meta.get("LOCATION_ALT", "")
        if alt:
            print(f"         （备选：{alt}）")

        to = str(meta.get("TO", "") or "")
        cc = str(meta.get("CC", "") or "")
        print(f"   收件：{to or '（未填）'}")
        if cc:
            print(f"   抄送：{cc}")

        print(f"   主题：{meta.get('SUBJECT', '（未填）')}")

        verified = str(meta.get("VERIFIED", "") or "")
        print(f"   来源：{verified[:160]}{'…' if len(verified) > 160 else ''}")

        for domain, status, detail in row["mx"]:
            icon = "✅" if status == "正常" else ("⚠️" if status == "未检查" else "❌")
            print(f"   MX  ：{domain} → {icon} {status}（{detail}）")

        if row["problems"]:
            print("   阻断项：")
            for item in row["problems"]:
                print(f"     ✗ {item}")

        if show_notes and row["notes"]:
            for item in row["notes"]:
                print(f"     ! {item}")

    print()
    print(LINE)
    print(f"合计 {len(rows)} 个目标：就绪 {ready} 个，阻断 {blocked} 个")
    print(LINE)


def render_rows_plain(rows) -> list:
    """把行数据转成 (状态, 公司, 岗位, 地点, 邮箱, 来源摘要) 便于导出。"""
    out = []
    for row in rows:
        meta = row["meta"]
        status = "阻断" if is_blocked(row) else "就绪"
        out.append({
            "ID": meta["ID"],
            "status": status,
            "company": meta.get("COMPANY", ""),
            "role": meta.get("ROLE", ""),
            "location": meta.get("LOCATION", ""),
            "to": meta.get("TO", ""),
            "cc": meta.get("CC", ""),
            "verified": meta.get("VERIFIED", ""),
            "problems": row["problems"],
            "mx": row["mx"],
        })
    return out


# ---------------------------------------------------------------- 导出 Markdown


def export_md(rows, out_path) -> Path:
    data = render_rows_plain(rows)
    lines = [
        "# 投递前核对表",
        "",
        f"> 生成时间：{dt.datetime.now():%Y-%m-%d %H:%M:%S}　"
        f"共 {len(data)} 个目标，就绪 {sum(1 for d in data if d['status'] == '就绪')} 个",
        ">",
        "> **请逐行确认以下五项后再授权发送。**",
        "",
        "| ID | 状态 | 公司名称 | 投递岗位 | 工作地点 | 收件邮箱 | 抄送 | 邮箱来源验证 |",
        "|----|------|----------|----------|----------|----------|------|--------------|",
    ]
    for item in data:
        icon = "🟢 就绪" if item["status"] == "就绪" else "🔴 阻断"
        verified = item["verified"].replace("|", "\\|")
        if len(verified) > 150:
            verified = verified[:150] + "…"
        lines.append(
            f"| {item['ID']} | {icon} | {item['company']} | {item['role']} | "
            f"{item['location']} | `{item['to']}` | `{item['cc']}` | {verified} |"
        )

    lines.append("")
    lines.append("## MX 体检")
    lines.append("")
    lines.append("| 域名 | 状态 | 说明 |")
    lines.append("|------|------|------|")
    seen = set()
    for item in data:
        for domain, status, detail in item["mx"]:
            if domain in seen:
                continue
            seen.add(domain)
            lines.append(f"| `{domain}` | {status} | {detail} |")

    blocked = [d for d in data if d["status"] == "阻断"]
    if blocked:
        lines.append("")
        lines.append("## 阻断项")
        lines.append("")
        for item in blocked:
            lines.append(f"**{item['ID']} {item['company']}**")
            for problem in item["problems"]:
                lines.append(f"- ✗ {problem}")
            lines.append("")

    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


# ---------------------------------------------------------------- 导出 HTML


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>投递前核对表</title>
<style>
  :root {{
    --bg:#0f1115; --panel:#171a21; --line:#2a2f3a; --ink:#e6e9ef; --ink2:#9aa4b2;
    --ok:#3fb950; --bad:#f85149; --warn:#d29922; --accent:#58a6ff;
  }}
  @media (prefers-color-scheme: light) {{
    :root {{
      --bg:#f6f7f9; --panel:#ffffff; --line:#e3e6ea; --ink:#1a1d22; --ink2:#5b6472;
      --ok:#1a7f37; --bad:#cf222e; --warn:#9a6700; --accent:#0969da;
    }}
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; padding:32px 20px 64px; background:var(--bg); color:var(--ink);
         font:15px/1.65 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif; }}
  .wrap {{ max-width:1180px; margin:0 auto; }}
  h1 {{ font-size:24px; margin:0 0 6px; letter-spacing:.3px; }}
  .sub {{ color:var(--ink2); font-size:13.5px; margin-bottom:22px; }}
  .stats {{ display:flex; gap:10px; margin-bottom:22px; flex-wrap:wrap; }}
  .stat {{ background:var(--panel); border:1px solid var(--line); border-radius:10px;
           padding:10px 16px; font-size:13.5px; }}
  .stat b {{ font-size:19px; margin-right:4px; }}
  .card {{ background:var(--panel); border:1px solid var(--line); border-radius:12px;
           padding:18px 20px; margin-bottom:14px; }}
  .card.blocked {{ border-left:3px solid var(--bad); }}
  .card.ready {{ border-left:3px solid var(--ok); }}
  .head {{ display:flex; align-items:center; gap:10px; margin-bottom:12px; flex-wrap:wrap; }}
  .badge {{ font-size:12px; padding:2px 9px; border-radius:999px; border:1px solid var(--line); }}
  .badge.ok {{ color:var(--ok); border-color:var(--ok); }}
  .badge.bad {{ color:var(--bad); border-color:var(--bad); }}
  .badge.id {{ color:var(--accent); border-color:var(--accent); font-family:ui-monospace,monospace; }}
  .co {{ font-size:17px; font-weight:600; }}
  table {{ width:100%; border-collapse:collapse; font-size:14px; }}
  th, td {{ text-align:left; padding:8px 10px; border-bottom:1px solid var(--line);
            vertical-align:top; }}
  th {{ color:var(--ink2); font-weight:500; width:96px; white-space:nowrap; }}
  td code {{ font-family:ui-monospace,SFMono-Regular,Consolas,monospace; font-size:13px;
             background:rgba(127,127,127,.12); padding:1px 6px; border-radius:4px; }}
  .problems {{ margin-top:12px; padding:10px 14px; border-radius:8px;
               background:rgba(248,81,73,.09); border:1px solid rgba(248,81,73,.35); }}
  .problems div {{ color:var(--bad); font-size:13.5px; }}
  .notes {{ margin-top:8px; font-size:13px; color:var(--warn); }}
  .foot {{ margin-top:26px; color:var(--ink2); font-size:12.5px; line-height:1.8;
           border-top:1px solid var(--line); padding-top:16px; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>投递前核对表</h1>
  <div class="sub">生成时间 {generated} · 请逐行确认五项后再授权发送</div>
  <div class="stats">
    <div class="stat"><b>{total}</b>个目标</div>
    <div class="stat"><b style="color:var(--ok)">{ready}</b>个就绪</div>
    <div class="stat"><b style="color:var(--bad)">{blocked}</b>个阻断</div>
  </div>
{cards}
  <div class="foot">
    核对五项：公司名称 · 投递岗位 · 工作地点 · 收件邮箱 · 邮箱来源验证。<br>
    任一为「阻断」的目标均不会被发送。本文件只读，不触发任何发送动作。
  </div>
</div>
</body>
</html>
"""


def _esc(text) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def export_html(rows, out_path) -> Path:
    data = render_rows_plain(rows)
    cards = []

    for item in data:
        ready = item["status"] == "就绪"
        mx_cells = ""
        for domain, status, detail in item["mx"]:
            badge = "ok" if status == "正常" else ("bad" if status == "异常" else "")
            mx_cells += (
                f'<tr><th>MX 体检</th><td><code>{_esc(domain)}</code> '
                f'<span class="badge {badge}">{_esc(status)}</span> {_esc(detail)}</td></tr>'
            )

        problems = ""
        if item["problems"]:
            items = "".join(f"<div>✗ {_esc(p)}</div>" for p in item["problems"])
            problems = f'<div class="problems">{items}</div>'

        cards.append(f"""  <div class="card {'ready' if ready else 'blocked'}">
    <div class="head">
      <span class="badge id">{_esc(item['ID'])}</span>
      <span class="badge {'ok' if ready else 'bad'}">{'就绪' if ready else '阻断'}</span>
      <span class="co">{_esc(item['company'])}</span>
    </div>
    <table>
      <tr><th>投递岗位</th><td>{_esc(item['role'])}</td></tr>
      <tr><th>工作地点</th><td>{_esc(item['location'])}</td></tr>
      <tr><th>收件邮箱</th><td><code>{_esc(item['to'])}</code></td></tr>
      <tr><th>抄送</th><td><code>{_esc(item['cc']) or '—'}</code></td></tr>
      <tr><th>邮箱来源验证</th><td>{_esc(item['verified'])}</td></tr>
      {mx_cells}
    </table>
    {problems}
  </div>""")

    html = HTML_TEMPLATE.format(
        generated=f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}",
        total=len(data),
        ready=sum(1 for d in data if d["status"] == "就绪"),
        blocked=sum(1 for d in data if d["status"] == "阻断"),
        cards="\n".join(cards) if cards else '  <div class="card">没有目标。</div>',
    )

    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding="utf-8")
    return target


# ---------------------------------------------------------------- 入口


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="投递前核对表（只读，不发信）")
    parser.add_argument("--only", default="", help="只看指定 ID，逗号分隔，如 D1,D2")
    parser.add_argument("--all", action="store_true", help="连已投递的目标一起列出")
    parser.add_argument("--dns", action="store_true", help="对收件域名做 MX 体检（较慢）")
    parser.add_argument("--md", action="store_true", help="导出 Markdown 到 state/preflight.md")
    parser.add_argument("--html", action="store_true", help="导出 HTML 到 state/preflight.html")
    parser.add_argument("--outdir", default="", help="导出目录（默认 state/）")
    parser.add_argument("--config", default="", help="指定配置文件")
    args = parser.parse_args(argv)

    try:
        cfg = _config.load_config(args.config or None, quiet=True)
    except _config.ConfigError as exc:
        return _config.fail(exc)

    draft_dir = _config.path_of(cfg, "paths.drafts", "drafts")
    drafts = _draft.load_drafts(draft_dir)

    if not drafts:
        print(f"在 {draft_dir} 下没有找到任何草稿（*.txt）。")
        print("可参考 drafts/_TEMPLATE.txt 新建一封。")
        return 0

    # 过滤：--only；默认排除已投递
    if args.only:
        wanted = {item.strip().upper() for item in args.only.split(",") if item.strip()}
        drafts = [d for d in drafts if d["ID"].upper() in wanted]
    elif not args.all:
        sent_ids = _load_sent_ids(cfg)
        drafts = [d for d in drafts if d["ID"] not in sent_ids]

    if not drafts:
        print("过滤后没有待核对的目标。加 --all 可查看全部。")
        return 0

    # ---- MX 体检 ----
    mx_map = {}
    if args.dns:
        domains = sorted(collect_domains(drafts))
        print(f"[MX 体检] 正在检查 {len(domains)} 个收件域名 …")
        mx_map = mx_check(domains)

    rows = build_rows(drafts, mx_map=mx_map)
    render_terminal(rows)

    # ---- 导出 ----
    outdir = Path(args.outdir) if args.outdir else _config.path_of(cfg, "paths.state", "state")
    if args.md:
        print(f"\n已导出 Markdown：{export_md(rows, outdir / 'preflight.md')}")
    if args.html:
        print(f"已导出 HTML　　：{export_html(rows, outdir / 'preflight.html')}")

    if any(is_blocked(row) for row in rows):
        print("\n存在阻断项。请先修正草稿，再重新生成核对表。")
        return 3

    print("\n下一步：把上表给用户过目 → 用户明确确认后执行")
    print("    python scripts/send_resume.py --send --approved")
    return 0


def _load_sent_ids(cfg) -> set:
    """从发送日志里读出已成功的 ID，用于默认跳过。"""
    import json

    log_path = _config.path_of(cfg, "paths.send_log", "state/send_log.json")
    if not log_path.exists():
        return set()
    try:
        data = json.loads(log_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return set()
    return {record.get("id", "") for record in data.get("sends", [])}


if __name__ == "__main__":
    sys.exit(main())
