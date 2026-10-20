# Changelog

## 1.0 – 2026-09-07

Initial public release.

Highlights:

- automatic stereo alignment with conservative Affine / Vergence / Y-Polish model selection;
- separate robust near/far/deviation analysis;
- automatic 3‰ near-point framing;
- manual fine alignment, crop and Floating Window masks;
- optional symmetric color matching;
- Full-SBS, MPO and separate Left/Right input workflows;
- reusable `.sfin` sidecars;
- analysis-only batch reports and favorites-only export;
- color and grayscale anaglyph output;
- German and English GUI;
- portable Windows onedir release with bundled ExifTool;
- MIT-licensed StereoFine source with separate third-party license material.
- final Windows-facing GUI regression fixes: structurally unobstructed activity ring, v41-style immediate Floating Window preview, and save completion using only `ready.wav` without an additional native info-dialog tone;
- post-handoff GUI cleanup: grid spacing remains editable after the keyboard cycle returns to Off; status values update in place to prevent footer/status flicker; F1 help uses a larger desktop-friendly window; preview sizing now reserves the documented dynamic 3% + 2 px black border outside the image so the full 30‰ Floating Window remains visible;
- spinner moving segment uses an even-width arc without oversized endpoint caps;
- Vergence status no longer exposes compatibility `V 0.000 / H 0.000` placeholders; the current projective Vergence stage reports the magnitude of the correction actually applied and preserves it across `.sfin` reloads;
- F1 keyboard help is rendered as a real typographic key/function table.
- sidebar mouse-wheel scrolling uses CustomTkinter's native single scroll path again; the redundant competing global StereoFine wheel forwarder was removed.

- batch progress status now follows every processed source even when a lightweight preview frame is unavailable;
- successful save/batch/analysis completion produces one `ready.wav` notification and no additional native Windows information-dialog chime;
- analysis-only report reduced to a readable aligned quality table: traffic light, deviation, near/far point, vertical error, Vergence, rotation and uncertainty note.
