# Draft: permission request to THS for EmuFusion / LSFG

## Current authorization status (verified 2026-08-26)

**NOT SENT / NO WRITTEN THS PERMISSION RECORDED.** A repository-wide audit
found no sent-message receipt, THS reply, agreement, license, or correspondence
artifact. The authoritative source lock therefore remains:

- `productIntegrationAllowed:false`;
- `privateAsset.redistributionAuthorized:false`;
- `privateAsset.executionAuthorized:false`;
- `qualificationGate.productEligible:false`.

Public descriptions that LSFG supports emulators, public MIT wrapper code, and
private technical feasibility results are not permission to use or distribute
THS's proprietary assets. Until the owner sends this request and records an
explicit written answer covering every item below, EmuFusion product routing
must skip LSFG and continue with a legally clean independent backend or Direct.

Do not infer approval from silence, a support response, public project links,
or a purchased copy of Lossless Scaling. Preserve the complete message headers,
date, sender/recipient, and unedited THS response as the future audit artifact.

## Delivery

Send this as a business inquiry through the official Lossless Scaling contact:

- `contact@losslessscaling.com` — business inquiries on the official website;
- optionally copy `losslessscaling@gmail.com`, which Steam lists as official
  Lossless Scaling support.

Official references rechecked 2026-08-26:

- <https://losslessscaling.com/> — official site, LSFG described as proprietary
  frame generation intended to support games including emulators, with
  separate user-support and business-inquiry addresses;
- <https://help.steampowered.com/en/wizard/HelpWithGameTechnicalIssue/?appid=993090>
  — Steam identifies THS as developer/publisher and lists the support email;
- <https://steamcommunity.com/app/993090/discussions/0/598521781543803818/>
  — developer-pinned official website and Discord links.

Do not attach, upload, or send any DLL, extracted shader, model, or other
proprietary asset with the request.

## Suggested subject

Permission / technical partnership request: LSFG for EmuFusion on Android

## Draft message

Hello THS,

I am developing EmuFusion, a unified Android emulation frontend intended to
make legally owned games launch and play through one automatic interface. I am
interested in using Lossless Scaling Frame Generation as an optional in-process
frame-generation backend on a 120 Hz Android handheld.

Before doing any LSFG implementation or distribution work, I want written
permission and clear technical/licensing boundaries. I will not bundle or
redistribute Lossless Scaling binaries, DLLs, shaders, models, or extracted
assets without your explicit authorization.

Could you please confirm whether THS would permit the following?

1. An Android/arm64 in-process implementation or port of LSFG integrated into
   EmuFusion, with EmuFusion retaining responsibility for timestamps, pacing,
   scene-cut rejection, and presentation.
2. A per-user flow in which a user who purchased Lossless Scaling through
   Steam locally supplies or extracts the required DLL/assets for their own
   device, without EmuFusion redistributing those proprietary files.
3. Distribution of EmuFusion itself without any proprietary THS assets, while
   providing an optional automatic setup path for licensed users.
4. A one-setting user experience in which EmuFusion automatically selects safe
   frame-generation rates and falls back to direct presentation when LSFG is
   unavailable or unqualified.
5. Use of the names “Lossless Scaling” and “LSFG” in settings, notices,
   compatibility documentation, and attribution.

If any of those uses require a commercial license, SDK agreement, royalty,
branding requirement, technical review, or a different distribution model,
please let me know. I would also welcome an official Android/Vulkan SDK or a
technical contact if one is available; I prefer an authorized integration over
reverse engineering.

The intended safety constraints are conservative: generated output never
exceeds 2× the measured unique source rate, rates are mapped only to uniform
panel divisors, interpolation never crosses a discontinuity or scene cut, and
the product never claims delivered FPS without physical presentation evidence.

I can provide a concise architecture and product/distribution description if
helpful. Please state explicitly what is permitted, what is prohibited, and
whether the permission applies to private testing, public distribution, and
commercial distribution separately.

Thank you,

[Name]
[Project/company, if applicable]
[Contact information]

## Required written answers before LSFG work resumes

- private Android feasibility work permitted: yes/no;
- Android in-process port/use permitted: yes/no and conditions;
- purchased-user local extraction/use permitted: yes/no and conditions;
- EmuFusion distribution without THS assets permitted: yes/no and conditions;
- proprietary asset redistribution permitted: yes/no and exact assets;
- LSFG/Lossless Scaling naming permitted: yes/no and branding requirements;
- public versus commercial distribution scope;
- SDK/source/API availability and technical contact;
- revocation, update, security, and attribution obligations.

Until those answers are received, `redistributionAuthorized:false` remains the
authoritative project state and LSFG implementation/distribution work stays
frozen. The clean, independently licensed RIFE arm may continue separately.
