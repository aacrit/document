# Engine log

Append-only issue log for the studio engine (decision "Capture every log", 2026-10-10): every defect, surprise or workaround found while building and piloting, with the run id or test that shows it, so lessons can become doctrine. Newest entry at the bottom. Never edit or delete a past entry; add one that supersedes it. Run ids name journals in `~/document-work/journal/` (or the scratch journal folder named in the entry); they are never committed.

<!-- Format:
## YYYY-MM-DD <ticket>: <short title>
Shown by: <run id or test>. What happened, why, and what fixed it or what is open.
-->

## 2026-10-10 T1: the A7 geometry lint refused a fill-mode still that was whole
Shown by: run r-20261010-113452-b1d4 (refused, `still-first-frame-whole` on S3). The first version compared the camera window with the photograph's own box. In fill mode (`fill_ok: true`) the first frame's window is the whole 16:9 frame, which reaches past the photograph into the field, so a correct whole opening failed. Fixed: `still_is_whole` checks that the window contains the entire photograph at the fit scale with its aspect unchanged. Covered by `test_still_first_frame_is_the_whole_photograph`.

## 2026-10-10 T1: a journal payload named `kind` crashed the run
Shown by: run r-20261010-113523-bd07 (failed, `TypeError: Journal.event() got multiple values for argument 'kind'`). The Lens's `run.start` carries a `kind` (render or calibrate), which collided with the journal's own `kind` argument. Renamed to `run_kind` on that event. Payload keys must never be `kind`, `stage`, `unit` or `lens`.

## 2026-10-10 T1: a failing blocking lint did not stop the run
Shown by: run r-20261010-113529-4ebe (outcome ok while `still-first-frame-whole-pixels` failed with severity block). The pixel check measured the fill-mode frame against the full frame instead of the photograph's fitted box (false failure), and the render never acted on the result. Fixed both: the check now measures against the fitted box with a 1 px edge margin, and a failure refuses the run before the master is encoded.

