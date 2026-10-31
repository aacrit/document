# Title v7 "The Record Stands": build state (t/title-v7)

Updated 2026-10-31 by the v7 builder. Working notes for the ticket, not law.

## Done
- Worktree D:/document-worktrees/title-v7, branch t/title-v7 from t/run-v6 (63a7f96); commit 26e904d.
- Globe measured (globe-measure.json): the sphere is a 5120-triangle icosphere using 18% of its 8192^2 texture,
  0.487 px/mm at 4 m (design 0.96). D = 2.031 m by the spec's diameter rule.
- Registration (registration.json, registration-fit.json): Kabsch on Guardafui, Good Hope, Dondra Head, Bermuda,
  Cape Horn; rms 1.55 deg. The meridian ring's plane contains the fitted pole to 0.02 deg; ring at 22.1E / 157.9W.
- plan_v7.py (camera, rises, diptych, flat-hold, dust); checks_v7.py analytic: A1, A2, A3, A4, A6, B1, B2, B3, C4 pass.
- render_v7.py: gate (globe + records pass), plan.json written to D:/document-media/title-sequence/v7/work/.
- scene_v7.py (Blender), foley_v7.py written; smoke render queued behind HEAVY.lock (Apollo 13 held it).

## Decisions and departures (each logged in plan_v7.DEPARTURES too)
- D = 2.031 m; boards keep 0.70 m (record 0.50 m), so the 0.18 D sheet rule is broken to hold B1 with B2.
- Atlas moved to 36N 13E (meridian-ring gap-fill stripe at 22E). Ring left at its scanned meridian over its stripe.
- Hinge at the board's near edge; boards lie on the ball before rising (rise from about -18 deg to 60).
- The film's record stands on 0.22 m brass feet so the ball under it is out of focus in the close-in (B2).
- Reads push in 4 cm (1.35 to 1.31 m) with the 4 cm/s drift (A1 flow floor).
- Foley: pinned CC0 stand-ins; no new brass recordings fetched.
- Motion blur shutter opens on the frame (no blur across the cut at 719).

## Risks to report
- Gap-filled texture (horizon-ring band, meridian stripe) is visible in the read frames' wider globe (about 20% of
  ball rays, mostly unlit or near the limb); judge on renders.
- The scan's own name says "Globus Ziemi po 1744" (after 1744); the ledger says 1728.
- R-C20-METAR-0851 is a typeset DRAWN plate (the spec's record), not a scan.

## Machine
- D: guard: every step refuses if D: would drop to 12 GB or less (render_v7.d_guard). D: was 17 GB free at 12:15.

## Next
smoke -> meter -> day-1 still -> frames (480p) -> assemble (lockup, marks, Foley, theme, mix, encode, sheet,
acceptance.json). The theme lands at D:/document-media/title-sequence/theme-v7/the-record-stands-theme-RW.wav.
