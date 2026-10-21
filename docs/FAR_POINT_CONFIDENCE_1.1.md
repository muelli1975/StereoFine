# Far-end confidence audit for 1.1

SGBM remains the candidate generator. A percentile and connected components do
not establish that a low-texture region contains identifiable correspondences.

The additional audit horizontally reflects both analysis images and negates
the reflected dense disparities. This maps the far end to the existing near-end
patch verifier without exchanging eyes. It reuses its raw-luma texture,
normalized correlation, uniqueness, reciprocal matching and spatial support
checks. Diagnostics explicitly label the reflected coordinate system.

An unsupported far percentile makes the range uncertain. A supported farther
surface outside the retained percentile estimate also makes it uncertain.
The numeric estimate, correction and near-point framing are not replaced.
This deliberately avoids treating a narrower observed span as the full scene
range. Cached disparity results are invalidated through pipeline version 4;
alignment and user settings remain reusable.

On the supplied bild098 original pair with AKAZE, the existing 67.4583358765
permille estimate now carries `far_edge_unconfirmed`. The selected model is
still Affine + yCubic, and the automatic horizontal offset remains 159 pixels.

Limits: this audit shares the existing patch verifier and its tolerances; it
is corroboration, not depth ground truth. Full-resolution far-end recovery,
search-boundary symmetry, broader real-image coverage and runtime profiling
remain follow-up work. There is no claim of a complete or automatically repaired
range. No platform package is produced for this change.
