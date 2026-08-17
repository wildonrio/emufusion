"""Phase 3 native-adapter scaffolding (Wii U/Cemu).

Structural, source-scanning coverage in the established tools/tests house style
that locks the fail-closed native-adapter foundation a compiled Cemu adapter
plugs into: the pinned registry identity, the NativeAdapterCatalog present+hash
gate, honest capability reporting, and the routing that stays EXTERNAL until the
in-process adapter is real.
"""

import json
import hashlib
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


REGISTRY = json.loads((ROOT / "engines" / "phase3-registry.json").read_text())
SOURCE_LOCK = json.loads((ROOT / "engines" / "cemu-source-lock.json").read_text())
CATALOG = _read(ROOT / "unified-android" / "src" / "com" / "thorium" /
                "preview" / "game" / "NativeAdapterCatalog.java")
SESSION = _read(ROOT / "unified-android" / "src" / "com" / "thorium" /
                "preview" / "game" / "NativeAdapterEngineSession.java")
BOOTSTRAP = _read(ROOT / "unified-android" / "src" / "com" / "thorium" /
                  "preview" / "game" / "InternalEngineBootstrap.java")
ROUTER = _read(ROOT / "android-companion" / "src" / "com" / "thorium" /
               "preview" / "GameLaunchRouter.java")
ROUTE_STORE = _read(ROOT / "android-companion" / "src" / "com" / "thorium" /
                    "preview" / "EngineRouteStore.java")
ABI_HEADER = _read(ROOT / "unified-android" / "native" / "include" /
                   "lucent_native_adapter.h")
HOST_C = _read(ROOT / "unified-android" / "native" / "lucent_native_adapter_host.c")
JNI_C = _read(ROOT / "unified-android" / "native" / "lucent_native_adapter_jni.c")
MOCK_C = _read(ROOT / "unified-android" / "native" / "tests" /
               "mock_native_adapter.c")
HOST_TEST_C = _read(ROOT / "unified-android" / "native" / "tests" /
                    "native_adapter_host_test.c")
RUN_TESTS = _read(ROOT / "unified-android" / "native" / "run_tests.sh")
CEMU_ADAPTER = _read(ROOT / "engines" / "patches" / "cemu-lucent-adapter.cpp")
CEMU_TREE = Path(SOURCE_LOCK["core"]["stagedTree"])
CEMU_SWKBD_H = _read(CEMU_TREE / "src" / "Cafe" / "OS" / "libs" /
                     "swkbd" / "swkbd.h")
CEMU_SWKBD_CPP = _read(CEMU_TREE / "src" / "Cafe" / "OS" / "libs" /
                       "swkbd" / "swkbd.cpp")
CEMU_COREINIT_MEM_H = _read(CEMU_TREE / "src" / "Cafe" / "OS" / "libs" /
                            "coreinit" / "coreinit_MEM.h")
CEMU_COREINIT_MEM_CPP = _read(CEMU_TREE / "src" / "Cafe" / "OS" / "libs" /
                              "coreinit" / "coreinit_MEM.cpp")
CEMU_PPC_RECOMPILER_H = _read(CEMU_TREE / "src" / "Cafe" / "HW" /
                              "Espresso" / "Recompiler" /
                              "PPCRecompiler.h")
CEMU_AARCH64_BACKEND = _read(CEMU_TREE / "src" / "Cafe" / "HW" /
                             "Espresso" / "Recompiler" /
                             "BackendAArch64" / "BackendAArch64.cpp")


