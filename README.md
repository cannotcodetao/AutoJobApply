# AutoJobApply

**把校招邮件投递做成一条有闸门、可追溯、不吹牛的流水线。**

不是「AI 帮你群发简历」——恰恰相反，这个项目的核心是**拦下不该发的那一封**。

<p align="center">
  <img src="assets/workflow.svg" alt="AutoJobApply 流程示意" width="880">
</p>

---

## 功能特性

所有能力均由仓库内 `scripts/` 的六个 Python 脚本与 `docs/`、`prompts/` 的规则文件承载。

### 全链路七步流程

调研 → 邮箱核实分级 → 岗位匹配 → 邮件定制 → 投递前核对表 → 用户确认闸门 → 送达核查。
每一步都有对应的脚本或清单；上一步没有产出，不进入下一步。详见 [`docs/01-workflow.md`](docs/01-workflow.md)。

### 逐模块能力

| 文件 | 能力 |
|---|---|
| `scripts/_config.py` | 统一配置加载。凭据**只从环境变量读取**，不落盘；配置中的 `{{占位符}}` 未替换时直接报错退出，防止把模板配置当成真配置发出去 |
| `scripts/_draft.py` | 草稿解析 + 投递前五项校验；对正文中的**高风险表述**给出告警（只提醒，不替代人判断） |
| `scripts/preflight.py` | 投递前核对表生成器。五项（公司 / 岗位 / 工作地点 / 收件人 / 邮箱来源验证）缺一即标「阻断」，并以退出码 3 拒发；可选 MX 体检；可导出 Markdown / HTML |
| `scripts/send_resume.py` | 幂等发送器。默认 dry-run；`--send` 必须同时带 `--approved`，否则以退出码 3 拦截；发送前再复核一次收件域名 MX；收件人与抄送查重；附件缺失即拒发 |
| `scripts/verify_delivery.py` | 五段式送达核查：发送日志 / MX 体检 / 退信扫描 / 「已发送」逐地址检索 / 可选 RCPT 探测 |
| `scripts/make_stats.py` | 投递统计表生成器（xlsx + md），内置「业务范围字数」自检与「发送日志 ↔ 统计表」工作地点交叉校验 |

### 三条不可妥协的原则

**1. 不把「发出去了」当成「送到了」。** 送达被拆成四级，汇报时禁止混为一谈。

| 级别 | 手段 | 能证明什么 |
|---|---|---|
| ① | SMTP 返回 250 | 发件服务器接受了这封信（**最弱**） |
| ② | 收件域名 MX 体检 | 对方域名当前能收信 |
| ③ | 无退信 / RCPT 返回 250 | 该地址很可能真实存在 |
| ④ | 收到企业回信 | HR 真的读到了——**任何工具都测不出来** |

**2. 不做虚假陈述。** 网申没提交，就不写「已同步完成网申」；技能缺口如实披露。`scripts/_draft.py` 会对以下模式告警：

| 高风险表述模式 | 风险 |
|---|---|
| 已(同步)?完成网申 | 断言已完成，除非真的提交过 |
| (头部\|领军\|龙头\|顶尖\|一流)企业 | 评价性断言，需有可引用的出处 |
| 与贵司.{0,6}(深度)?合作 | 暗示既有合作关系 |
| 贵司.{0,10}(唯一\|首家\|最大) | 最高级断言，需有出处 |

**3. 未经确认，程序发不出去。** `--send` 必须配 `--approved`，语义是「用户已逐行确认过核对表」。这道闸门不靠人记住流程，而是靠退出码：

```bash
python scripts/send_resume.py --send
# ! 已拦截：--send 未附带 --approved —— 尚未取得用户对核对表的确认。
# 退出码 3
```

### 九条硬规则

完整内容见 [`docs/03-safety-rules.md`](docs/03-safety-rules.md)。每条都对应一个真实发生过的场景：

1. 只发「你亲自打开并读到原文」的邮箱（多校转载一致 ≠ 你亲自核实；JS 渲染页面读不到正文 → 一律暂缓）
2. 邮箱可信 ≠ 能送达。投递前必过三道：来源可追溯 / **MX 体检（硬性）** / RCPT 探测（可选）
3. 区分「简历接收邮箱」与「咨询邮箱」——咨询邮箱场景正文必须写明网申才是主渠道
4. 代发对外邮件必须逐封通读正文，凡无源可依的评价性断言一律删改
5. 不做虚假陈述，技能缺口如实披露并给替代岗位建议
6. 核查「已发送」不能看总数，必须按每个收件地址（含抄送）逐条检索
7. 脚本一律幂等 + 默认干跑；退出码明确；改用户原文件前先备份
8. 「给我命令」时只输出命令，不代为执行（用户保留最后一步的控制权）
9. 汇报时不得混淆验证级别

