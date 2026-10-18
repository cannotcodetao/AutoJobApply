# AutoJobApply

**A guarded, auditable pipeline for emailing your résumé to campus recruiters.**

Not a bulk sender. The whole point is to **stop the one email that shouldn't go out** — wrong company, wrong role, a dead mailbox, a false claim, or a send that nobody approved.

<p align="center">
  <img src="assets/workflow.svg" alt="Seven-step workflow" width="880">
</p>

---

## The problem it solves

Emailing a résumé looks trivial: write a message, attach a PDF, hit send. In practice:

| You assume | What actually happens |
|---|---|
| A published recruiting address works | The domain's **MX record points at a host that doesn't exist**. SMTP returns `250`, the message is bounced seconds later, and you never notice |
| "Sent" means "delivered" | `250` only means *your* server accepted it. There is a whole road after that |
| Five universities list the same address, so it's verified | Five copies of the same source are still one source |
| Let an AI blast fifty applications | It will quietly turn "I will apply via your portal" into "I have completed the application" |
| You'll remember what you applied to | A week later you won't remember the role, the city, or the outcome |

AutoJobApply turns each of those into an **executable check**.

---

## Three non-negotiables

### 1. "Sent" is not "delivered"

Delivery is reported at four distinct levels, always kept separate:

| Level | Method | What it actually proves |
|---|---|---|
| ① | SMTP `250` | My sending server accepted it (**weakest**) |
| ② | MX health check | The recipient's domain can currently receive mail |
| ③ | No bounce / RCPT `250` | The mailbox very likely exists |
| ④ | A human replies | Someone actually read it — **unobservable by any tool** |

Most automation stops at ① and calls it success.

### 2. No false statements

"I have completed the application via your portal" is only allowed if the portal was actually submitted. Otherwise: "I will submit via your portal."

`scripts/_draft.py` flags high-risk phrasing in every draft body.

### 3. Nothing sends without approval

```bash
$ python scripts/send_resume.py --send
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
Blocked: --send requires --approved — the preflight checklist has not been
confirmed by the user.
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
$ echo $?
3
```

The gate is an **exit code**, not a reminder in the docs.

---

## Quick start

```bash
git clone https://github.com/<you>/AutoJobApply.git
cd AutoJobApply
pip install openpyxl                      # optional, for the Excel report

cp config/config.example.json config/config.json
# replace every {{placeholder}} — unfilled placeholders abort on load, by design

export AUTOJOB_AUTHCODE='your-app-password'

cp drafts/examples/E1_标准技术岗.txt drafts/D1_SomeCompany.txt
# edit the header, rewrite the body

python scripts/preflight.py --dns --html    # ① build the checklist
# ② human reviews it
python scripts/send_resume.py --send --approved --only D1
python scripts/verify_delivery.py           # ③ verify, level by level
```

---

## Layout

```
config/     configuration template (credentials never live here)
scripts/    preflight.py · send_resume.py · verify_delivery.py · make_stats.py
drafts/     one .txt per email, with a metadata header
docs/       workflow, verification, safety rules, platform setup, pitfalls
prompts/    one rule set, adapted for GPTs / Trae / Doubao / Claude
state/      runtime artifacts (gitignored)
```

---

## Without scripts

The methodology does not require Python. `prompts/` contains the same rule set adapted for
GPTs, Trae, Doubao, and Claude.

The difference is honest:

> **With scripts, the gate is an exit code. Without them, the gate is a promise.**

The tradeoff is documented in [`prompts/README.md`](prompts/README.md).

---

## Honest limits

- **Cannot detect whether a human read your email.** No read receipt, no way to know.
- **Cannot guarantee an address is valid.** `250` from RCPT means the server will accept it, nothing more.
- **Cannot write a good email for you.** It can only prevent one with factual errors or obvious boilerplate.
- **Does not circumvent any platform's rules.** No forging, no spraying, no re-applying to the same role.
- **`nslookup` depends on your network.** The scripts distinguish "nslookup failed locally" from "the domain genuinely has no MX".

---

## Where this came from

Every hard rule here was paid for by a real mistake — or a mistake that was caught just in time —
during one actual 2027 campus recruiting cycle: 12 emails, 20 companies, one full verification pass.

Company names and addresses in the docs are redacted. The cases are in
[`docs/05-troubleshooting.md`](docs/05-troubleshooting.md) (Chinese).

---

## License

[MIT](LICENSE)