class Phase3RegistryCemuTest(unittest.TestCase):
    def _cemu(self):
        rows = [row for row in REGISTRY["engines"] if row["id"] == "cemu"]
        self.assertEqual(1, len(rows), "exactly one cemu registry row")
        return rows[0]

    def test_cemu_is_a_native_adapter_at_the_pinned_commit(self):
        cemu = self._cemu()
        self.assertEqual("native-adapter", cemu["route"])
        self.assertEqual(["wiiu"], cemu["systems"])
        # SSimco/Cemu is the Android port and is the tree that is actually
        # compiled; the old pin named cemu-project/Cemu, the desktop repository,
        # which describes no artifact we build. The row now carries repository
        # and commit only -- the archive hash moved into the source lock's
        # localArchive object, because it describes a local tarball rather than
        # anything fetchable from that URL.
        self.assertEqual("https://github.com/SSimco/Cemu",
                         cemu["source"]["repository"])
        self.assertEqual("5897c6d3092612ef410137ba2f7c35043b9b3061",
                         cemu["source"]["commit"])
        self.assertNotIn("archiveSha256", cemu["source"])

    def test_cemu_registry_row_stays_fail_closed(self):
        cemu = self._cemu()
        self.assertEqual("research", cemu["status"])
        self.assertFalse(cemu["shipped"])
        self.assertTrue(all(v is False for v in cemu["gates"].values()))

    def test_source_lock_reuses_the_registry_identity_and_is_not_reproducible(self):
        self.assertEqual("native-adapter", SOURCE_LOCK["route"])
        self.assertIs(False, SOURCE_LOCK["reproducible"])
        cemu = self._cemu()
        # The point of this test is that the registry and the source lock can
        # never drift apart on WHICH engine was built, so both identity fields
        # they share are compared, not just the commit.
        self.assertEqual(cemu["source"]["repository"],
                         SOURCE_LOCK["core"]["repository"])
        self.assertEqual(cemu["source"]["commit"], SOURCE_LOCK["core"]["commit"])
        # The archive hash lives only in the lock now, under localArchive, and
        # describes a tarball on this machine rather than a release asset. It is
        # still pinned -- asserted here so it cannot quietly disappear.
        local_archive = SOURCE_LOCK["core"]["localArchive"]
        self.assertEqual(64, len(local_archive["sha256"]))
        self.assertTrue(local_archive["path"])
        self.assertGreater(local_archive["sizeBytes"], 0)
        self.assertEqual("lucent_native_adapter_entry",
                         SOURCE_LOCK["adapterAbi"]["entrySymbol"])
        self.assertEqual("liblucent_native_adapter_cemu.so",
                         SOURCE_LOCK["adapterAbi"]["expectedLibraryName"])

    def test_cemu_lock_matches_every_local_patch_and_staged_artifact(self):
        for patch in SOURCE_LOCK["patches"]:
            if patch.get("pathIsRelativeTo"):
                path = Path(patch["pathIsRelativeTo"]) / patch["path"]
            else:
                path = ROOT / patch["path"]
            payload = path.read_bytes()
            self.assertEqual(patch["sizeBytes"], len(payload), str(path))
            self.assertEqual(patch["sha256"], hashlib.sha256(payload).hexdigest(),
                             str(path))

        artifact = SOURCE_LOCK["artifact"]
        path = ROOT / artifact["stagedPath"]
        payload = path.read_bytes()
        self.assertEqual(artifact["sizeBytes"], len(payload))
        self.assertEqual(artifact["sha256"], hashlib.sha256(payload).hexdigest())


class NativeAdapterCatalogGateTest(unittest.TestCase):
    def test_catalog_is_present_plus_hash_verified_and_fail_closed(self):
        # The adapter .so must be bundled in the APK's native library dir AND
        # hash exactly to the signed manifest, or the entry fails closed.
        self.assertIn("context.getApplicationInfo().nativeLibraryDir", CATALOG)
        self.assertIn("InternalEngineCatalog.verifiedSha256(context, core)", CATALOG)
        self.assertIn("core.isFile()", CATALOG)
        self.assertIn("libraryRoot.equals(core.getParentFile())", CATALOG)
        self.assertIn('"[0-9a-f]{64}"', CATALOG)
        self.assertIn('"native-adapter".equals(runtime)', CATALOG)
        self.assertIn('"native-adapter".equals(row.optString("route"))', CATALOG)

    def test_catalog_absent_opt_in_yields_empty_catalog(self):
        # No opt-in asset ships today; its absence must return an empty catalog
        # rather than throwing or enabling an unverified adapter.
        self.assertIn("readAssetOrNull(context, OPT_IN)", CATALOG)
        self.assertIn("if (optInRaw == null) return result;", CATALOG)
        self.assertIn("Collections.<String, Entry>emptyMap()", CATALOG)

    def test_catalog_is_bootstrapped_off_main_thread_like_the_others(self):
        self.assertIn("NativeAdapterCatalog.expectBootstrapOn(verifier)", BOOTSTRAP)
        self.assertIn("NativeAdapterCatalog.bootstrapComplete()", BOOTSTRAP)
        self.assertIn("new NativeAdapterEngineSession(sessionContext, entry)", BOOTSTRAP)

    def test_switch_adapter_is_preloaded_on_verified_background_bootstrap(self):
        self.assertIn('if ("eden".equals(entry.id))', BOOTSTRAP)
        self.assertIn("NativeAdapterHost.preload(entry.coreFile, trusted)", BOOTSTRAP)
        self.assertIn("Native adapter preload failed", BOOTSTRAP)
        host_java = _read(ROOT / "unified-android" / "src" / "com" / "thorium" /
                          "preview" / "NativeAdapterHost.java")
        self.assertIn("public static long preload", host_java)
        self.assertIn("try (NativeAdapterHost ignored", host_java)

    def test_android_jni_onload_is_process_once_for_retained_adapters(self):
        self.assertIn("adapter_jni_onload_lock", HOST_C)
        self.assertIn("adapter_jni_initialized", HOST_C)
        self.assertIn("adapter_jni_initialized[index] == library", HOST_C)

    def test_ambiguous_owner_fails_closed(self):
        self.assertIn("if (match != null) return null;", CATALOG)


