import hashlib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HOST = ROOT / "unified-android" / "src" / "com" / "thorium" / "preview" / "game" / "InWindowGameHost.java"
THEME = ROOT / "theme" / "theme.qml"
COMMAND = ROOT / "unified-android" / "src" / "com" / "thorium" / "lucent" / "metadata" / "MetadataGameLaunchCommand.java"
BRIDGE = ROOT / "android-companion" / "src" / "com" / "thorium" / "preview" / "InProcessGameLaunchCommand.java"
PATCHER = ROOT / "unified-android" / "tools" / "patch_main_activity_right_stick.py"
GLES_SESSION = ROOT / "unified-android" / "src" / "com" / "thorium" / "preview" / "game" / "PpssppGlesEngineSession.java"
GLES_LOOP = ROOT / "unified-android" / "src" / "com" / "thorium" / "preview" / "ExperimentalGlesRenderLoop.java"
PREVIEW = ROOT / "android-companion" / "src" / "com" / "thorium" / "preview" / "PreviewActivity.java"


class InWindowInstantReturnTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = HOST.read_text(encoding="utf-8")

    def method(self, start: str, end: str) -> str:
        return self.source.split(start, 1)[1].split(end, 1)[0]

    def test_pause_buttons_do_not_consume_first_touch_for_focus(self):
        button = self.method("private Button menuButton(String label)",
                             "private LinearLayout.LayoutParams rowParams")
        self.assertIn("button.setFocusable(true);", button)
        self.assertIn("button.setFocusableInTouchMode(false);", button)
        self.assertNotIn("button.setFocusableInTouchMode(true);", button)

    def test_landscape_pause_menu_scrolls_exit_into_view(self):
        menu = self.source.split("private FrameLayout createPauseOverlay()", 1)[1].split(
            "return overlay;", 1)[0]
        self.assertIn("ScrollView scroller = new ScrollView(activity);", menu)
        self.assertIn("scroller.addView(panel", menu)
        self.assertIn("overlay.addView(scroller, menuParams)", menu)
        self.assertIn("ViewGroup.LayoutParams.MATCH_PARENT, Gravity.CENTER", menu)
        self.assertNotIn("overlay.addView(panel", menu)

    def test_full_game_focus_target_does_not_tint_video(self):
        build = self.method("private void buildUi()", "private FrameLayout.LayoutParams match()")
        self.assertIn("root.setDefaultFocusHighlightEnabled(false);", build)

    def test_theme_is_frozen_while_runtime_return_is_changed(self):
        # Re-pinned after completing the emulator-route Settings flow. Each
        # system now exposes an Automatic default row that clears its explicit
        # override, reads the backend's resolved route, and reports failures
        # without duplicating EngineRouteStore's policy in QML. The existing
        # missing-box-art review remains part of this frozen theme. Later
        # reviewed changes added the library-driven emulator inventory and the
        # default-on, dual-display video screensaver. The screensaver now owns
        # a source-deduplicated shuffled deck, dual upper crossfade players and
        # read-only game metadata chrome; gameplay navigation remains unchanged.
        # The owner subsequently replaced the old global Boolean with explicit
        # Off / Built-in (Alpha) / LSFG choices and required upgrades to reset
        # to strict Off. It still does not alter the in-game return flow.
        # The screensaver completion watchdog is also reviewed here: it advances
        # held EndOfMedia frames without enabling video looping.
        # The reviewed raised-hand feedback control and its transcript sheet
        # are library chrome only; they do not alter in-game return ordering.
        # User-visible branding now consistently says EmuFusion; compatibility
        # identifiers and return mechanics remain unchanged.
        # The default-on built-in widescreen selector is library chrome and a
        # pre-launch core preference; it does not alter return ordering.
        # Preview video sound now defaults Off with an explicit persistent
        # Settings toggle; that library-only audio preference does not alter
        # the in-window gameplay lifecycle either.
        # The Settings sheet gained slot 23, WIDESCREEN HACK (a persisted
        # pre-launch core preference served by settings/widescreen-hack); it is
        # library chrome and does not alter the in-window return flow.
        # EmuFusion 3.2.18/3.2.19 renamed the package and bumped the version
        # label; the version text now prefers the installed versionName from
        # the updater status. Those are library chrome only and do not alter
        # the in-window return flow.
        # The pin exists so unrelated runtime-return work cannot alter the theme
        # unnoticed.
        self.assertEqual(
            hashlib.sha256(THEME.read_bytes()).hexdigest(),
            "3e7f0c8110313d00668a6bd9a6e41d38e36527414d854b972da4f1e683023bfb",
        )

    def test_no_preparing_or_saving_interstitial_is_visible(self):
        self.assertNotIn('setText("Preparing ', self.source)
        self.assertNotIn('setText("Saving and returning', self.source)
        build = self.method("private void buildUi()", "private FrameLayout.LayoutParams match()")
        self.assertIn("status.setVisibility(View.GONE);", build)

    def test_library_returns_before_background_stop_commit(self):
        exit_method = self.method(
            "private void exitToLibrary(String reason)", "private void returnToLibraryUi(long"
        )
        self.assertLess(
            exit_method.index("RETIRING_SESSIONS.add(ending)"),
            exit_method.index("returnToLibraryUi(returnStartedUptimeMs, renderQuiesced);"),
        )
        self.assertLess(
            exit_method.index("ending.quiesceForExit();"),
            exit_method.index("returnToLibraryUi(returnStartedUptimeMs, renderQuiesced);"),
        )
        self.assertLess(
            exit_method.index("returnToLibraryUi(returnStartedUptimeMs, renderQuiesced);"),
            exit_method.index("ending.stop("),
        )
        restore = self.method(
            "private void returnToLibraryUi(long", "private synchronized void finishRetiringSession"
        )
        self.assertIn("revealLibraryOverRetiringSurface();", restore)
        self.assertIn("if (renderQuiesced)", restore)
        self.assertIn("detachViews();", restore)
        self.assertIn("if (active == this) active = null;", restore)

    def test_quiesced_surface_detaches_before_checkpoint_with_safe_fallback(self):
        exit_method = self.method(
            "private void exitToLibrary(String reason)", "private void returnToLibraryUi(long"
        )
        self.assertLess(
            exit_method.index("ending.quiesceForExit();"),
            exit_method.index("returnToLibraryUi(returnStartedUptimeMs, renderQuiesced);"),
        )
        reveal = self.method(
            "private void revealLibraryOverRetiringSurface()", "@Override public void onSurfaceAvailable"
        )
        self.assertIn("child.bringToFront();", reveal)
        self.assertNotIn("content.removeView(root)", reveal)
        finish = self.method(
            "private synchronized void finishRetiringSession", "private void destroyNow()"
        )
        self.assertIn("mainHandler.post", finish)
        self.assertIn("detachViews();", finish)

    def test_gles_exit_barrier_precedes_snapshot_and_late_error_cannot_poison_it(self):
        session = GLES_SESSION.read_text(encoding="utf-8")
        loop = GLES_LOOP.read_text(encoding="utf-8")
        quiesce = session.split(
            "@Override public void quiesceForExit()", 1
        )[1].split("@Override public boolean dispatchKeyEvent", 1)[0]
        self.assertIn("active.pauseAndWait();", quiesce)
        stop = session.split("@Override public void stop", 1)[1].split(
            "@Override public void release", 1
        )[0]
        self.assertLess(
            stop.index("active.pauseAndWait();"),
            stop.index("saveQuickResume(true)"),
        )
        error = session.split("@Override public void onError", 1)[1].split(
            "prepared = false;", 1
        )[0]
        self.assertIn("if (stopping.get() || released.get())", error)
        barrier = loop.split("public void pauseAndWait()", 1)[1].split(
            "public void setJoypadButton", 1
        )[0]
        self.assertIn("call(() ->", barrier)
        self.assertIn("resumeRequested = false;", barrier)
        self.assertIn("host.pause();", barrier)

    def test_qt_library_stays_warm_and_is_not_lifecycle_restarted(self):
        self.assertNotIn("invokeQtDelegateLifecycle", self.source)
        self.assertNotIn("suspendQtRenderer", self.source)
        self.assertNotIn("resumeQtRenderer", self.source)
        attach = self.method("private void attach()", "private boolean sameRequest")
        self.assertNotIn("child.setVisibility(View.INVISIBLE);", attach)
        self.assertIn("Keep the Qt SurfaceView attached, visible", attach)
        build = self.method("private void buildUi()", "private FrameLayout.LayoutParams match()")
        self.assertIn("root.setBackgroundColor(Color.BLACK);", build)
        # Every engine receives the same full physical Surface.  The running
        # emulator's live video geometry is authoritative, so the host must not
        # pre-shape a Surface from a system-wide aspect-ratio guess.
        self.assertIn("session instanceof NativeAdapterEngineSession", build)
        self.assertNotIn("PresentationGeometry.systemDisplayAspect", build)
        self.assertGreaterEqual(build.count("layer.setDisplayAspect(0f);"), 2)
        detach = self.method("private void detachViews()", "private void onSurfaceAvailable")
        self.assertIn("child.setVisibility(libraryVisibility.get(index));", detach)

    def test_generator_startup_failure_cannot_leave_loading_curtain_forever(self):
        build = self.method("private void buildUi()", "private FrameLayout.LayoutParams match()")
        surface = (ROOT / "unified-android" / "src" / "com" / "thorium" /
                   "preview" / "game" / "GameSurfaceView.java").read_text(
                           encoding="utf-8")
        self.assertIn("public boolean usesDirectPresentation()", surface)
        self.assertIn("using direct presentation", surface)
        self.assertIn("session.setFirstFrameCallback(() ->", build)
        self.assertIn("if (layer.usesDirectPresentation()) dismissLaunchCurtain();", build)
        self.assertIn("setFirstSubmittedFrameListener(this::dismissLaunchCurtain)", build)

    def test_generator_startup_runs_off_the_ui_thread(self):
        """surfaceChanged runs inside the pre-draw traversal; a synchronous
        generator startup there froze the frontend 3-9 s and raised an ANR
        over live gameplay (2026-09-03).  Startup must run on a worker and
        the engine must receive its Surface from the UI thread afterwards."""
        surface = (ROOT / "unified-android" / "src" / "com" / "thorium" /
                   "preview" / "game" / "GameSurfaceView.java").read_text(
                           encoding="utf-8")
        changed = surface.split("public void surfaceChanged(", 1)[1].split(
            "private void startGeneratorAsync(", 1)[0]
        self.assertRegex(changed, r"if \(first && launchMode != FrameGenerationSettings.Mode.OFF &&\s*!startupFellBackToDirect\) \{")
        self.assertIn("startGeneratorAsync(holder.getSurface(), width, height);", changed)
        self.assertIn("if (generatorStartupPending) {", changed)
        started = surface.split("private void startGeneratorAsync(", 1)[1].split(
            "private void finishGeneratorStartup(", 1)[0]
        self.assertIn("GENERATOR_STARTUP.execute(() -> {", started)
        self.assertIn("createGenerator(output, width, height);", started)
        self.assertIn("mainHandler.post(() -> finishGeneratorStartup(generation, output,", started)
        finished = surface.split("private void finishGeneratorStartup(", 1)[1].split(
            "public void surfaceDestroyed(", 1)[0]
        # An owner-requested switch to Direct (frame generation Off) also
        # cancels an in-flight startup; the original three guards remain.
        self.assertRegex(
            finished,
            r"if \(generation != surfaceGeneration \|\| !surfaceLive \|\| runtimePresentationFailed \|\|"
            r"\s*ownerRequestedDirect\) \{")
        self.assertIn("retireCancelledStartup(problem);", finished)
        retirement = surface.split("private void retireCancelledStartup(", 1)[1].split(
            "public void surfaceDestroyed(", 1)[0]
        self.assertIn("GENERATOR_STARTUP.execute(() -> {", retirement)
        self.assertIn("if (cancelled != null) cancelled.close();", retirement)
        self.assertIn("listener.onSurfaceAvailable(engineSurface, pendingWidth, pendingHeight);", finished)
        destroyed = surface.split("public void surfaceDestroyed(", 1)[1].split(
            "private void createGenerator(", 1)[0]
        self.assertIn("++surfaceGeneration;", destroyed)
        # Admission can reopen in the acknowledgement callback, never in the
        # synchronous destroy prefix while the producer still owns its input.
        self.assertNotIn("generatorStartupPending = false;",
                         destroyed.split("listener.retireSurfaceRenderer", 1)[0])
        self.assertIn("failure -> mainHandler.post", destroyed)
        self.assertIn("if (!generatorStartupPending) releaseGenerator();", destroyed)

    def test_lsfg_startup_retry_is_bounded_and_falls_open(self):
        surface = (ROOT / "unified-android" / "src" / "com" / "thorium" /
                   "preview" / "game" / "GameSurfaceView.java").read_text(
                           encoding="utf-8")
        qualification = surface.split(
            "if (qualification != null)", 1
        )[1].split(
            "FrameGenerationBackendPolicy.Selection selection", 1
        )[0]
        self.assertIn("for (int attempt = 1; attempt <= 2; ++attempt)", qualification)
        self.assertIn("retrying with a clean transport", qualification)
        self.assertIn("unavailable after bounded retry", qualification)
        # An ordinary rejection may return Direct after complete retirement;
        # unresolved Surface ownership may neither retry nor hand it to anyone.
        self.assertIn("using exact direct Surface", qualification)
        self.assertIn("useDirectAfterUnavailableLsfg(output)", qualification)
        self.assertIn("retireFailedGenerator(failure)", qualification)
        self.assertIn("if (SurfaceOwnershipException.isUnsafe(failure)) throw failure;", qualification)
        self.assertNotIn("selecting the built-in generator", qualification)

    def test_real_menu_launch_does_not_restart_the_qt_activity_lifecycle(self):
        command = COMMAND.read_text(encoding="utf-8")
        bridge = BRIDGE.read_text(encoding="utf-8")
        patcher = PATCHER.read_text(encoding="utf-8")
        self.assertIn('return "am start -a', command)
        self.assertNotIn('return "am broadcast', command)
        self.assertIn("org.pegasus_frontend.android.MainActivity", command)
        self.assertIn("LucentApplication.currentMainActivity()", bridge)
        self.assertIn("activity.runOnUiThread", bridge)
        self.assertIn("InWindowGameHost.handleIntent(activity, request)", bridge)
        self.assertNotIn("startActivity(", bridge)
        self.assertIn("InProcessGameLaunchCommand;->tryLaunch", patcher)

    def test_retiring_session_has_strong_owner_and_native_release_is_off_ui(self):
        self.assertIn("private static final Set<EngineSession> RETIRING_SESSIONS", self.source)
        self.assertIn("private static final ExecutorService RETIREMENT_RELEASES", self.source)
        finish = self.method(
            "private synchronized void finishRetiringSession", "private void destroyNow()"
        )
        self.assertIn("RETIRING_SESSIONS.remove(ending);", finish)
        self.assertLess(finish.index("releaseSessionWhenComplete(ending, () ->"),
                        finish.index("RETIRING_SESSIONS.remove(ending);"))
        # Completion hops back to the UI thread, where adapters that cannot
        # reuse the process begin a clean frontend restart and every other
        # engine restores pending recreations.
        completion = finish.split("releaseSessionWhenComplete(ending, () ->", 1)[1].split(
            "dispatchQtTerminalShutdownIfReady();", 1)[0]
        self.assertLess(completion.index("RETIRING_SESSIONS.remove(ending);"),
                        completion.index("mainHandler.post(() -> {"))
        posted = completion.split("mainHandler.post(() -> {", 1)[1]
        self.assertIn("if (requiresCleanFrontendRestart()) beginCleanFrontendRestart();", posted)
        self.assertIn("else restorePendingRecreations();", posted)
        self.assertNotIn("activity.runOnUiThread", finish)

    def test_late_save_failures_cleanup_without_reopening_game_overlay(self):
        error = self.method(
            "@Override public void onSessionError", "@Override public void onSessionStopRejected"
        )
        rejected = self.method(
            "@Override public void onSessionStopRejected", "@Override public void onRestoreAvailabilityChanged"
        )
        for callback in (error, rejected):
            self.assertIn("if (libraryReturned)", callback)
            self.assertIn("finishRetiringSession(retiringSession", callback)
            before_return = callback.split("return;", 1)[0]
            self.assertNotIn("status.setVisibility(View.VISIBLE)", before_return)

    def test_launch_a_up_cannot_dismiss_a_prepare_failure(self):
        handler = self.method("private boolean handleKeyEvent", "private boolean handleMotionEvent")
        fatal = handler.split("if (fatalErrorVisible)", 1)[1].split("return true;", 1)[0]
        self.assertNotIn("KEYCODE_BUTTON_A", fatal)
        self.assertNotIn("KEYCODE_DPAD_CENTER", fatal)
        self.assertIn('exitToLibrary("fatal-back-key")', handler)
        self.assertIn('new Throwable("Lucent exit origin")', self.source)
        self.assertIn('Log.e(TAG, "Engine session error engine="', self.source)

    def test_stale_menu_metadata_cannot_route_to_an_unpackaged_core(self):
        request = self.method("private static GameLaunchRequest requestFrom", "private void attach()")
        self.assertIn("InternalEngineCatalog.byId(activity, engine)", request)
        self.assertIn("Phase2QualificationCatalog.byId(activity, engine)", request)
        self.assertIn("phaseOne != null && phaseOne.supports(system)", request)
        self.assertIn("phaseTwo != null && phaseTwo.supports(system)", request)
        # Phase 3 in-process native adapters are gated by their own fail-closed
        # catalog, so the approval expression covers all three catalogs.
        self.assertIn("NativeAdapterCatalog.byId(activity, engine)", request)
        self.assertIn("phaseThree != null && phaseThree.supports(system)", request)
        self.assertIn(
            "if (!approvedPhaseOne && !approvedPhaseTwo && !approvedPhaseThree)",
            request)
        self.assertIn("Rejected stale/unpackaged engine route", request)

    def test_every_teardown_route_quiesces_before_surface_detach(self):
        # The 818adab8 stop race was fixed in exitToLibrary alone; destroyNow
        # and replaceWith kept the original surface-detach-before-pause
        # ordering. Every teardown owner must quiesce first, and release()
        # (which joins engine threads) must stay off the UI thread.
        destroy = self.method("private void destroyNow()", "private void detachViewsAfterDestroyStop")
        self.assertIn("ending.quiesceForExit();", destroy)
        self.assertLess(
            destroy.index("ending.quiesceForExit();"),
            destroy.index("detachViews();"),
        )
        self.assertNotIn("ending.release();", destroy)
        self.assertIn("releaseDestroyedSession(ending);", destroy)
        release = self.method("private void releaseDestroyedSession", "private void detachViews()")
        self.assertLess(release.index("RETIREMENT_RELEASES.execute(() ->"),
                        release.index("ending.release();"))
        replace = self.method(
            "private void replaceWith(GameLaunchRequest next)", "private void buildUi()"
        )
        self.assertIn("ending.quiesceForExit();", replace)
        self.assertIn("else releaseSessionWhenComplete(ending, released);", replace)
        self.assertLess(replace.index("Runnable released = () ->"),
                        replace.index("RETIRING_SESSIONS.remove(ending);"))

    def test_tap_select_press_is_latched_across_frame_polls(self):
        # Cores sample the joypad once per retro_run; a same-timestamp
        # down/up pair is invisible to them and breaks the tap-vs-hold
        # contract for the Thor Stop/Select button.
        stop = self.method("private boolean handleStopButton", "private void showPauseMenu()")
        self.assertIn("TAP_SELECT_HOLD_MS", stop)
        self.assertIn("mainHandler.postDelayed", stop)
        self.assertIn("if (session == target) target.dispatchKeyEvent(up);", stop)
        self.assertIn("private static final long TAP_SELECT_HOLD_MS", self.source)

    def test_gles_stop_error_still_requires_actual_native_close(self):
        session = GLES_SESSION.read_text(encoding="utf-8")
        stop = session.split("@Override public void stop(StopReason reason", 1)[1]
        stop = stop.split("@Override public void release()", 1)[0]
        # A save/pause failure still attempts native close, but must not release
        # the host's retirement/Qt gate until the close actually acknowledges.
        self.assertIn("} catch (Throwable failure) {", stop)
        stop_body = stop.split("private void closeForStop(", 1)[0]
        catch_block = stop_body.split("} catch (Throwable failure) {", 1)[1]
        self.assertIn("closeForStop(renderLoop);", catch_block)
        self.assertNotIn("completion.complete();", catch_block)
        close = stop.split("private void closeForStop(", 1)[1].split(
            "private void completeStop(", 1)[0]
        self.assertIn("closing.closeWhenComplete(() -> completeStop(closing));", close)
        self.assertNotIn("completeStop(", close.split("catch (Throwable failure)", 1)[1])
        self.assertIn("onSessionStopRejected(", stop)

    def test_destroy_defers_view_detach_until_stop_completion(self):
        # Activity destroy must not detach the game views while the final
        # ACTIVITY_DESTROYED checkpoint still serializes against them; the
        # bounded fallback keeps a completion that never fires from leaking
        # the destroyed Activity's view tree.
        destroy = self.method("private void destroyNow()", "private void detachViews()")
        self.assertIn("detachViewsAfterDestroyStop(ending);", destroy)
        self.assertIn(
            "mainHandler.postDelayed(detachOnce, DESTROY_DETACH_FALLBACK_MS);", destroy
        )
        completion = destroy.split("StopReason.ACTIVITY_DESTROYED", 1)[1]
        self.assertIn("releaseOnce.run();", completion)
        self.assertIn("releaseStarted.compareAndSet(false, true)", destroy)
        self.assertIn("RETIREMENT_RELEASES.execute(() ->", destroy)
        self.assertIn("mainHandler.post(detachOnce);", completion)
        self.assertIn("private static final long DESTROY_DETACH_FALLBACK_MS", self.source)

    def test_texture_destroy_waits_for_bounded_gles_detach(self):
        # TextureView releases its Surface as soon as the destroy callback
        # returns, but the GLES detach is posted to the render thread. The
        # host must wait for the session's bounded synchronous detach or a
        # queued swap lands on the dead surface (EGL_BAD_SURFACE 0x300d).
        destroyed = self.method(
            "@Override public void onSurfaceDestroyed()",
            "@Override public void onSessionReady()",
        )
        self.assertIn("detachSurfaceAndWait();", destroyed)
        session = GLES_SESSION.read_text(encoding="utf-8")
        wait = session.split("void detachSurfaceAndWait()", 1)[1].split(
            "@Override public void onSecondarySurfaceAvailable", 1
        )[0]
        self.assertIn("active.detachSurfaceAndWait()", wait)
        loop = GLES_LOOP.read_text(encoding="utf-8")
        self.assertIn(
            "private static final long SURFACE_DETACH_WAIT_MILLIS = 250L;", loop
        )
        self.assertIn("public boolean detachSurfaceAndWait()", loop)
        bounded = loop.split("private boolean awaitDetach(Runnable detach)", 1)[1].split(
            "public void resume()", 1
        )[0]
        self.assertIn(
            "finished.await(SURFACE_DETACH_WAIT_MILLIS, TimeUnit.MILLISECONDS)", bounded
        )

    def test_background_resume_waits_for_a_fresh_gameplay_surface(self):
        pause = self.method(
            "public static synchronized void onPause(Activity activity)",
            "public static synchronized void onDestroy(Activity activity)",
        )
        self.assertLess(pause.index("current.pause("),
                        pause.index("active.detachCurrentSurface(current);"))
        self.assertIn("active.surfaceAvailable = false;", pause)
        self.assertIn("active.gameSurface.setVisibility(View.INVISIBLE);", pause)

        resume = self.method(
            "public static synchronized void onResume(Activity activity)",
            "public static synchronized void onPause(Activity activity)",
        )
        self.assertIn("active.gameSurface.setVisibility(View.VISIBLE);", resume)
        self.assertIn("active.attachSurfaceListener();", resume)
        self.assertIn("active.surfaceAvailable", resume)

        available = self.method(
            "@Override public void onSurfaceAvailable(Surface surface, int width, int height)",
            "@Override public void onSurfaceSizeChanged(int width, int height)",
        )
        self.assertLess(available.index("current.attachSurface(surface, width, height);"),
                        available.index("current.resume();"))
        self.assertIn("surface != null && surface.isValid()", available)

    def test_lower_display_removal_waits_for_bounded_swapchain_detach(self):
        # PreviewActivity removes the lower SurfaceView right after the
        # destroyed notification; the session must therefore detach its
        # swapchain synchronously (bounded) inside that notification.
        session = GLES_SESSION.read_text(encoding="utf-8")
        destroyed = session.split(
            "@Override public void onSecondarySurfaceDestroyed()", 1
        )[1].split("@Override public void onSecondaryTouch", 1)[0]
        self.assertIn("detachSecondarySurfaceAndWaitBounded()", destroyed)
        loop = GLES_LOOP.read_text(encoding="utf-8")
        self.assertIn("public boolean detachSecondarySurfaceAndWaitBounded()", loop)
        preview = PREVIEW.read_text(encoding="utf-8")
        leave = preview.split("private void leaveGameplaySurface(", 1)[1]
        self.assertLess(
            leave.index("SecondaryGameplaySurfaceRouter.surfaceDestroyed("),
            leave.index("root.removeView(existing);"),
        )

    def test_preview_destroy_survives_the_primary_display_reject_path(self):
        # The display-0 reject path finishes before registerReceiver runs;
        # onDestroy must not crash on the unregistered receiver and media
        # teardown must still execute.
        preview = PREVIEW.read_text(encoding="utf-8")
        self.assertIn("private boolean receiverRegistered;", preview)
        destroy = preview.split("protected void onDestroy()", 1)[1].split(
            "private final class PlayerSlot", 1
        )[0]
        self.assertIn("if (receiverRegistered) unregisterReceiver(receiver);", destroy)
        self.assertIn("finally {", destroy)
        self.assertIn("leaveGameplaySurface(false);", destroy)
        self.assertIn("stopPlayers();", destroy)
        players = preview.split("private void stopPlayers()", 1)[1].split(
            "private void applySoundEnabled", 1
        )[0]
        self.assertIn("if (slots == null) return;", players)

    def test_phase1_exit_save_failure_is_visible_not_swallowed(self):
        session = (ROOT / "unified-android" / "src" / "com" / "thorium" /
                   "preview" / "game" / "LibretroEngineSession.java").read_text(encoding="utf-8")
        save = session.split("private void saveQuickResume(boolean waitForCommit", 1)[1]
        save = save.split("private void restore(", 1)[0]
        self.assertNotIn("catch (Throwable ignored)", save)
        self.assertIn("marker=save-failure", save)
        self.assertIn("onSessionStopRejected(", save)


if __name__ == "__main__":
    unittest.main()
