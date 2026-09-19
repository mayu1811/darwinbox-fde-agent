# Demo Script — 3 to 5 minutes

**Setup before you start:** backend on `:8000`, frontend on `:5173`, and click
**Reset demo** in the sidebar so you begin from an empty state.

The single sentence to land: **automation should be the default, but
uncertainty should be explicit.**

---

## 1 · The problem (25s)

> "A client is moving off a legacy HR system. They send two exports that
> disagree with each other. Doing this by hand takes days and makes silent
> mistakes. A naive script takes seconds and makes *confident* silent mistakes."

## 2 · The messy input (30s)

Open `data/employees_legacy.csv` next to `data/employees_hr.xlsx`.

> "Different column names — `Emp ID` versus `employee_code`, `DOB` versus
> `birth_date`. Different date formats in the same dataset. Stray whitespace,
> shouting emails. The same employees in both files. Duplicate rows inside each
> file. One employee with no email anywhere. And a column called `Contact No`
> that could mean two different things."

*(Optional: `python seed_demo.py` prints all 16 intentional defects.)*

## 3 · Start the agent (20s)

Click **Run demo migration**.

> "The agent ingests both files, profiles every column, and starts mapping. The
> UI isn't animating — every number is backend state streaming over SSE."

Point at the pipeline on **Agent activity** as it moves through
`PROFILING → MAPPING → CLEANING → DEDUPLICATING → VALIDATING`.

## 4 · Schema discovery and mapping (40s)

Open **Field mappings**.

> "It inferred each source schema and scored every column against the target.
> `DOB` → `date_of_birth` at 99%. `joiningDate` → `joining_date` at 99% —
> it split the camelCase first."

Click a row to expand.

> "Every mapping carries its reasoning and every candidate it considered. And
> note `Remarks` and `location`: no target field resembles them, so they are
> left unmapped. Not guessing is the correct answer."

## 5 · Cleaning (25s)

Open **Data preview**, expand `EMP1001`.

> "`'  Rajesh  Kumar '` → `Rajesh Kumar`. `'RAJESH.KUMAR@ACME-CORP.COM '` →
> lowercased. `12/08/1988` → `1988-08-12`. `Active` → `active`. Every change
> shows its rule and is reversible from the audit trail. None of this needed a
> human — it's deterministic and meaning-preserving."

## 6 · Duplicates (25s)

Filter to **Duplicates**.

> "33 source rows became 26 employees. Exact duplicate rows merged silently.
> `EMP1031` had no email in the CSV but did in the Excel — the agent filled it
> from the duplicate. That's a gain of information, so no human needed."

## 7 · Where it stops (45s) — **the heart of the demo**

Open **Escalations**. Three cards, and the panel explaining the boundary.

> "It made about 310 decisions on its own and has three questions."

Read the `Contact No` card:

> "`mobile_phone` 74%, `work_phone` 70%. The agent is **confident it's a phone
> field** and **uncertain which one**. A single confidence score hides that. So
> the policy uses the *margin* — a four-point gap is below the fifteen points
> required to decide alone."

Then `EMP1042`:

> "No email in either file. It *can* derive one from the name — it shows you
> that suggestion at 45% — but it won't apply it. A wrong email is an
> onboarding failure, and it isn't reversible once the welcome mail goes out."

Contrast with `EMP1004`:

> "Compare that to this record's date of birth: `31 February 1990`. Also
> impossible to fix. But the field is optional, so the agent dropped it,
> recorded why, and carried on. Same uncertainty, different consequence,
> different answer. **That's the whole design.**"

## 8 · Human resolves, agent resumes (35s)

- `Contact No` → **`mobile_phone`** (add a note: *"legacy CRM only stored mobiles"*)
- `EMP1017` status → **`inactive`**
- `EMP1042` email → accept the suggestion

> "On the third decision the agent resumes automatically. It re-runs the
> transform pipeline with the new facts, re-validates the affected records, and
> pushes. The consultant makes a decision, not a sequence of clicks."

Show the resolved cards: *Resolved by · Applied · Agent resumed and re-validated.*

## 9 · Push, failure, retry (45s)

Open **Target push**.

> "25 accepted. Three records are interesting."

- `EMP1009` — `#1✕ #2✕ #3✓`
  > "Two transient 503s, retried with backoff, succeeded on the third. The agent
  > never asked — retrying a transient error is routine work, not a decision."
- `EMP1011` — **not retryable**
  > "`Ops Excellence` isn't in the target's department master data. That's a 422.
  > Retrying a 422 is just a slower 422, so it's surfaced instead of looped."
- `EMP1022` — **retryable**, failed all three attempts.

Click **Retry failed**.

> "`EMP1022` succeeds on attempt four. `EMP1011` stays failed — correctly."

## 10 · Audit trail (25s)

Open **Audit trail**. Filter actor → **Human**.

> "343 events. Three of them human. Every agent decision has a confidence and a
> reason; every human decision has who, what and why. This is what you show the
> client when they ask what you changed in their data."

## 11 · Rollback (20s)

Click **Rollback**, read the confirmation dialog, confirm.

> "Every write was tagged with the migration id, so this removes exactly this
> migration's 25 records — anything already in the target is untouched. That
> reversibility is half the reason the agent is allowed to act alone in the
> first place."

## 12 · Close (20s)

> "The principle is **confidence plus reversibility determines autonomy**.
> Deterministic, reversible, high-confidence work happens automatically — that
> was 310 decisions here. Ambiguity, mandatory-field guesses, conflicting
> identities and destructive actions go to a human — that was three.
>
> The goal isn't an agent that never asks. It's an agent that asks about the
> right three things, and can tell you exactly why."

---

## If you have another minute

- **Pause / Resume** mid-run — state is in SQLite, not in the task.
- **Upload your own CSV/XLSX** — same pipeline, no demo data involved.
- `GET /api/health` — shows demo mode, thresholds and LLM status.
- `/docs` — the full API surface.
- `pytest` — 51 tests, including the full lifecycle end to end.

## Questions you should expect

**"Why not just use an LLM for mapping?"**
It is supported — set `LLM_PROVIDER=ollama`. But it is an *advisor*: it can
move a score by ±0.12 and cannot introduce a target the deterministic layer did
not consider. That bounds the blast radius of a hallucination and keeps the
demo reproducible. Thresholds and the escalation boundary stay deterministic.

**"How do you pick 0.90 / 0.70 / 0.15?"**
Today they are reasoned defaults, environment-configurable. The honest answer
is that they should be *calibrated* against accepted/rejected human decisions —
that is the first thing I would build next.

**"What happens with 500,000 rows?"**
This process would struggle — it is a single asyncio task with an in-memory
event bus. The pipeline itself is per-record and isolated, so the change is
durable queueing and parallel workers, not a rewrite of the agent.

**"Is it production-ready?"**
No, and the README says so. No auth, no RBAC, no PII masking, mock target.
It is a prototype of the decision model.