class NativeAdapterRoutingTest(unittest.TestCase):
    def test_router_prefers_internal_engines_then_falls_through_to_native_adapter(self):
        block = ROUTER[ROUTER.index("private static String engineIdForSystem"):]
        self.assertIn("InternalEngineCatalog.availableForSystem", block)
        self.assertIn("Phase2QualificationCatalog.libraryEngineIdForSystem", block)
        # Native adapter is the LAST fallback, so a system with no bundled
        # adapter resolves empty and EngineRouteStore emits its external route.
        self.assertIn("NativeAdapterCatalog.libraryEngineIdForSystem(context, normalized)",
                      block)
        phase2_at = block.index("Phase2QualificationCatalog.libraryEngineIdForSystem")
        adapter_at = block.index("NativeAdapterCatalog.libraryEngineIdForSystem")
        self.assertLess(phase2_at, adapter_at)

    def test_wiiu_prefers_external_until_the_adapter_is_present(self):
        # EngineRouteStore.resolve returns EXTERNAL when no internal engine
        # supports the system; supportsSystem is empty until the catalog gates
        # a bundled+hashed adapter in. That is the FAIL-CLOSED path, not the
        # intended one: a build made with LUCENT_INCLUDE_PHASE3_CEMU=1 bundles
        # the Cemu adapter and Wii U runs INTERNALLY. Only a build that omits
        # the flag drops Wii U onto external Cemu.
        self.assertIn("return internalAvailable ? INTERNAL : EXTERNAL;", ROUTE_STORE)
        self.assertIn("GameLaunchRouter.supportsSystem(context,", ROUTE_STORE)
        self.assertIn("libraryEngineIdForSystem", CATALOG)
        self.assertIn("NativeAdapterPrerequisites.isReady(context, normalized)", ROUTER)

    def test_session_reports_capabilities_honestly(self):
        # No fake Quick Resume: stop() flushes persistent saves and reports no
        # restore availability when has_quick_resume is false.
        self.assertIn("capabilities.hasPersistentSave", SESSION)
        self.assertIn("onRestoreAvailabilityChanged(false)", SESSION)
        self.assertIn("public boolean openRestoreHistory()", SESSION)
        self.assertIn("Native adapter is not installed", SESSION)
        # Dual screen through the shared secondary-display router.
        self.assertIn("SecondaryGameplaySurfaceRouter.request", SESSION)

    def test_wiiu_claims_the_resumed_lower_display_before_cold_cemu_open(self):
        # Cemu's dlopen/JNI/GPU discovery can take seconds on a cold process.
        # The physical lower display is an Android surface and does not depend
        # on native capability discovery, so the hash-pinned cemu/wiiu route
        # must claim it before NativeAdapterHost performs that expensive work.
        prepare = SESSION.split(
            "@Override public void prepare(GameLaunchRequest request, Listener callback)", 1
        )[1].split("private void logLaunchPhase", 1)[0]
        self.assertLess(
            prepare.index("requestPinnedWiiUSecondaryDisplay(request)"),
            prepare.index("new NativeAdapterHost(entry.coreFile, trusted)"),
        )
        early = SESSION.split(
            "private void requestPinnedWiiUSecondaryDisplay", 1
        )[1].split("private boolean isPinnedWiiUDualScreenRoute", 1)[0]
        self.assertIn("SecondaryGameplaySurfaceRouter.request", early)
        route = SESSION.split(
            "private boolean isPinnedWiiUDualScreenRoute", 1
        )[1].split("private int controlOrdinal", 1)[0]
        self.assertIn('"cemu".equals(entry.id)', route)
        self.assertIn("isWiiUSystem(launch.systemId)", route)

    def test_nintendo_native_adapters_use_nintendo_face_letters(self):
        mapping = SESSION.split("private int controlOrdinal", 1)[1].split(
            "private static float normalizeAxis", 1
        )[0]
        self.assertIn('"eden".equals(entry.id)', mapping)
        self.assertIn('"cemu".equals(entry.id)', mapping)
        self.assertIn("case EAST: return nintendoFaceLayout ? PAD_A : PAD_B", mapping)
        self.assertIn("case SOUTH: return nintendoFaceLayout ? PAD_B : PAD_A", mapping)
        self.assertIn("case NORTH: return nintendoFaceLayout ? PAD_X : PAD_Y", mapping)
        self.assertIn("case WEST: return nintendoFaceLayout ? PAD_Y : PAD_X", mapping)

    def test_physical_native_adapter_input_is_evidence_visible(self):
        dispatch = SESSION.split("@Override public boolean dispatchKeyEvent", 1)[1].split(
            "@Override public boolean dispatchGenericMotionEvent", 1
        )[0]
        self.assertIn("Adapter input engine=", dispatch)
        self.assertIn("event.getRepeatCount() == 0", dispatch)

    def test_wiiu_early_surface_request_is_reconciled_fail_closed(self):
        prepare = SESSION.split(
            "@Override public void prepare(GameLaunchRequest request, Listener callback)", 1
        )[1].split("private void logLaunchPhase", 1)[0]
        describe = prepare.index("capabilities = created.describe()")
        reconcile = prepare.index(
            "isPinnedWiiUDualScreenRoute(request) && !capabilities.dualScreen"
        )
        self.assertLess(describe, reconcile)
        self.assertIn(
            "Pinned Cemu adapter did not report its required dual screen", prepare
        )
        # Every preparation failure releases a surface requested early.
        catch = prepare.split("} catch (Throwable failure)", 1)[1]
        self.assertIn("releaseSecondaryDisplay();", catch)


