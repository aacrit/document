# void document · As It Was: assets and provenance

Every image in the title sequence is a real period source under PD, CC0 or CC BY, recorded here and then in `title-ledger.json` (proposed below) before the builder uses it. Licences and dates were read from each file's Wikimedia Commons metadata, or the holding institution's API, on 2026-10-16. The builder re-checks each one at the institution before download and records `licence_evidence` as the house ledgers do.

**AI-generated pixels: none.** No texture, fill, upscale or atmosphere comes from a generative model (see `CONCEPT.md`, open question 1). Where a scan is too small, the surface is framed so it is never magnified past 1.6 output pixels per source pixel (the house FILL limit). It is never upscaled by a model.

**Never on screen:** a person, from any source. The modelling references below that show people (the 1890 engraving, the 1568 woodcut) are used for measurement only and never appear in a render.

## The shared machine (beats 1 to 10)

Use: **T** texture (the scan appears on a surface), **R** reference only (measured, never shown), **H** relief traced from what the sheet prints (a studio-drawn height map, credited as drawn from that sheet).

| Id | Beat | Artifact | Date and basis | Holder | Licence and basis | Source file | Use |
|---|---|---|---|---|---|---|---|
| T-01 | 1 | Record of temple workers, Umma (24 columns, nearly 20,000 names), obverse, reverse and edges | c. 2094 to 2047 BCE; the tablet dates itself to Shulgi's 37th year (Walters record) | Walters Art Museum 48.1767 | Public domain; Walters open-access images (CC0) | [Commons: Walters 481767, View A](https://commons.wikimedia.org/wiki/File:Sumerian_-_Record_of_Temple_Workers_-_Walters_481767_-_View_A.jpg) 1066 x 1800 (thumbnail; get the full-resolution views from art.thewalters.org) | T (albedo and a height derived from the raking-light photograph); the tablet's body is modelled |
| T-02 | 2 | Turin papyrus map: the Wadi Hammamat, its hills, roads and quarries | c. 1156 to 1150 BCE, reign of Ramesses IV (Museo Egizio record) | Museo Egizio, Turin, Cat. 1879, 1899 and 1969 | CC0 (Museo Egizio collection online) | [Commons: p01](https://commons.wikimedia.org/wiki/File:Turin_Papyrus_(geological_map)_-_Museo_Egizio_Turin_C_1879_1969_1899_p01.jpg) 15000 x 2712; p02 likewise | T, H (the scribe's painted hills) |
| T-03 | 2 | Catalan Atlas, attributed to Abraham Cresques | 1375 (BnF) | Bibliothèque nationale de France, Espagnol 30 | Public domain (PD-Art on Commons). BnF's own terms ask a fee for commercial reuse of its files; confirm whether the channel is monetised before use. | [Commons: full atlas](https://commons.wikimedia.org/wiki/File:1375_Atlas_Catalan_Abraham_Cresques.jpg) 11811 x 3850; Gallica master for the boards | T, H (the painted ranges); framing avoids the painted figures |
| T-04 | 3 | Piri Reis map, the surviving fragment, with the coast of South America | 1513 (dated on the sheet) | Topkapı Palace Museum Library, H 1824 | Public domain (PD-Art) | [Commons: Piri reis world map 01](https://commons.wikimedia.org/wiki/File:Piri_reis_world_map_01.jpg) 1964 x 2619 (low for a ground plane; search for a higher-resolution PD scan, and frame wide if none) | T |
| T-05 | 3 | Inka khipu (fibre recording device): primary cord, pendants, subsidiaries, knots | c. 1400 to 1532 (Cleveland Museum of Art) | Cleveland Museum of Art 1940.469 | CC0 (CMA Open Access) | [Commons: CMA 1940.469](https://commons.wikimedia.org/wiki/File:Peru,_Inca_Period,_15th-16th_Century_-_Inka_Khipu_(Fiber_Recording_Device)_-_1940.469_-_Cleveland_Museum_of_Art.tif) 5968 x 4958 | R (cord count, colours, knot types and positions, measured per cord into `khipu-knots.csv`); fibre albedo sampled from the photograph |
| T-06 | 4 | Gutenberg Bible (B42), Genesis 1, with the red rubric | c. 1455 | Copy to be identified from the Commons source chain before use | Public domain | [Commons: B42 Genesis](https://commons.wikimedia.org/wiki/File:Gutenberg_Bible_B42_Genesis.JPG) 6843 x 9616 | T (the leaf) |
| T-07 | 4 | Jost Amman, "Der Buchdrucker", woodcut in the *Ständebuch*: a common press | 1568 | (Commons reproduction) | Public domain | [Commons: Printer in 1568-ce](https://commons.wikimedia.org/wiki/File:Printer_in_1568-ce.png) | R (press proportions: cheeks, screw, bar, platen, carriage); people in the woodcut never shown |
| T-08 | 5 | Ino Tadataka, *Dai Nihon enkai yochi zenzu*, sheet 6 (coast, roads, red survey lines, pictorial relief) | Catalogued [1821]; surveyed 1800 to 1816 (LoC record) | Library of Congress, Geography and Map Division, 2001620020 | Public domain (LoC: manuscript of 1821) | [Commons: LOC 2001620020-6](https://commons.wikimedia.org/wiki/File:Dai_Nihon_enkai_yochi_zenzu_LOC_2001620020-6.jpg) 9918 x 5739; [loc.gov/item/2001620020](https://www.loc.gov/item/2001620020/) | T, H (pictorial mountains); the glint follows the printed red line |
| T-09 | 6 | Morse's first telegraph message, the embossed tape, Washington to Baltimore | 24 May 1844, 8:45 a.m. (on the tape) | Library of Congress, Samuel F. B. Morse Papers, mcc.019 | Public domain | [loc.gov/item/mcc.019](http://www.loc.gov/item/mcc.019/); [Commons: The First Telegraph](https://commons.wikimedia.org/wiki/File:The_First_Telegraph.jpg) 3860 x 190 (too short for a close shot; use the LoC master TIFF) | T (the tape) |
| T-10 | 6 | Morse-Vail telegraph key | 1844 (NMAH) | Smithsonian NMAH 1096762 | CC0 (Smithsonian Open Access) | Smithsonian Open Access id `ld1-1643398853934-1643398870277-0` | R |
| T-11 | 6 | Telegraph register | 1849 (NMAH) | Smithsonian NMAH 706500 | CC0 (Smithsonian Open Access) | id `ld1-1643398853934-1643398871139-0` | R |
| T-12 | 7 | Hollerith electric counting machines, engraving | *Scientific American*, 30 August 1890 | (Commons reproduction) | Public domain | [Commons: 1890 Census Hollerith](https://commons.wikimedia.org/wiki/File:1890_Census_Hollerith_Electrical_Counting_Machines_Sci_Amer.jpg) | R only (shows a clerk; never shown): the 4 x 10 dial bank, press, sorting box |
| T-13 | 7 | Hollerith tabulator (replica), photograph | photograph 2000s; machine of c. 1890 | Computer History Museum; photo Adam Schuster | CC BY 2.0: credit "Adam Schuster, CC BY 2.0" | [Commons: HollerithMachine.CHM.jpg](https://commons.wikimedia.org/wiki/File:HollerithMachine.CHM.jpg) | R (dial faces, bezels, press) |
| T-14 | 7 | Counter from a Hollerith tabulating machine | 1890s (NMAH) | Smithsonian NMAH | Licence not shown by the API: confirm CC0 before use | Smithsonian Open Access id `ld1-1643398853934-1643398891168-1` | R (dial graduation and hands) |
| T-15 | 8 | Lumière cinématographe, front and rear | 1896 | NPGallery (US National Park Service), Edison NHP historical photo | Public domain (US federal) | [Commons: Cinématographe two views](https://commons.wikimedia.org/wiki/File:Cinematographe_Lumiere_motion_picture_projector,_two_views,_front_and_rear._By_Auguste_%26_Louis_Lumiere._(c3a8372e-e839-4bda-981f-e166fc3843a4).jpg) | R (box, spool, gate, claw, crank, lens) |
| T-16 | 8 | Alexandre Promio, *Panorama du Grand Canal pris d'un bateau* (Lumière), frames | Shot October to December 1896; screened in Lyon on 13 December 1896 (Commons record) | Institut Lumière (Blu-ray transfer, 2015) | Public domain (Promio d. 1926; the Lumières d. 1948 and 1954); a faithful transfer adds no new right in the US | [Commons: webm 1364 x 1022](https://commons.wikimedia.org/wiki/File:Venise_Panorama_du_Grand_Canal_1896.webm); still [Panorama du Grand Canal.jpg](https://commons.wikimedia.org/wiki/File:Panorama_du_Grand_Canal.jpg) | T (consecutive frames on the strip, in order; gondoliers never framed as subjects) |
| T-17 | 9 | Underwood Standard No. 5 | photograph before October 1922 (*Popular Science*); model from 1900 | (Commons) | Public domain | [Commons: Underwood no5](https://commons.wikimedia.org/wiki/File:Underwood_no5.jpg); [colour advertisement, 1924](https://commons.wikimedia.org/wiki/File:Underwood_Standard_Typewriter_No._5_(colored).jpg) | R (42 typebars, basket, segment, platen, carriage) |
| T-18 | 9 | A typed page | must be dated 1900 to 1931 so the core stays at or before 1931 | to be chosen: NARA catalogue (US federal, public domain) | Public domain | lead: a typed federal record of 1900 to 1931 with no personal data and no event in it (a survey or census office memorandum fits the machine) | T (revealed character by character in beat 9) |
| T-19 | 10 | Rebbelib stick chart, Ratak and Ralik chains: shells for atolls, straight sticks for currents, curved sticks for swells, typed name strips | 1920s (cataloguer's date) | Library of Congress 2010586182 | Public domain | [Commons: LOC 2010586182](https://commons.wikimedia.org/wiki/File:Marshall_Islands_stick_chart,_Rebbelib_type._LOC_2010586182.jpg) 10966 x 10176 | R (every stick traced from the top-down photograph into curves; shell and strip positions); T (strip and shell crops) |
| T-20 | 10 | Admiralty chart 983, *Marshall Islands* | Published 1891, new edition 1931 (printed on the sheet) | UK Hydrographic Office (scan) | Public domain (Crown copyright, 50 years from publication, expired) | [Commons: Admiralty Chart No 983](https://commons.wikimedia.org/wiki/File:Admiralty_Chart_No_983_Marshall_Islands,_Published_1891,_New_Edition_1931.jpg) 16232 x 10955 | T |

**Why not the LoC mattang** (2010586180)? The cataloguer notes that the class "was used as a training aid and represents no particular" place. Laid over a chart of real atolls, it would claim a correspondence it does not have. The rebbelib charts both chains, so the juxtaposition in beat 10 is true.

## The films' records (beat 11), from the house ledgers

| Film | Ledger id | Record | Where |
|---|---|---|---|
| Not a Free Agent (Partition) | S-130 | *The Gazette of India Extraordinary*, Sunday 17 August 1947, page 1: the Reports of the Bengal and Punjab Boundary Commissions | `C:/Users/aacri/document-work/partition/stills-ledger.json`; file `partition/stills/S-130.png` |
| Not a Free Agent (alternate) | M-008 | Survey of India quarter-inch sheet 44 I Lahore, edition 1943 | `partition/sheets-ledger.json` |
| The Next Village (smallpox) | S-16928 | World-wide smallpox endemic areas, 1976 (WHO map) | `smallpox/stills-ledger.json`; `smallpox/stills/S-16928.jpg` |
| The Next Village (alternate) | S-7703 | A map of Sylhet with flags on the villages where smallpox had been found, 1975 | `smallpox/stills-ledger.json` |
| September 11 | S11-NASA-GOES8-ERIN | GOES-8, 14:39 UTC: Hurricane Erin and the plume over New York | `sept11/stills-ledger.json`; `sept11/stills/S11-NASA-GOES8-ERIN.jpg` |
| September 11 (alternate) | S11-NASA-ISS003-E-5388 | New York from the International Space Station | `sept11/stills-ledger.json` |

The record keeps its ledger entry, licence and credit. The title adds a use, not a new item.

## Modelled versus textured

| Modelled (geometry; materials procedural unless a T id is given) | Textured from a scan (the scan is the surface) |
|---|---|
| Clay tablet body and the 24-tooth fired-clay ring | Tablet faces (T-01) |
| Table plane; the Atlas's six boards and hinges | Papyrus (T-02), Atlas boards (T-03), Piri Reis sheet (T-04) |
| Khipu drum; cords as two-ply curves; knots as instanced single, long and figure-eight knots at measured positions (T-05) | Cord colour sampled from T-05 |
| Common press: cheeks, head, screw thread, bar, platen, bed, tympan (T-07) | Genesis leaf (T-06) |
| Paper sheets with fold lines; relief by displacement from H maps | Ino sheet (T-08), Admiralty chart (T-20) |
| Morse-Vail key, register train, rollers, stylus (T-10, T-11); the tape as a ribbon | The tape (T-09) |
| Tabulator: 40 counters, bezels, hands, press, pin box (T-12 to T-14); blank card | Dial graduation drawn by the studio from T-14, no figures |
| Cinématographe box, spool, gate, claw, crank, lens (T-15); film strip with round perforations | Frames on the strip (T-16) |
| Typewriter basket of 42 bars, segment, platen, carriage (T-17) | Typed page (T-18) |
| Rebbelib sticks traced as curves, lashings, shells (T-19) | Name strips and shell crops (T-19) |
| The record plate, at the scan's exact aspect | The film's record (beat 11) |
| Lamp, dust, haze: procedural (no image) | |

## Proposed `title-ledger.json`

The house ledger shape (as in `partition/sheets-ledger.json`), one item per T id, plus three fields: `use` (`texture`, `reference` or `relief`), `beats` (the beats it appears in) and `module_date` (the latest date it brings into its module, read by the horizon rule). A relief map (H) is its own item, `class: "drawn"`, `drawn_from: "T-08"`, dated by what it draws. The build script refuses an image datablock in the `.blend` that has no ledger item (`BLENDER-PLAN.md`, provenance check).

## Reserve modules for early horizons (leads only; nothing sourced)

| Lead | Region, era | Where to look |
|---|---|---|
| Shang oracle-bone inscriptions | China, c. 1200 BCE | Commons, museum open-access collections (check each licence) |
| Tabula Peutingeriana | Roman road map, a 13th-century copy | Österreichische Nationalbibliothek, Cod. 324 |
| Kangnido | Korea, 1402 (copy of c. 1470s) | Ryukoku University (licence to check) |
| A Maya codex (Dresden) | Maya, c. 11th to 12th century | SLUB Dresden digital collections (licence to check) |
