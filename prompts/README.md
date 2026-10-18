# 提示词：选哪个

同一套规则，四份裁剪。**规则内容一致，只是长度和形态适配不同平台。**

| 文件 | 用在哪 | 特点 |
|---|---|---|
| [`universal.md`](universal.md) | Claude / WorkBuddy / 任何支持长指令的平台 | 最完整，含方法论解释 |
| [`gpt.md`](gpt.md) | GPTs → Instructions | 压缩版，保留全部硬规则 + 核对表示例 |
| [`trae.md`](trae.md) | Trae → `.trae/rules/project_rules.md` | 含「如何调用本仓库 scripts/」的操作段 |
| [`doubao.md`](doubao.md) | 豆包 → 智能体角色设定 | 对话式追问脚本，适配无执行环境 |

---

## 一句话选择

```
能碰文件、能跑脚本  →  trae.md（Trae）或 universal.md（Claude/WorkBuddy）
只能聊天            →  gpt.md（GPTs）或 doubao.md（豆包）
不确定              →  universal.md
```

---

## 一个重要的区别

| 有脚本 | 没脚本 |
|---|---|
| 闸门是**退出码 3** | 闸门是**模型的一句承诺** |
| MX 异常自动阻断 | 要模型主动记得拦住 |
| 幂等由日志保证 | 要靠模型记得「这封发过了」 |

**所以：没有执行环境的平台上，真实发送这一步请自己手动做。**

推荐分工：

```
GPTs / 豆包    →  写正文、查来源、列核对表
本地 scripts/  →  发送、核查、统计
```

让每个工具做它擅长的事。

---

## 改规则时

**四份一起改。**

如果 `trae.md` 里说「MX 不通过不发」，而 `doubao.md` 里没说，
就会出现「在 Trae 里被拦下的操作，在豆包里被放行」——这比没有规则更危险。
