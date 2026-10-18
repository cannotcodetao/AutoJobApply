# AutoJobApply

**A guarded, auditable, no-false-claims pipeline for emailing your résumé to campus recruiters.**

Not a bulk sender. The whole point is to **stop the one email that shouldn't go out**.

<p align="center">
  <img src="assets/workflow.svg" alt="AutoJobApply workflow" width="880">
</p>

---

## Features

Everything below is implemented by the six Python scripts in `scripts/` plus the rule files in `docs/` and `prompts/`.

### Seven-step pipeline

Research → verify and grade the address → match the role → customise the email → build a preflight checklist → user approval gate → delivery verification.
Each step has a corresponding script or checklist; a step never starts without the previous step's output. See [`docs/01-workflow.md`](docs/01-workflow.md).

### Module-by-module

| File | Capability |
|---|---|
| `scripts/_config.py` | Central config loading. Credentials are read **only from environment variables**, never written to disk; unfilled `{{placeholders}}` abort on load instead of sending to a template address |
| `scripts/_draft.py` | Draft parsing plus the five pre-send field checks; flags **high-risk phrasing** in the body (warning only, never a substitute for human review) |
| `scripts/preflight.py` | Preflight checklist generator. Five fields (company / role / work location / recipient / source verification) — any missing one marks the target "blocked" and refuses to send with exit code 3; optional MX health check; can export Markdown / HTML |
| `scripts/send_resume.py` | Idempotent sender. Dry-run by default; `--send` must be paired with `--approved` or it is blocked with exit code 3; the recipient domain MX is re-checked immediately before sending; duplicate checks across To and Cc; refuses to send when an attachment is missing |
| `scripts/verify_delivery.py` | Five-part delivery verification: send log / MX health check / bounce scan / per-address search in "Sent" / optional RCPT probe |
| `scripts/make_stats.py` | Application stats generator (xlsx + md) with a built-in "business scope character count" self-check and a cross-check between the send log and the work location in the stats table |

### Three non-negotiables

**1. "Sent" is not "delivered".** Delivery is reported at four distinct levels, always kept separate:

| Level | Method | What it actually proves |
|---|---|---|
| ① | SMTP `250` | My sending server accepted it (**weakest**) |
| ② | Recipient domain MX health check | The domain can currently receive mail |
| ③ | No bounce / RCPT `250` | The mailbox very likely exists |
| ④ | A human replies | Someone actually read it — **unobservable by any tool** |

**2. No false statements.** If the online application form was not submitted, do not write "I have completed the application"; disclose skill gaps as they are. `scripts/_draft.py` flags these patterns:

| High-risk pattern | Risk |
|---|---|
| 已(同步)?完成网申 | Asserts completion unless it was actually submitted |
| (头部\|领军\|龙头\|顶尖\|一流)企业 | Evaluative claim, requires a citable source |
| 与贵司.{0,6}(深度)?合作 | Implies an existing partnership |
| 贵司.{0,10}(唯一\|首家\|最大) | Superlative claim, requires a source |

**3. Nothing sends without approval.** `--send` must be paired with `--approved`, meaning "the user has confirmed the preflight checklist line by line". The gate is an **exit code**, not a reminder in the docs:

```bash
python scripts/send_resume.py --send
# ! Blocked: --send requires --approved — the preflight checklist has not been confirmed.
# exit code 3
```

### Nine hard rules

Full text in [`docs/03-safety-rules.md`](docs/03-safety-rules.md). Each one came out of a real incident:

1. Only email addresses you have personally opened and read on an official page (five universities listing the same address is still one source; a JS-rendered page you cannot read → stop, do not guess)
2. A plausible address is not a deliverable one. Three gates before sending: traceable source / **MX health check (mandatory)** / RCPT probe (optional)
3. Distinguish "résumé intake address" from "enquiry address" — for an enquiry address the body must state that the official portal is the primary channel
4. Read every outgoing body in full; delete any evaluative claim with no citable source
5. No false statements; disclose skill gaps and suggest an alternative role
6. Verifying "Sent" by total count is invalid — search per recipient address, including Cc
7. Scripts are idempotent and dry-run by default; exit codes are explicit; back up user files before modifying them
8. When the user asks for a command, output the command and do not execute it (the user keeps control of the last step)
9. Never conflate verification levels when reporting

