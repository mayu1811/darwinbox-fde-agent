# Recording script — 2 to 3 minutes

The brief requires the recording to show **at least one escalation being
resolved through the UI**. That is beat 4 below; everything else is framing.

Keep it short. A tight 2:30 beats a rambling 6:00.

---

## Before you hit record

```bash
cd "C:\Users\bicycle\Downloads\darwinbox-fde-agent\backend" && .venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
```

```bash
cd "C:\Users\bicycle\Downloads\darwinbox-fde-agent\frontend" && npm run dev
```

- Open **http://localhost:5173** and click **Reset demo** → confirm. Start from
  the empty state.
- Close other tabs, silence notifications, browser at ~90% zoom so the stat
  cards and the escalation card both fit.
- Have `data/employees_legacy.csv` open in a second tab or window for beat 1.

**Tool:** Windows **Xbox Game Bar** is already installed — `Win + G`, then the
record button, or `Win + Alt + R` to start/stop directly. It writes MP4 to
`Videos\Captures`. [OBS](https://obsproject.com) if you want a webcam inset.
Record the browser window only, not the whole desktop.

---

## The five beats

### 1 · The problem (20s)
Show the CSV next to the XLSX.

> "A client is migrating off a legacy HR system. Two exports that disagree:
> different column names, three date formats, duplicate rows, one employee
> with no email anywhere, and a column called `Contact No` that could mean two
> different things."

### 2 · Start it (25s)
Click **Run demo migration**. Stay on the overview while it runs.

> "It profiles both files, maps every column against the target schema, cleans,
> de-duplicates and validates. This isn't animation — every number is backend
> state streaming over SSE."

Let the stat cards land: **33 source rows → 26 records, 7 duplicates
reconciled, ~96 values cleaned.**

### 3 · Where it stops (30s)
It halts at `WAITING FOR HUMAN`. Click **Review now**.

> "About 310 decisions on its own, and three questions."

Open the `Contact No` card and read the reasoning line aloud:

> "`mobile_phone` 74%, `work_phone` 70%. It's confident this is a phone field
> and uncertain which one — a single confidence score hides that, so the policy
> uses the *margin*. A four-point gap is below the fifteen required to decide
> alone."

### 4 · Resolve it — **the required beat** (35s)
Type a note in the audit field: *"legacy CRM only ever stored personal mobiles"*.
Click **mobile_phone**.

Show the card flip to resolved — *Resolved by · Applied · Agent resumed*.

Resolve the other two:
- `EMP1017` status → **inactive**
- `EMP1042` email → accept the suggestion

> "On the third decision the agent resumes on its own — re-runs the pipeline
> with the new facts, re-validates, and pushes. One decision, not a sequence of
> clicks."

### 5 · Push, retry, audit, rollback (45s)
**Target push:**

> "`EMP1009` — two transient 503s, retried automatically, succeeded on the
> third. `EMP1011` — the target rejected its department outright; that's a 422,
> so it's surfaced rather than retried forever."

Click **Retry failed** → `EMP1022` succeeds on attempt 4.

**Audit trail** → filter actor = **Human**:

> "343 events. Three of them human. That's the autonomy story."

**Rollback** → confirm.

> "Every write was tagged with the migration id, so this removes exactly this
> migration's records. That reversibility is half of why the agent is allowed
> to act alone."

---

## Close (10s)

> "Confidence plus reversibility determines autonomy. Deterministic, reversible,
> high-confidence work happens automatically. Ambiguity, mandatory-field
> guesses and destructive actions go to a human. The goal isn't an agent that
> never asks — it's one that asks about the right three things and can tell you
> exactly why."

---

## If a take goes wrong

**Reset demo** in the sidebar wipes everything and you start clean. The run is
deterministic: the same 3 escalations, the same failures, every time. Don't try
to fix a fluffed take mid-recording — reset and go again.

## Don't bother filming

Setup, `npm install`, the test suite, the code. Link the repo for those. The
recording exists to prove the escalation loop works end to end.
