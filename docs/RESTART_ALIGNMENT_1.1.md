# Explicit single-image alignment restart

## Report and cause

After an image was aligned, crop zoom/pan and manual arrow-key X/Y nudges could
be saved. Choosing Start alignment again used ordinary cache-preserving
processing. That could reuse geometry and retained the nudges even after the
automatic near point had been measured again. The remaining manual offsets
therefore survived in both the preview and subsequent output.

## Corrected behavior

The explicit single-image Start action (including Space) requests
`ProcessingOptions.restart_alignment`. The processing worker:

- clears only manual X/Y nudges in its local state;
- recomputes geometry and the near-point measurement;
- retains crop zoom, pan, output aspect, eye orientation/order, favorite,
  floating-window masks and the color-enabled choice;
- applies the established 3-per-mille automatic near framing when a measurement
  is available, with the existing uncertainty handling;
- invalidates fitted color data after the reset.

The established geometry estimator still works on the oriented source pair;
near-point analysis uses the selected output crop. No new crop-only geometry
estimator, warp, matcher, near-point threshold or renderer is introduced.

Save and batch keep the default cache-preserving processing options, including
saved manual fine adjustments. Ctrl+R retains its separate existing reset
behavior, which also clears crop zoom/pan and floating windows.

The restart changes remain local until successful processing is ready to save.
Failure or cancellation before that commit preserves the saved edits and the
displayed session. Existing
schema-3 `.sfin` fields store the resulting zero manual offsets and recomputed
automatic correction. No schema or calculation-version bump is required for
this explicit-action change; existing sessions remain compatible.

## Verification

Local regression checks passed 180 application tests and 42 research tests.
The new processing test with synthetic image arrays reproduces analyzed input, zoom, crop pan, X/Y
nudges and restart. Its native output is pixel-identical to a clean control
analysis with the same crop, the detected near point is at least 3 per mille
behind the window, and saved/reopened sessions retain zero manual offsets.
It also checks that ordinary processing keeps the manual edits, cache reuse
still works after restart and a repeated explicit Start recalculates again.
A second test cancels after actual feature analysis and verifies that saved
edits remain byte-for-byte unchanged.

The DE/EN GUI smoke adds the same interaction through the real asynchronous
single-image worker on the supplied stereo reference image in a temporary
folder. Code commit `0f2537567b1dca4bf021691608a7329f4f741fe1` passed
all seven jobs in [run 39563335496](https://github.com/muelli1975/StereoFine/actions/runs/39563335496):
180 application and 42 research tests on Windows, Linux and macOS, both GUI
languages, and actual frozen packages on Windows, Linux, macOS ARM and macOS
Intel. Published RC3 and stable 1.0 are unchanged.
