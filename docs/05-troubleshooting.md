# 五、踩坑记录

> 这一节里的每一条都是**真的踩过**才写下来的。
> 附带的修复方式已经体现在代码里，这里记录「为什么」——避免以后有人把它改回去。

---

## 坑 1 · `nslookup` 在中文 Windows 下输出 GBK，`text=True` 会崩

### 现象

```python
subprocess.run(["nslookup", "-type=mx", domain], capture_output=True, text=True)
```

抛 `UnicodeDecodeError`，或者 `.stdout` 直接变成 `None`，后续 `AttributeError`。

### 原因

Windows 下 `nslookup` 按系统本地代码页输出。简体中文系统是 GBK，
而 `text=True` 默认用 UTF-8 解码。

### 修复

```python
# 按字节捕获，容错解码
proc = subprocess.run(args, capture_output=True, timeout=25)
output = proc.stdout.decode("utf-8", "ignore")
```

我们只关心 MX 主机名和 IP，都是 ASCII，中文乱码不影响判断。

---

## 坑 2 · 用正则找 IPv4，被 IPv6 骗了

### 现象

某个域名明明能收信（实际也收到了邮件），MX 体检却报「❌ MX 不解析」。

### 原因

初版正则要求 IP 紧跟在 `Address:` 标签后面：

```python
# 错
re.search(r"Address(?:es)?\s*:\s*\d+\.\d+\.\d+\.\d+", output)
```

但 `nslookup` 经常**先打印 IPv6**：

```
Name:    mx1.example.com
Addresses:  2408:4003:...
            203.0.113.10
```

`Addresses:` 后面第一个是 IPv6，正则匹配失败 → 误判为「没有 IPv4」。

### 修复

```python
# 对：在整个输出里找任意一个 IPv4
re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", output)
```

### 更好的修复

本项目最终改用 `socket.getaddrinfo`，从根上绕开文本解析：

```python
infos = socket.getaddrinfo(host, 25, socket.AF_INET, socket.SOCK_STREAM)
return bool(infos)
```

既不受编码影响，也不会被 IPv6 干扰，还跨平台。

> **教训：能从协议层拿结论，就不要靠解析命令行文本。**

---

## 坑 3 · MX 体检发现问题，但邮件还是发出去了

### 现象

核对表里明确显示 `MX ❌ 异常`，但该目标仍然被标为「就绪」，照样可以发送。

### 原因

初版的 `check()` 只校验五项字段，**不包含 MX 结果**。MX 只是「展示信息」，
没有参与阻断判断。

这正好复现了那个最危险的事故模式：**看到了警告，但警告没有拦人。**

### 修复

把 MX 异常升级为阻断项：

```python
if status == "异常" and "nslookup" not in detail:
    problems.append(f"收件域名 {domain} 的 MX 不可用（{detail}）——该地址一定收不到信")
```

同时，`send_resume.py` 在真正发送前会**再复核一次 MX**（`_mx_gate`），
因为核对表可能是几小时前生成的。

### 但要注意区分

| 情况 | 是否阻断 | 理由 |
|---|---|---|
| 域名确实没有 MX / MX 主机解析不出 IP | ✅ 阻断 | 这封信一定进不去 |
| `nslookup` 本身执行失败 | ❌ 只警告 | 可能是本地网络/DNS 问题，不是对方的问题 |

**把「环境问题」和「对方问题」分开，否则在自己网络不好时会误伤所有目标。**

---

## 坑 4 · 退信扫描报出一堆无关地址

### 现象

退信扫描报告：

```
发现退信地址：PostMaster@qq.com, localhost.localdomain, tencent_xxx@qq.com
```

真正要关注的地址反而被淹没了。

### 原因

直接从退信正文里正则提取**所有**邮箱地址。而 DSN 里必然混有：
- 你自己的退信通知地址（`PostMaster@qq.com`）
- 邮件系统内部地址（`mailer-daemon@localhost.localdomain`、`tencent_xxx@qq.com`）

### 修复

只保留**发送日志里真实出现过的地址**：

```python
known = {日志里所有 TO 和 CC，小写}
失败地址 = {DSN 里提取的所有地址} & known
```

