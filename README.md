# AutoJobApply

**把校招邮件投递做成一条有闸门、可追溯、不吹牛的流水线。**

不是「AI 帮你群发简历」。恰恰相反——这个项目的核心是**拦下不该发的那一封**。

<p align="center">
  <img src="assets/workflow.svg" alt="AutoJobApply 七步流程" width="880">
</p>

---

## 它解决的问题

邮箱投递校招简历，看起来只是「写封邮件附个简历」。真实情况是：

| 你以为 | 实际会发生 |
|---|---|
| 招聘简章上的邮箱一定能收到 | 企业官网公示的邮箱，所在的域名 **MX 记录指向一台不存在的主机**。你的邮件 SMTP 返回成功，几秒后被退回，而你毫不知情 |
| 发送成功 = 投递成功 | 发送成功只代表**你的**发件服务器收了这封信。中间还有一整段路要走 |
| 多所学校都写了这个邮箱，应该没错 | 多校转载一致，只说明**大家抄的是同一个来源**，不等于你亲自看到过原文 |
| 把邮箱发给 AI，让它批量投 | AI 会把「我会通过网申提交」写成「我已同步完成网申」——这是一句可以对方法务追责的假话 |
| 投完记一下就行 | 一周后你会发现：投了几家、投的什么岗、在哪个城市，全都记不清了 |

AutoJobApply 把上面五件事各自变成一道**可执行的检查**，而不是靠记性。

---

## 七步流程

```
① 调研      企业官网 / 高校就业网原文 → 岗位、专业口径、工作地
② 核实      邮箱来源分级 → MX 体检 → 必要时 RCPT 探测
③ 匹配      岗位职责 ↔ 你的项目经历，找出真正重合的那一条
④ 定制      每封单独写，不套模板；技能缺口如实披露
⑤ 核对表    公司 / 岗位 / 地点 / 收件人 / 来源验证，五项摊开给人看
⑥ 闸门      用户明确确认 → 才允许发送（程序层面强制）
⑦ 核查      发送日志 → MX → 退信扫描 → 「已发送」逐地址检索
```

每一步都有对应的脚本或清单，见 [`docs/01-workflow.md`](docs/01-workflow.md)。

---

## 三条不可妥协的原则

### 1. 不把「发出去了」当成「送到了」

送达被拆成四级，**汇报时禁止混为一谈**：

| 级别 | 手段 | 能证明什么 |
|---|---|---|
| ① | SMTP 返回 250 | 我的发件服务器接受了这封信（**最弱**） |
| ② | 收件域名 MX 体检 | 对方域名当前能收信 |
| ③ | 无退信 / RCPT 返回 250 | 这个地址很可能真实存在 |
| ④ | 收到企业回信 | HR 真的读到了——**任何工具都测不出来** |

大多数「自动化投递工具」只做到 ①，然后告诉你「投递成功」。

### 2. 不做虚假陈述

邮件正文里出现「已同步完成网申」这句话时，前提必须是网申**真的提交了**。
没提交就写「我会通过贵司官方网申渠道提交」——意思一样，事实不同。

`scripts/_draft.py` 会对若干高风险表述给出告警（只提醒，不替代人判断）：

```
! 正文出现「已同步完成网申」——断言已完成网申，除非真的提交过，否则改为「我会通过……提交网申」
! 正文出现「头部企业」——对企业地位的评价性断言，需有可引用的原始出处，否则删除
```

### 3. 未经确认，程序发不出去

`--send` 必须同时带 `--approved`。语义是：**用户已经逐行确认过核对表**。

```
$ python scripts/send_resume.py --send
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
已拦截：--send 未附带 --approved —— 尚未取得用户对核对表的确认。
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
$ echo $?
3
```

这条闸门不是靠人记住流程，而是退出码 3。

---

## 快速开始

### 1. 拿到代码

```bash
git clone https://github.com/<你的用户名>/AutoJobApply.git
cd AutoJobApply
pip install openpyxl          # 可选，用于生成 Excel 统计表
```

### 2. 配置

```bash
cp config/config.example.json config/config.json
# 填写 config.json 里所有 {{...}} 占位符

export AUTOJOB_AUTHCODE='你的邮箱授权码'    # Windows PowerShell: $env:AUTOJOB_AUTHCODE='...'
```

> **占位符没填完会直接报错退出**，并列出未填的每一项。这是故意的——
> 防止拿模板配置把邮件发到 `{{SENDER_EMAIL}}` 这种地址。

