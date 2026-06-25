# STATE.md

**Purpose:** current status only, one section per active pattern. A loop
reads this at the start of a run to know what happened last time, and
overwrites its own section when it finishes. This file should always
reflect "where things stand right now" — never a history (that's
`RUNLOG.md`'s job).

**Rules for editing this file:**
- A pattern only owns its own section. Never edit another pattern's section.
- Overwrite, don't append, within a section.
- If a value is unknown or not yet set, write `unset` — don't leave it blank
  (blank is ambiguous between "checked, nothing there" and "never checked").
- Keep each section short enough that a loop can read it in one pass without
  burning meaningful context.

---

## Global

- **Project phase:** L0 (no automation running yet)
- **Active patterns:** none
- **Last human review:** unset
- **Open incidents:** none

---

## Pattern: _(template — copy this block per pattern, delete when unused)_

- **Phase:** L0 / L1 / L2 / L3
- **Last run:** unset
- **Last result:** unset (clean / found-issue / error / escalated)
- **Cursor / checkpoint:** _(whatever the loop needs to know where it left off —
  e.g. last commit SHA reviewed, last issue number triaged, last date range covered)_
- **Open items from last run:** none
- **Budget used this period:** unset
- **Notes for next run:** none