## 2026-10-10 T1: fieldmatch's automatic field order leaves combed frames
Shown by: `test_inverse_telecine_restores_the_film_frames` (prototype in the builder's scratch run: 15 of 48 frames far from any film frame with plain `fieldmatch,decimate`; 0 of 48 with `order=tff:combmatch=full`). On a 3:2 pulldown source decoded from H.264, `fieldmatch` with defaults mis-paired fields. The conform now names the order from the ledger's `field_order` or the file's probed `field_order` (tt or tb is tff, bb or bt is bff) with `combmatch=full`; if neither states it, the engine journals a decision and a warning lint `field-order-known`. A6 holds only with the order named.

## 2026-10-10 T1: inverse telecine at a clip's end yields one frame short
Shown by: `test_inverse_telecine_restores_the_film_frames` (47 frames for 2 s). `decimate` drops a frame of the last incomplete cycle at end of stream. The video reader holds the last decoded frame for the missing tail and journals `held_frames` on the shot's `unit.done`, so a held frame is visible in the log. Open: a hold longer than a frame or two should become a lint.

## 2026-10-10 T1: Rec.709 tags missing from the master
Shown by: run r-20261010-114047-5fc5 (master probed with `color_primaries=unknown`, `color_transfer=unknown`); fixed in run r-20261010-114119-257b. With ffmpeg 9 the frame properties coming out of the filter graph override the `-color_primaries` and `-color_trc` output options. The segment and master chains now end in `setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv`. ffmpeg's default RGB to YUV matrix is BT.601, so both chains also name `bt709` in `scale`.

## 2026-10-10 T1: segment container chosen for exact frame counts
Shown by: `test_master_is_24fps_h264_with_every_frame` and the `master-format` lint (594 of 594 frames). Matroska stores millisecond timestamps, and 24 fps frames (41.67 ms) can gain or lose a frame when segments are concatenated. Segments are MP4 with a 24000 timescale; each segment's packet count is checked against its frame range before it is cached, and the master's packet count against the film's.

## 2026-10-10 T1: interpretations a director should confirm
Shown by: the fixture render (any run above) and `test_fill_only_with_fill_ok`.
- A7 without a fill: "the move stays within the native shape" is read as the camera moving inside the photograph's own pillarboxed rectangle; the field around it never changes. With `fill_ok: true` the camera may grow the picture to fill 16:9.
- PULL after the whole opening: the path goes from the whole photograph to PULL's end framing (z 1.0), skipping its z 1.12 start, because opening whole and then pushing in only to pull out reads as a stutter.
- Preset zoom with a fill is relative to the largest 16:9 window (GRAMMAR 7.2); without a fill it is relative to the whole photograph.
- 23.976 fps after inverse telecine reaches 24 by repeating 1 frame in 1000, never by a 0.1% speed-up, which GRAMMAR 4.2 would call re-timed.
- The opening is min(1.5 s, 40% of the shot), so a 3 s DETAIL still opens whole.

## 2026-10-10 T1: the fixture's test clip cannot carry an ARCHIVE mark
Shown by: `test_sources_timeline` (S6 is DRAWN and `test_fixture: true`). The ticket's synthetic testsrc clip must never read as archival, but GRAMMAR 12 lets `archive_video` carry only ARCHIVE or RECONSTRUCTED. The engine requires mark DRAWN for a ledger item with `synthetic: true` ("DRAWN from ffmpeg testsrc, test fixture") and refuses DRAWN on any real clip.

## 2026-10-10 T1: lint-size forbade any image in git
Shown by: `npm run gate` (lint-size) before the change. The ticket's fixture needs three small ledger stills, and lint-size banned every `.jpg`. lint-size now allows `studio/tests/fixture/stills/*.jpg` up to 200 KB each and caps the whole fixture folder at 1 MB; `.gitignore` un-ignores only that folder's JPEGs. The fixture clip and test tone are generated at test time, never committed.

## 2026-10-10 T1: what T1 does not draw or measure yet
Shown by: the fixture render's journal (`overlay-rendered`, `audio-present`, `clip-sound` warnings).
- Text over footage (`overlay`) is journaled as a warning and not drawn.
- `generated` shots are refused (the pilot's AI-GENERATED share is 0); `drawn` shots need a pre-rendered image cited as their asset.
- WAVs are found at `audio/<line or cue id>.wav` in the film folder, or the element's `wav` field; a missing one is a warning and silence. Archival clip sound is mixed mono.
- `fsutil dirty query D:` can need an elevated shell; when it cannot be read the engine warns and goes on, and refuses only when it reports dirty.
- Frame progress goes to the journal once a second of film per shot (plus each shot's last frame), with no preview JPEG yet.

## 2026-10-10 T1: the output drive is near the 10 GB floor
Shown by: run r-20261010-113529-4ebe (`preflight-free-disk`: C: had 15.61 GB free). A render keeps one intermediate segment per shot (x264 CRF 12, 4:4:4) plus the master. The fixture's 1080p segments took 5.6 MB for 24.75 s (run r-20261010-114119-257b), but that film is mostly cards; archival frames will cost far more, and the first pilot render must measure it. With 15.6 GB free, C: has about 5.6 GB above the floor. The tests pass `min_free_gb=1` for their 640x360 renders; the CLI keeps the 10 GB floor.

## 2026-10-10 T1: run.start was not the journal's first event
Shown by: the verifier on run r-20261010-114432-e308 (`run.start` was seq 67, after 66 scout events). The engine waited for the plan so `run.start` could carry the units and the film's length, which hid the settings of every run refused during scout. Now `run.start` is seq 1 of every run, with its settings, workers (requested and used), engine model, ffmpeg version and machine. A `run.plan` event follows the scout stage with the units, the duration, and the shots to render or take from the cache. `run.end` stays last, on success, refusal or failure. Covered by `test_run_start_is_the_first_event_and_run_end_the_last` and `test_a_refused_run_also_starts_with_run_start`. The Lens reads its units from `run.plan`.

## 2026-10-10 T1: non-square pixels, the ledger's display aspect, and low frame rates
Shown by: the verifier's note on the teaser's 720x480 NTSC source (SAR 8:9, DAR 4:3, interlaced top field first), then `test_ntsc_sar_8_9_clip_is_pillarboxed_at_4_3_not_3_2`, `test_ledger_display_aspect_overrides_the_file` and `test_true_10fps_source_is_repeated_to_24_and_journaled`. The fit already used width x SAR / height from ffprobe. That source now has a test: a generated 720x480 SAR 8:9 telecined clip fits at 480x360 in a 640x360 frame, 4:3 and never 3:2, with inverse telecine top field first. A ledger `display_aspect` (`4:3`, `4/3` or a number) now overrides the file's SAR, with a journaled decision when the two differ. The `clip-aspect` lint records the storage size, SAR, where the aspect came from, and the fit. A true 10 fps source is conformed to 24 by frame repeat (`fps=24`, about 30 distinct frames in 3 s, no speed change). Every repeat conform now also journals a decision. Open: an interlaced source that is not telecined (true 59.94 fields) has no deinterlace path yet. Frame drop would weave its fields, so such a clip needs a ledger flag and a GRAMMAR ruling on whether deinterlacing is a material alteration.

## 2026-10-10 T1 review: held frames were never counted, and a clip could freeze without limit
Shown by: the Gatehouse review of `render_segment` (the held-frame sum ran after `pics.close()` had cleared the readers, so `held_frames` was always 0), then `test_a_short_clip_holds_under_2s_and_counts_its_held_frames` (36 held frames for a 1.5 s overrun) and `test_a_hold_over_2s_is_refused_unless_re_timed`. The sum now runs before close. The probe reads the video stream's own duration, not the container's, which an audio track can lengthen; `duration_from` says which it used. A clip whose out point runs past its stream holds its last frame. That is a warning up to 2 s, and refused beyond 2 s unless the shot is RECONSTRUCTED `re-timed` (GRAMMAR 7.1). The plan checks it (`clip-hold`), and the render checks it again on the frames actually held (`clip-hold-rendered`).

## 2026-10-10 T1 review: the synthetic-to-DRAWN rule covered clips only
Shown by: `test_a_synthetic_still_cannot_be_marked_archive`. A ledger item with `synthetic`, `test_fixture` or `generator` now allows only DRAWN on every shot kind, stills included (`is_synthetic`). Supersedes the scope of the earlier entry "the fixture's test clip cannot carry an ARCHIVE mark".

## 2026-10-10 T1 review: Commons photographs were committed to the repo
Shown by: the Gatehouse review (R-08) and `test_fixture_commits_no_media`. The three fixture stills were Commons downloads, tracked through a lint-size exception. Supersedes the entry "lint-size forbade any image in git": that exception and the `.gitignore` un-ignore are reverted, and the photographs are gone from the branch history. `studio/tests/fixture/make_media.py` now draws three test images with PIL at test time, at the same sizes (500x350, 395x316, 300x420), and the fixture tracks only JSON and Python. The test images are synthetic, so they are marked DRAWN; the fixture no longer exercises ARCHIVE pixels, while the lints keep their ARCHIVE cases.

## 2026-10-10 T1 review: the D: check could never pass unelevated
Shown by: the Gatehouse review (`fsutil dirty query` needs elevation, so it always returned unreadable and the engine only warned), then `test_preflight_refuses_a_full_disk_and_an_unhealthy_d` and `test_an_unreadable_d_refuses_unless_the_override_is_set`. The pre-flight reads `Get-Volume -DriveLetter D` (HealthStatus, OperationalStatus) through PowerShell, which needs no elevation; on this laptop it reads Healthy / OK. Anything other than Healthy and OK refuses. An unreadable volume refuses unless `DOCUMENT_ALLOW_UNVERIFIED_DISK=1`, which journals a `human` override. A known-unhealthy volume refuses even with the override. Lowering the free-disk floor below 10 GB is journaled as a `human` override too.

## 2026-10-10 T1 review: the cache key and the master's bytes
Shown by: `test_the_cache_key_holds_ffmpeg_and_the_fonts` and `test_the_master_does_not_depend_on_workers` (one worker and two workers give byte-identical masters). A segment's key now includes the ffmpeg version line and the sha256 of every font file, so an upgrade of either re-renders. The master encode uses a fixed `-threads 4` instead of following `--workers`, so the same inputs give the same bytes.

## 2026-10-10 T1 review: decoders ran multi-threaded inside worker processes
Shown by: `test_decoders_and_encoders_run_single_threaded`. Each worker's clip decoder, the clip-audio decoder and the segment encoder now run with `-threads 1 -filter_threads 1`. Otherwise 8 workers could start 8 ffmpeg processes with a thread per core each, which is the parallel load this laptop crashes under.

## 2026-10-10 T1 review: a failed segment could leave its partial file
Shown by: `test_a_failed_segment_leaves_no_partial_file` (an encoder with an unknown codec). After killing the encoder, the worker now waits up to 10 s for it to exit, then removes the `.part` file with retries, because Windows can hold the file a moment after its writer dies (WinError 32).

## 2026-10-10 T1 review: text the engine does not draw is refused; overlays are drawn
Shown by: `test_an_undrawn_text_kind_is_refused` and `test_overlay_is_drawn_bottom_right_and_never_over_a_card`. Supersedes the overlay line of "what T1 does not draw or measure yet". GRAMMAR 9's text over footage is now drawn by `motion.overlay_frame`: one line, bottom right, flush at 4% of width with its box bottom at 92%, numerals in the data face, held by a feathered wash from the right edge, arriving on `settle` and fading over 0.5 s. The `overlay-format` lint refuses more than one line, an overlay over a card, or one over a lower third. A text kind outside lower_third, overlay, chapter_card, title_card and silent_record is refused (`kind-supported`, blocking).

## 2026-10-10 T1 review: a missing voice WAV now blocks
Shown by: `test_a_missing_voice_wav_blocks_unless_draft` and `test_draft_is_journaled_as_a_human_override`. A narration or testimony line without its WAV refuses the run, because silence there would ship a film missing its words. `--draft` places silence instead and is journaled as a `human` override and in the run's settings. A missing music or ambience cue stays a warning.

## 2026-10-10 T1 review: frame rate, telecine and field order
Shown by: `test_telecine_must_be_declared_for_a_29_97_source` and `test_an_unknown_field_order_blocks_inverse_telecine`. The probe uses `avg_frame_rate`, falling back to `r_frame_rate`, which for field-coded streams can report the field rate. A 29.97 or 59.94 fps source must state `telecined: true|false` in its ledger, or the run is refused (previously a warning plus a guess). Inverse telecine with an unknown field order is refused (previously a warning).

## 2026-10-10 T1 review: two GRAMMAR lints were missing
Shown by: `test_a_cross_class_dip_under_12_frames_is_refused` and `test_a_still_zoom_past_its_preset_is_refused`. A dip between two mark classes shorter than 12 frames is refused (GRAMMAR 4.4). A still move whose zoom exceeds its preset's limit (HOLD 1.0, PUSH and PULL 1.12, DRIFT 1.15, TILT 1.2, DETAIL 1.3), or 1.3 in any case, is refused (7.2).

## 2026-10-10 T1 review: ducking ran a full-film convolution
Shown by: `test_ducking_average_matches_a_convolution`. The 250 ms smoothing of the voice envelope used `np.convolve` over the whole programme, which is O(n x 12000) at 48 kHz, about 10^12 multiply-adds for a 25-minute film. A cumulative-sum moving average gives the same curve in O(n).

## 2026-10-10 T1 review: what the journal records, added
Shown by: `test_segments_mix_and_master_are_artifacts_with_hashes`. Every shot segment, the mix, the normalised mix, the master and `sources.json` are journaled as `artifact` events with their sha256. A loudnorm fallback from linear to dynamic mode is flagged (`loudnorm-linear`, a warning with the reason). Overrides (`--draft`, `DOCUMENT_ALLOW_UNVERIFIED_DISK`, a lowered free-disk floor) are journaled as `human` events.
