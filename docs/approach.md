# Approach — AI Agent for Client Data Migration

**Automation should be the default, but uncertainty should be explicit.**

An agent that asks about every imperfect value is a slow human. One that silently guesses is worse:
it produces a clean-looking dataset that is quietly wrong. The engineering is in drawing that line
and making it visible.

## Architecture

`MigrationAgent` is a state machine over SQLite, not an in-memory object:

`INGEST → PROFILE → MAP → CLEAN → DEDUPLICATE → VALIDATE → [ESCALATE → human → REVALIDATE] → PUSH → RETRY → (ROLLBACK)`

The transform phase is **idempotent** — rebuilt from immutable source rows every run — so resuming
after a human decision is "run it again with one more fact known", not a patch-in-place. State lives
in the database, so a run is inspectable and resumable. An LLM is optional and strictly advisory: it
can move a confidence by at most ±0.12 and cannot introduce a target the deterministic layer did not
consider. That bounds the blast radius of a hallucination and keeps the run reproducible.

## What it handles alone

Whitespace, casing, emails; dates to ISO-8601; enums (`"y"`, `"resigned"` → `active`/`inactive`);
exact-duplicate merges; filling a blank field from its duplicate; non-critical conflicts by source
precedence; transient API retries with backoff; and mappings above the thresholds. It also leaves a
column unmapped when nothing resembles it — not guessing is the right answer for `Remarks`.

Dates show the reasoning. The **column** is profiled once for day-first vs month-first from evidence
(any day > 12), so every conversion in it is deterministic and explainable. That is exactly why date
normalisation needs no human.

On the demo data: **~310 agent decisions, 3 human ones.**

## Where I drew the line, and why

Autonomy is **confidence × margin × reversibility × criticality** — never confidence alone.

`Contact No` scores 74% for `mobile_phone` and 70% for `work_phone`. The agent is *confident it is a
phone field* and *uncertain which one*. A single score hides that; the **margin** exposes it. Below a
15-point gap it stops, whatever the absolute score. (This falls out of damping scores derived from an
alias several target fields legitimately claim — without it the column would score 0.98 and be
silently auto-applied.)

The mirror case is the real test. `EMP1042` has no email in any source. The agent *can* derive one
from the name and the file's domain pattern — it shows that suggestion at 45% — but will not apply
it: a wrong email is an onboarding failure and is not reversible once the welcome mail goes out.
Compare `EMP1004`'s date of birth, `31/02/1990`: equally unfixable, but the field is optional, so the
agent drops it, records why, and continues.

Same uncertainty, different consequence, different answer. Escalation costs a consultant's attention
and stalls the run, so it is spent only where a wrong answer is both *likely* and *costly*.
Deterministic transformations are neither.

So it escalates on exactly six triggers: competing mappings inside the margin; a mandatory field
unresolvable from any source; a value that cannot be cleaned without guessing; a record still invalid
after two automatic repairs; duplicates conflicting on a *critical* field (identity, employment
status); and anything destructive. Nothing else.

## Human-in-the-loop

Each card answers four questions at a glance: what the agent saw, every candidate it considered with
scores, **why it stopped** in plain English, and the choice — approve, correct, reject. Resolving the
last blocking escalation resumes the agent automatically: the decision is written back, the pipeline
re-runs, affected records are re-validated, the push starts. One decision, not a sequence of clicks.

## What I would build next

Confidence **calibration** against accepted/rejected decisions — today's scores are principled but
uncalibrated, and that is the honest weakness. Then a versioned schema registry with per-tenant alias
vocabularies so mapping improves across engagements; field-level lineage; approval policies and RBAC;
PII masking; durable distributed execution; and an evaluation harness over labelled datasets so a
threshold change is a measured decision, not an opinion.

**Not production-ready** — a prototype of the decision model.
