# Staged learned estimator (not compiled into the app)

`LearnedFrameEstimator.java` runs the PhaseNet passes (structure from the REA
study of Lossless Scaling's frame generation; our own weights) on GLES3.
`LearnedFrameShaders.java` is generated from a trained checkpoint:

    /Library/Developer/CommandLineTools/usr/bin/python3 -m tools.learned_framegen.export_gles CHECKPOINT \
        --java unified-android/src/com/thorium/preview/game/LearnedFrameShaders.java

and `verify_gles.py` checks every pass against PyTorch on the desktop GPU.
Training from scratch collapsed to a cross-fade (October 14, 2026), so the
runtime is staged here until a trained network beats the shipped DIS paths
on the paired Thor hold-out. `test_learned_framegen_staged.py` moves back to
`tools/tests/` with it.
