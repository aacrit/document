The Run v4, state at the pause (2026-10-18; paused for Real World's score work)

1. Where: tickets 1-2 are done and tested (bench.py, relief.py; tests/). Tickets 3-6 are written. sim_run.py runs physically from latch to papyrus, hinge valley, U1 (Piri Reis's curl), knots and galley. `--until-frame 520` bakes that stretch to D:/document-media/title-sequence/run/sim/v4/.
2. Next, the reduced milestone A: `plan_camera.py --until-frame 500`, then `RUN_END_FRAME=500` with render_take's prefix build at --calib --res 854x480 (frames 36-500). Then foley_take and assemble_take for that stretch: both still read a tail bake, so add a prefix-only path. Then the contact sheet, the shadow-band measure, the in-frame shares, the pan report, and the RMS between events.
3. The first scene build has not been verified yet. It failed on PIL inside Blender, now fixed (the margin colours come from relief.py's sidecars). Expect a few more build errors on the first real run.
4. Open in the chain: U2 (the pair stops on Ino short of its lifted edge; the lead stays in the galley), then the crease, reels, card, strip, U3, platen, lattice, brass at f866/f926, and the tails. Expect 3-6 probes per hand-off.
5. Design fixes so far (all physical, all in bench.py comments): cockle troughs carry the legs; the latch frame is turned 8 degrees; the papyrus cups 3 mm, is mounted on a backing and is stiff; the tablet moved and the lattice moved; the Atlas boards are 1.5 mm and the hinge is at -66 degrees; Piri Reis is turned 180 degrees and lies over board 2; the leaf lies over Piri; the galley presses the paper flat; the galley's sorts are 8-to-em spaces.

## Rulings to apply on resume (2026-10-18, the coordinator deciding for the founder)
1. **Beats 2-3 follow:** cap the exempt follow at about 40 px a frame (about 3.5 times the still guide), eased in and out. Where the marble outruns that, widen the frame for the stretch instead of whipping, keeping the marble in frame. Log the peak px a frame in the master's review items. The 189 px a frame whip is not approved.
2. **S-130 and S-16928:** lay them with the long side along y (or scale the felt bay) at real size. The table's end and the A7 pose rule win; never shrink a record.
3. **First deliverable on resume:** the 480p animatic of the working stretch (latch to galley), sent to the coordinator.

## Founder ruling, 2026-10-18 (binding): physics only, one shot
"All changes are physics only in the title. No transitions, fading, nothing. One single shot following the marble; everything else behaves according to physics. A light breeze to keep things alive can be an addition if it's not a heavy lift."
- **The record beat:** the 24-frame dissolve is GONE. The camera descends in-camera onto the film's record, lying physically on the felt (the real scan as a sheet with relief), until it fills the A7 pose (record_pose, A7 ≤ 6.0, edge strips ≤ 12, a 0.5 s hold).
- **Light and cuts:** no fades, no hidden cuts, no time remaps. The lamp stays constant unless something physical moves it. The iris "closing onto the record" and the lamp "finding" cues are OUT, so record legibility must come from constant light.
- **Breeze:** a gentle MuJoCo wind on light bodies only (the khipu cord, the 35 mm strip, the Morse tape), and only where cheap. Skip it if it needs cloth for the sheets or perturbs a hand-off, and say so.
- **Open, waiting on the coordinator:** does the lockup (dip to `void document · As It Was`) stay after the shot, as a separate card outside the title shot? Until answered, build the shot to end on the record pose.

## Decided 2026-10-18 (coordinator, delegated)
- **Lockup:** option (a). A separate CARD shot after the one-shot title, joined by a hard CUT, with no dip. The master ends on the record pose and holds no lockup.
- **titles.py:** WG-4 changes it after the animatic. `dip: null`, no lockup_frame, the CARD out of the master's timeline, the handover cut and cut, with tests, through the gate.
- **A7 under constant light:** measure it on the first tail. If it fails, fix it physically (the record in the constant lamp's pool from the start of the tail, or laid flatter), never with a grade or a fade.