### 3. 写第一封草稿

```bash
cp drafts/examples/E1_标准技术岗.txt drafts/D1_某某公司.txt
# 改头部五项 + 重写正文
```

### 4. 出核对表，人工确认

```bash
python scripts/preflight.py --dns --html
```

终端会打印五个字段，并生成 `state/preflight.html` 供逐行核对。

### 5. 确认后投递

```bash
python scripts/send_resume.py --send --approved --only D1
```

### 6. 核查送达

```bash
python scripts/verify_delivery.py
```

### 7. 同步统计

```bash
cp state/applications.example.json state/applications.json
# 按实际投递情况填写
python scripts/make_stats.py
```

---

## 目录结构

```
AutoJobApply/
├── config/
│   ├── config.example.json     配置模板（全占位符）
│   └── README.md              配置项逐条说明
├── scripts/
│   ├── _config.py             配置加载：占位符检测、环境变量凭据
│   ├── _draft.py              草稿解析 + 投递前五项校验
│   ├── preflight.py           核对表生成器（含 MX 体检）
│   ├── send_resume.py         幂等发送器（含 --approved 闸门）
│   ├── verify_delivery.py     五段式送达核查
│   └── make_stats.py          统计表生成（含交叉校验）
├── drafts/
│   ├── _TEMPLATE.txt          草稿模板（含全部字段说明）
│   └── examples/              三个脱敏示例：标准 / 诚实披露 / 咨询邮箱
├── docs/
│   ├── 01-workflow.md         七步流程详解
│   ├── 02-email-verification.md  邮箱来源分级与核实方法
│   ├── 03-safety-rules.md     九条硬规则
│   ├── 04-platform-setup.md   GPT / Trae / 豆包 / Claude 接入
│   ├── 05-troubleshooting.md  踩过的坑
│   └── 06-deliverability.md   送达原理与退信归因
├── prompts/
│   ├── universal.md           通用提示词（任何平台可粘贴）
│   ├── gpt.md                 GPTs Instructions 版
│   ├── trae.md                Trae rules 版
│   └── doubao.md              豆包智能体指令版
└── state/                     运行产物（已被 .gitignore 排除）
```

---

## 不想用脚本？也可以

这套方法论**不依赖 Python**。`prompts/` 下有四个平台的提示词版本，
把对应文件粘进 GPTs / Trae / 豆包 / Claude 的自定义指令，就得到一个会按同样流程办事的助手。

| 平台 | 用哪个文件 | 贴在哪里 |
|---|---|---|
| GPTs | `prompts/gpt.md` | Create → Instructions |
| Trae | `prompts/trae.md` | `.trae/rules/project_rules.md` |
| 豆包 | `prompts/doubao.md` | 智能体 → 角色设定 |
| Claude / WorkBuddy | `prompts/universal.md` | Project Instructions 或 Skill |
| 其他 | `prompts/universal.md` | 任何支持自定义指令的对话框 |

区别在于：**没有脚本时，闸门是「规则」；有脚本时，闸门是「退出码」。**
后者不会因为模型这一次心情好就放行。

---

## 诚实的边界

这个项目**做不到**的事，写在这里而不是留给你自己发现：

- **测不出 HR 是否读了你的邮件。** 没有已读回执就是没有，任何声称能测的都是猜。
- **不能保证邮箱一定有效。** RCPT 返回 250 也只说明服务器愿意收下，不代表有真人看。
- **不能替你写出一封好邮件。** 它只能防止你写出一封有事实错误或明显套话的邮件。
- **不绕过任何平台的规则。** 频繁投递、伪造身份、同一岗位反复投，这些事它不帮你做，也不该做。
- **`nslookup` 依赖本地网络。** 如果你在国内网络环境下 DNS 被污染或拦截，MX 体检结果可能不准；脚本会把「nslookup 本身跑不起来」和「域名真的没有 MX」区分开。

---

## 关于这个仓库的来历

代码和规则来自一次真实的 2027 届秋招投递工程：12 封邮件、20 家企业、一轮完整的核实与核查。

里面每一条硬规则都不是拍脑袋写的，而是**由一次真实失误或一次险些发生的失误换来的**——
包括那条「SMTP 返回成功后邮件被退回」的规则，以及「看已发送文件夹总数会把两轮的账记混」的规则。

具体案例在 [`docs/05-troubleshooting.md`](docs/05-troubleshooting.md) 里，公司名与邮箱已脱敏。

---

## License

[MIT](LICENSE)