### 退出码约定

便于把脚本串起来做判断，详见 `scripts/_config.py` 与各脚本实现：

| 退出码 | 含义 | 来源 |
|---|---|---|
| `0` | 正常完成（含 dry-run 与无待处理目标） | 各脚本 |
| `1` | 交叉校验失败 / 字数自检未通过 | `make_stats.py` |
| `2` | 配置或凭据错误（缺授权码、占位符未填等） | `_config.py` |
| `3` | 闸门拦截：核对表存在阻断项，或 `--send` 未带 `--approved` | `preflight.py` / `send_resume.py` |
| `4` | 发送前 MX 复核失败，全部目标被拦下，一封未发 | `send_resume.py` |

### 多平台提示词

`prompts/` 提供一份通用规则与三份平台适配版。**没有脚本时，闸门是「规则」；有脚本时，闸门是「退出码」。**

| 平台 | 用哪个文件 | 贴在哪里 |
|---|---|---|
| Claude / WorkBuddy 等长指令平台 | `prompts/universal.md` | 全文粘贴到自定义指令 / Project Instructions |
| GPTs | `prompts/gpt.md` | Create → Instructions |
| Trae | `prompts/trae.md` | 项目根目录 `.trae/rules/project_rules.md` 或 Trae Rules 设置 |
| 豆包 | `prompts/doubao.md` | 智能体 → 角色设定 |

选择建议见 [`prompts/README.md`](prompts/README.md)。

---

## 目录结构

```
AutoJobApply/
├── .gitattributes                统一换行符为 LF，避免 Windows clone 后脚本因 CRLF 报错
├── .gitignore                    排除凭据、真实简历附件、运行产物
├── LICENSE                       MIT
├── README.md                     本文件（中文）
├── README.en.md                  英文版说明
├── CHANGELOG.md                  版本变更记录（语义化版本）
├── assets/
│   └── workflow.svg              流程示意配图
├── attachments/                  简历附件根目录（内容不入库，仅保留 .gitkeep）
│   └── .gitkeep
├── config/
│   ├── config.example.json       配置模板（全部为 {{占位符}}）
│   └── README.md                 配置项逐条说明
├── docs/
│   ├── 01-workflow.md            七步流程详解
│   ├── 02-email-verification.md  邮箱来源分级与核实方法（MX / RCPT）
│   ├── 03-safety-rules.md        九条硬规则
│   ├── 04-platform-setup.md      GPT / Trae / 豆包 / Claude 接入说明
│   ├── 05-troubleshooting.md     排错手册（含 nslookup 编码、IPv6 干扰等）
│   └── 06-deliverability.md      送达原理与退信归因
├── drafts/
│   ├── _TEMPLATE.txt             草稿模板（含全部字段与正文写作原则；以 _ 开头的文件会被脚本跳过）
│   └── examples/
│       ├── README.md             三个示例的说明与使用流程
│       ├── E1_标准技术岗.txt             常规技术岗三段式写法
│       ├── E2_诚实披露技能缺口.txt       技能缺口如实披露 + 替代方案
│       └── E3_咨询邮箱场景.txt           咨询邮箱场景，正文写明网申为主渠道
├── prompts/
│   ├── README.md                 平台对照表与选择建议
│   ├── universal.md              通用规则（任何平台可粘贴）
│   ├── gpt.md                    GPTs Instructions 版
│   ├── trae.md                   Trae rules 版
│   └── doubao.md                 豆包智能体指令版
├── scripts/
│   ├── _config.py                配置加载：占位符检测、环境变量凭据、退出码包装
│   ├── _draft.py                 草稿解析 + 正文高风险表述告警
│   ├── preflight.py              核对表生成器（含 MX 体检、md/html 导出）
│   ├── send_resume.py            幂等发送器（含 --approved 闸门、发送前 MX 复核）
│   ├── verify_delivery.py        五段式送达核查
│   └── make_stats.py             统计表生成（xlsx + md，含交叉校验）
└── state/                        运行产物目录（内容不入库）
    ├── .gitkeep
    └── applications.example.json 投递台账模板（统计表的唯一数据源）
```