一个交集操作同时解决两件事：过滤噪声 + 把退信归因到具体某一封。

---

## 坑 5 · 「已发送」开关不补录历史，看总数会把两轮记混

### 现象

先得出结论「总数 147 → 152，当天 5 封，第二轮已存档」。
改成逐地址检索后发现：真实是 153 / 当天 6 封，命中 9 个地址，
而且**第一轮 5 个地址命中数全是 0**。

### 原因

两个独立的错误叠在一起：

1. **「SMTP 发信保存到服务器」是后开的**，它不会补录开启之前发出的邮件
2. **看总数无法区分是哪几封**，多轮投递的账混在一起

### 修复

核查脚本第四部分改成**按发送日志里的每个地址（含抄送）逐个 `SEARCH TO`**，
输出命中率和命中清单。

并在输出里明确写一句：

> 未命中 ≠ 投递失败：若「SMTP 发信保存到服务器」开关是后开的，
> 它不会补录开启之前发出的历史邮件。

### 教训

**任何「汇总数字」都可能掩盖分类错误。** 当你要验证「某几件事是否都做成了」，
就逐件验证，不要看总数。

---

## 坑 6 · 抄送地址没被纳入退信归因

### 现象

退信里提到了抄送地址，但脚本没报出来。

### 原因

收集「已知收件人」时只取了日志里的 `to` 字段，漏了 `cc`。

### 修复

```python
for key in ("to", "cc"):
    ...收集地址...
```

**抄送地址失效同样会产生退信，同样影响发件信誉。**

---

## 坑 7 · `LOCATION` 字段混入说明文字，污染统计口径

### 现象

统计交叉校验报错：

```
C1: 工作地点不一致 —— 发送日志「珠海（另有郑州、许昌、北京…）」 vs 统计表「珠海」
```

### 原因

草稿里把「首选城市 + 其他可选城市」全写进了 `LOCATION` 一个字段。
而 `LOCATION` 是**统计口径字段**，必须是单一值。

### 修复

拆成两个字段：

```ini
# LOCATION: 珠海                    ← 统计口径，只放首个意向城市
# LOCATION_ALT: 郑州、许昌、北京…    ← 备选城市，仅供人看，不进统计
```

### 通用原则

**一个字段只承担一种语义。** 想同时表达「首选」和「备选」，就开两个字段。

---

## 坑 8 · bash 吃掉了 Python f-string 里的花括号

### 现象

用 `cat <<EOF` 往文件里追加内容，结果生成的文本里出现了字面量：

```
收件人：　抄送：
```

本该被替换的变量全空了。

### 原因

多层引号嵌套时，shell 与 Python 的转义规则互相干扰。中文 `echo` 配合
f-string 内插尤其容易出事。

### 修复

**不要在 shell heredoc 里写需要变量内插的复杂 Python 代码。**

改用：
- 独立的 `.py` 文件（用 Write 工具直接写文件，不经 shell）
- 或者 `python - <<'PY'`（注意引号：`'PY'` 阻止 shell 展开）

本项目所有文件生成都走 Write 工具，不经 shell 拼接。

---

## 坑 9 · 装不上 `openpyxl`：镜像源没有 index

### 现象

```bash
pip install openpyxl
# ERROR: No matching distribution found for openpyxl
```

### 原因

配置的清华镜像源缺少索引文件（或该镜像当前异常）。

### 修复

显式指定官方源：

```bash
pip install openpyxl -i https://pypi.org/simple
```

### 更稳妥的做法

`make_stats.py` 里把 `openpyxl` 做成**可选依赖**：

```python
try:
    from openpyxl import Workbook
except ImportError:
    print("[跳过] 未安装 openpyxl，只生成 Markdown。安装：pip install openpyxl")
    return False
```

**核心功能（Markdown 统计表）不依赖它。** 少一个依赖就少一个装不上的理由。

---

## 坑 10 · 邮件头混合编码导致 `LookupError`

### 现象

```python
from email.header import decode_header, make_header
str(make_header(decode_header(raw)))
# LookupError: unknown encoding: unknown-8bit
```

### 原因

