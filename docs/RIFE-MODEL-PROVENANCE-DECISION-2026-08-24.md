# RIFE model provenance decision — 2026-08-24

## Current decision

The exact converted RIFE v4.6 model may now be redistributed in an explicitly
named, debug-signed **qualification-only** EmuFusion APK. It remains forbidden
from normal release APKs and must not receive product frames until the remaining
integration, performance, stability, and physical-gameplay gates pass.

The original-author licensing identity and the numerical identity of the
separately converted ncnn graph and weights are now closed with locked evidence.

## Stronger primary-source evidence found

At historical Practical-RIFE commit
`f6b5132517695127bdb5d5a8c3727e719f0fda22`, authored by the original project,
the README both states that the linked trained-model contents use the project's
MIT license and names `v4.6 - 2022.9.26`. Its v4.6 link resolves to the exact
Google Drive archive locked below. The MIT license permits use, modification,
publication, distribution, sublicensing, and sale with the required notice.

Frozen upstream identity at audit time:

```text
Practical-RIFE commit  f6b5132517695127bdb5d5a8c3727e719f0fda22
README SHA-256         436b94a67e75ae79df43a77f779040d6f6e0f37a9b2557ccc2cfc75ae99d2a36
LICENSE SHA-256        7932fb49341512b959b1744a6d9cbb39e5a1ec89da438a34d0454d5d8df9fecd
v4.6 archive bytes     19,747,567
v4.6 archive SHA-256   52b094d14cf275e925a5ae25381e46f94fab1c232a847dc45117cfd7c89ceec2
checkpoint path        train_log/flownet.pkl (21,273,159 bytes)
```

Primary URLs:

- <https://github.com/hzwer/Practical-RIFE/blob/f6b5132517695127bdb5d5a8c3727e719f0fda22/README.md>
- <https://raw.githubusercontent.com/hzwer/Practical-RIFE/f6b5132517695127bdb5d5a8c3727e719f0fda22/LICENSE>
- <https://raw.githubusercontent.com/nihui/rife-ncnn-vulkan/a7532fc3f9f8f008cd6eecd6f2ffe2a9698e0cf7/LICENSE>

## Promotion rule

The exact original checkpoint, source URL/hash, README, and license snapshot are
locked in `experiments/rife-ncnn-vulkan-android/upstream-lock.json`.

## Converted-model numerical identity

The original float32 PyTorch checkpoint was executed with the same v4.6 fast
configuration used by the Android benchmark: scale list 8/4/2/1, timestep 0.5,
no spatial TTA, no temporal TTA, and no UHD mode. Its pixels were compared with
the frozen physical Adreno fp16/ncnn outputs for all 120 corpus pairs.

The four intentionally marked scene cuts remain reported but are excluded from
the equivalence decision because product policy forbids interpolation across
them. All 116 lawful motion pairs passed:

```text
aggregate PSNR                 57.313755 dB
minimum per-frame PSNR         51.026206 dB
mean absolute byte error        0.069288 / 255
bytes within two levels        99.748283%
maximum absolute byte error    15 / 255
```

Evidence:

```text
evidence/model-provenance-2026-08-24/v46-ncnn-equivalence.json
SHA-256 fc55aabaa2ffba0eda5e4c01c8e6c9631e75fd41a4a4daf6de69811794cc73a6
```

This proves the selected converted graph and weights implement the expressly
MIT-licensed original v4.6 checkpoint within the expected fp16/Vulkan rounding
envelope. It does not, by itself, approve product routing.

## Qualification redistribution decision

The pinned original-author README says that the linked model contents use the
same MIT license as Practical-RIFE and identifies the exact v4.6 release. MIT
expressly permits use, modification, publication, distribution, sublicensing,
and sale when the copyright and permission notice are retained. The frozen ncnn
conversion is numerically equivalent to that exact checkpoint, so the locked
`flownet.param`/`flownet.bin` pair may travel only with:

- the Practical-RIFE and rife-ncnn-vulkan MIT notices;
- the complete ncnn and glslang third-party notices;
- an exact hash-bound qualification manifest; and
- `productIntegrationAllowed:false` and
  `routeProductFramesToProvider:false` until physical promotion.

This is a bounded engineering distribution decision, not legal advice. It does
not claim independently reconstructed training-data provenance or a separate
patent grant, and it does not authorize a public product route before the
remaining acceptance gates.

## Remaining promotion rule

Product promotion still requires:

1. a notice-complete, hash-bound qualification package whose default build is
   model-free;
2. a nonblocking, fence-owned live path with no synchronous readback or waits;
3. content, deadline, thermal, stability, memory, and failover gates; and
4. representative moving-game physical qualification under the shared EmuFusion
   timestamp and pacing authority.

This is an engineering provenance decision, not legal advice. Ambiguity remains
fail-closed.
