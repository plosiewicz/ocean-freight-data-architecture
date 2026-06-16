# Recorded Backup — Can't-Fail-Live Demo Fallback (DEL-01)

> **STATUS (2026-06-16) — RECORDED BACKUP INTENTIONALLY NOT PRODUCED.**
> Per the user's decision, no recorded backup video/`.cast` is being produced.
> The **demo of record satisfying DEL-01 is the live working demo notebook**
> (`docs/demo.ipynb`, run via `make demo`), which executes end-to-end against the
> committed frozen `data/golden/uc*.golden.json` snapshots — no credentials, no
> network — and so is itself can't-fail-live. The capture procedure below is
> retained **as documentation** for anyone who wants to record a backup later; it
> is not a pending action item.

> **Front-loaded manual step (human checkpoint).** This is the recorded-backup
> capture procedure for the final presentation. Like the `make verify-cluster`
> connection-smoke check, **the agent cannot perform this step** — *you* run the
> recorder against your own screen/terminal. Follow this doc, capture the run,
> save the artifact, and confirm it plays back. This recording is the
> **can't-fail-live fallback**: if the live demo machine has no network, no
> projector audio, or a wedged kernel during the Final, you play this instead.

This records the **four-UC demo run** (`docs/demo.ipynb`, built in 07-03). The
demo answers all four analytical use cases — UC1/UC2 from the BigQuery star,
UC3/UC4 from the ArangoDB graph — by reading the committed
`data/golden/uc*.golden.json` snapshots. **It runs with NO live credentials and
NO network** (the notebook's default cell path reads frozen goldens only), so
the capture **cannot fail mid-record** on a flaky cluster or BigQuery hiccup.

---

## 1. Chosen tool: asciinema (terminal capture of `make demo`)

The demo surface is a `nbconvert --execute` terminal run, so a **terminal
recorder is the right fit** — it produces a tiny, replayable, text-faithful
artifact (no multi-hundred-MB video, no codec/projector-resolution gambling).

**Chosen recorder: [asciinema](https://asciinema.org)** capturing `make demo`.

```bash
# one-time install (macOS)
brew install asciinema
# or: pipx install asciinema  /  pip install asciinema
```

**Why asciinema over a screen recorder here:**
- `make demo` is a terminal command → the relevant output is text in the scrollback.
- The `.cast` file is small enough to play back instantly and loops cleanly.
- Deterministic: it captures the exact frozen-snapshot run, byte-for-byte.

**Fallback (rendered-notebook visuals):** if you want the *rendered notebook*
(tables/markdown as they appear in Jupyter) rather than the terminal run, use a
screen recorder instead — macOS **QuickTime Player → File → New Screen
Recording** (or `Cmd-Shift-5`), record the browser/VS Code while you run
`docs/demo.ipynb` top-to-bottom, and save the `.mov`. Document which one you
captured in step 4 below. The asciinema terminal capture is the recommended
default; the screen recording is the equivalent fallback.

---

## 2. What to capture — the four-UC demo run, end-to-end

> **Before you record (threat T-07-12 — no on-screen secrets):** the default
> demo path loads **no credentials**, but to be safe **close any terminal tab or
> editor window showing a populated `.env`, an `ARANGO_*` value, a JWT, or a GCP
> key** before you start recording. Record only the frozen-snapshot run shown
> here — do **not** flip the notebook's `LIVE = False` aside to `True` while
> recording (that would touch the cluster and could surface a credential).

Capture this exact sequence:

```bash
# (run once, off-record, if not already installed: pip install -e .[dev])

asciinema rec docs/demo-backup.cast --title "Grilled Cheesin — 4-UC demo (frozen snapshots)" --command "make demo"
```

`make demo` runs `jupyter nbconvert --to notebook --execute --inplace
docs/demo.ipynb` against the **frozen `data/golden/uc*.golden.json` snapshots**,
so the recorder captures the notebook executing top-to-bottom and exiting clean.

If you prefer to narrate cell-by-cell, instead start a plain recording and open
the executed notebook so all four UC sections are visible:

```bash
asciinema rec docs/demo-backup.cast --title "Grilled Cheesin — 4-UC demo (frozen snapshots)"
# then, inside the recording:
make demo
jupyter nbconvert --to script --stdout docs/demo.ipynb | less   # optional: show the cells
exit   # stops the recording
```

**Confirm all four UC answers render in the capture:**

| UC | Store | What must appear in the recording |
|----|-------|-----------------------------------|
| UC1 — ETA reliability | BigQuery | the carrier/lane on-time reliability table |
| UC2 — congestion/dwell | BigQuery | per-port mean/peak turnaround across the date slice |
| UC3 — chokepoint exposure | ArangoDB | transit share **and** the **SUEZ reroute delta — strictly positive (~76 h)** **and** the **GIBRALTAR reachability drop — closed count < open count (e.g. 29 → fewer)**, both read from the committed golden |
| UC4 — disruption rerouting | ArangoDB | baseline vs. rerouted path (differs, detours via USLAX) + positive delta |

The SUEZ delta and the GIBRALTAR drop are the **non-degeneracy proof** (gate 19)
— they are read *from the golden*, asserted direction-only in the notebook
(`delta > 0`, `closed < open`), and are the headline numbers for the Final.

---

## 3. Where the recording lives (stays OUT of git — threat T-07-13)

Large/binary recordings **must not be committed** — `data/` and binaries are
gitignored and the repo stays lean (course deliverable, low risk).

- **asciinema `.cast`** (small, text-based) — even so, treat it as a deliverable
  artifact, **not** source. Either:
  - **Upload to asciinema.org** (`asciinema upload docs/demo-backup.cast`) and
    record the resulting **share URL** in the deck speaker notes + the M4
    checklist, **or**
  - keep `docs/demo-backup.cast` **local / out of git** and store a copy in the
    team's shared Google Drive demo folder, linked from the deck.
- **screen-recording `.mov`/`.mp4`** (large binary) — **never** commit. Upload to
  the team Google Drive (or YouTube unlisted) and record the **link** in the deck
  + M4 checklist.

**Do not `git add` the recording itself.** If you place the `.cast` under the
repo for convenience, drop it where the existing `data/*` / binary ignore rules
already exclude it (e.g. `data/`), or add a one-line ignore — the committed
reference is the **link**, not the bytes. The only thing that lands in git from
this step is, at most, a link line in the deck/checklist.

**Reference for the Final presentation:** add the recording link to the Final
section of `docs/deck/SLIDES-M3-FINAL.md` speaker notes (and/or
`docs/M4-CHECKLIST.md`) as: *"Recorded backup of the four-UC demo run:
<link> — play this if the live run is unavailable."*

---

## 4. Confirm playback (the human-check)

1. Play it back end-to-end:
   - asciinema: `asciinema play docs/demo-backup.cast` (or open the share URL).
   - screen recording: open the `.mov`/`.mp4` in any player.
2. Confirm the **full four-UC run** is visible and the headline non-degeneracy
   numbers render: **SUEZ reroute delta strictly positive (~76 h)** and
   **GIBRALTAR reachability closed < open (e.g. 29 → fewer)**, as read from the
   committed golden.
3. Confirm there are **no on-screen secrets** anywhere in the capture.
4. Note in the deck/checklist **which** artifact you captured (asciinema `.cast`
   share URL, or screen-recording link) and where it lives.

Once a playable recording of the full four-UC run exists at the named location,
this checkpoint is satisfied — the demo has a can't-fail-live fallback.