### Exit codes

| Exit code | Meaning | Source |
|---|---|---|
| `0` | Completed normally (including dry-run and no pending targets) | all scripts |
| `1` | Cross-check failed / character-count self-check failed | `make_stats.py` |
| `2` | Config or credential error (missing auth code, unfilled placeholders, …) | `_config.py` |
| `3` | Gate blocked: the checklist has blocked items, or `--send` was used without `--approved` | `preflight.py` / `send_resume.py` |
| `4` | Pre-send MX re-check failed; every target was blocked and nothing was sent | `send_resume.py` |

### Multi-platform prompts

`prompts/` ships one universal rule set plus three platform-adapted versions. **With the scripts, the gate is an exit code; without them, the gate is a rule.**

| Platform | File | Where to paste it |
|---|---|---|
| Claude / WorkBuddy and other long-instruction platforms | `prompts/universal.md` | Paste the whole file into custom instructions / Project Instructions |
| GPTs | `prompts/gpt.md` | Create → Instructions |
| Trae | `prompts/trae.md` | Project root `.trae/rules/project_rules.md` or Trae Rules settings |
| Doubao | `prompts/doubao.md` | Agent → role definition |

Selection guidance is in [`prompts/README.md`](prompts/README.md).

---

## Repository layout

```
AutoJobApply/
├── .gitattributes                Force LF line endings so scripts do not fail on CRLF after a Windows clone
├── .gitignore                    Excludes credentials, real résumé attachments, runtime artifacts
├── LICENSE                       MIT
├── README.md                     Chinese README
├── README.en.md                  This file
├── CHANGELOG.md                  Version history (semantic versioning)
├── assets/
│   └── workflow.svg              Pipeline diagram
├── attachments/                  Résumé attachment root (contents not tracked; only .gitkeep kept)
│   └── .gitkeep
├── config/
│   ├── config.example.json       Config template (all values are {{placeholders}})
│   └── README.md                 Field-by-field config reference
├── docs/
│   ├── 01-workflow.md            Seven-step pipeline in detail
│   ├── 02-email-verification.md  Address source grading and verification (MX / RCPT)
│   ├── 03-safety-rules.md        The nine hard rules
│   ├── 04-platform-setup.md      GPT / Trae / Doubao / Claude setup
│   ├── 05-troubleshooting.md     Troubleshooting (nslookup encoding, IPv6 interference, …)
│   └── 06-deliverability.md      Delivery mechanics and bounce attribution
├── drafts/
│   ├── _TEMPLATE.txt             Draft template with every field and body-writing rule
│   │                             (files starting with _ are skipped by the scripts)
│   └── examples/
│       ├── README.md                        Notes on the three examples and how to use them
│       ├── E1_标准技术岗.txt                 Standard technical role, three-paragraph body
│       ├── E2_诚实披露技能缺口.txt           Honest skill-gap disclosure plus a fallback
│       └── E3_咨询邮箱场景.txt               Enquiry-address case, body states the portal is primary
├── prompts/
│   ├── README.md                 Platform matrix and selection guidance
│   ├── universal.md              Universal rule set (pasteable anywhere)
│   ├── gpt.md                    GPTs Instructions version
│   ├── trae.md                   Trae rules version
│   └── doubao.md                 Doubao agent instruction version
├── scripts/
│   ├── _config.py                Config loading: placeholder detection, env-var credentials, exit-code wrapper
│   ├── _draft.py                 Draft parsing plus high-risk phrasing warnings
│   ├── preflight.py              Checklist generator (MX health check, md/html export)
│   ├── send_resume.py            Idempotent sender (--approved gate, pre-send MX re-check)
│   ├── verify_delivery.py        Five-part delivery verification
│   └── make_stats.py             Stats generator (xlsx + md, with cross-checks)
└── state/                        Runtime artifacts (contents not tracked)
    ├── .gitkeep
    └── applications.example.json Application log template (the only data source for the stats table)
```

