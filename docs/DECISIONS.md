# Decisions

Append-only log of scope and architecture decisions for Document. Newest entry
at the bottom. Do not edit or delete past entries; add a new one that
supersedes it instead.

<!-- Format:
## YYYY-MM-DD: <short title>
<what was decided and why, 2-4 sentences>
-->

## 2026-10-10: G1 approved, Maxwell Street pilot
Founder approved Document at G1 in chat. Spine: portraits of places; imagery archival-first (every frame traces to a licensed source, image-to-video only for labelled atmosphere on real photographs); public good, no money; 12–18 min every two weeks. Fable writes treatment, screenplay and shot plan at the founder's request. Pilot place: Maxwell Street, Chicago. Own brand at document.voidvision.org; void news and void history strands come later.

## 2026-10-10: Director's Lens joins the Studio surface
Founder asked for a UI that launches during an end-to-end render and shows live stats and frames as they are generated, scaled up from Backlot's latent rendering view. It is part of the Studio surface (local only, never served at document.voidvision.org), designed in Blueprint and signed off at G2.

## 2026-10-10: Blueprint design direction (founder, in chat)
Site feel: cinema house (a dark theatre, the film fills the screen, title cards set like film credits, the sources ledger reads as end credits). Accent: safelight amber, meaning "this is real, here is where it came from" (timecodes, credits, ledger links). Director's Lens: control room (live monitor, filmstrip of every shot, side rail with stage, GPU/VRAM/temperature, narration waveform and the current shot's source card). Lens reach: localhost on the laptop, plus a status snapshot written to the Board every few minutes for checking overnight renders from the Claude app.

## 2026-10-10: Director's Lens is private, local and hosted (founder, in chat)
The Lens is the founder's own tool; document.voidvision.org stays the sleek, viewer-facing home for films and never shows studio language or links to it. The Lens runs live on localhost during a render and is also hosted at document.voidvision.org/studio behind Cloudflare Access with Google SSO, allowing only aacrit@gmail.com; the laptop pushes a snapshot (state + latest frame) about every 5 s, capped in code against the free tiers. The Board gets one card when a render finishes or fails, replacing the periodic snapshot. Setting up Access (Google OAuth client + Zero Trust app) is one founder ask, opened when the Lens is built.

## 2026-10-10: Lens login is a simple admin password (founder, in chat)
Supersedes the Google SSO / Cloudflare Access part of the entry above. Hosted /studio uses one admin username and password: the password is generated when the route is built, shared with the founder in chat once, and stored only as a hash in a Worker secret; a 12-hour HttpOnly, Secure, SameSite=Strict session cookie scoped to /studio; login attempts are rate-limited.

## 2026-10-10: Film grammar (founder, in chat)
Spine: voices first; each portrait is built around first-person words from the place, and images serve the voices. Voices: a sparse narrator for time and fact, plus a read-by cast. Archival recordings play as themselves; every other first-person text (life histories, oral histories, letters, diaries, court and census testimony, quoted interviews; public domain or CC BY) is read word for word by a credited computer voice, never paraphrased. Ending: every film returns to the place today (CC0/CC BY contemporary images and public facts). Music: one Document house motif opens and closes every film; between, the place's own musical tradition. Places: Fable scouts three candidates per film, ranked by depth of voices and photographs, and the founder picks one in chat. On screen: an opening title card, 4 to 6 named chapters, and a lower third naming each speaker, year and source the first time they speak; nothing else. Sound: sparse ambience from real CC0/public-domain field recordings only, credited in the ledger; near-silence allowed; no synthetic Foley.