**关于草稿文件的命名约定**：`drafts/` 下以 `_` 开头的文件会被脚本跳过，因此 `_TEMPLATE.txt` 不会被误发。

---

## 环境要求与依赖

> **说明**：本仓库**没有** `requirements.txt`、`pyproject.toml`、`setup.py`、`package.json`、`go.mod`、`Cargo.toml`、`pom.xml` 等任何依赖清单文件（已全仓检索确认）。因此下表的依赖是从 `scripts/*.py` 的 `import` 语句逐一归纳而来，不是从配置文件读取。

### 运行环境

| 项 | 要求 | 依据 |
|---|---|---|
| 操作系统 | Windows / macOS / Linux 均可 | 脚本仅用标准库；`.gitattributes` 强制 LF 以兼容 Windows |
| 解释器 | Python 3 | `scripts/*.py` |
| Python 最低版本 | **TODO: 待补充**（仓库未声明版本号） | — |
| 网络 | 需要能访问目标收件域名的 DNS；需要能连发件服务器 `465`（SSL）或 `587`（STARTTLS）；核查需要 `993`（IMAP） | `config/config.example.json` 的 `smtp_port` / `imap_port` |
| 系统工具 | `nslookup`（`preflight.py` 的 MX 体检会调用） | `scripts/preflight.py` |

### Python 依赖