class NativeAdapterAbiAndTestsTest(unittest.TestCase):

    def test_cemu_stop_retires_guest_owned_software_keyboard_state(self):
        self.assertIn("void resetForTitleShutdown();", CEMU_SWKBD_H)
        reset = CEMU_SWKBD_CPP.split(
            "void swkbd::resetForTitleShutdown()", 1
        )[1].split("void swkbdExport_", 1)[0]
        self.assertIn("swkbdInternalState->isActive = false;", reset)
        self.assertIn("swkbdInternalState = nullptr;", reset)
        stop = CEMU_ADAPTER.split("static void adapter_stop", 1)[1].split(
            "static void adapter_destroy", 1
        )[0]
        self.assertLess(stop.index("swkbd::resetForTitleShutdown();"),
                        stop.index("CafeSystem::ShutdownTitle();"))

    def test_cemu_reclaims_only_title_owned_system_area_after_shutdown(self):
        # Cemu's stock Android app exits after one title. Lucent retains the
        # library, so the 32 MiB process-lifetime bump allocator must not leak
        # a new 8 MiB coreinit heap on every launch. The device regression was
        # a SIGTRAP at 0x1dd5000 + 8 MiB in InitSysHeap on a later launch.
        self.assertIn("void coreinit_markProcessSysAreaEnd();",
                      CEMU_COREINIT_MEM_H)
        self.assertIn("void coreinit_resetTitleSysArea();",
                      CEMU_COREINIT_MEM_H)
        self.assertIn("s_processSysAreaEnd = sysAreaAllocatorOffset;",
                      CEMU_COREINIT_MEM_CPP)
        self.assertIn("if (!s_processSysAreaEndMarked)",
                      CEMU_COREINIT_MEM_CPP)
        self.assertIn("sysAreaAllocatorOffset = s_processSysAreaEnd;",
                      CEMU_COREINIT_MEM_CPP)
        self.assertIn("coreinit::MEMResetToDefaultState();",
                      CEMU_COREINIT_MEM_CPP)

        load = CEMU_ADAPTER.split("static bool adapter_load", 1)[1].split(
            "static bool adapter_start", 1
        )[0]
        self.assertLess(load.index("CemuCommonInit();"),
                        load.index("coreinit_markProcessSysAreaEnd();"))
        self.assertLess(load.index("coreinit_markProcessSysAreaEnd();"),
                        load.index("CafeSystem::PrepareForegroundTitle"))

        stop = CEMU_ADAPTER.split("static void adapter_stop", 1)[1].split(
            "static void adapter_destroy", 1
        )[0]
        self.assertLess(stop.index("CafeSystem::ShutdownTitle();"),
                        stop.index("coreinit_resetTitleSysArea();"))

        # The measured failing pre-allocation offset was already 0x1dd5000.
        # A raw cumulative allocator cannot fit the next 8 MiB heap in 32 MiB;
        # rewinding to any valid process prefix <= the measured pre-title
        # offset makes the allocation reusable for arbitrarily many titles.
        cemu_area_size = 0x02000000
        failing_offset = 0x01DD5000
        sys_heap_size = 8 * 1024 * 1024
        self.assertGreater(failing_offset + sys_heap_size, cemu_area_size)
        process_prefix = failing_offset - sys_heap_size
        for _ in range(100):
            title_end = process_prefix + sys_heap_size
            self.assertLess(title_end, cemu_area_size)
            title_end = process_prefix
        self.assertEqual(process_prefix, title_end)

    def test_cemu_aarch64_entry_loads_current_recompiler_instance(self):
        # The generated entry trampoline lives for the process, but Cemu frees
        # and re-reserves its large per-title recompiler instance. Embedding the
        # first reservation therefore worked only while mmap happened to reuse
        # that address. On the measured third title, x27 still held the old
        # 0x79b4237000 reservation and the JIT faulted at x27 + 0x20000000,
        # exactly the beginning of ppcRecompilerDirectJumpTable.
        enter = CEMU_AARCH64_BACKEND.split(
            "void AArch64GenContext_t::enterRecompilerCode()", 1
        )[1].split("void AArch64GenContext_t::leaveRecompilerCode", 1)[0]
        address_load = (
            "mov(PPC_REC_INSTANCE_REG, "
            "(uint64)&ppcRecompilerInstanceData);"
        )
        pointer_load = (
            "ldr(PPC_REC_INSTANCE_REG, "
            "AdrUimm(PPC_REC_INSTANCE_REG, 0));"
        )
        stale_embed = (
            "mov(PPC_REC_INSTANCE_REG, "
            "(uint64)ppcRecompilerInstanceData);"
        )
        self.assertIn(address_load, enter)
        self.assertIn(pointer_load, enter)
        self.assertNotIn(stale_embed, enter)
        self.assertLess(enter.index(address_load), enter.index(pointer_load))
        self.assertLess(enter.index(pointer_load), enter.index("blr(x0);"))

        instance = CEMU_PPC_RECOMPILER_H.split(
            "typedef struct", 1
        )[1].split("}PPCRecompilerInstanceData_t;", 1)[0]
        self.assertLess(instance.index("ppcRecompilerFuncTable"),
                        instance.index("ppcRecompilerDirectJumpTable"))
        ppc_code_area_size = 0x10000000
        function_pointer_size = 8
        guest_instruction_size = 4
        direct_jump_offset = (
            ppc_code_area_size // guest_instruction_size * function_pointer_size
        )
        self.assertEqual(0x20000000, direct_jump_offset)
        stale_instance = 0x79B4237000
        measured_fault = 0x79D4237000
        self.assertEqual(measured_fault, stale_instance + direct_jump_offset)

    def test_abi_version_is_pinned(self):
        self.assertIn("#define LUCENT_NATIVE_ADAPTER_ABI_VERSION 1u", ABI_HEADER)
        self.assertIn('#define LUCENT_NATIVE_ADAPTER_ENTRY_SYMBOL '
                      '"lucent_native_adapter_entry"', ABI_HEADER)

    def test_host_fails_closed_on_every_load_gate(self):
        for guard in ("cannot load adapter",
                      "adapter is missing required symbol",
                      "adapter entry returned no vtable",
                      "unsupported adapter ABI",
                      "adapter vtable has a null function pointer",
                      "adapter must be inside Lucent's trusted directory"):
            self.assertIn(guard, HOST_C)
        # Serialize/unserialize are refused without Quick Resume.
        self.assertIn("if (!host->capabilities.has_quick_resume) return 0;", HOST_C)
        self.assertIn("does not support Quick Resume", HOST_C)

    def test_mock_adapter_reports_the_documented_capabilities(self):
        self.assertIn('out->engine_id = "mock-wiiu";', MOCK_C)
        self.assertIn("out->has_quick_resume = false;", MOCK_C)
        self.assertIn("out->has_persistent_save = true;", MOCK_C)
        self.assertIn("out->dual_screen = true;", MOCK_C)
        # Fail closed on NULL content; serialize returns 0/false.
        self.assertIn("content path is required", MOCK_C)

    def test_host_test_is_wired_into_run_tests_with_asan_ubsan(self):
        self.assertIn("mock_native_adapter.c", RUN_TESTS)
        self.assertIn("-DMOCK_ABI_MISMATCH=1", RUN_TESTS)
        self.assertIn("native_adapter_host_test", RUN_TESTS)
        self.assertIn("trusted native-adapter path rejection", RUN_TESTS)
        # Runs under the sanitizer pass exactly like the other native suites.
        sanitized = RUN_TESTS[RUN_TESTS.index("SANITIZER_FLAGS="):]
        self.assertIn("native_adapter_host_test", sanitized)

    def test_host_test_asserts_the_required_lifecycle_and_fail_closed_paths(self):
        for assertion in ("adapter with mismatched ABI was accepted",
                          "adapter loaded NULL content",
                          "serialize was not refused without Quick Resume",
                          "flush_save did not write the sentinel file"):
            self.assertIn(assertion, HOST_TEST_C)

    def test_jni_bridge_exposes_the_complete_lifecycle(self):
        for symbol in ("nativeOpen", "nativeCreate", "nativeLoadContent",
                       "nativeStart", "nativeRunFrame", "nativeSetControl",
                       "nativePause", "nativeResume", "nativeFlushSave",
                       "nativeSerialize", "nativeUnserialize",
                       "nativeSurfaceRecreated", "nativeStop", "nativeDestroy",
                       "nativeDescribe"):
            self.assertIn("Java_com_thorium_preview_NativeAdapterHost_" + symbol,
                          JNI_C)
        self.assertIn("ANativeWindow_fromSurface", JNI_C)

    def test_phase3_gameplay_gets_its_own_layer_not_a_textureview(self):
        # A TextureView publishes into the Qt window's own surface, and the
        # non-opaque one Lucent uses made every published game frame dirty the
        # whole window -- so HWUI recomposited, and Qt Quick re-rendered,
        # underneath live gameplay for the entire session. That is where the
        # Adreno null dereference in QSGBatchRenderer::renderBatches() came
        # from. The Phase 3 engines present from their own GPU thread and must
        # therefore get a real SurfaceFlinger layer instead.
        layer = _read(ROOT / "unified-android" / "src" / "com" / "thorium" /
                      "preview" / "game" / "GameSurfaceView.java")
        self.assertIn("extends SurfaceView", layer)
        # Sublayer -1: above Qt's own QtSurface (built with
        # setZOrderMediaOverlay(false), sublayer -2) and still below this
        # window, so the pause menu, cheats sheet and on-screen controls keep
        # drawing over the game. setZOrderOnTop would hide all three.
        self.assertIn("setZOrderMediaOverlay(true)", layer)
        code = re.sub(r"/\*.*?\*/", "", layer, flags=re.S)
        self.assertNotIn("setZOrderOnTop(", code)
        # A background on the layer clears PFLAG_SKIP_DRAW, which moves the
        # transparent hole punch into draw() and repaints it away.
        self.assertNotIn("setBackgroundColor", layer)
        host = _read(ROOT / "unified-android" / "src" / "com" / "thorium" /
                     "preview" / "game" / "InWindowGameHost.java")
        build = host.split("private void buildUi()", 1)[1].split(
            "private FrameLayout.LayoutParams match()", 1)[0]
        self.assertIn("session instanceof NativeAdapterEngineSession", build)
        self.assertIn("new GameSurfaceView(activity)", build)
        # Frame generation owns opaque output for every engine. Keeping all
        # gameplay on a distinct layer makes cadence evidence identify the
        # actual game rather than the Qt/HWUI parent window.
        self.assertNotIn("new GameSurface(activity)", build)
        # The session must be built before the views, or the host cannot know
        # which surface this game needs.
        attach = host.split("private void attach()", 1)[1].split(
            "private boolean sameRequest", 1)[0]
        self.assertLess(attach.index("EngineSessionRegistry.create"),
                        attach.index("buildUi();"))

    def test_phase3_layer_is_curtained_until_the_guest_advances(self):
        # The layer punches a transparent hole through the window, so before
        # the engine publishes a buffer the hole shows the still-attached Qt
        # library rather than the neutral black a launch should look like.
        host = _read(ROOT / "unified-android" / "src" / "com" / "thorium" /
                     "preview" / "game" / "InWindowGameHost.java")
        self.assertIn("setFirstFrameCallback(this::dismissLaunchCurtain)", host)
        self.assertIn("launchCurtain.setBackgroundColor(Color.BLACK);", host)
        # Cemu exports no FPS hook, so the shared presentation layer must also
        # drop the curtain on its first consumed producer buffer. A timer is
        # not evidence: it exposed an empty Surface while large titles booted.
        self.assertIn("layer.setFirstSubmittedFrameListener("
                      "this::dismissLaunchCurtain);", host)
        self.assertNotIn("LAUNCH_CURTAIN_MAX_MS", host)
        self.assertIn("void setFirstFrameCallback(Runnable callback)", SESSION)
        # Fired on the first measured non-zero frame rate, and deliberately not
        # subject to the two-second log throttle.
        speed = SESSION.split("private void reportEngineSpeed", 1)[1].split(
            "private void renderLoop", 1)[0]
        self.assertIn("awaitingFirstFrame && fps > 0.0", speed)

    def test_phase3_launch_identity_never_streams_the_whole_game_image(self):
        self.assertIn("String gameIdentity = launchIdentity(request, game);", SESSION)
        identity = SESSION.split("private static String launchIdentity", 1)[1]
        self.assertIn("file.getCanonicalPath()", identity)
        self.assertIn("file.length()", identity)
        self.assertLess(identity.index("file.length()"),
                        identity.index("private static String contentSha256Short"))
        self.assertIn('"aps3e".equals(entry.id)', SESSION)
        self.assertNotIn("sha256Short(game)", SESSION)

    def test_aps3e_stop_does_not_kill_the_process(self):
        policy = _read(ROOT / "unified-android" / "src" / "com" / "thorium" /
                       "lucent" / "emulators" / "NativeAdapterStopPolicy.java")
        self.assertIn("public static boolean reportsQuickResume(", policy)
        self.assertIn("public static boolean destroyNativeHostOnStop(", policy)
        self.assertIn("!isAps3e(engineId)", policy)
        self.assertIn("Retaining aPS3e native host after library return", SESSION)
        self.assertIn("marker=aps3e-stop-no-kill", SESSION)
        self.assertIn(
            "NativeAdapterStopPolicy.reportsQuickResume(", SESSION)
        self.assertIn("retireHost(entry.id)", SESSION)
        stop = SESSION.split("public void stop(StopReason reason", 1)[1].split(
            "private byte[] serializeQuickResumeOnRenderThread", 1)[0]
        self.assertNotIn("closeHost();", stop)

    def test_phase3_surface_detach_waits_for_the_render_owner(self):
        # A SurfaceView disconnects its Surface as soon as surfaceDestroyed
        # returns, so the UI thread has to know no frame is in flight.
        self.assertIn("void detachSurfaceAndWait()", SESSION)
        detach = SESSION.split("void detachSurfaceAndWait()", 1)[1].split(
            "@Override public void prepare", 1)[0]
        self.assertIn("surface = null;", detach)
        self.assertIn("runOnRenderThread", detach)
        host = _read(ROOT / "unified-android" / "src" / "com" / "thorium" /
                     "preview" / "game" / "InWindowGameHost.java")
        destroyed = host.split("public void onSurfaceDestroyed()", 1)[1].split(
            "@Override public void onSessionReady", 1)[0]
        self.assertIn(
            "((NativeAdapterEngineSession) current).detachSurfaceAndWait();",
            destroyed)


if __name__ == "__main__":
    unittest.main()