## 2026-10-10: Pivot to void document, Partition of India pilot (founder, in chat)
Supersedes the place-portrait spine, the Maxwell Street pilot and the film-grammar entry above; their principles carry, their content does not. Brand: "void document" at document.voidvision.org, a sibling of void news and void history (cross-links later). Pilot: the Partition of India, 20-25 min, English with Hindi and Urdu subtitles. Archival moving image is the backbone; the storyline (void-history's Partition research as input, not as the script) is fitted to the footage that exists, and narration, sound and music enhance it. Licences: public domain, CC0 and CC BY only. Generated content (text over footage, AI images, AI clips) fills gaps but never shows people, faces, crowds or violence and never recreates a specific recorded event; it is context (maps, landscapes, places, objects, weather, light). Every second carries an in-picture provenance mark: ARCHIVE (with archive and year at each new shot), AI-GENERATED (never amber), or RECONSTRUCTED (archival footage materially altered); end credits list every shot's source. Treatment: many named accounts (Indian, Pakistani, Bangladeshi, British, Sikh, women's), none given the last word; violence told through testimony, aftermath and silence, with no archival footage of bodies or killings. This needs a revised brief and a second G1 round; G2 Blueprint is paused, and the Maxwell Street stub stays live until the pilot replaces it.

## 2026-10-10: G1 round 2 approved (founder, in chat)
void document, Partition of India pilot, hybrid footage approach (brief round 2). Back to Blueprint: film grammar for archive-backed history and provenance marks first, then the design round.

## 2026-10-10: Predictive status from measured timings (founder, in chat)
The Director's Lens shows predictive status only from measured step timings on this machine: every unit of studio work is recorded to a timing ledger (stage, unit size in its cost driver, wall time, machine conditions); ETAs are per-stage ranges (median to p90 of history, blended with the live rate after three units) with their sample counts; no estimate is shown before three samples exist. A `doc calibrate` command times each stage on fixed inputs to set baselines.

## 2026-10-10: Trust Wikimedia Commons' licence tags for stills (founder, in chat)
Stills hosted on Commons as PD-India, PD-Pakistan, PD-UKGov and similar home-country public-domain tags are usable without a separate US-status proof, as most documentaries and educators do. The risk (possible URAA-restored US copyright on 1947 works, so takedowns or Content ID claims on YouTube) is accepted: each item's Commons tag and URL stay in the ledger and credits, and a takedown is answered by swapping the shot and re-releasing. Moving-image footage keeps the stricter rule (verified PD, CC0 or CC BY per item).

## 2026-10-10: Testimony from home-country public-domain texts, archives asked (founder, in chat)
The read-by cast draws on texts that are public domain in their home country (Indian, Pakistani and UK government publications, leaders' 1947 speeches, Gandhi's prayer-meeting speeches, legislators' debates including women members on the recovery of abducted women, witness statements compiled in Khosla's Stern Reckoning, Fatima Jinnah's and Begum Shah Nawaz's speeches), on the same accepted-risk footing as the stills, alongside the fully open FRUS cables and Hansard. In parallel, permission is requested from the 1947 Partition Archive and the Citizens Archive of Pakistan for a few survivor testimonies (Bengali, Sikh and Muslim women first), credited as third-party material inside an otherwise CC BY film. Real footage and our own oral histories are a later expansion. Any balance shortfall is stated on a record-is-silent card.

## 2026-10-10: No AI-generated imagery in the Partition pilot (founder, in chat)
The pilot's AI-GENERATED share is 0%. The film is real archival video, real photographs, maps drawn from cited data (DRAWN), text cards and black frames under readings; if that carries less than 20 minutes, the film runs shorter. The studio keeps the capability and the AI-GENERATED mark for later films; generation stays off the GPU for this pilot.

## 2026-10-10: Storyblocks as a free search index only (founder, in chat)
No Storyblocks subscription: its Individual licence ends with the subscription and is proprietary, so it fits neither the $0 rule nor CC BY. Its 1940s India clips (repackaged government newsreels in the "1942 - ..." style) are used only as leads, traced to their public-domain originals at the National Archives or Internet Archive and taken from there under the usual per-item rights check.

## 2026-10-10: Branding kit with on-film motion, BBC-inspired lower thirds and a channel watermark (founder, in chat)
The brand stays "void document". A branding kit, designed by Fable, fits it under the void news umbrella and adds: a channel watermark (in-film and YouTube), BBC-inspired lower thirds, and a motion system for the film itself (lower thirds, chapter cards, mark plates, transitions) built on sleek spring physics, specified precisely enough for the studio to render frame by frame.

## 2026-10-10: Stills open whole, then move in (founder, in chat)
Each photograph first appears whole at its native aspect on near-black, then the camera may move in to fill 16:9, provided every person in it is in frame at some point in the shot. Archival video stays at native aspect, pillarboxed. Plain resampling stays ARCHIVE at any scale; telecined newsreels are restored by inverse telecine. Recorded as GRAMMAR amendments A5 to A7.

## 2026-10-10: Speaker side versus publisher perspective (Chief of Staff ruling)
A reading's `side` is the speaker's own community; the publisher of the text is a separate `perspective` field shown on screen by the partisan flag. Darshan Singh (quoted in the Government of West Punjab's Note on the Sikh Plan, 1948) is side `sikh`, perspective Government of West Punjab, and his seconds are listed as mediated by a partisan source in the balance panel. Chapter 5 keeps the treatment's title, "After the line".

## 2026-10-10: Crown copyright texts under the Open Government Licence (Chief of Staff ruling)
Texts from The Transfer of Power 1942-47 (Mansergh, HMSO) and other UK Crown copyright publications are used under the Open Government Licence v3.0, which is compatible with CC BY, on the same accepted-risk footing as the Commons stills. Credits carry "Contains public sector information licensed under the Open Government Licence v3.0." Ledger rule: no reading enters the ledger from a blog or other unsourced copy; only primary or authoritative publications (official records, parliamentary and government publications, newspapers of record, scholarly editions, archival scans).

## 2026-10-10: Voices (founder, in chat)
Readers speak in their own world's English: South Asian speakers by distinct South Asian English computer voices, British speakers by British voices, US diplomats by American ones; this is about place, never an impression of the person (GRAMMAR 6.2 still forbids imitating anyone's real voice). The narrator, the same in every void document film, is chosen by ear from a five-voice audition of free, local models (Orpheus 3B: tara, leah, mia; Kokoro: bf_emma, hf_alpha; hf_beta as a bonus). Indic Parler-TTS (AI4Bharat, Apache 2.0) is gated on Hugging Face and needs a founder sign-up before it can be used.

## 2026-10-10: Narrator Tara; South Asian readers on Kokoro (founder, in chat)
Narrator: Orpheus 3B "tara", the same voice as void history, for every void document film. South Asian women readers: Kokoro's Hindi-trained voices hf_alpha and hf_beta reading English, both approved by ear. Male South Asian readers start from Kokoro's hm_omega and hm_psi; because GRAMMAR 6.2 needs one distinct voice per speaker and the pilot has more South Asian men than that, further distinct voices are made by fixed blends of Kokoro voice embeddings, auditioned by the founder before use. British and American readers use Kokoro's British and American voices. Indic Parler-TTS stays optional (needs a founder sign-up).

## 2026-10-10: G2 approved (founder, in chat)
Design sign-off for void document: films/GRAMMAR.md (with amendments A1 to A9), films/partition-of-india/TREATMENT.md (revision 2), design/ (spec, tokens, BRAND, mocks) and design/brand-kit/ (watermark, lower thirds, motion.py), narrator Tara, readers in their own world's English. Packet: https://claude.ai/artifact/5UH3a2BuTjcWmMVAiKVoCp. The product stays in Blueprint until the build slot is free (Ratio holds it, R-07).
