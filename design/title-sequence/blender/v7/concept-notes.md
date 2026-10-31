# v7 "The Record Stands": concept notes for the build

Fable's concept and beats are in reports/briefs/title-v7 (Agentique). These notes record what the build decided
on 2026-10-31, with the founder away and every decision delegated to the coordinator.

## The anachronism is the point (coordinator ruling)

The Catalan Atlas (1375) and Admiralty chart 983 (1931) stand on a globe drawn in 1728. That is deliberate. Each
record is the claim of its own day, and the globe is the claim of 1728. Where a record disagrees with the ground it
stands on, that disagreement is "As It Was". The Marshall Islands chart rises from sea the 1728 globe leaves empty.
No date is reconciled and no map is corrected. The record stands as it was made.

## What every surface is

- Scanned and gated: the globe's sphere and meridian ring (Doppelmayr, Jagiellonian University Museum 4119; 119/V,
  CC0, run-scan-ledger gate pass, every file's sha256 checked at plan time); the Catalan Atlas boards 1 and 2 (T-03),
  Ino's sheet 6 (T-08) and Admiralty chart 983 (T-20), each a public-domain ledger item pinned by sha256.
- The film's record: R-C20-METAR-0851 is the ledger's typeset DRAWN plate of the four 08:51 METAR rows (verbatim),
  as the spec names it. It is a text record, not a scan, and it is marked "Drawn · 2001".
- Hand-modelled (DRAWN): the globe's scale, the boards (dark matte card), the brass hinge rods and feet, the haze and
  the dust. Nothing else exists in the scene.

## Decisions taken in the build

Each one is also in `plan_v7.DEPARTURES` and in acceptance.json.

1. The globe is 2.031 m across, not 4 m. The scan's sphere is a 5120-triangle icosphere that uses 18% of its 8192^2
   texture, so it measures 0.487 px/mm at 4 m, half the design's 0.96. The spec's diameter rule scales the globe by
   that ratio. The boards keep their 0.70 m (the record keeps 0.50 m), so the reads stay at 50% of the frame width
   while FILL holds. The 0.18 D sheet rule is the one given up.
2. The Atlas stands at 36N 13E, not 20E. The scan's gap fill along the meridian ring (a blurred stripe near 22E)
   would otherwise sit under the read. The ring is left at its scanned meridian, over its own stripe. It stands behind
   the Atlas and passes under the camera at f301; it is not swept under at f30.
3. Each hinge sits at the board's near edge, so the face rises toward the camera and leans back 30 degrees. A prefix
   board lies on the ball before it rises. The film's record rests level on a 0.22 m brass stand, so the ball under
   it falls out of focus during the close-in (B2).
4. Every read drifts 4 cm/s and pushes in 4 cm (1.35 to 1.31 m), so no read is static (A1).
5. The Foley uses pinned CC0 stand-ins (a bearing for the hinge and the ring, a small metal fall for the brass tick,
   a hard object laid down for card on brass). No new brass recordings were fetched.
6. The motion-blur shutter opens on each frame, so frame 719 never blurs back across the cut.
