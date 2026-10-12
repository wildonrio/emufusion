# PUAE minimal legal fixture

`build_fixture.py` creates a deterministic 880 KiB Amiga floppy image. Its
boot block writes red to the first custom-chip color register and loops. The
fixture contains no Commodore or third-party firmware, game data, filesystem,
or copyrighted asset.

Build it with:

```sh
python3 engines/qa/fixtures/puae-minimal/build_fixture.py /tmp/emufusion-puae.adf
```

Expected SHA-256: `e5692a1ef7a769936b283b465f1dd965979a2cae1e16e4f8af32e41c310724b1`.

Runtime/device qualification is intentionally separate and remains open.