| 依赖 | 必需性 | 用途 | 依据 |
|---|---|---|---|
| Python 标准库 | 必需 | `argparse` `hashlib` `json` `smtplib` `ssl` `sys` `time` `datetime` `email` `pathlib` `imaplib` `re` `socket` `subprocess` `os` | 各脚本 `import` 语句 |
| [`openpyxl`](https://pypi.org/project/openpyxl/) | **可选** | 生成 xlsx 统计表；未安装时 `make_stats.py` 仍可用 | `scripts/make_stats.py` 中 `from openpyxl import Workbook` 为函数内延迟导入 |

安装可选依赖：

```bash
pip install openpyxl
```

依赖版本锁定方式：**TODO: 待补充**（仓库内无依赖清单，无法给出确切版本约束）。

---

## 安装与构建

本仓库为**纯脚本仓库，没有构建步骤**，也不需要 `pip install` 安装成包。仓库内不存在 `Makefile`、CI 配置（`.github/workflows` 等）或打包脚本。

### 1. 克隆仓库

```bash
git clone https://github.com/cannotcodetao/AutoJobApply.git
cd AutoJobApply
```

### 2. 安装可选依赖

```bash
pip install openpyxl
```

### 3. 生成配置文件

```bash
cp config/config.example.json config/config.json
```

`config/config.json` 已被 `.gitignore` 排除，**不会被提交**。

### 4. 设置凭据环境变量

邮箱授权码**只从环境变量读取**，配置文件里永远不写。

```bash
# macOS / Linux
export AUTOJOB_AUTHCODE='你的邮箱授权码'
```

```powershell
# Windows PowerShell
$env:AUTOJOB_AUTHCODE='你的邮箱授权码'
```

> 若想用别的变量名，改配置里的 `sender.authcode_env` 即可，变量名本身不敏感。

### 5. 准备草稿

```bash
cp drafts/examples/E1_标准技术岗.txt drafts/D1_某某公司.txt
```

复制后需修改头部字段并重写正文，字段说明见 `drafts/_TEMPLATE.txt`。

---

## 快速开始 / 使用示例

以下命令均取自仓库内的模板、文档与示例说明，可直接复制运行。**所有脚本默认不发信。**

### 步骤 1 · 生成投递前核对表（人工确认）

```bash
python scripts/preflight.py --dns --html
```

终端会打印核对表五项字段，并在 `state/` 下生成 `preflight.html` 供逐行核对。

可用参数：

```bash
python scripts/preflight.py --only D1,D2   # 只看指定 ID
python scripts/preflight.py --all          # 连已投递的目标一起列出
python scripts/preflight.py --dns          # 对收件域名做 MX 体检（较慢）
python scripts/preflight.py --md           # 导出 Markdown 到 state/preflight.md
python scripts/preflight.py --html         # 导出 HTML 到 state/preflight.html
python scripts/preflight.py --outdir 路径   # 指定导出目录（默认 state/）
python scripts/preflight.py --config 路径   # 指定配置文件
```

### 步骤 2 · 先预览（不发送）

```bash
python scripts/send_resume.py --list
```

### 步骤 3 · 用户确认后投递

```bash
python scripts/send_resume.py --send --approved --only D1
```

可用参数：

```bash
python scripts/send_resume.py --send            # 真实发送（默认只预览）
python scripts/send_resume.py --approved        # 确认已取得用户对核对表的批准（--send 的必备配套）
python scripts/send_resume.py --only D1,D2      # 只处理指定 ID，逗号分隔
python scripts/send_resume.py --force           # 忽略发送日志，强制重发
python scripts/send_resume.py --list            # 只列状态，不做任何事
python scripts/send_resume.py --include-unverified   # 连来源未核实的目标也纳入（不推荐）
python scripts/send_resume.py --limit 3         # 本次最多发送几封
python scripts/send_resume.py --config 路径      # 指定配置文件
```

### 步骤 4 · 核查送达

```bash
python scripts/verify_delivery.py
```

可用参数：

```bash
python scripts/verify_delivery.py --no-dns      # 跳过 MX 体检
python scripts/verify_delivery.py --log-only    # 只看本地发送日志
python scripts/verify_delivery.py --probe       # 额外做 SMTP RCPT 探测（慢）
python scripts/verify_delivery.py --days 7      # 只扫最近 N 天的退信
python scripts/verify_delivery.py --config 路径  # 指定配置文件
```

### 步骤 5 · 维护台账并生成统计表

```bash
cp state/applications.example.json state/applications.json
# 按实际投递情况填写（非邮箱渠道的投递没有机器日志，只能手工维护）
python scripts/make_stats.py
```

可用参数：

```bash
python scripts/make_stats.py --out-xlsx 路径   # xlsx 输出路径（默认 state/applications.xlsx）
python scripts/make_stats.py --out-md 路径     # md 输出路径（默认 state/applications.md）
python scripts/make_stats.py --config 路径     # 指定配置文件
```

### 全局干跑（推荐不确定环境先跑一遍）

```bash
# macOS / Linux
export AUTOJOB_DRY_RUN=1
```

```powershell
# Windows PowerShell
$env:AUTOJOB_DRY_RUN='1'
```

设为 `1` 时**全局干跑**，任何脚本都不会真实发信。

### 手动核实收件域名（不使用脚本时）

```bash
nslookup -type=mx example.com
nslookup mx1.example.com
```

MX 记录指向的主机若解析不出 IPv4，即为规则 2 所述的**静默失败**场景。

---

## 配置说明

配置文件为 `config/config.json`（由 `config/config.example.json` 复制而来）。相对路径一律相对**仓库根**解析，因此脚本从任何目录调用都能运行。

### `sender` —— 发件与收件服务器

| 字段 | 默认值 | 说明 |
|---|---|---|
| `email` | `{{SENDER_EMAIL}}` | 发件邮箱。**必须填**，且与授权码对应 |
| `from_name` | `""`（空） | 收件人看到的发件人显示名，留空则只显示邮箱地址 |
| `smtp_host` | `smtp.qq.com` | 发信服务器。QQ 为 `smtp.qq.com:465`（SSL）；163 为 `smtp.163.com:465`；Gmail 为 `smtp.gmail.com:587`（脚本自动改用 STARTTLS） |
| `smtp_port` | `465` | 发信端口 |
| `imap_host` | `imap.qq.com` | 收信服务器，仅核查脚本使用 |
| `imap_port` | `993` | 收信端口 |
| `authcode_env` | `AUTOJOB_AUTHCODE` | 存放授权码的环境变量名 |
| `interval_sec` | `25` | 两封邮件之间的间隔秒数。不建议低于 10 秒，连续快速发信容易触发风控 |

### `candidate` —— 候选人信息

这些值**不会自动替换进草稿**，作用是给 AI 写邮件时一个权威事实来源，也便于每次核对。

| 字段 | 默认值 |
|---|---|
| `name` | `{{姓名}}` |
| `phone` | `{{手机号}}` |
| `email` | `{{联系邮箱}}` |
| `school` | `{{学校}}` |
| `major` | `{{专业}}` |
| `degree` | `{{学历}}` |
| `graduation` | `{{毕业时间，如 2027.06}}` |

### `preferences` —— 求职偏好

| 字段 | 默认值 | 说明 |
|---|---|---|
| `priority_cities` | `["{{城市1}}", "{{城市2}}"]` | 优先城市列表。核对表里「工作地点」是否命中此列表，是拍板依据 |
| `accepts_travel` | `true` | 是否接受出差 / 驻厂 |
| `notes` | `"{{其他约束，如「接受出差/驻厂」}}"` | 其他硬约束，自由文本 |

### `paths` —— 路径

| 字段 | 默认值 | 说明 |
|---|---|---|
| `drafts` | `drafts` | 草稿目录 |
| `attachments` | `attachments` | 附件根目录（草稿里 `ATTACH` 写相对路径时以它的上级为基准） |
| `state` | `state` | 运行产物目录（日志、导出文件） |
| `send_log` | `state/send_log.json` | 发送日志，幂等判断依据 |
| `applications` | `state/applications.json` | 投递台账，统计表的数据源 |
| `stats_xlsx` | `state/applications.xlsx` | 统计表输出路径 |

### `safety` —— 安全闸门

**除非完全清楚后果，否则不要改这几项。**

| 字段 | 默认值 | 说明 |
|---|---|---|
| `require_approved` | `true` | `--send` 必须配 `--approved` 才真发。改成 `false` 等于拆掉确认闸门 |
| `max_sends_per_run` | `10` | 单次运行最多发几封，防止误配导致批量群发 |
| `block_unverified_source` | `true` | 来源标注为「待核实」的目标一律拒发 |
| `verify_mx_before_send` | `true` | 真正投递前再查一次收件域名 MX |

### `stats` —— 统计

| 字段 | 默认值 | 说明 |
|---|---|---|
| `business_scope_max_chars` | `15` | 「业务范围」列的字数上限，超过会在生成时被点名 |

### 环境变量

| 变量 | 作用 | 依据 |
|---|---|---|
| `AUTOJOB_AUTHCODE` | 邮箱授权码（可用 `sender.authcode_env` 改名为其他变量） | `scripts/_config.py` |
| `AUTOJOB_CONFIG` | 指定配置文件路径，默认 `config/config.json` | `scripts/_config.py` |
| `AUTOJOB_DRY_RUN` | 设为 `1` / `true` / `TRUE` / `yes` 时全局干跑，任何脚本都不真实发信 | `scripts/_config.py` |

### 草稿头部字段

草稿文件（`drafts/*.txt`）以 `# KEY: value` 形式声明元信息，正文写在 `# ---BODY---` 之后。完整说明见 `drafts/_TEMPLATE.txt`。

**必填五项**，缺任何一项核对表会将该目标标为「阻断」并拒发：

| 字段 | 说明 |
|---|---|
| `COMPANY` | 公司名称。写全称，注意集团与子公司不要混 |
| `ROLE` | 投递岗位，写清岗位序列与层级 |
| `LOCATION` | 工作地点。**只写首个意向城市**，这是统计口径字段 |
| `TO` | 主收件人 |
| `VERIFIED` | 邮箱来源验证。必须写「你在哪个页面、看到哪句话」 |

**可选字段**：`CC`（抄送，逗号或分号分隔，同一地址不能既在 TO 又在 CC）、`SUBJECT`、`ATTACH`（分号分隔，相对路径以 `attachments` 目录的上级为基准）、`LOCATION_ALT`（备选城市，统计只取 `LOCATION`）、`BUSINESS`（业务范围，15 字以内）、`CHANNEL`、`APPLIED_AT`、`STATUS`、`NOTE`。

---

## 测试与运行方式

### 自动化测试

**仓库内目前没有自动化测试**：无 `tests/` 目录、无 `test_*.py` / `*_test.py`、无 `conftest.py`、无 `tox.ini` / `pytest` 配置，也没有任何 CI 配置（`.github/workflows` 等均不存在）。此项已全仓检索确认。

`TODO: 待补充` —— 后续可考虑为零依赖的纯函数（如 `_draft.py` 的告警规则、`preflight.py` 的阻断判定、`make_stats.py` 的交叉校验）补充单元测试。

### 手动运行与自检方式

所有脚本都支持**干跑**，建议按下面的顺序自检：

```bash
# 1. 全局干跑：任何脚本都不真实发信
export AUTOJOB_DRY_RUN=1        # Windows PowerShell: $env:AUTOJOB_DRY_RUN='1'

# 2. 核对表（含 MX 体检）——存在阻断项时退出码为 3
python scripts/preflight.py --dns --html

# 3. 只列发送状态，不做任何事
python scripts/send_resume.py --list

# 4. 预览一次发送（未加 --send，默认不真发）
python scripts/send_resume.py

# 5. 只读本地日志，跳过网络
python scripts/verify_delivery.py --log-only

# 6. 生成统计表并触发交叉校验（有字数或台账问题退出码为 1）
python scripts/make_stats.py
```

### 各脚本运行前提速查

| 脚本 | 运行前提 |
|---|---|
| `preflight.py` | `config/config.json` 已填完占位符；`drafts/` 下至少有一份草稿 |
| `send_resume.py` | 同上；真实发送还需 `--approved` 与环境变量中的授权码 |
| `verify_delivery.py` | 同上；`--log-only` 不需要网络，其余需要 DNS / IMAP |
| `make_stats.py` | `state/applications.json` 已存在并填写；生成 xlsx 需要 `openpyxl` |

脚本之间会互相导入（例如 `send_resume.py` 与 `verify_delivery.py` 复用 `preflight.py` 中的 MX 实现），这是为**避免两处逻辑漂移**，因此请保持 `scripts/` 目录完整、不要单独复制其中某一个文件到别处运行。

---

## 常见问题与注意事项

### 常见配置错误

| 现象 | 原因 | 处理 |
|---|---|---|
| `配置里还有 N 项占位符未填写` | 复制了模板但没替换 `{{...}}` | 按提示逐项填写。这是**故意的**——防止拿模板配置把邮件发到占位符地址 |
| `缺少邮箱授权码：环境变量 ... 未设置` | 没设环境变量，或设在了另一个终端窗口 | 在当前终端重新设置；PowerShell 的 `$env:` 只在当前会话有效 |
| `配置文件中出现了疑似敏感字段` | 把密码写进了 config.json | 删掉该字段，改用环境变量 |
| `SMTPAuthenticationError 535` | 用了登录密码而不是授权码 | 去邮箱设置里生成授权码（QQ 邮箱：设置 → 账号 → POP3/IMAP/SMTP 服务 → 开启并生成授权码） |

### 注意事项

- **授权码不是登录密码。** 用登录密码会直接认证失败。
- **凭据不落盘。** 授权码只从环境变量读取，配置文件与仓库里永远不存在可被提交的密码。
- **`nslookup` 依赖本地网络。** 若 DNS 被污染或拦截，MX 体检结果可能不准。脚本会把「`nslookup` 本身跑不起来」与「域名真的没有 MX」区分开：前者属于本地环境问题，只警告不阻断。
- **默认不发信。** 所有脚本默认 dry-run，真实发送需要两个独立开关同时打开（`--send` + `--approved`）。
- **幂等。** 发送日志用于判重，重跑不会重复投递，可以放心反复执行。
- **核查「已发送」必须逐地址检索，不能看总数。** 多轮投递会混账；且「保存到服务器」开关**不会补录历史邮件**，开启前发出的邮件在「已发送」里根本不存在。
- **咨询邮箱场景要写明网申是主渠道**，否则对方不会把这封邮件当作正式申请。

### 诚实的边界

这个项目**做不到**的事：

- **测不出 HR 是否读了你的邮件。** 没有已读回执就是没有，任何声称能测的都是猜。
- **不能保证邮箱一定有效。** RCPT 返回 250 也只说明服务器愿意收下，不代表有真人看。
- **不能替你写出一封好邮件。** 它只能防止你写出一封有事实错误或明显套话的邮件。
- **不绕过任何平台的规则。** 频繁投递、伪造身份、同一岗位反复投，这些事它不帮你做，也不该做。

### 排错手册

`nslookup` 在 Windows 上的本地代码页（GBK）解码问题、IPv6 干扰导致的误判等具体故障与修复过程，见 [`docs/05-troubleshooting.md`](docs/05-troubleshooting.md)。

---

## License

[MIT](LICENSE)

Copyright (c) 2026 AutoJobApply contributors