**Draft naming convention**: files in `drafts/` whose name starts with `_` are skipped by the scripts, so `_TEMPLATE.txt` is never sent by accident.

---

## Requirements and dependencies

> **Note**: this repository contains **no** `requirements.txt`, `pyproject.toml`, `setup.py`, `package.json`, `go.mod`, `Cargo.toml`, or `pom.xml` (confirmed by a full-repo search). The dependency list below is therefore derived by reading the `import` statements in `scripts/*.py`, not from a manifest file.

### Runtime

| Item | Requirement | Evidence |
|---|---|---|
| OS | Windows / macOS / Linux | Scripts use the standard library only; `.gitattributes` forces LF for Windows compatibility |
| Interpreter | Python 3 | `scripts/*.py` |
| Minimum Python version | **TODO: to be added** (not declared in this repo) | — |
| Network | DNS access to recipient domains; outbound `465` (SSL) or `587` (STARTTLS) to the sending server; `993` (IMAP) for verification | `smtp_port` / `imap_port` in `config/config.example.json` |
| System tool | `nslookup` (called by `preflight.py` for the MX health check) | `scripts/preflight.py` |

### Python dependencies

| Dependency | Required? | Purpose | Evidence |
|---|---|---|---|
| Python standard library | Required | `argparse` `hashlib` `json` `smtplib` `ssl` `sys` `time` `datetime` `email` `pathlib` `imaplib` `re` `socket` `subprocess` `os` | `import` statements in every script |
| [`openpyxl`](https://pypi.org/project/openpyxl/) | **Optional** | Generating the xlsx stats table; `make_stats.py` still runs without it | `from openpyxl import Workbook` is a lazy in-function import in `scripts/make_stats.py` |

Install the optional dependency:

```bash
pip install openpyxl
```

Dependency version pinning: **TODO: to be added** (no manifest file in the repo, so no version constraints can be stated).

---

## Installation and build

This is a **script-only repository with no build step**, and no `pip install` packaging. There is no `Makefile`, no CI configuration (`.github/workflows` etc.), and no packaging script.

### 1. Clone the repository

```bash
git clone https://github.com/cannotcodetao/AutoJobApply.git
cd AutoJobApply
```

### 2. Install the optional dependency

```bash
pip install openpyxl
```

### 3. Create the config file

```bash
cp config/config.example.json config/config.json
```

`config/config.json` is excluded by `.gitignore` and **is never committed**.

### 4. Set the credential environment variable

The mailbox auth code is read **only from an environment variable** and is never written to the config file.

```bash
# macOS / Linux
export AUTOJOB_AUTHCODE='your-mailbox-auth-code'
```

```powershell
# Windows PowerShell
$env:AUTOJOB_AUTHCODE='your-mailbox-auth-code'
```

> To use a different variable name, change `sender.authcode_env`. The variable name itself is not sensitive.

### 5. Prepare a draft

```bash
cp drafts/examples/E1_标准技术岗.txt drafts/D1_SomeCompany.txt
```

Edit the header fields and rewrite the body. Field reference: `drafts/_TEMPLATE.txt`.

---

## Quick start / usage

Every command below is taken from the repository's own templates, docs, and examples and can be copied and run directly. **No script sends mail by default.**

### Step 1 · Build the preflight checklist

```bash
python scripts/preflight.py --dns --html
```

The five checklist fields are printed to the terminal, and `state/preflight.html` is written for line-by-line review.

Available options:

```bash
python scripts/preflight.py --only D1,D2   # only the given IDs
python scripts/preflight.py --all          # include already-applied targets
python scripts/preflight.py --dns          # MX health check on recipient domains (slower)
python scripts/preflight.py --md           # export Markdown to state/preflight.md
python scripts/preflight.py --html         # export HTML to state/preflight.html
python scripts/preflight.py --outdir PATH  # export directory (default: state/)
python scripts/preflight.py --config PATH  # config file
```

### Step 2 · Preview (nothing is sent)

```bash
python scripts/send_resume.py --list
```

### Step 3 · Send after user approval

```bash
python scripts/send_resume.py --send --approved --only D1
```

Available options:

```bash
python scripts/send_resume.py --send               # actually send (preview by default)
python scripts/send_resume.py --approved           # confirms the user approved the checklist (required with --send)
python scripts/send_resume.py --only D1,D2         # comma-separated IDs
python scripts/send_resume.py --force              # ignore the send log and resend
python scripts/send_resume.py --list               # list status only, do nothing
python scripts/send_resume.py --include-unverified # include unverified sources (not recommended)
python scripts/send_resume.py --limit 3            # send at most N in this run
python scripts/send_resume.py --config PATH        # config file
```

### Step 4 · Verify delivery

```bash
python scripts/verify_delivery.py
```

Available options:

```bash
python scripts/verify_delivery.py --no-dns      # skip the MX health check
python scripts/verify_delivery.py --log-only    # local send log only
python scripts/verify_delivery.py --probe       # additionally run an SMTP RCPT probe (slow)
python scripts/verify_delivery.py --days 7      # scan bounces from the last N days
python scripts/verify_delivery.py --config PATH # config file
```

### Step 5 · Maintain the application log and generate stats

```bash
cp state/applications.example.json state/applications.json
# fill it in from your actual applications
# (non-email channels leave no machine log, so this log is maintained by hand)
python scripts/make_stats.py
```

Available options:

```bash
python scripts/make_stats.py --out-xlsx PATH   # xlsx path (default: state/applications.xlsx)
python scripts/make_stats.py --out-md PATH     # md path (default: state/applications.md)
python scripts/make_stats.py --config PATH     # config file
```

### Global dry run

```bash
# macOS / Linux
export AUTOJOB_DRY_RUN=1
```

```powershell
# Windows PowerShell
$env:AUTOJOB_DRY_RUN='1'
```

When set to `1`, **every script runs in dry-run mode** and nothing is actually sent.

### Manual address check (without the scripts)

```bash
nslookup -type=mx example.com
nslookup mx1.example.com
```

If the host the MX record points at resolves to no IPv4 address, that is the **silent failure** case described in rule 2.

---

## Configuration

The config file is `config/config.json`, copied from `config/config.example.json`. Relative paths are always resolved against the **repository root**, so scripts run from any directory.

### `sender` — outgoing and incoming servers

| Field | Default | Meaning |
|---|---|---|
| `email` | `{{SENDER_EMAIL}}` | Sending mailbox. **Required**, and must match the auth code |
| `from_name` | `""` (empty) | Display name the recipient sees; empty shows the address only |
| `smtp_host` | `smtp.qq.com` | Sending server. QQ uses `smtp.qq.com:465` (SSL); 163 uses `smtp.163.com:465`; Gmail uses `smtp.gmail.com:587` (the script switches to STARTTLS automatically) |
| `smtp_port` | `465` | Sending port |
| `imap_host` | `imap.qq.com` | Incoming server, used by the verification script only |
| `imap_port` | `993` | Incoming port |
| `authcode_env` | `AUTOJOB_AUTHCODE` | Name of the environment variable holding the auth code |
| `interval_sec` | `25` | Seconds between two messages. Values below 10 are discouraged — rapid sending tends to trigger rate limiting |

### `candidate` — applicant details

These values are **not substituted into drafts automatically**; they give the AI an authoritative source of facts and make manual review easier.

| Field | Default |
|---|---|
| `name` | `{{姓名}}` |
| `phone` | `{{手机号}}` |
| `email` | `{{联系邮箱}}` |
| `school` | `{{学校}}` |
| `major` | `{{专业}}` |
| `degree` | `{{学历}}` |
| `graduation` | `{{毕业时间，如 2027.06}}` |

### `preferences` — job preferences

| Field | Default | Meaning |
|---|---|---|
| `priority_cities` | `["{{城市1}}", "{{城市2}}"]` | Preferred cities. Whether the checklist's work location hits this list is the basis for your decision |
| `accepts_travel` | `true` | Whether travel / on-site assignments are acceptable |
| `notes` | `"{{其他约束，如「接受出差/驻厂」}}"` | Other hard constraints, free text |

### `paths` — paths

| Field | Default | Meaning |
|---|---|---|
| `drafts` | `drafts` | Draft directory |
| `attachments` | `attachments` | Attachment root (a relative `ATTACH` path is resolved against its parent) |
| `state` | `state` | Runtime artifacts directory (logs, exports) |
| `send_log` | `state/send_log.json` | Send log, the basis for idempotency |
| `applications` | `state/applications.json` | Application log, the data source for stats |
| `stats_xlsx` | `state/applications.xlsx` | Stats output path |

### `safety` — safety gates

**Do not change these unless you fully understand the consequences.**

| Field | Default | Meaning |
|---|---|---|
| `require_approved` | `true` | `--send` needs `--approved` to actually send. Setting it to `false` removes the confirmation gate |
| `max_sends_per_run` | `10` | Maximum messages per run, to prevent a misconfiguration from turning into a mass send |
| `block_unverified_source` | `true` | Targets marked "unverified" are refused |
| `verify_mx_before_send` | `true` | Re-check the recipient domain MX immediately before sending |

### `stats` — statistics

| Field | Default | Meaning |
|---|---|---|
| `business_scope_max_chars` | `15` | Character limit for the "business scope" column; exceeding it is reported when generating the table |

### Environment variables

| Variable | Purpose | Evidence |
|---|---|---|
| `AUTOJOB_AUTHCODE` | Mailbox auth code (rename via `sender.authcode_env`) | `scripts/_config.py` |
| `AUTOJOB_CONFIG` | Config file path, default `config/config.json` | `scripts/_config.py` |
| `AUTOJOB_DRY_RUN` | Set to `1` / `true` / `TRUE` / `yes` to force a global dry run; nothing is sent | `scripts/_config.py` |

### Draft header fields

Drafts (`drafts/*.txt`) declare metadata as `# KEY: value` lines; the body starts after `# ---BODY---`. Full reference: `drafts/_TEMPLATE.txt`.

**Five required fields** — any missing one marks the target "blocked" and refuses to send:

| Field | Meaning |
|---|---|
| `COMPANY` | Company name. Use the full legal name; do not confuse a group with its subsidiary |
| `ROLE` | Target role, including the role track and level |
| `LOCATION` | Work location. **First preferred city only** — this is the stats dimension |
| `TO` | Primary recipient |
| `VERIFIED` | Address source verification. Must state which page and which sentence you saw |

**Optional fields**: `CC` (comma- or semicolon-separated; an address may not appear in both `TO` and `CC`), `SUBJECT`, `ATTACH` (semicolon-separated; relative paths resolve against the parent of the `attachments` directory), `LOCATION_ALT` (alternate cities — stats only use `LOCATION`), `BUSINESS` (business scope, 15 characters max), `CHANNEL`, `APPLIED_AT`, `STATUS`, `NOTE`.

---

## Testing and running

### Automated tests

**There are currently no automated tests**: no `tests/` directory, no `test_*.py` / `*_test.py`, no `conftest.py`, no `tox.ini` / `pytest` configuration, and no CI configuration of any kind (`.github/workflows` etc. do not exist). Confirmed by a full-repo search.

`TODO: to be added` — candidate targets for unit tests are the dependency-free pure functions: the warning rules in `_draft.py`, the blocking logic in `preflight.py`, and the cross-checks in `make_stats.py`.

### Manual running and self-checks

Every script supports a dry run. Recommended self-check sequence:

```bash
# 1. Global dry run: nothing is actually sent
export AUTOJOB_DRY_RUN=1        # Windows PowerShell: $env:AUTOJOB_DRY_RUN='1'

# 2. Checklist with MX health check — exit code 3 when items are blocked
python scripts/preflight.py --dns --html

# 3. List status only, do nothing
python scripts/send_resume.py --list

# 4. Preview a send (no --send, so nothing is sent)
python scripts/send_resume.py

# 5. Local log only, no network
python scripts/verify_delivery.py --log-only

# 6. Generate stats and trigger the cross-checks — exit code 1 on count or log problems
python scripts/make_stats.py
```

### Preconditions per script

| Script | Precondition |
|---|---|
| `preflight.py` | `config/config.json` has no unfilled placeholders; at least one draft exists in `drafts/` |
| `send_resume.py` | Same as above; actually sending also needs `--approved` and the auth code in the environment |
| `verify_delivery.py` | Same as above; `--log-only` needs no network, the rest need DNS / IMAP |
| `make_stats.py` | `state/applications.json` exists and is filled in; generating xlsx needs `openpyxl` |

The scripts import each other (for example `send_resume.py` and `verify_delivery.py` reuse the MX implementation in `preflight.py`) to avoid two divergent copies of the same logic. Keep the `scripts/` directory intact; do not copy a single file elsewhere and run it there.

---

## FAQ and notes

### Common configuration errors

| Symptom | Cause | Fix |
|---|---|---|
| `配置里还有 N 项占位符未填写` | Template copied but `{{...}}` not replaced | Fill them in. This is **intentional** — it prevents sending to a placeholder address |
| `缺少邮箱授权码：环境变量 ... 未设置` | Variable not set, or set in another terminal window | Set it in the current terminal; PowerShell `$env:` only lasts for the current session |
| `配置文件中出现了疑似敏感字段` | A password was written into config.json | Remove the field and use the environment variable |
| `SMTPAuthenticationError 535` | The login password was used instead of the auth code | Generate an auth code in the mailbox settings (QQ Mail: Settings → Account → POP3/IMAP/SMTP service → enable and generate) |

### Notes

- **An auth code is not a login password.** Using the login password fails authentication outright.
- **Credentials never touch disk.** The auth code is read only from the environment; no commit-able password exists in the config file or the repository.
- **`nslookup` depends on your local network.** If DNS is poisoned or intercepted, MX results may be wrong. The scripts distinguish "`nslookup` failed locally" from "the domain genuinely has no MX": the former is a local environment problem and only warns, it does not block.
- **Nothing sends by default.** All scripts default to dry-run; a real send requires two independent switches (`--send` + `--approved`).
- **Idempotent.** The send log is used for duplicate detection, so re-running never re-sends the same application.
- **Verifying "Sent" requires a per-address search, never a total count.** Multiple rounds get conflated; and the "save sent mail on the server" setting does **not** backfill history, so messages sent before it was enabled do not exist in "Sent" at all.
- **For an enquiry address, state that the official portal is the primary channel**, otherwise the recipient will not treat the message as a formal application.

### Honest limits

What this project **cannot** do:

- **Cannot detect whether a human read your email.** No read receipt, no way to know; anything claiming otherwise is guessing.
- **Cannot guarantee an address is valid.** `250` from RCPT only means the server will accept it, not that a person will read it.
- **Cannot write a good email for you.** It can only prevent one with factual errors or obvious boilerplate.
- **Does not circumvent any platform's rules.** Frequent sending, identity forgery, and repeated applications to the same role are neither supported nor appropriate.

### Troubleshooting

Concrete failures and fixes — `nslookup` decoding on the Windows local code page (GBK), misjudgements caused by IPv6 interference — are documented in [`docs/05-troubleshooting.md`](docs/05-troubleshooting.md) (Chinese).

---

## License

[MIT](LICENSE)

Copyright (c) 2026 AutoJobApply contributors
