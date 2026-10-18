# 配置说明

复制模板并填写：

```bash
cp config/config.example.json config/config.json
```

`config/config.json` 已在 `.gitignore` 中，**不会被提交**。

---

## 一条最重要的规则：凭据不落盘

邮箱密码 / 授权码**只从环境变量读取**，配置文件里永远不写。这样即使整份配置被误提交、
被截图、被分享，也不存在凭据泄露。

```bash
# macOS / Linux
export AUTOJOB_AUTHCODE='你的授权码'

# Windows PowerShell
$env:AUTOJOB_AUTHCODE='你的授权码'
```

> QQ 邮箱授权码获取路径：设置 → 账号 → POP3/IMAP/SMTP 服务 → 开启并生成授权码。
> **注意是授权码，不是 QQ 登录密码。** 用密码登录会直接失败。

若想用别的变量名，改 `sender.authcode_env` 即可；变量名本身不敏感。

---

## sender —— 发件与收件服务器

| 字段 | 说明 |
|---|---|
| `email` | 发件邮箱。**必须填**，且与授权码对应 |
| `from_name` | 收件人看到的发件人显示名，可留空（留空则只显示邮箱地址） |
| `smtp_host` / `smtp_port` | 发信服务器。QQ 邮箱为 `smtp.qq.com:465`（SSL）；163 为 `smtp.163.com:465`；Gmail 为 `smtp.gmail.com:587`（脚本会自动改用 STARTTLS） |
| `imap_host` / `imap_port` | 收信服务器，仅核查脚本使用。QQ 为 `imap.qq.com:993` |
| `authcode_env` | 存放授权码的环境变量名，默认 `AUTOJOB_AUTHCODE` |
| `interval_sec` | 两封邮件之间的间隔秒数。不建议低于 10 秒，连续快速发信容易触发风控 |

---

## candidate —— 候选人信息

这些值不会自动替换进草稿。它们的作用是**让 AI 写邮件时有一个权威的事实来源**，
也让你自己每次核对时不必翻记录。

| 字段 | 说明 |
|---|---|
| `name` | 姓名 |
| `phone` | 手机号 |
| `email` | 联系邮箱（可以就是发件邮箱） |
| `school` / `major` / `degree` | 学校 / 专业 / 学历 |
| `graduation` | 毕业时间，如 `2027.06` |

> **为什么要填全**：邮件正文里出现的人名、电话、学校如果和配置对不上，
> 是最容易被 HR 记住的低级错误。配置化之后至少有一个地方是准的。

---

## preferences —— 求职偏好

| 字段 | 说明 |
|---|---|
| `priority_cities` | 优先城市列表。核对表里「工作地点」是否命中这个列表，是你拍板的依据 |
| `accepts_travel` | 是否接受出差 / 驻厂 |
| `notes` | 其他硬约束，自由文本 |

---

## paths —— 路径

相对路径一律相对**仓库根**解析，所以脚本从任何目录调用都能跑。

| 字段 | 默认 | 说明 |
|---|---|---|
| `drafts` | `drafts` | 草稿目录 |
| `attachments` | `attachments` | 附件根目录（草稿里的 `ATTACH` 写相对路径时以它的上级为基准） |
| `state` | `state` | 运行产物目录（日志、导出文件） |
| `send_log` | `state/send_log.json` | 发送日志，幂等判断依据 |
| `applications` | `state/applications.json` | 投递台账，统计表的数据源 |
| `stats_xlsx` | `state/applications.xlsx` | 统计表输出路径 |

---

## safety —— 安全闸门

**除非你完全清楚后果，否则不要改这几项。**

| 字段 | 默认 | 说明 |
|---|---|---|
| `require_approved` | `true` | `--send` 必须配 `--approved` 才真发。改成 `false` 等于拆掉确认闸门 |
| `max_sends_per_run` | `10` | 单次运行最多发几封，防止误配导致批量群发 |
| `block_unverified_source` | `true` | 来源标注为「待核实」的目标一律拒发 |
| `verify_mx_before_send` | `true` | 真正投递前再查一次收件域名的 MX。**这条是拿一次真实退信换来的**：SMTP 返回成功之后邮件依然可能因域名 MX 指向不存在的主机而被退回 |

---

## stats —— 统计

| 字段 | 默认 | 说明 |
|---|---|---|
| `business_scope_max_chars` | `15` | 「业务范围」列的字数上限。超过会在生成时被点名，逼你把描述压短 |

---

## 环境变量一览

| 变量 | 作用 |
|---|---|
| `AUTOJOB_AUTHCODE` | 邮箱授权码（或用 `sender.authcode_env` 自定义名字） |
| `AUTOJOB_CONFIG` | 指定配置文件路径，默认 `config/config.json` |
| `AUTOJOB_DRY_RUN` | 设为 `1` 时**全局干跑**，任何脚本都不会真实发信。适合在不确定环境里先跑一遍 |

---

## 常见配置错误

| 现象 | 原因 | 处理 |
|---|---|---|
| `配置里还有 N 项占位符未填写` | 复制了模板但没替换 `{{...}}` | 按提示逐项填写。这是**故意的**——防止拿模板配置把邮件发到占位符地址 |
| `缺少邮箱授权码：环境变量 ... 未设置` | 没设环境变量，或设置在了另一个终端窗口 | 在当前终端重新 export；PowerShell 里 `$env:` 只在当前会话有效 |
| `配置文件中出现了疑似敏感字段` | 把密码写进了 config.json | 删掉该字段，改用环境变量 |
| `SMTPAuthenticationError 535` | 用了登录密码而不是授权码 | 去邮箱设置里生成授权码 |
