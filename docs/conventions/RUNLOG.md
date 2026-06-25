# RUNLOG.md

**Purpose:** append-only audit trail. One line per run. Never edit or delete
a past row — if a run needs correcting, add a new row noting the correction.
This is what you (or a future session) reconstructs history from when
something goes wrong and you need to know exactly what happened and when.

**Format:**

`| Date/Time | Pattern | Result | Action Taken | Artifact / Link | Notes |`

- **Result:** one of `clean` (ran, nothing to do), `found` (ran, surfaced
  something), `error` (failed to complete), `escalated` (stopped and handed
  to a human)
- **Action Taken:** `none`, `wrote-state`, `opened-issue`, `opened-pr`,
  `committed`, `escalated-to-human`
- **Artifact / Link:** PR/issue link, commit SHA, or `n/a`

---

| Date/Time | Pattern | Result | Action Taken | Artifact / Link | Notes |
|---|---|---|---|---|---|
| _(no runs yet)_ | | | | | |