某些邮件客户端生成的头里声明了 `unknown-8bit` 这类非标准编码。
`make_header` 遇到不认识的编码直接抛异常。

### 修复

包一层容错：

```python
def decode_header_safe(raw) -> str:
    try:
        return str(make_header(decode_header(raw or "")))
    except Exception:
        return (raw or "").encode("utf-8", "ignore").decode("utf-8", "ignore")
```

**扫描退信时，遇到一封解不开的邮件不应该让整个扫描中断。**

---

## 坑 11 · 交叉校验过严：把「没日志」当成「错」

### 现象

台账里登记了 `draft_id`，但发送日志里没有对应记录（因为那条是网申渠道，
或者日志被清理过）。脚本直接报错，退出码 1。

### 原因

校验逻辑把「台账有、日志无」和「地点不一致」当成了同一等级的硬错误。

但它们不是一回事：

| 情况 | 严重性 | 理由 |
|---|---|---|
| 地点不一致 | **硬错误** | 统计口径已失真，必须修 |
| 日志有、台账没登记 | **硬错误** | 真的漏账，统计偏少 |
| 台账有、日志没有 | 提示 | 可能是网申渠道、历史台账、日志清理 |

### 修复

拆成 `(errors, notices)` 两个返回：

```python
errors, notices = check_against_log(records, send_log)
```

只有 `errors` 影响退出码。

> **教训：校验要分级。全是硬错误等于没有分级，会逼人忽略所有报错。**

---

## 坑 12 · 配置模板的占位符没填，脚本把邮件发给了 `{{SENDER_EMAIL}}`

### 现象（这是被提前拦下的一次）

如果配置里留着一个未替换的占位符，SMTP 会尝试连接那个地址并失败，
或者在更糟的情况下，用错误的发件人身份发出去。

### 修复

**占位符即错误。** `load_config()` 加载时递归扫描所有 `{{...}}`，
发现任何一个就抛出 `ConfigError` 并列出全部未填项：

```
配置里还有 3 项占位符未填写：
  · sender.email -> {{SENDER_EMAIL}}
  · candidate.name -> {{姓名}}
  · preferences.priority_cities[0] -> {{城市1}}
请在 config/config.json 中替换后再运行。
```

这个检查会让「复制模板就想跑」的人卡在第一步。**这是故意的。**

---

## 坑 13 · 中文路径里带 `&`，shell 里必须整体加引号

### 现象

```bash
cd D:/工作/个人简介&工作/求职     # & 后面的被当成另一个命令
```

### 修复

```bash
cd "D:/工作/个人简介&工作/求职"
```

Windows 中文路径 + `&` 是 Git Bash 里的高频事故点。
本项目的仓库路径特意避开了中文与 `&`，就是这个原因。

---

## 坑 14 · 代码里写了「已同步完成网申」，实际没投

### 现象

邮件正文里出现「我也已通过贵司官方网申渠道同步提交申请」，
但网申并没有提交。

### 原因

写草稿时「顺手」把这句话写成了既成事实。这是**最容易复发**的一类错误——
因为这句话读起来更顺、更主动、显得更有诚意。

### 修复

统一改成意愿表述：

```
✅ 我会通过贵司官方网申渠道提交申请，此信作为补充
❌ 我已同步在贵司网申系统完成投递
```

并在 `_draft.py` 里加了模式告警，每次生成核对表时都会检查。

### 教训

**这个错误不是「不小心」，是「表达习惯」导致的系统性偏差。**
必须靠工具反复检查，不能靠记性。

---

## 一份检查清单

改这个项目的代码之前，先问：

- [ ] 我有没有把「展示用的信息」和「参与判断的信息」搞混？（坑 3）
- [ ] 我有没有用文本解析去做协议层能给出答案的事？（坑 2）
- [ ] 我的校验会不会把「环境问题」和「对方问题」当成一回事？（坑 3）
- [ ] 我有没有依赖一个可能装不上的包来完成核心功能？（坑 9）
- [ ] 我的报错是分级的，还是全都很严重？（坑 11）
- [ ] 我有没有在 shell 里拼需要变量内插的代码？（坑 8）
- [ ] 我改动的是「统计口径字段」还是「展示字段」？（坑 7）
