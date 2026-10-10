# Films

One folder per film: the text that makes it, never the media (R-08).

- `dossier.json`: the ledger of licensed assets (archive, item URL, rights, credit, what is in the frame).
- `screenplay.json`: shots, moves and narration, written by Fable; every shot cites a dossier asset.
- `score.yaml`: the music as note data on pinned CC0 / CC BY samples (void-history's score.py format).

Images live in the studio's working folder; rendered films, posters and `sources.json` live in R2 (`document-media/<film>/`).
Render: `python studio/sketch.py <working folder>` with the dossier's `sources/` beside these files.
A screenplay v2 (GRAMMAR 12) renders with `python -m studio.engine.render <film folder>` (master, `sources.json`, journal).
