import QtQuick 2.9
import QtMultimedia 5.9
import QtGraphicalEffects 1.0
import SortFilterProxyModel 0.2

FocusScope {
    id: root
    focus: true
    width: 1920
    height: 1080

    readonly property string lucentVersion: "3.2.17"

    // ---- Vertical envelope ------------------------------------------------
    // Android used to reserve the bottom 55 px of the panel for its navigation
    // bar, so every view was authored against a 1025 px floor. The theme now
    // owns the whole display. The floor is stated once, here, and each view
    // measures against it instead of carrying its own copy: if the usable
    // height moves again the views re-proportion rather than leaving a dead
    // band under the last row.
    // One inset, used on every edge. The header bar sits 34px down from the
    // top, so 34 is what the bottom owes as well: an 11px bottom against a
    // 34px top is the mismatch that made the reclaimed strip read as a
    // leftover gap rather than as margin. Anything that wants to hug an edge
    // measures from here, so the frame stays even the whole way round.
    readonly property real screenMargin: 34
    readonly property real footerFontSize: 15
    // The legend is the bottom edge's counterpart to the clock and battery at
    // the top, so it is toned against the same wash rather than darker than it.
    // At #7f899c it measured 137 luma against a 128 luma wallpaper -- 1.08:1,
    // which is not a reading contrast, it is camouflage. The top bar reads at
    // 209 luma over the same wash; this lands between the two, bright enough to
    // read on light artwork and still plainly secondary to the titles.
    readonly property color footerColor: "#b6bfd0"
    // Legends line up with the header bar rather than sitting 6 px further in.
    readonly property real footerSideMargin: 56
    readonly property real footerLineHeight: Math.round(footerFontSize * 1.4)
    // The instruction strip is drawn straight onto the wallpaper -- no plate,
    // and no opaque gradient behind it either -- exactly like the clock and
    // battery at the top, which is the treatment this has to match.
    readonly property real footerY: height - footerLineHeight - screenMargin
    // Right edge of the labels at the left end of the footer line. The button
    // legends are right-aligned and only shrink when they would run into
    // these (narrow phone windows); where they fit they render unchanged.
    readonly property real footerLegendLeft: Math.max(
            footerViewName.visible ? footerViewName.x + footerViewName.paintedWidth : 0,
            coverNavigationHint.visible ?
                coverNavigationHint.x + coverNavigationHint.paintedWidth : 0) + 36
    // Nothing that scrolls, or that grows under selection, may cross this.
    // The content-to-footer gap is deliberately tighter than the outer margin:
    // the footer is a label on the frame, not a panel, so crowding it slightly
    // costs nothing and hands the difference back to the artwork.
    readonly property real contentBottom: footerY - Math.round(screenMargin * 0.4)

    property string page: "home"
    // 0 systems; 1 continue; 2 most played; 3 recently added;
    // 4 critic; 5 user; 6 A-Z; 7 release.
    property int homeZone: 0
    property bool previewReady: false
    property double previewRequestSequence: Date.now()
    property double currentBottomPreviewSequence: 0
    property var currentBottomPreviewGame: null
    property bool launchPollPending: false
    property bool applicationWasActive: false
    // True while a game owns the screen. The frontend cannot work this out on
    // its own: in-window gameplay adds its view to the SAME Activity and keeps
    // the Qt window warm, so Qt.application.state stays ApplicationActive. The
    // companion reports it on /heartbeat instead. Every poller below stands
    // down while this is set -- each poll is a fresh TCP connection (the
    // companion answers Connection: close), and thousands of them during a
    // session both steal CPU from the emulator and, at ~10 sockets/second,
    // crashed the process in Qt's own network thread mid-game.
    property bool gameplayActive: false
    property int previewHeartbeatSequence: 0
    property int previewHeartbeatAppliedSequence: 0
    onGameplayActiveChanged: handleGameplayActiveChanged()

    function handleGameplayActiveChanged() {
        console.warn("EmuFusion frontend gameplay=" + gameplayActive +
                     " qtApplicationState=" + Qt.application.state)
        if (gameplayActive) {
            // Clearing ordinary PIP sources is insufficient: an already-active
            // screensaver owns two other Qt video textures and queued callbacks.
            stopScreensaver(false)
        } else {
            screensaverTopStillSince = Date.now()
            Qt.callLater(function() { root.refreshCurrentPreview() })
        }
    }
    // Capability detection keeps physical lower-display playback exclusive to
    // dual-screen hardware. Single-screen devices use the in-theme PIP below.
    property bool dualScreenDevice: true
    property string previewPlacementMode: "auto" // auto, bottom, top, off
    // Preview movies are silent until the user explicitly enables their sound
    // in Settings. This does not affect menu sound effects or game audio.
    property bool previewSoundEnabled: false
    property bool privateDiagnosticsConfigured: false
    property bool privateDiagnosticsEnabled: false
    property bool privateDiagnosticsPending: false
    property bool soundEffectsEnabled: true
    // Explicit and fail-closed. No legacy Boolean is allowed to silently turn
    // an experimental renderer back on after an update.
    property string frameGenerationMode: "off"
    // The displayed value is committed Android state, never an optimistic UI
    // guess. A launch requested while a write/status read is in flight waits
    // for the service acknowledgement.
    property bool frameGenerationModePending: false
    property bool frameGenerationModeConfirmed: false
    property string frameGenerationRequestedMode: "off"
    property int frameGenerationRequestSequence: 0
    property var frameGenerationPendingLaunch: null
    property bool screensaverEnabled: true
    property bool screensaverActive: false
    property bool screensaverRequestPending: false
    property var screensaverDeck: []
    property int screensaverDeckIndex: 0
    property var screensaverGame: null
    property var screensaverPendingGame: null
    property string screensaverSourceA: ""
    property string screensaverSourceB: ""
    property int screensaverCurrentSlot: -1
    property int screensaverPendingSlot: -1
    property int screensaverGeneration: 0
    property double screensaverTopStillSince: Date.now()
    readonly property int screensaverStillTimeoutMs: 120000
    readonly property int screensaverCrossfadeMs: 500
    // Single-screen devices can exchange the PIP and box-art columns. The
    // preference may persist across hardware, but is never applied or exposed
    // while a physical lower display is available.
    property bool singleScreenMediaSwapped: false
    // Cover View is a vertical sequence of Systems plus the seven library
    // shelves. One large row is the calm default; users can expose two or
    // three at once and can reorder the sequence without changing what each
    // shelf means.
    property int coverViewRowCount: 1
    property var coverRowOrder: [0, 1, 2, 3, 4, 5, 6, 7]
    property bool coverOrderEditorOpen: false
    property int coverOrderEditorIndex: 0

    // ---- Missing box art review -------------------------------------------
    // The companion searches every platform catalog during a maintenance scan
    // and lists the games it could find no box art for. It never acts on that
    // list: the owner answers once per game here, and the answer is stored
    // beside the media so a rescan or a reinstall never asks again. Deleting
    // the ROM is the only destructive answer and is the only one that asks
    // for a second press.
    property bool artworkReviewOpen: false
    property var artworkReviewGames: []
    property int artworkReviewIndex: 0
    // 0 leave as is, 1 remove from the menus, 2 delete the ROM file.
    property int artworkReviewChoice: 0
    property bool artworkReviewConfirming: false
    property bool artworkReviewBusy: false
    property bool artworkReviewLoaded: false
    property string artworkReviewMessage: ""
    property int artworkReviewCount: 0

    readonly property real coverContentTop: 314
    readonly property real coverContentHeight: contentBottom - coverContentTop
    readonly property real coverRowSlotHeight: coverContentHeight / coverViewRowCount
    // A shelf slot pays for its heading and its caption; whatever remains is
    // artwork. Stating both here keeps the package scale below honest about
    // how much room a cover actually has.
    readonly property real coverShelfLabelHeight: coverViewRowCount === 3 ? 34 : 44
    readonly property real coverShelfCaptionHeight: coverViewRowCount === 1 ? 104 :
                                                      (coverViewRowCount === 2 ? 84 : 66)
    // Centering reference for the shelf rails. Derived from the same formula
    // the delegate uses for the commonest package (a 135 mm case) so the
    // selected cover really lands on the middle of the display.
    readonly property real coverShelfCardWidth: Math.max(
            coverViewRowCount === 1 ? 180 : (coverViewRowCount === 2 ? 150 : 130),
            135 * coverShelfPixelsPerMillimetre() + 22)
    // System cards are the one shelf whose contents are not packages, so they
    // are sized from the slot rather than from a package dimension. They used
    // to be stated as constants -- 440x330 for a single row -- against a slot
    // that is now 697 px tall, which left a 239 px band of wallpaper under the
    // shelf: the single largest dead space on any screen, and the "awkward
    // large gap on the bottom" exactly. Height therefore comes from the slot,
    // so the shelf bottoms out on the content floor whatever the row count is.
    // The band a system shelf may occupy. One row starts below the hardware
    // photograph (which ends at y=438) and runs to the content floor; two or
    // three share the slot they are given.
    readonly property real coverSystemSelectedScale: 1.10
    readonly property real coverSystemBandTop: coverContentTop +
            (coverViewRowCount === 1 ? 128 : 0)
    readonly property real coverSystemBandHeight: coverViewRowCount === 1 ?
            contentBottom - coverSystemBandTop :
            coverRowSlotHeight - (coverViewRowCount === 2 ? 20 : 14)
    // Sized so the SELECTED card -- the one that grows -- is what lands on the
    // content floor. Dividing the band by the selection scale first is the
    // whole trick: sizing the nominal card to the band instead made the grown
    // card overhang the floor by 28 px and print itself over the legend.
    readonly property real coverSystemCardHeight:
            Math.floor(coverSystemBandHeight / coverSystemSelectedScale)
    // Centre the nominal card in the band, so the grown card fills it exactly.
    readonly property real coverSystemRailTop: coverSystemBandTop +
            Math.round((coverSystemBandHeight - coverSystemCardHeight) / 2)
    // Width follows height at the card's original 4:3 proportion, but is capped
    // so a hero shelf still reads as a rail of several systems rather than one
    // card and two slivers. Past the cap the card simply becomes squarer, which
    // the delegate handles: the wordmark is aspect-fitted inside it.
    readonly property real coverSystemCardWidth: Math.min(
            coverViewRowCount === 1 ? 540 : (coverViewRowCount === 2 ? 400 : 290),
            Math.round(coverSystemCardHeight * 4 / 3))
    // Games view cover width. Widened with the taller rail so a 135x190 mm
    // case still fills the card edge to edge at the new artwork height; one
    // fewer card is visible per screen and each is a fifth larger.
    readonly property real gameCardWidth: 296
    // System identity is intentionally static while selected. Every system
    // owns one decoded wallpaper and receives its next random wallpaper only
    // after the user leaves it. The experimental motion layer was removed
    // because decoder startup could replace the visible artwork after entry.
    property bool systemMotionEnabled: false
    property bool systemVideoStarted: false
    property string currentSystemMotionSource: ""
    property bool settingsOpen: false
    property int settingsIndex: 0
    property bool rightStickViewSwitchingEnabled: true
    property bool viewTransitionsEnabled: false
    property bool liquidGlassEnabled: false
    // Platform family means the hardware brand (Nintendo, PlayStation, Sega,
    // Xbox/Microsoft, Atari, and so on).  It is more precise than the generic
    // word "company" and remains useful when many studios published games for
    // the same console.
    // "wallpaper" resolves each game's accent from the complementary color the
    // importer already derived from its wallpaper and stored in metadata. It
    // is never computed here: browsing must cost no image work.
    property string accentGrouping: "system" // family, system, wallpaper
    property var customFamilyAccents: ({})
    property var customSystemAccents: ({})
    property bool accentEditorOpen: false
    property int accentEditorTargetIndex: 0
    property int accentEditorChannel: 0 // target, hue, saturation, lightness
    property real accentEditorHue: 0
    property real accentEditorSaturation: 0.78
    property real accentEditorLightness: 0.58
    property bool systemLedEnabled: true
    property int systemLedBrightness: 2
    // Read only by the hidden pre-3.0.40 settings markup retained below.
    property bool systemLedUseDeviceBrightness: false
    property string startViewPreference: "cover"
    property bool widescreenEnhancementsEnabled: true
    property bool widescreenEnhancementsPending: false
    // The geometry-expanding per-system hack (/settings/widescreen-hack);
    // off by default, independent of the native 16:9 flag above.
    property bool widescreenHackEnabled: false
    property bool widescreenHackPending: false
    readonly property int baseSettingsOptionCount: dualScreenDevice ? 16 : 17
    // Three rows live below the historic block, and the legal notice must stay
    // at the very bottom. The single-screen-only PIP row (slot 16) sits
    // between them and the rest, so an absolute index is no longer the same
    // thing as a slot -- settingSlot() is the one place that difference is
    // resolved, and the tail order is written down here rather than implied by
    // the slot numbers so a new row can be inserted without renumbering.
    readonly property var settingsTailSlots: [17, 21, 22, 23, 20, 19, 24, 18]
    readonly property int settingsTailCount: settingsTailSlots.length
    readonly property int settingsOptionCount:
            baseSettingsOptionCount + settingsTailCount
    // Reclaimed panel height buys another ROW, not padding: listRowCount and
    // listRowHeight decide the page size and the row stride together, so the
    // page always bottoms out flush instead of leaving a band under the last
    // row. 102 is the smallest row that still holds a title over a description
    // at a comfortable touch size.
    readonly property real settingsListTop: 152
    readonly property real settingsListSpacing: 12
    readonly property real settingsPanelHeight: root.height - 80
    readonly property real settingsListAvailable: settingsPanelHeight -
            settingsListTop - (footerLineHeight + 40)
    readonly property int settingsPageSize:
            listRowCount(settingsListAvailable, 102, settingsListSpacing)
    readonly property real settingsRowHeight:
            listRowHeight(settingsListAvailable, 102, 132, settingsListSpacing)
    readonly property int settingsPage: Math.floor(settingsIndex / settingsPageSize)

    // ---- Per-system emulator routing (Settings) ---------------------------
    // Internal is the default wherever a bundled engine exists; External is a
    // per-system choice. All state below is a cache of what /route/* reports --
    // the Java side stays the single source of truth, and every mutation is
    // followed by a re-read rather than a local guess.
    property bool emulatorRoutesOpen: false
    property int emulatorRoutesIndex: 0
    property var emulatorRouteSystems: []
    property bool emulatorRoutesLoading: false
    property string emulatorRoutesNotice: ""

    property bool emulatorPickerOpen: false
    property string emulatorPickerSystem: ""
    property string emulatorPickerLabel: ""
    property int emulatorPickerIndex: 0
    property var emulatorPickerData: null
    property var emulatorPickerRowList: []
    property string emulatorPickerNotice: ""
    property bool emulatorPickerLoading: false
    property bool emulatorPickerBusy: false

    // Both sub-screens reuse the settings panel's envelope so the three read as
    // one surface, and both size their rows with listRowHeight so the last row
    // lands on the panel floor instead of leaving a band under it.
    readonly property real routesListAvailable: settingsPanelHeight -
            settingsListTop - (footerLineHeight + 40)
    readonly property int routesRowMinimum: 92
    readonly property real routesRowHeight: listRowHeight(
            routesListAvailable, routesRowMinimum, 118, settingsListSpacing)
    readonly property int routesPageSize: listRowCount(
            routesListAvailable, routesRowMinimum, settingsListSpacing)
    readonly property int routesPage: Math.floor(emulatorRoutesIndex / routesPageSize)

    // The option and custom-setup sheets show every row at once, so their row
    // count is fixed and it is the HEIGHT that absorbs the panel: each row
    // takes an equal share, capped so a three-item list does not become three
    // slabs. When the cap bites, the block is centred rather than left hanging
    // -- a short list with even margins reads as deliberate, which a list
    // pinned to the top with a dead band beneath it does not.
    function shareRowHeight(available, count, minimum, maximum, spacing) {
        return Math.max(minimum, Math.min(maximum,
                Math.floor((available + spacing) / Math.max(1, count)) - spacing))
    }

    function centredListTop(available, count, rowHeight, spacing) {
        var block = count * rowHeight + Math.max(0, count - 1) * spacing
        return settingsListTop + Math.max(0, Math.round((available - block) / 2))
    }

    readonly property int pickerRowCount: emulatorPickerRowList.length
    readonly property real pickerRowHeight:
            shareRowHeight(routesListAvailable, pickerRowCount, 88, 150, 12)
    readonly property real pickerListTop: centredListTop(
            routesListAvailable, pickerRowCount, pickerRowHeight, 12)

    readonly property real customFormAvailable: settingsPanelHeight - 150 -
            (footerLineHeight + 40)
    readonly property int customFormRowCount: customEmulatorRowCount()
    readonly property real customRowHeight:
            shareRowHeight(customFormAvailable, customFormRowCount, 88, 132, 10)
    readonly property real customFormTop: 150 + Math.max(0, Math.round(
            (customFormAvailable - (customFormRowCount * customRowHeight +
             Math.max(0, customFormRowCount - 1) * 10)) / 2))

    property bool customEmulatorOpen: false
    property int customEmulatorIndex: 0
    property string customEmulatorPackage: ""
    property string customEmulatorActivity: ""
    property string customEmulatorDelivery: "file-path"
    property string customEmulatorKey: ""
    property var customEmulatorProblems: []
    property string customEmulatorNotice: ""
    property bool customEmulatorConfigured: false

    property bool legalOpen: false
    property string legalTitle: "Legal Notice"
    property var legalParagraphs: []
    property real legalScroll: 0
    property real legalBodyHeight: 0
    readonly property real legalViewportHeight: settingsPanelHeight - 250
    property bool searchOpen: false
    property string searchQuery: ""
    property bool searchKeyboardAccepting: false
    property bool gameActionOpen: false
    property string gameActionMode: "menu"
    property int gameActionIndex: 0
    property var gameActionGame: null
    property string gameActionMessage: ""
    // Fetched once per opening of the game options, never polled: a cheat
    // catalogue only changes when the user edits their own file, and the
    // answer is what decides whether the Cheats row is offered at all.
    property var gameActionCheats: []
    property int gameActionCheatIndex: 0
    property string gameActionCheatState: "idle"
    // Multiplayer (alpha): the roster is fetched fresh each time the panel
    // opens, and the want toggle writes optimistically -- both follow the
    // same demand-driven, never-polled rule as the cheat catalogue above.
    property bool gameActionMultiplayerWant: false
    property bool gameActionMultiplayerPending: false
    property string gameActionMultiplayerState: "idle"
    property var gameActionMultiplayerRoster: []
    property var renamedGameTitles: ({})
    property var hiddenGameIds: ({})
    // These are deliberately category-specific. Removing a behavioral item
    // from Continue, Most Played, or Recently Added must never hide that game
    // from the complete critic/user/A-Z/release library views.
    property var removedHomeCategoryGameIds: ({ "1": {}, "2": {}, "3": {} })
    property int gameActionCategory: 0
    property int libraryMutationRevision: 0
    property int singleCurrentSlot: -1
    property int singleTargetSlot: -1
    property string singleSourceA: ""
    property string singleSourceB: ""
    property string singleSourceC: ""
    property var activePreviewSlot: null
    property var homePreviewGame: null
    property var departedHomeSlot: null
    property var lastHomeGameBySystem: ({})
    property var homePreviewCandidatesBySystem: ({})
    property int lastSystemPreviewIndex: -1
    property int departedSystemIndex: -1
    property string sortMode: "user"
    property string gameViewMode: "covers"
    property string homeViewMode: "covers"
    property int homeListCategory: 1
    property int homeListFocusColumn: 1 // 0 systems, 1 category/game list
    property var homeListEntries: []
    // The row the video preview is showcasing while the system column owns
    // focus. This is deliberately NOT homeListRail.currentIndex: that property
    // also drives the list's scroll position, so storing a random showcase pick
    // in it scrolled the visible games to a different place on every system
    // change. The list must always start at the top of the selected sort.
    property int homeListPreviewIndex: -1
    property var homeListCache: ({})
    property var availableBrandSlugs: []
    property var collectionFolderMap: ({})
    property var systemGameCache: ({})
    property var libraryGameMap: ({})
    property var activeSystemGames: []
    property bool libraryIndexReady: false
    property var pendingLibraryIndex: null
    property var pendingLibraryGameMap: ({})
    property int libraryIndexBuildPosition: 0
    property bool updatePromptOpen: false
    property bool voiceFeedbackOpen: false
    property string voiceFeedbackState: "idle"
    property string voiceFeedbackTranscript: ""
    property string voiceFeedbackMessage: ""
    property int voiceFeedbackChoice: 0
    property bool voiceFeedbackGithubOpened: false
    property bool aboutOpen: false
    property int updatePromptChoice: 0
    property bool updatePromptDismissed: false
    property string updateStatusMessage: ""
    // Navigation state is durable, but QSettings writes must never run inside
    // a controller input frame. These values are flushed after interaction
    // settles; launch() still commits synchronously before leaving Pegasus.
    property bool navigationPersistencePending: false
    property string importState: "idle"
    // A recreated Qt scene polls the companion's last completed status. Treat
    // that first completed response as a silent baseline so returning from a
    // game never resurrects an old "library update complete" notification.
    property bool importStatusInitialized: false
    property real importProgress: 0
    property string importMessage: ""
    property string importDetail: ""
    property int importCurrent: 0
    property int importTotal: 0
    property var importTitles: []
    property int importIdentified: 0
    property int importAdded: 0
    property bool importNeedsReload: false
    property bool importReloadRequested: false
    property bool importToastVisible: false
    property string lastImportFingerprint: ""
    property var hardwarePhotoBySystem: []
    property int lastHardwareSystemIndex: -1
    property int upperArtworkSlot: 0
    property int upperArtworkPendingSlot: -1
    property string upperArtworkTarget: ""
    property int boxArtworkSlot: 0
    property int boxArtworkPendingSlot: -1
    property string boxArtworkTarget: ""
    property string boxArtworkSourceA: ""
    property string boxArtworkSourceB: ""
    // Capture the system that owns the open game page. Some Android controller
    // key-up events can arrive while the home ListView is losing focus; using
    // its live currentIndex after that transition can open/display a stale
    // neighboring collection.
    property int activeSystemIndex: 0
    property bool allSystemsActive: false
    property int activeGameSystemIndex: {
        // ListModel contents are dynamic. Referencing count makes this binding
        // re-evaluate after startup discovery appends the detected systems.
        var modelDependency = systemModel.count
        return systemIndexForGame(activeGame)
    }
    property int shelfDisplaySystemIndex: page === "home" && homeZone > 0 ?
            activeGameSystemIndex : -1
    readonly property bool homeListUsesAllSystemsAccent: page === "home" &&
            homeViewMode === "list" && systemRail.currentIndex === 0 &&
            homeListFocusColumn === 0
    property int displaySystemIndex: {
        // The aggregate List View owns a neutral visual identity. Its preview
        // game must never leak Nintendo/Sega/Sony/etc. color into the header,
        // category strip, lighting, or selected list row.
        if (homeListUsesAllSystemsAccent)
            return 0
        if (page === "games" && allSystemsActive && activeGameSystemIndex > 0)
            return activeGameSystemIndex
        if (page === "games")
            return activeSystemIndex
        if (shelfDisplaySystemIndex > 0)
            return shelfDisplaySystemIndex
        return systemRail.currentIndex
    }
    // All Systems represents the installed library, not whichever random game
    // happens to be supplying its preview. Keep the installed-platform logo row
    // visible while the system column owns focus; once a game is locked, the
    // header can switch to that game's individual platform brand.
    property bool showAvailableBrandRow: page === "home" &&
            systemRail.currentIndex === 0 &&
            ((homeViewMode === "covers" && homeZone === 0) ||
             (homeViewMode === "list" && homeListFocusColumn === 0))
    // Keep the highlighted home system separate from the collection backing
    // gameSortModel. Rebinding that source on every home-screen arrow forced a
    // complete proxy-model rebuild and score sort for a list that was hidden.
    property var selectedCollection: systemRail.currentIndex === 0 ? null :
            collectionNamed(systemModel.get(systemRail.currentIndex).collectionName)
    property var activeCollection: null
    // The expensive aggregate library has four persistent native indexes.
    // Individual systems stay on one small dynamic proxy, avoiding both the
    // 5,000-row re-sort on input and an excessive matrix of startup models.
    property var activeGameSortModel: {
        if (searchQuery !== "")
            return allSystemsActive ? allGamesSearchSortModel :
                                      systemGameSearchSortModel
        if (!allSystemsActive)
            return libraryIndexReady ? null : systemGameSortModel
        if (sortMode === "critic") return allCriticSortModel
        if (sortMode === "user") return allUserSortModel
        if (sortMode === "release") return allReleaseSortModel
        return allAlphaSortModel
    }
    property var activeGameModel: searchQuery === "" && !allSystemsActive && libraryIndexReady ?
            activeSystemGames : activeGameSortModel
    property int activeGameCount: searchQuery === "" && !allSystemsActive && libraryIndexReady ?
            activeSystemGames.length : (activeGameSortModel ? activeGameSortModel.count : 0)
    property var activeGame: {
        if (page === "games" && activeGameCount > 0)
            return gameAtDisplayIndex(gameRail.currentIndex)
        if (page === "home" && homeViewMode === "list")
            return homeListGameAt(homeListPreviewRow())
        if (page === "home" && homeZone > 0)
            return homeShelfGame(homeZone)
        return homePreviewGame
    }
    // The single resolved accent for the current selection. The Thor stick
    // LEDs are driven from this exact value, so they match the UI precisely in
    // every grouping mode, including the per-game wallpaper accents.
    property color accent: {
        // While the system column owns focus the chrome still belongs to the
        // collection, not to whichever game happens to supply its preview.
        if (accentGrouping === "wallpaper" && !showSystemBackdrop) {
            var wallpaperAccent = storedWallpaperAccent(activeGame)
            if (wallpaperAccent !== "") return wallpaperAccent
        }
        return systemModel.get(displaySystemIndex).accent
    }
    onAccentChanged: {
        if (systemLedEnabled) systemLedCommit.restart()
    }
    // Settings has ten entry points and no single opener, so the missing-art
    // count is fetched from the panel's own visibility. Once per launch: the
    // list only changes when a maintenance scan runs or a row is answered,
    // and both of those re-read it themselves.
    onSettingsOpenChanged: {
        if (settingsOpen) refreshPrivateDiagnostics()
        if (settingsOpen && !artworkReviewLoaded) loadArtworkReview(null)
    }
    property string clockText: ""

    readonly property bool homeListBrowsingSystems: page === "home" &&
            homeViewMode === "list" && homeListFocusColumn === 0
    readonly property bool showSystemBackdrop: page === "home" &&
            ((homeViewMode === "covers" && homeZone === 0) ||
             homeListBrowsingSystems)
    readonly property string currentViewName: page === "games" ? "SYSTEM VIEW" :
            (homeViewMode === "list" ? "LIST VIEW" : "COVER VIEW")

    /*
     * Qt 5 has no native Liquid Glass material, so reproduce the optical
     * behavior in one GPU pass. The rounded-rectangle SDF identifies the
     * physical edge of the lens; the background is displaced along that
     * edge normal, lightly scattered in the body, split spectrally at the
     * rim, then lit from the upper-left. This keeps the center readable while
     * making the perimeter visibly refract instead of merely looking blurred.
     */
    property string liquidGlassFragmentShader:
        "varying highp vec2 qt_TexCoord0;\n" +
        "uniform lowp sampler2D source;\n" +
        "uniform highp vec2 glassSize;\n" +
        "uniform highp float cornerRadius;\n" +
        "uniform highp float edgeThickness;\n" +
        "uniform highp float distortionStrength;\n" +
        "uniform highp float scatterRadius;\n" +
        "uniform highp float samplePadding;\n" +
        "uniform lowp vec4 glassTint;\n" +
        "uniform lowp float qt_Opacity;\n" +
        "highp float roundedBox(highp vec2 p, highp vec2 b, highp float r) {\n" +
        "    highp vec2 q = abs(p) - (b - vec2(r));\n" +
        "    return length(max(q, vec2(0.0))) + min(max(q.x, q.y), 0.0) - r;\n" +
        "}\n" +
        "void main() {\n" +
        "    highp vec2 uv = qt_TexCoord0;\n" +
        "    highp vec2 safeSize = max(glassSize, vec2(1.0));\n" +
        "    highp vec2 sampleExtent = safeSize + vec2(samplePadding * 2.0);\n" +
        "    highp vec2 texel = 1.0 / sampleExtent;\n" +
        "    highp vec2 baseUv = (uv * safeSize + vec2(samplePadding)) / sampleExtent;\n" +
        "    highp vec2 halfBox = safeSize * 0.5;\n" +
        "    highp vec2 p = uv * safeSize - halfBox;\n" +
        "    highp float d = roundedBox(p, halfBox, cornerRadius);\n" +
        "    highp float mask = 1.0 - smoothstep(-0.75, 0.75, d);\n" +
        "    highp float insideDistance = max(-d, 0.0);\n" +
        "    highp float edge = 1.0 - smoothstep(0.8, edgeThickness, insideDistance);\n" +
        "    highp vec2 dx = vec2(1.0, 0.0);\n" +
        "    highp vec2 dy = vec2(0.0, 1.0);\n" +
        "    highp vec2 grad = vec2(\n" +
        "        roundedBox(p + dx, halfBox, cornerRadius) - roundedBox(p - dx, halfBox, cornerRadius),\n" +
        "        roundedBox(p + dy, halfBox, cornerRadius) - roundedBox(p - dy, halfBox, cornerRadius));\n" +
        "    highp vec2 normal = normalize(grad + vec2(0.0001));\n" +
        "    highp float lensRipple = 0.78 + 0.22 * cos(insideDistance * 0.42);\n" +
        "    highp float bend = distortionStrength * edge * edge * lensRipple;\n" +
        "    highp vec2 lensUv = clamp(baseUv - normal * bend * texel, texel, vec2(1.0) - texel);\n" +
        "    highp vec2 sx = vec2(scatterRadius * texel.x, 0.0);\n" +
        "    highp vec2 sy = vec2(0.0, scatterRadius * texel.y);\n" +
        "    lowp vec4 sampleColor = texture2D(source, lensUv) * 0.24;\n" +
        "    sampleColor += texture2D(source, clamp(lensUv + sx, texel, vec2(1.0) - texel)) * 0.11;\n" +
        "    sampleColor += texture2D(source, clamp(lensUv - sx, texel, vec2(1.0) - texel)) * 0.11;\n" +
        "    sampleColor += texture2D(source, clamp(lensUv + sy, texel, vec2(1.0) - texel)) * 0.11;\n" +
        "    sampleColor += texture2D(source, clamp(lensUv - sy, texel, vec2(1.0) - texel)) * 0.11;\n" +
        "    sampleColor += texture2D(source, clamp(lensUv + sx + sy, texel, vec2(1.0) - texel)) * 0.08;\n" +
        "    sampleColor += texture2D(source, clamp(lensUv + sx - sy, texel, vec2(1.0) - texel)) * 0.08;\n" +
        "    sampleColor += texture2D(source, clamp(lensUv - sx + sy, texel, vec2(1.0) - texel)) * 0.08;\n" +
        "    sampleColor += texture2D(source, clamp(lensUv - sx - sy, texel, vec2(1.0) - texel)) * 0.08;\n" +
        "    lowp vec3 color = sampleColor.rgb;\n" +
        "    highp float chroma = 1.35 * edge;\n" +
        "    highp vec2 redUv = clamp(lensUv - normal * chroma * texel, texel, vec2(1.0) - texel);\n" +
        "    highp vec2 blueUv = clamp(lensUv + normal * chroma * texel, texel, vec2(1.0) - texel);\n" +
        "    color.r = mix(color.r, texture2D(source, redUv).r, edge * 0.30);\n" +
        "    color.b = mix(color.b, texture2D(source, blueUv).b, edge * 0.30);\n" +
        "    highp float luminance = dot(color, vec3(0.2126, 0.7152, 0.0722));\n" +
        "    highp float adaptiveDim = 0.40 * smoothstep(0.46, 0.86, luminance);\n" +
        "    color *= 1.0 - adaptiveDim;\n" +
        "    color = mix(color, glassTint.rgb, glassTint.a);\n" +
        "    highp vec2 lightDirection = normalize(vec2(-0.62, -0.78));\n" +
        "    highp float litRim = pow(max(dot(normal, lightDirection), 0.0), 3.0) * edge;\n" +
        "    highp float darkRim = pow(max(dot(normal, -lightDirection), 0.0), 2.0) * edge;\n" +
        "    highp float innerCaustic = smoothstep(0.8, 3.0, insideDistance) *\n" +
        "        (1.0 - smoothstep(3.0, 9.0, insideDistance));\n" +
        "    color += vec3(0.14, 0.16, 0.19) * litRim;\n" +
        "    color += vec3(0.045, 0.05, 0.06) * innerCaustic;\n" +
        "    color *= 1.0 - 0.17 * darkRim;\n" +
        "    gl_FragColor = vec4(color * mask, mask) * qt_Opacity;\n" +
        "}\n"

    function brandSlugForSystem(index) {
        if (index < 0 || index >= systemModel.count) return ""
        return String(systemModel.get(index).family || "")
    }

    function brandNameForSystem(index) {
        var brand = brandSlugForSystem(index)
        if (brand === "sega") return "SEGA"
        if (brand === "sony") return "SONY"
        if (brand === "microsoft") return "MICROSOFT"
        if (brand === "nintendo") return "NINTENDO"
        if (brand === "arcade") return "ARCADE"
        if (brand === "atari") return "ATARI"
        if (brand === "commodore") return "COMMODORE"
        if (brand === "snk") return "SNK"
        if (brand === "nec") return "NEC"
        if (brand === "bandai") return "BANDAI"
        if (brand === "mattel") return "MATTEL"
        if (brand === "magnavox") return "MAGNAVOX"
        if (brand === "coleco") return "COLECO"
        if (brand === "apple") return "APPLE"
        if (brand === "amstrad") return "AMSTRAD"
        if (brand === "sinclair") return "SINCLAIR"
        if (brand === "3do") return "3DO"
        return "MULTI-PUBLISHER"
    }

    function brandLogoForSystem(index) {
        var brand = brandSlugForSystem(index)
        if (brand === "arcade")
            return Qt.resolvedUrl("assets/logos-png/arcade.png")
        return brand ? Qt.resolvedUrl("assets/brands/" + brand + ".png") : ""
    }

    function defaultFamilyAccent(family) {
        // Spread unrelated platform families around the color wheel while
        // retaining Lucent's established colors for the four families on the
        // reference Thor library.
        var defaults = {
            "nintendo": "#ff9f43", "sega": "#4fd17f",
            "sony": "#a987ff", "microsoft": "#4aa3ff",
            "arcade": "#35d0e6", "atari": "#ff5964",
            "commodore": "#23c9b8", "snk": "#ffd166",
            "nec": "#ef6cff", "bandai": "#ff7d3a",
            "mattel": "#48cae4", "magnavox": "#c7f464",
            "coleco": "#f72585", "apple": "#a8b2c1",
            "amstrad": "#00b4d8", "sinclair": "#e63946",
            "3do": "#b8f2e6", "open": "#7bdff2"
        }
        return defaults[String(family)] || "#dce4f2"
    }

    function hueChannel(p, q, t) {
        var wrapped = t
        if (wrapped < 0) wrapped += 1
        if (wrapped > 1) wrapped -= 1
        if (wrapped < 1 / 6) return p + (q - p) * 6 * wrapped
        if (wrapped < 1 / 2) return q
        if (wrapped < 2 / 3) return p + (q - p) * (2 / 3 - wrapped) * 6
        return p
    }

    function hslHex(hue, saturation, lightness) {
        var red = lightness
        var green = lightness
        var blue = lightness
        if (saturation > 0) {
            var q = lightness < 0.5 ?
                    lightness * (1 + saturation) :
                    lightness + saturation - lightness * saturation
            var p = 2 * lightness - q
            red = hueChannel(p, q, hue + 1 / 3)
            green = hueChannel(p, q, hue)
            blue = hueChannel(p, q, hue - 1 / 3)
        }
        return "#" + colorByteHex(red) + colorByteHex(green) + colorByteHex(blue)
    }

    function defaultSystemAccent(index) {
        if (index <= 0 || systemModel.count <= 1) return "#dce4f2"
        // Evenly spaced HSL hues make seven installed systems resolve to a
        // ROYGBIV-like spectrum, while any other count still uses the full
        // wheel instead of clustering near one color family.
        var count = Math.max(1, systemModel.count - 1)
        var hue = ((index - 1) % count) / count
        // ListModel infers this role as a string from systemCatalog. Returning
        // the same type is essential: assigning a QColor here can silently
        // leave the original family color in place on Qt 5.
        return hslHex(hue, 0.82, 0.59)
    }

    // The system palette is also the fallback layer for "by wallpaper", so
    // per-system hues stay in force for games whose wallpaper yielded nothing.
    function baseAccentGrouping() {
        return accentGrouping === "family" ? "family" : "system"
    }

    function normalizedAccentGrouping(value) {
        if (value === "family") return "family"
        if (value === "wallpaper") return "wallpaper"
        return "system"
    }

    function accentGroupingOptions() {
        return ["family", "system", "wallpaper"]
    }

    // Precomputed by the Lucent importer as x-lucent-accent. Reading a stored
    // string keeps game selection free of any color analysis.
    function storedWallpaperAccent(game) {
        if (!game || !game.extra) return ""
        var stored = game.extra["lucent-accent"]
        if (stored === undefined || stored === null) return ""
        var text = String(stored).trim().toLowerCase()
        return /^#[0-9a-f]{6}$/.test(text) ? text : ""
    }

    function resolvedAccentForSystem(index) {
        if (index <= 0) return "#dce4f2"
        var system = systemModel.get(index)
        if (baseAccentGrouping() === "system") {
            var systemKey = String(system.folder)
            return customSystemAccents[systemKey] || defaultSystemAccent(index)
        }
        var familyKey = String(system.family || "open")
        return customFamilyAccents[familyKey] || defaultFamilyAccent(familyKey)
    }

    function applyAccentPalette() {
        for (var index = 0; index < systemModel.count; ++index)
            systemModel.setProperty(index, "accent", resolvedAccentForSystem(index))
        if (systemLedEnabled) systemLedCommit.restart()
    }

    function setAccentGrouping(value) {
        accentGrouping = normalizedAccentGrouping(value)
        api.memory.set("lucentAccentGrouping", accentGrouping)
        accentEditorTargetIndex = 0
        applyAccentPalette()
    }

    function cycleAccentGrouping(direction) {
        var options = accentGroupingOptions()
        var current = Math.max(0, options.indexOf(accentGrouping))
        var step = direction < 0 ? -1 : 1
        setAccentGrouping(options[(current + step + options.length) % options.length])
    }

    function accentTargets() {
        var targets = []
        var seen = ({})
        for (var index = 1; index < systemModel.count; ++index) {
            var value = baseAccentGrouping() === "system" ?
                    String(systemModel.get(index).folder) :
                    String(systemModel.get(index).family || "open")
            if (seen[value]) continue
            seen[value] = true
            targets.push(value)
        }
        return targets
    }

    function accentTargetLabel(key) {
        if (baseAccentGrouping() === "family") {
            for (var index = 1; index < systemModel.count; ++index) {
                if (String(systemModel.get(index).family || "open") === key)
                    return brandNameForSystem(index)
            }
            return String(key).toUpperCase()
        }
        for (var systemIndex = 1; systemIndex < systemModel.count; ++systemIndex) {
            if (String(systemModel.get(systemIndex).folder) === key)
                return String(systemModel.get(systemIndex).name)
        }
        return String(key).toUpperCase()
    }

    function accentEditorColor() {
        return Qt.hsla(accentEditorHue, accentEditorSaturation,
                accentEditorLightness, 1.0)
    }

    function loadAccentEditorTarget() {
        var targets = accentTargets()
        if (targets.length === 0) return
        accentEditorTargetIndex = Math.max(0,
                Math.min(targets.length - 1, accentEditorTargetIndex))
        var key = targets[accentEditorTargetIndex]
        var saved = baseAccentGrouping() === "system" ?
                customSystemAccents[key] : customFamilyAccents[key]
        var rawColor = saved || (baseAccentGrouping() === "system" ?
                resolvedAccentForSystem(accentEditorTargetIndex + 1) :
                defaultFamilyAccent(key))
        var color = Qt.tint(rawColor, "#00000000")
        accentEditorHue = color.hslHue < 0 ? 0 : color.hslHue
        accentEditorSaturation = color.hslSaturation
        accentEditorLightness = color.hslLightness
    }

    function openAccentEditor() {
        accentEditorTargetIndex = 0
        accentEditorChannel = 0
        loadAccentEditorTarget()
        accentEditorOpen = true
    }

    function storeAccentEditorColor() {
        var targets = accentTargets()
        if (targets.length === 0) return
        var key = targets[accentEditorTargetIndex]
        var hex = "#" + colorByteHex(accentEditorColor().r) +
                colorByteHex(accentEditorColor().g) +
                colorByteHex(accentEditorColor().b)
        if (baseAccentGrouping() === "system") {
            var systemCopy = JSON.parse(JSON.stringify(customSystemAccents))
            systemCopy[key] = hex
            customSystemAccents = systemCopy
            api.memory.set("lucentCustomSystemAccents", JSON.stringify(systemCopy))
        } else {
            var familyCopy = JSON.parse(JSON.stringify(customFamilyAccents))
            familyCopy[key] = hex
            customFamilyAccents = familyCopy
            api.memory.set("lucentCustomFamilyAccents", JSON.stringify(familyCopy))
        }
        applyAccentPalette()
    }

    function adjustAccentEditor(direction) {
        var targets = accentTargets()
        if (targets.length === 0) return
        if (accentEditorChannel === 0) {
            accentEditorTargetIndex = (accentEditorTargetIndex +
                    (direction < 0 ? -1 : 1) + targets.length) % targets.length
            loadAccentEditorTarget()
            return
        }
        if (accentEditorChannel === 1)
            accentEditorHue = (accentEditorHue + (direction < 0 ? -1 : 1) / 72 + 1) % 1
        else if (accentEditorChannel === 2)
            accentEditorSaturation = Math.max(0, Math.min(1,
                    accentEditorSaturation + (direction < 0 ? -0.02 : 0.02)))
        else
            accentEditorLightness = Math.max(0.18, Math.min(0.82,
                    accentEditorLightness + (direction < 0 ? -0.02 : 0.02)))
        storeAccentEditorColor()
    }

    function resetAccentEditorColor() {
        var targets = accentTargets()
        if (targets.length === 0) return
        var key = targets[accentEditorTargetIndex]
        if (baseAccentGrouping() === "system") {
            var systemCopy = JSON.parse(JSON.stringify(customSystemAccents))
            delete systemCopy[key]
            customSystemAccents = systemCopy
            api.memory.set("lucentCustomSystemAccents", JSON.stringify(systemCopy))
        } else {
            var familyCopy = JSON.parse(JSON.stringify(customFamilyAccents))
            delete familyCopy[key]
            customFamilyAccents = familyCopy
            api.memory.set("lucentCustomFamilyAccents", JSON.stringify(familyCopy))
        }
        applyAccentPalette()
        loadAccentEditorTarget()
    }

    function hardwareVariants(folder) {
        // Rotate every audited real-hardware angle available for the platform.
        // Only folders that physically contain fewer source photographs are
        // restricted; no generated stand-ins are used.
        if (folder === "all") return [0]
        if (folder === "psx") return [0, 1]
        if (folder === "nds") return [0, 1, 2, 3]
        if (folder === "arcade" || folder === "n64" ||
                folder === "ps2" || folder === "psp")
            return [0, 1, 2, 3, 4]
        return [0, 1, 2]
    }

    function hardwarePhotoUrl(index, variant) {
        var folder = systemModel.get(index).folder
        return Qt.resolvedUrl("assets/hardware-cutouts/" + folder + "/" + variant + ".png")
    }

    function initializeHardwarePhotos() {
        var photos = []
        for (var index = 0; index < systemModel.count; ++index) {
            var variants = hardwareVariants(systemModel.get(index).folder)
            photos[index] = hardwarePhotoUrl(index,
                    variants[Math.floor(Math.random() * variants.length)])
        }
        hardwarePhotoBySystem = photos
        lastHardwareSystemIndex = systemRail.currentIndex
    }

    function rerollHardwarePhoto(index) {
        if (index < 0 || index >= systemModel.count) return
        var variants = hardwareVariants(systemModel.get(index).folder)
        var current = String(hardwarePhotoBySystem[index] || "")
        var match = current.match(/\/(\d+)\.png(?:\?.*)?$/)
        var previous = match ? Number(match[1]) : -1
        var next = variants[Math.floor(Math.random() * variants.length)]
        if (variants.length > 1 && next === previous) {
            var position = variants.indexOf(next)
            next = variants[(position + 1 + Math.floor(Math.random() *
                    (variants.length - 1))) % variants.length]
        }
        var photos = hardwarePhotoBySystem.slice(0)
        photos[index] = hardwarePhotoUrl(index, next)
        hardwarePhotoBySystem = photos
    }

    function collectionNamed(name) {
        for (var i = 0; i < api.collections.count; ++i) {
            var candidate = api.collections.get(i)
            if (candidate.name === name)
                return candidate
        }
        return null
    }

    function rebuildVisibleSystems() {
        while (systemModel.count > 1)
            systemModel.remove(systemModel.count - 1)
        for (var index = 1; index < systemCatalog.count; ++index) {
            var definition = systemCatalog.get(index)
            var collection = collectionNamed(definition.collectionName)
            if (!collection || collection.games.count <= 0)
                continue
            systemModel.append({
                "name": definition.name,
                "years": definition.years,
                "mark": definition.mark,
                "collectionName": definition.collectionName,
                "folder": definition.folder,
                "family": definition.family,
                "accent": definition.accent
            })
        }
        applyAccentPalette()
        refreshAvailableBrands()
        Qt.callLater(function() { root.loadLibraryIndex() })
    }

    function refreshAvailableBrands() {
        var seen = ({})
        var brands = []
        var folders = ({})
        for (var index = 1; index < systemModel.count; ++index) {
            folders[String(systemModel.get(index).collectionName)] =
                    String(systemModel.get(index).folder)
            var brand = brandSlugForSystem(index)
            if (brand === "" || seen[brand]) continue
            seen[brand] = true
            brands.push(brand)
        }
        collectionFolderMap = folders
        availableBrandSlugs = brands
    }

    function libraryCacheKey(folder, title) {
        return String(folder || "") + "|" +
                String(title || "").toLowerCase().trim().replace(/\s+/g, " ")
    }

    function loadLibraryIndex() {
        var request = new XMLHttpRequest()
        request.onreadystatechange = function() {
            if (request.readyState !== XMLHttpRequest.DONE) return
            if (request.status !== 200) {
                libraryIndexRetry.restart()
                return
            }
            try {
                var payload = JSON.parse(request.responseText)
                // Keep the native service's compact key arrays intact. Turning
                // every key into a QML game object in one callback created a
                // multi-second UI-thread stall. Only the 5K game lookup is
                // built here, in small event-loop slices; individual rails
                // resolve the handful of keys they actually render.
                root.libraryIndexReady = false
                root.pendingLibraryIndex = payload.systems || ({})
                root.pendingLibraryGameMap = ({})
                root.libraryIndexBuildPosition = 0
                libraryIndexBuildTimer.restart()
            } catch (error) {
                libraryIndexRetry.restart()
            }
        }
        request.open("GET", "http://127.0.0.1:43821/library/index", true)
        request.send()
    }

    function continueLibraryIndexBuild() {
        if (!pendingLibraryIndex) return
        var gameMap = pendingLibraryGameMap
        var end = Math.min(api.allGames.count, libraryIndexBuildPosition + 180)
        for (var gameIndex = libraryIndexBuildPosition; gameIndex < end; ++gameIndex) {
            var game = api.allGames.get(gameIndex)
            if (!isLucentLibraryGame(game) || !gameVisibleAfterMutation(game)) continue
            for (var collectionIndex = 0;
                 collectionIndex < game.collections.count; ++collectionIndex) {
                var collectionName = String(game.collections.get(collectionIndex).name || "")
                var folder = collectionFolderMap[collectionName]
                if (!folder) continue
                gameMap[libraryCacheKey(folder, game.title)] = game
                break
            }
        }
        libraryIndexBuildPosition = end
        if (end < api.allGames.count) {
            libraryIndexBuildTimer.restart()
            return
        }

        libraryGameMap = gameMap
        systemGameCache = pendingLibraryIndex
        pendingLibraryIndex = null
        pendingLibraryGameMap = ({})
        libraryIndexReady = true
        // The startup screen lives in Java (it has to cover the
        // frontend's own splash, which exists before any QML does), so
        // this is the only way to tell it the wait is over.
        requestPreviewEndpoint("frontend/ready")
        homeListCache = ({})
        activateCachedSystemSort()
        if (page === "home" && homeViewMode === "list")
            rebuildHomeList()
        else if (page === "games") {
            gameRail.currentIndex = Math.max(0,
                    Math.min(gameRail.currentIndex, activeGameCount - 1))
            Qt.callLater(function() { root.activateGamePreview() })
        }
    }

    function activateCachedSystemSort() {
        if (allSystemsActive || activeSystemIndex <= 0) {
            activeSystemGames = []
            return
        }
        var folder = String(systemModel.get(activeSystemIndex).folder)
        var systemCache = systemGameCache[folder]
        activeSystemGames = systemCache && systemCache[sortMode] ?
                systemCache[sortMode] : []
    }

    function recentGame(index) {
        if (index < 0 || index >= recentModel.count)
            return null
        return api.allGames.get(recentModel.mapToSource(index))
    }

    function proxyGame(proxy, index) {
        if (!proxy || index < 0 || index >= proxy.count)
            return null
        return api.allGames.get(proxy.mapToSource(index))
    }

    function mostPlayedGame(index) {
        return proxyGame(mostPlayedModel, index)
    }

    function aggregateSortedSourceIndex(proxy, index) {
        if (!proxy || index < 0 || index >= proxy.count) return -1
        var filteredIndex = proxy.mapToSource(index)
        return filteredIndex < 0 ? -1 : allLibraryFilterModel.mapToSource(filteredIndex)
    }

    function aggregateSortedGame(proxy, index) {
        var sourceIndex = aggregateSortedSourceIndex(proxy, index)
        return sourceIndex < 0 ? null : api.allGames.get(sourceIndex)
    }

    function recentlyAddedGame(index) {
        if (index < 0 || index >= recentlyAddedModel.count)
            return null
        return api.allGames.get(recentlyAddedModel.get(index).sourceIndex)
    }

    function rebuildRecentlyAddedModel() {
        var candidates = []
        for (var index = 0; index < api.allGames.count; ++index) {
            var game = api.allGames.get(index)
            if (!isLucentLibraryGame(game) || !gameVisibleAfterMutation(game) ||
                    !gameVisibleInHomeCategory(game, 3))
                continue
            var values = game.extra ? game.extra["added-at"] : null
            var timestamp = Number(values || 0)
            if (timestamp > 0)
                candidates.push({ "sourceIndex": index, "timestamp": timestamp })
        }
        candidates.sort(function(left, right) { return right.timestamp - left.timestamp })
        recentlyAddedModel.clear()
        for (var candidate = 0; candidate < Math.min(60, candidates.length); ++candidate)
            recentlyAddedModel.append(candidates[candidate])
    }

    function homeShelfModel(zone) {
        if (zone === 1) return recentModel
        if (zone === 2) return mostPlayedModel
        if (zone === 3) return recentlyAddedModel
        if (zone === 4) return allCriticSortModel
        if (zone === 5) return allUserSortModel
        if (zone === 6) return allAlphaSortModel
        return allReleaseSortModel
    }

    function homeShelfRail(zone) {
        if (zone === 1) return recentRail
        if (zone === 2) return mostPlayedRail
        if (zone === 3) return recentlyAddedRail
        if (zone === 4) return criticRail
        if (zone === 5) return userRail
        if (zone === 6) return alphaRail
        return releaseRail
    }

    function homeShelfGameAt(zone, index) {
        if (zone === 1) return recentGame(index)
        if (zone === 2) return mostPlayedGame(index)
        if (zone === 3) return recentlyAddedGame(index)
        return aggregateSortedGame(homeShelfModel(zone), index)
    }

    function homeShelfGame(zone) {
        var rail = homeShelfRail(zone)
        return rail ? homeShelfGameAt(zone, rail.currentIndex) : null
    }

    function homeShelfName(zone) {
        if (zone === 1) return "CONTINUE PLAYING"
        if (zone === 2) return "MOST PLAYED"
        if (zone === 3) return "RECENTLY ADDED"
        if (zone === 4) return "CRITIC SCORE"
        if (zone === 5) return "USER SCORE"
        if (zone === 6) return "A–Z"
        return "RELEASE DATE"
    }

    function homeCategorySourceIndex(zone, index) {
        if (zone === 1)
            return index >= 0 && index < recentModel.count ? recentModel.mapToSource(index) : -1
        if (zone === 2)
            return index >= 0 && index < mostPlayedModel.count ? mostPlayedModel.mapToSource(index) : -1
        if (zone === 3)
            return index >= 0 && index < recentlyAddedModel.count ?
                    Number(recentlyAddedModel.get(index).sourceIndex) : -1
        return aggregateSortedSourceIndex(homeShelfModel(zone), index)
    }

    function homeCategoryCount(zone) {
        if (zone === 1) return recentModel.count
        if (zone === 2) return mostPlayedModel.count
        if (zone === 3) return recentlyAddedModel.count
        return homeShelfModel(zone).count
    }

    function homeListGameAt(index) {
        if (index < 0 || index >= homeListEntries.length)
            return null
        return homeListEntries[index]
    }

    function rebuildHomeList() {
        if (homeViewMode !== "list") return
        var systemIndex = Math.max(0, systemRail.currentIndex)
        var cacheKey = libraryMutationRevision + ":" + homeListCategory + ":" + systemIndex
        var cached = homeListCache[cacheKey]
        if (!cached) {
            cached = []
            if (systemIndex > 0 && homeListCategory >= 4) {
                var sortNames = ["", "", "", "", "critic", "user", "alpha", "release"]
                var folder = String(systemModel.get(systemIndex).folder)
                var systemCache = systemGameCache[folder]
                var orderedKeys = systemCache ? systemCache[sortNames[homeListCategory]] : null
                if (orderedKeys) {
                    for (var keyIndex = 0;
                         keyIndex < orderedKeys.length && cached.length < 240; ++keyIndex) {
                        var indexedGame = libraryGameMap[String(orderedKeys[keyIndex])]
                        if (indexedGame) cached.push(indexedGame)
                    }
                }
            } else {
                var sourceCount = homeCategoryCount(homeListCategory)
                // Aggregate sorted views stop after 240 rows. Continue/Most/
                // Recent are compact native models, so filtering those by one
                // system never traverses the full library.
                for (var index = 0; index < sourceCount && cached.length < 240; ++index) {
                    var game = homeShelfGameAt(homeListCategory, index)
                    if (game && (systemIndex === 0 || systemIndexForGame(game) === systemIndex))
                        cached.push(game)
                }
            }
            homeListCache[cacheKey] = cached
        }
        homeListEntries = cached.slice(0)
        homeZone = homeListCategory
        // While the user is moving through systems, no game row is selected.
        // A random item from the active category drives only the video preview;
        // the upper display stays on the selected console's hardware artwork.
        // Pressing A locks the system and deliberately selects row 0.
        //
        // The list itself always starts at row 0 so switching systems or
        // categories shows the top of that sort every time. The random
        // showcase pick lives in homeListPreviewIndex, which no view reads.
        homeListRail.currentIndex = homeListEntries.length > 0 ? 0 : -1
        homeListPreviewIndex = homeListEntries.length > 0 ?
                (homeListFocusColumn === 0 ?
                 Math.floor(Math.random() * homeListEntries.length) : 0) : -1
        // Row zero is the deterministic A-button destination. Warm its cover
        // even while a random video is playing so entering the game column can
        // never expose that random video's old cover for a frame.
        boxArtworkPreloadEntry.source = boxArtwork(homeListGameAt(0))
        upperArtworkPreloadEntry.source = artwork(homeListGameAt(0))
        Qt.callLater(function() {
            if (root.homeViewMode !== "list" || root.page !== "home") return
            // Always the top of the list, never a remembered or random offset.
            homeListRail.positionViewAtBeginning()
            root.activateHomeListPreview()
            root.forceActiveFocus()
        })
    }

    function cycleHomeListCategory(direction) {
        var next = homeListCategory + (direction < 0 ? -1 : 1)
        if (next < 1) {
            homeListFocusColumn = 0
            rebuildHomeList()
            root.forceActiveFocus()
            return
        }
        if (next > 7) return
        homeListFocusColumn = 1
        homeListCategory = next
        rebuildHomeList()
    }

    function enterHomeListGames() {
        homeListFocusColumn = 1
        if (homeListEntries.length > 0)
            homeListRail.currentIndex = 0
        // The showcase pick stops applying the moment a real row is selected.
        homeListPreviewIndex = homeListEntries.length > 0 ? 0 : -1
        activateHomeListPreview()
        root.forceActiveFocus()
    }

    function toggleHomeView() {
        homeViewMode = homeViewMode === "covers" ? "list" : "covers"
        api.memory.set("thoriumHomeView", homeViewMode)
        if (homeViewMode === "list") {
            homeListCategory = homeZone > 0 ? homeZone : 1
            homeListFocusColumn = 0
            rebuildHomeList()
        } else {
            homeZone = 0
            chooseSystemWallpaper(systemRail.currentIndex)
            Qt.callLater(function() { root.activateHomePreview(false) })
            systemRail.forceActiveFocus()
        }
    }

    function systemGameCount(index) {
        if (index === 0) return romGameCount()
        var collection = collectionAtSystem(index)
        return collection ? collection.games.count : 0
    }

    function systemIndexForGame(game) {
        if (!game || !game.collections || game.collections.count <= 0)
            return -1
        for (var collectionIndex = 0; collectionIndex < game.collections.count; ++collectionIndex) {
            var collectionName = game.collections.get(collectionIndex).name
            for (var systemIndex = 0; systemIndex < systemModel.count; ++systemIndex) {
                if (systemModel.get(systemIndex).collectionName === collectionName)
                    return systemIndex
            }
        }
        return -1
    }

    function packageDimensionsForSystem(index) {
        // Front-face dimensions in millimetres. Cover View uses one shared
        // pixels-per-millimetre scale, so unlike boxes retain the proportions
        // they would have on a physical shelf. Closely related retail formats
        // deliberately share a standard (CD jewel, DVD keep, Blu-ray, etc.).
        var folder = index > 0 && index < systemModel.count ?
                String(systemModel.get(index).folder) : ""
        var dimensions = {
            "nes": [127, 178], "snes": [180, 130], "n64": [180, 130],
            "gb": [125, 125], "gbc": [125, 125], "gba": [125, 125],
            "nds": [122, 135], "n3ds": [125, 135],
            "megadrive": [130, 180], "gamegear": [125, 180],
            "saturn": [142, 125], "dreamcast": [142, 125],
            "psx": [142, 125], "ps2": [135, 190], "ps3": [135, 172],
            "ps4": [135, 172], "ps5": [135, 172],
            "psp": [105, 177], "psvita": [105, 135],
            "gc": [135, 190], "wii": [135, 190], "wiiu": [135, 190],
            "switch": [105, 170], "windows": [135, 190],
            "xbox": [135, 190], "xbox360": [135, 190],
            "arcade": [135, 190]
        }
        var selected = dimensions[folder] || [135, 190]
        return { "width": selected[0], "height": selected[1] }
    }

    function packageDimensionsForGame(game) {
        return packageDimensionsForSystem(systemIndexForGame(game))
    }

    // Millimetres of real packaging per pixel of screen. Raised across the
    // board once the navigation-bar inset was reclaimed: a 190 mm case now
    // fits the taller shelf slot, and cards that were leaving a third of
    // their artwork area unused are drawn at the size the slot can carry.
    function coverShelfPixelsPerMillimetre() {
        if (coverViewRowCount === 1) return 2.90
        if (coverViewRowCount === 2) return 1.18
        return 0.64
    }

    function isLucentLibraryGame(game) {
        // Pegasus exposes installed Android applications through api.allGames.
        // Lucent is a ROM library: the built-in Android provider is never a
        // game source. Keep real ROM collections visible even before a custom
        // rail card/logo has been added for a newly detected platform.
        if (!game || !game.collections || game.collections.count <= 0)
            return false
        for (var index = 0; index < game.collections.count; ++index) {
            var name = String(game.collections.get(index).name || "").toLowerCase()
            if (name === "android" || name === "android apps" ||
                    name === "applications" || name === "apps")
                return false
        }
        return true
    }

    function romGameCount() {
        // Referencing count keeps this binding reactive when Pegasus reparses
        // metadata, while the identity test excludes Applications/emulators.
        var sourceCount = api.allGames.count
        var count = 0
        for (var index = 0; index < sourceCount; ++index) {
            if (isLucentLibraryGame(api.allGames.get(index))) ++count
        }
        return count
    }

    function markForGame(game) {
        var index = systemIndexForGame(game)
        return index >= 0 ? systemModel.get(index).mark : "GAME"
    }

    function accentForGame(game) {
        if (accentGrouping === "wallpaper") {
            var wallpaperAccent = storedWallpaperAccent(game)
            // A game with no wallpaper, or one whose wallpaper had no usable
            // hue, keeps its system accent instead of an invented color.
            if (wallpaperAccent !== "") return wallpaperAccent
        }
        var index = systemIndexForGame(game)
        return index >= 0 ? systemModel.get(index).accent : root.accent
    }

    function homeListAccentForGame(game) {
        return homeListUsesAllSystemsAccent ? systemModel.get(0).accent :
                                              accentForGame(game)
    }

    function artwork(game) {
        if (!game) return ""
        // Never promote a capture or portrait cover into the wallpaper layer.
        // Missing real fanart falls through to the console backdrop underneath.
        return game.assets.background || ""
    }

    function chooseSystemWallpaper(index) {
        var wrapped = wrappedSystemIndex(index)
        if (wrapped < 0) return
        var departed = lastHardwareSystemIndex
        if (hardwarePhotoBySystem.length > 0 && departed >= 0 && departed !== wrapped)
            rerollHardwarePhoto(departed)
        lastHardwareSystemIndex = wrapped
    }

    function upperArtworkSource() {
        if (showSystemBackdrop)
            return ""
        if (!activeGame) return ""
        // Only provider-labeled/vision-audited background art belongs here.
        // The system backdrop remains visible when no genuine wallpaper exists.
        return activeGame.assets.background || ""
    }

    function upperArtworkLayer(slot) {
        return slot === 0 ? upperArtworkA : upperArtworkB
    }

    function promoteUpperArtwork(slot) {
        if (slot !== upperArtworkPendingSlot)
            return
        var layer = upperArtworkLayer(slot)
        if (!layer || layer.status !== Image.Ready ||
                String(layer.source) !== String(upperArtworkTarget))
            return
        upperArtworkSlot = slot
        upperArtworkPendingSlot = -1
    }

    function queueUpperArtwork(game, previousGame, nextGame) {
        // Decode both likely D-pad destinations before they are selected.
        // Assigning one of these URLs to the visible standby buffer then hits
        // Qt's image cache instead of briefly exposing the black base layer.
        upperArtworkPreloadPrevious.source = artwork(previousGame)
        upperArtworkPreloadNext.source = artwork(nextGame)

        var requested = String(artwork(game) || "")
        if (!requested) {
            // A missing wallpaper is a real state, not a slow load. Hide both
            // decoded buffers immediately so the neutral platform backdrop
            // underneath is revealed. Keeping the old slot visible here made
            // the previous game's artwork look as though it belonged to the
            // newly selected title.
            upperArtworkTarget = ""
            upperArtworkPendingSlot = -1
            upperArtworkSlot = -1
            return
        }
        var activeLayer = upperArtworkLayer(upperArtworkSlot)
        if (activeLayer && String(activeLayer.source) === requested) {
            // Rapidly moving away and straight back can leave a later request
            // decoding in the standby slot. Cancel its promotion so it cannot
            // replace the artwork the user has already returned to.
            upperArtworkTarget = requested
            upperArtworkPendingSlot = -1
            return
        }
        var incomingSlot = upperArtworkSlot === 0 ? 1 : 0
        var incomingLayer = upperArtworkLayer(incomingSlot)
        upperArtworkTarget = requested
        upperArtworkPendingSlot = incomingSlot
        incomingLayer.source = requested
        if (incomingLayer.status === Image.Ready)
            promoteUpperArtwork(incomingSlot)
    }

    function boxArtwork(game) {
        return game && game.assets ? String(game.assets.boxFront || "") : ""
    }

    function boxArtworkLayer(slot) {
        return slot === 0 ? homeListBoxArtA : homeListBoxArtB
    }

    function setBoxArtworkSource(slot, source) {
        if (slot === 0) boxArtworkSourceA = source
        else boxArtworkSourceB = source
    }

    function promoteBoxArtwork(slot) {
        if (slot !== boxArtworkPendingSlot)
            return
        var layer = boxArtworkLayer(slot)
        if (!layer || layer.status !== Image.Ready ||
                String(layer.source) !== String(boxArtworkTarget))
            return
        boxArtworkSlot = slot
        boxArtworkPendingSlot = -1
    }

    function queueBoxArtwork(game, previousGame, nextGame) {
        // Decode both directions before input reaches them. The visible cover
        // remains intact until the requested standby buffer is fully ready.
        boxArtworkPreloadPrevious.source = boxArtwork(previousGame)
        boxArtworkPreloadNext.source = boxArtwork(nextGame)

        var requested = boxArtwork(game)
        if (!requested) {
            boxArtworkTarget = ""
            boxArtworkPendingSlot = -1
            boxArtworkSlot = -1
            return
        }
        var activeSource = boxArtworkSlot === 0 ? boxArtworkSourceA : boxArtworkSourceB
        if (String(activeSource) === requested) {
            boxArtworkTarget = requested
            boxArtworkPendingSlot = -1
            return
        }
        var incomingSlot = boxArtworkSlot === 0 ? 1 : 0
        boxArtworkTarget = requested
        boxArtworkPendingSlot = incomingSlot
        setBoxArtworkSource(incomingSlot, requested)
        var incomingLayer = boxArtworkLayer(incomingSlot)
        if (incomingLayer && incomingLayer.status === Image.Ready)
            promoteBoxArtwork(incomingSlot)
    }

    function numericExtra(game, key) {
        if (!game || !game.extra) return NaN
        var raw = game.extra[key]
        // Pegasus preserves punctuation in x-* keys on this Android build.
        // Accept both API spellings so metadata refreshes cannot blank scores.
        if ((raw === undefined || raw === null || raw === "") && key === "userScore")
            raw = game.extra["user-score"] || game.extra["metacritic-user"]
        if ((raw === undefined || raw === null || raw === "") && key === "userComposite")
            raw = game.extra["user-composite"]
        if ((raw === undefined || raw === null || raw === "") && key === "criticComposite")
            raw = game.extra["critic-composite"]
        var value = Number(raw)
        return isNaN(value) ? NaN : value
    }

    function userScore(game) {
        // `rating` is reserved as the native, fast critic-sort role. Keep the
        // displayed user score sourced from its explicit metadata field.
        var score = numericExtra(game, "userComposite")
        if (isNaN(score)) score = numericExtra(game, "userScore")
        return isNaN(score) || score <= 0 ? NaN : score
    }

    function criticScore(game) {
        var score = numericExtra(game, "criticComposite")
        if (isNaN(score)) {
            score = game && game.extra ? Number(game.extra.critic) : NaN
            if (!isNaN(score) && score > 10) score /= 10.0
        }
        return isNaN(score) || score <= 0 ? NaN : score
    }

    function criticLabel(game) {
        return "CRITICS"
    }

    function scoreText(game) {
        var critic = criticScore(game)
        var user = userScore(game)
        return "CRITICS  " + (isNaN(critic) ? "N/A" : critic.toFixed(1)) +
                "     USERS  " + (isNaN(user) ? "N/A" : user.toFixed(1))
    }

    function releaseYear(game) {
        if (!game || !game.release) return "N/A"
        var formatted = Qt.formatDate(game.release, "yyyy")
        if (formatted && formatted !== "0" && formatted !== "NaN")
            return formatted
        var match = String(game.release).match(/(?:19|20)\d{2}/)
        return match ? match[0] : "N/A"
    }

    function gameFactsText(game) {
        return scoreText(game) + "     RELEASE  " + releaseYear(game)
    }

    function gameAtDisplayIndex(index) {
        if ((!allSystemsActive && !activeCollection) || activeGameCount <= 0 ||
                index < 0 || index >= activeGameCount)
            return null
        if (!allSystemsActive && searchQuery === "" && libraryIndexReady)
            return libraryGameMap[String(activeSystemGames[index])] || null
        if (allSystemsActive) {
            var allSourceIndex = activeGameSortModel.mapToSource(index)
            // Normal aggregate browsing sorts the already-filtered base index;
            // search proxies still map directly to api.allGames.
            if (searchQuery === "")
                allSourceIndex = allLibraryFilterModel.mapToSource(allSourceIndex)
            return api.allGames.get(allSourceIndex)
        }
        return activeCollection.games.get(activeGameSortModel.mapToSource(index))
    }

    function cycleSort(direction) {
        var modes = ["critic", "user", "alpha", "release"]
        var current = modes.indexOf(sortMode)
        var step = direction === -1 ? -1 : 1
        sortMode = modes[(current + step + modes.length) % modes.length]
        activateCachedSystemSort()
        scheduleNavigationPersistence()
        if (page === "home" && homeViewMode === "list") {
            rebuildHomeList()
            root.forceActiveFocus()
            return
        }
        gameRail.currentIndex = 0
        // A model pointer swap destroys the previously focused delegate. Keep
        // the scope itself focused so consecutive shoulder presses are never
        // swallowed while the new delegate is instantiated.
        root.forceActiveFocus()
        // The selected warm proxy changes immediately. Preview/media work is
        // still coalesced outside this input frame.
        sortChangeCommit.restart()
    }

    function toggleGameView() {
        gameViewMode = gameViewMode === "covers" ? "list" : "covers"
        scheduleNavigationPersistence()
        Qt.callLater(function() {
            if (gameViewMode === "list")
                positionGameListAtIndex(gameRail.currentIndex)
            else
                gameRail.positionViewAtIndex(gameRail.currentIndex, ListView.Center)
        })
    }

    function positionGameListAtIndex(index) {
        // A conservative floor, not a measurement: the viewport quantises
        // itself to whole strides and may now hold more rows than this.
        // Paging from the smaller number only means the last page overlaps by
        // a row, which is harmless; overstating it would skip games.
        var visibleRows = 8
        var leadingRows = 3
        var maximumStart = Math.max(0, activeGameCount - visibleRows)
        var start = Math.max(0, Math.min(maximumStart, index - leadingRows))
        gameListRail.positionViewAtIndex(start, ListView.Beginning)
    }

    function sortLabel(mode) {
        if (mode === "user") return "USER SCORE"
        if (mode === "critic") return "CRITIC SCORE"
        if (mode === "release") return "RELEASE"
        return "A–Z"
    }

    function videoSource(game) {
        return game && game.assets.video ? game.assets.video : ""
    }

    function gameIdentifier(game) {
        if (!game || !game.extra) return ""
        return String(game.extra["lucent-id"] || game.extra.lucentId || "")
    }

    // Older, hand-authored Pegasus metafiles predate Lucent's x-lucent-id.
    // They are still first-class library games, so behavioral preferences
    // need a durable local key. Destructive companion APIs continue to use
    // only the importer-issued identity above.
    function behavioralGameIdentifier(game) {
        var identity = gameIdentifier(game)
        if (identity !== "") return identity
        if (!game) return ""
        var title = String(game.title || "").trim().toLowerCase()
        if (title === "") return ""
        return "legacy:" + systemIndexForGame(game) + ":" + title
    }

    function displayTitle(game) {
        if (!game) return ""
        var identity = gameIdentifier(game)
        return identity !== "" && renamedGameTitles[identity] ?
                    renamedGameTitles[identity] : String(game.title || "")
    }

    function gameVisibleAfterMutation(game) {
        var revisionDependency = libraryMutationRevision
        var identity = gameIdentifier(game)
        return identity === "" || !hiddenGameIds[identity]
    }

    function gameVisibleInHomeCategory(game, category) {
        var revisionDependency = libraryMutationRevision
        if (category < 1 || category > 3) return true
        var identity = behavioralGameIdentifier(game)
        if (identity === "") return true
        var bucket = removedHomeCategoryGameIds[String(category)] || ({})
        return !bucket[identity]
    }

    function gameActionAllowsRemoveFromList() {
        return gameActionCategory >= 1 && gameActionCategory <= 3
    }

    function gameActionOptionCount() {
        return gameActionAllowsRemoveFromList() ? 5 : 4
    }

    // Cheats keeps a fixed slot even for a game that has none. The list is
    // fetched asynchronously, so a row that appeared on arrival would renumber
    // the options under the user -- and the row it would push down is DELETE.
    function gameActionCheatsOptionIndex() { return 1 }

    function gameActionRemoveOptionIndex() { return 2 }

    function gameActionDeleteOptionIndex() {
        return gameActionAllowsRemoveFromList() ? 3 : 2
    }

    // Always the new last row -- appended after DELETE so every existing
    // option index above stays exactly as it was before this feature.
    function gameActionMultiplayerOptionIndex() {
        return gameActionDeleteOptionIndex() + 1
    }

    function gameActionHasCheats() { return gameActionCheats.length > 0 }

    function moveGameActionSelection(direction) {
        var count = gameActionOptionCount()
        var next = gameActionIndex
        for (var step = 0; step < count; ++step) {
            next = (next + direction + count) % count
            if (next !== gameActionCheatsOptionIndex() || gameActionHasCheats()) break
        }
        gameActionIndex = next
    }

    function openGameActions(game, index) {
        if (!game) return
        gameRail.currentIndex = index
        gameActionGame = game
        loadGameActionCheats(game)
        gameActionCategory = page === "home" ?
                    (homeViewMode === "list" ? homeListCategory : homeZone) : 0
        gameActionIndex = 0
        gameActionMode = "menu"
        gameActionMessage = ""
        gameActionOpen = true
        root.forceActiveFocus()
    }

    function closeGameActions() {
        Qt.inputMethod.reset()
        Qt.inputMethod.hide()
        renameField.focus = false
        gameActionOpen = false
        gameActionGame = null
        gameActionCategory = 0
        gameActionMode = "menu"
        gameActionCheats = []
        gameActionCheatIndex = 0
        gameActionCheatState = "idle"
        gameActionMultiplayerRoster = []
        gameActionMultiplayerState = "idle"
        gameActionMultiplayerWant = false
        gameActionMultiplayerPending = false
        root.forceActiveFocus()
    }

    // The engine keys a game's cheats by the ROM file it launches, so send
    // that when Pegasus exposes it. A scraped display title that differs from
    // the file name would otherwise offer cheats here that the launch could
    // never find. CheatDatabase.normalise drops the directory and extension.
    function cheatGameKeyForGame(game) {
        if (!game) return ""
        try {
            if (game.files && game.files.count > 0) {
                var path = String(game.files.get(0).path || "")
                if (path !== "") return path
            }
        } catch (unavailable) {
        }
        return String(game.title || "")
    }

    function cheatSystemForGame(game) {
        var index = systemIndexForGame(game)
        return index > 0 && index < systemModel.count ?
                    String(systemModel.get(index).folder) : ""
    }

    // PLACEHOLDER gameKey: there is no cross-device-stable game identity
    // reachable from QML yet (that lives Java-side as CheatGameIdentity and
    // is not exposed here today). This deliberately sends the raw TITLE,
    // not cheatGameKeyForGame's file path -- a path is per-device and
    // would never match between two different players' copies of the same
    // game, or match the in-game overlay's own key at all (MultiplayerOverlay
    // computes CheatDatabase.key(system, title) from the launch request, so
    // both sides must feed it the same (system, title) pair to land on the
    // same string). The companion endpoint normalizes this the same way via
    // CheatDatabase.key(system, title) server-side -- this wire field is
    // named "gameKey" for the API contract but carries a raw title.
    function multiplayerGameKeyForGame(game) {
        if (!game) return ""
        return String(game.title || "")
    }

    function multiplayerSystemForGame(game) { return cheatSystemForGame(game) }

    function loadGameActionCheats(game) {
        gameActionCheats = []
        gameActionCheatIndex = 0
        var system = cheatSystemForGame(game)
        var key = cheatGameKeyForGame(game)
        if (system === "" || key === "") {
            gameActionCheatState = "ready"
            return
        }
        gameActionCheatState = "loading"
        var request = new XMLHttpRequest()
        request.onreadystatechange = function() {
            if (request.readyState !== XMLHttpRequest.DONE) return
            // The overlay may already have moved to another game; a late reply
            // must never list one game's cheats against another.
            if (root.gameActionGame !== game) return
            if (request.status !== 200) {
                root.gameActionCheatState = "error"
                return
            }
            try {
                var payload = JSON.parse(request.responseText)
                root.gameActionCheats = payload.cheats || []
                root.gameActionCheatState = "ready"
            } catch (malformed) {
                root.gameActionCheatState = "error"
            }
        }
        request.open("GET", "http://127.0.0.1:43821/cheats/list?system=" +
                     encodeURIComponent(system) + "&title=" +
                     encodeURIComponent(key), true)
        request.send()
    }

    function gameActionCheatsLabel() {
        if (gameActionCheatState === "loading") return "CHEATS  •  CHECKING"
        if (gameActionCheatState === "error") return "CHEATS  •  UNAVAILABLE"
        if (!gameActionHasCheats()) return "CHEATS  •  NONE FOR THIS GAME"
        return "CHEATS  •  " + gameActionCheats.length
    }

    function openGameActionCheats() {
        if (!gameActionHasCheats()) return
        gameActionCheatIndex = 0
        cheatList.currentIndex = 0
        gameActionMode = "cheats"
    }

    function moveGameActionCheatSelection(direction) {
        var count = gameActionCheats.length
        if (count <= 0) return
        gameActionCheatIndex = (gameActionCheatIndex + direction + count) % count
        cheatList.currentIndex = gameActionCheatIndex
    }

    // The row is redrawn from the service's answer rather than from what was
    // asked for, so a rejected write cannot leave a switch showing a position
    // the stored selection is not in.
    function toggleGameActionCheat(index) {
        if (index < 0 || index >= gameActionCheats.length) return
        var game = gameActionGame
        var entry = gameActionCheats[index]
        var system = cheatSystemForGame(game)
        var key = cheatGameKeyForGame(game)
        if (system === "" || key === "" || !entry) return
        var wanted = !entry.enabled
        var request = new XMLHttpRequest()
        request.onreadystatechange = function() {
            if (request.readyState !== XMLHttpRequest.DONE) return
            if (root.gameActionGame !== game || request.status !== 200) return
            // Reassigned wholesale: mutating an element in place changes no
            // property QML is watching, and the row would keep its old label.
            var updated = root.gameActionCheats.slice()
            updated[index] = { "id": entry.id, "name": entry.name,
                               "description": entry.description,
                               "enabled": wanted }
            root.gameActionCheats = updated
        }
        request.open("GET", "http://127.0.0.1:43821/cheats/set?system=" +
                     encodeURIComponent(system) + "&title=" +
                     encodeURIComponent(key) + "&id=" +
                     encodeURIComponent(entry.id) + "&enabled=" +
                     (wanted ? "1" : "0"), true)
        request.send()
    }

    // Fetched fresh every time the panel opens -- see the property comment
    // above for why this is never polled while the sheet stays open.
    function openGameActionMultiplayer() {
        gameActionMultiplayerRoster = []
        gameActionMultiplayerState = "loading"
        gameActionMode = "multiplayer"
        var game = gameActionGame
        var key = multiplayerGameKeyForGame(game)
        var system = multiplayerSystemForGame(game)
        requestPreviewJson("multiplayer/roster?gameKey=" + encodeURIComponent(key) +
                     "&system=" + encodeURIComponent(system),
                function(payload) {
                    // The sheet may already have moved to another game by the
                    // time this answer arrives.
                    if (root.gameActionGame !== game) return
                    if (!payload || !payload.entries) {
                        root.gameActionMultiplayerState = "error"
                        return
                    }
                    root.gameActionMultiplayerRoster = payload.entries
                    root.gameActionMultiplayerState = "ready"
                })
    }

    // Optimistic write, same shape as setWidescreenHack above: flip locally,
    // send the request, and only revert if the companion actually refused it.
    // Min/max players are hardcoded to 2/2 for this pass -- a real
    // min/max-player picker UI is deferred, not solved here.
    function setGameActionMultiplayerWant(wanted) {
        if (gameActionMultiplayerPending) return
        var game = gameActionGame
        var key = multiplayerGameKeyForGame(game)
        var system = multiplayerSystemForGame(game)
        var previous = gameActionMultiplayerWant
        gameActionMultiplayerWant = wanted
        gameActionMultiplayerPending = true
        requestPreviewJson("multiplayer/want?gameKey=" + encodeURIComponent(key) +
                     "&system=" + encodeURIComponent(system) + "&want=" +
                     (wanted ? "1" : "0") + "&minPlayers=2&maxPlayers=2",
                function(payload) {
                    root.gameActionMultiplayerPending = false
                    if (root.gameActionGame !== game) return
                    if (!payload || payload.ok !== true) {
                        root.gameActionMultiplayerWant = previous
                        root.requestPreviewEndpoint("sfx?name=error")
                    }
                })
    }

    function beginRenameGame() {
        if (!gameActionGame || gameIdentifier(gameActionGame) === "") {
            gameActionMessage = "This game must be imported by EmuFusion before it can be renamed."
            gameActionMode = "error"
            return
        }
        gameActionMode = "rename"
        renameField.text = displayTitle(gameActionGame)
        Qt.callLater(function() {
            renameField.forceActiveFocus()
            renameField.selectAll()
            Qt.inputMethod.show()
        })
    }

    function submitRenameGame() {
        var title = String(renameField.text || "").trim()
        var identity = gameIdentifier(gameActionGame)
        if (identity === "" || title === "") return
        Qt.inputMethod.hide()
        renameField.focus = false
        gameActionMode = "working"
        gameActionMessage = "RENAMING…"
        var request = new XMLHttpRequest()
        request.onreadystatechange = function() {
            if (request.readyState !== XMLHttpRequest.DONE) return
            if (request.status === 200) {
                root.renamedGameTitles[identity] = title
                root.libraryMutationRevision += 1
                root.libraryIndexReady = false
                root.loadLibraryIndex()
                root.gameActionMessage = "RENAMED"
                root.gameActionMode = "success"
            } else {
                root.gameActionMessage = "RENAME FAILED"
                root.gameActionMode = "error"
            }
        }
        request.open("GET", "http://127.0.0.1:43821/game/rename?id=" +
                     encodeURIComponent(identity) + "&title=" + encodeURIComponent(title), true)
        request.send()
    }

    function submitDeleteGame() {
        var identity = gameIdentifier(gameActionGame)
        if (identity === "") {
            gameActionMessage = "This game must be imported by EmuFusion before it can be deleted."
            gameActionMode = "error"
            return
        }
        gameActionMode = "working"
        gameActionMessage = "DELETING ROM FILE…"
        var request = new XMLHttpRequest()
        request.onreadystatechange = function() {
            if (request.readyState !== XMLHttpRequest.DONE) return
            if (request.status === 200) {
                root.hiddenGameIds[identity] = true
                root.libraryMutationRevision += 1
                root.libraryIndexReady = false
                root.loadLibraryIndex()
                root.gameActionMessage = "ROM FILE DELETED"
                root.gameActionMode = "success"
                gameRail.currentIndex = Math.max(0, Math.min(gameRail.currentIndex,
                                                             activeGameCount - 1))
            } else {
                root.gameActionMessage = "DELETE FAILED"
                root.gameActionMode = "error"
            }
        }
        request.open("GET", "http://127.0.0.1:43821/game/delete?id=" +
                     encodeURIComponent(identity), true)
        request.send()
    }

    function submitRemoveFromList() {
        if (!gameActionAllowsRemoveFromList()) {
            gameActionMessage = "REMOVE FROM LIST IS ONLY AVAILABLE FOR CONTINUE, MOST PLAYED, AND RECENTLY ADDED."
            gameActionMode = "error"
            return
        }
        var identity = behavioralGameIdentifier(gameActionGame)
        if (identity === "") {
            gameActionMessage = "THIS GAME COULD NOT BE IDENTIFIED"
            gameActionMode = "error"
            return
        }
        var allBuckets = removedHomeCategoryGameIds
        var categoryKey = String(gameActionCategory)
        var bucket = allBuckets[categoryKey] || ({})
        bucket[identity] = true
        allBuckets[categoryKey] = bucket
        removedHomeCategoryGameIds = allBuckets
        api.memory.set("lucentRemovedHomeCategoryGameIds", JSON.stringify(allBuckets))
        libraryMutationRevision += 1
        homeListCache = ({})
        if (gameActionCategory === 3)
            rebuildRecentlyAddedModel()
        if (page === "home" && homeViewMode === "list")
            rebuildHomeList()
        gameActionMessage = "REMOVED FROM " + homeShelfName(gameActionCategory)
        gameActionMode = "success"
    }

    function boxAspectForSystem(index) {
        // Width / height for the physical packaging used by each platform.
        // Games within one system always share the same visual canvas.
        var folder = systemModel.get(index).folder
        if (folder === "n64" || folder === "snes") return 1.43
        if (folder === "psx" || folder === "dreamcast") return 1.0
        if (folder === "nds") return 0.86
        if (folder === "ps3") return 0.79
        if (folder === "psp") return 0.58
        if (folder === "gb" || folder === "gba" || folder === "gbc") return 1.0
        return 0.70
    }

    function previewUrl(game, previousGame, nextGame, auxiliaryGame) {
        previewRequestSequence += 1
        currentBottomPreviewSequence = previewRequestSequence
        var video = videoSource(game)
        var art = game ? artwork(game) : ""
        var title = game ? displayTitle(game) : ""
        var gameSystemIndex = systemIndexForGame(game)
        var systemName = gameSystemIndex >= 0 ? systemModel.get(gameSystemIndex).name : ""
        var score = game ? scoreText(game) : ""
        return "http://127.0.0.1:43821/play?seq=" + previewRequestSequence +
                "&video=" + encodeURIComponent(video) +
                "&art=" + encodeURIComponent(art) +
                "&title=" + encodeURIComponent(title) +
                "&system=" + encodeURIComponent(systemName) +
                "&score=" + encodeURIComponent(score) +
                "&advance=" + (randomHomePreviewActive() ? "1" : "0") +
                "&preload_prev=" + encodeURIComponent(videoSource(previousGame)) +
                "&preload_next=" + encodeURIComponent(videoSource(nextGame)) +
                "&preload_aux=" + encodeURIComponent(videoSource(auxiliaryGame))
    }

    function sendBottomPreview(game, previousGame, nextGame, auxiliaryGame) {
        if (gameplayActive) return
        if (previewPlacementMode === "off") {
            currentBottomPreviewGame = null
            currentBottomPreviewSequence = 0
            singleCurrentSlot = -1
            requestPreviewEndpoint("blank")
            return
        }
        if (!useBottomPreview()) {
            currentBottomPreviewGame = null
            currentBottomPreviewSequence = 0
            requestPreviewEndpoint("blank")
            setSingleScreenPreview(videoSource(game), videoSource(previousGame),
                                   videoSource(nextGame))
            return
        }
        currentBottomPreviewGame = game
        var url = previewUrl(game, previousGame, nextGame, auxiliaryGame)
        var request = new XMLHttpRequest()
        request.open("GET", url, true)
        request.send()
    }

    // The row the preview is showing: the random showcase pick while the system
    // column owns focus, otherwise the highlighted row itself. Keeping this
    // separate from the rail's currentIndex is what lets the visible list stay
    // pinned to the top of the sort while the preview still rotates.
    function homeListPreviewRow() {
        if (homeListFocusColumn === 0 && homeListPreviewIndex >= 0 &&
                homeListPreviewIndex < homeListEntries.length)
            return homeListPreviewIndex
        return homeListRail.currentIndex
    }

    /**
     * Keys that belong to Android, never to the theme.
     *
     * Qt maps the hardware rocker to Qt.Key_VolumeUp/Down, but the Thor's two
     * volume buttons sit on different input devices and some builds surface
     * them only by native scan code (115 up, 114 down), so both are checked.
     */
    function isPlatformVolumeKey(event) {
        return event.key === Qt.Key_VolumeUp || event.key === Qt.Key_VolumeDown ||
                event.key === Qt.Key_VolumeMute ||
                event.nativeScanCode === 114 || event.nativeScanCode === 115
    }

    function randomHomePreviewActive() {
        return !gameplayActive && page === "home" &&
                ((homeViewMode === "covers" && homeZone === 0) ||
                 (homeViewMode === "list" && homeListFocusColumn === 0))
    }

    function advanceRandomHomePreview() {
        if (gameplayActive || page !== "home") return
        if (homeViewMode === "list" && homeListFocusColumn === 0) {
            if (homeListEntries.length <= 1) {
                activateHomeListPreview()
                return
            }
            // Advance the showcase pick only. Moving the rail here is what made
            // the visible list drift while the user was still on the systems.
            var previous = homeListPreviewRow()
            var next = Math.floor(Math.random() * (homeListEntries.length - 1))
            if (next >= previous) ++next
            homeListPreviewIndex = next
            activateHomeListPreview()
        } else if (homeViewMode === "covers" && homeZone === 0) {
            activateHomePreview(true)
        }
    }

    function useBottomPreview() {
        if (!dualScreenDevice) return false
        return previewPlacementMode === "auto" || previewPlacementMode === "bottom"
    }

    function requestPreviewEndpoint(endpoint) {
        var request = new XMLHttpRequest()
        request.open("GET", "http://127.0.0.1:43821/" + endpoint, true)
        request.send()
    }

    function pollBottomLaunchRequest() {
        if (gameplayActive || launchPollPending || !useBottomPreview() || !currentBottomPreviewGame)
            return
        launchPollPending = true
        var request = new XMLHttpRequest()
        request.onreadystatechange = function() {
            if (request.readyState !== XMLHttpRequest.DONE)
                return
            root.launchPollPending = false
            if (root.gameplayActive) return
            if (request.status !== 200)
                return
            try {
                var payload = JSON.parse(request.responseText)
                var requestedSequence = Number(payload.seq || 0)
                if (requestedSequence > 0 &&
                        requestedSequence === root.currentBottomPreviewSequence &&
                        root.currentBottomPreviewGame)
                    root.launch(root.currentBottomPreviewGame)
                var completedSequence = Number(payload.completedSeq || 0)
                if (completedSequence > 0 &&
                        completedSequence === root.currentBottomPreviewSequence &&
                        root.randomHomePreviewActive())
                    Qt.callLater(function() { root.advanceRandomHomePreview() })
            } catch (error) {
                // A missing optional companion must never affect navigation.
            }
        }
        request.open("GET", "http://127.0.0.1:43821/launch/status", true)
        request.send()
    }

    function refreshCurrentPreview() {
        if (gameplayActive || Qt.application.state !== Qt.ApplicationActive) return
        if (previewPlacementMode === "off") {
            singleCurrentSlot = -1
            currentBottomPreviewGame = null
            currentBottomPreviewSequence = 0
            requestPreviewEndpoint("blank")
            return
        }
        if (!useBottomPreview())
            requestPreviewEndpoint("blank")
        else
            singleCurrentSlot = -1
        if (page === "home" && homeViewMode === "list")
            activateHomeListPreview()
        else if (page === "home" && homeZone === 0)
            activateHomePreview(false)
        else if (page === "games")
            activateGamePreview()
        else
            activateShelfPreview(homeZone)
    }

    function cyclePreviewPlacement(direction) {
        var modes = dualScreenDevice ? ["auto", "bottom", "top", "off"] :
                                       ["auto", "top", "off"]
        var current = modes.indexOf(previewPlacementMode)
        if (current < 0) current = 0
        previewPlacementMode = modes[(current + direction + modes.length) % modes.length]
        api.memory.set("thoriumPreviewPlacement", previewPlacementMode)
        refreshCurrentPreview()
    }

    function setPreviewSoundEnabled(enabled) {
        previewSoundEnabled = Boolean(enabled)
        api.memory.set("thoriumPreviewSound", previewSoundEnabled)
        requestPreviewEndpoint("settings/sound?enabled=" +
                (previewSoundEnabled ? "1" : "0"))
    }

    function applyWidescreenStatus(payload) {
        if (!payload || payload.widescreenEnhancements === undefined) return false
        widescreenEnhancementsEnabled = Boolean(payload.widescreenEnhancements)
        api.memory.set("emufusionWidescreenEnhancements",
                widescreenEnhancementsEnabled)
        return true
    }

    function refreshWidescreenEnhancements() {
        requestPreviewJson("settings/widescreen", function(payload) {
            root.widescreenEnhancementsPending = false
            root.applyWidescreenStatus(payload)
        })
    }

    function setWidescreenEnhancements(enabled) {
        if (widescreenEnhancementsPending) return
        widescreenEnhancementsPending = true
        requestPreviewJson("settings/widescreen?enabled=" + (enabled ? "1" : "0"),
                function(payload) {
                    root.widescreenEnhancementsPending = false
                    if (!root.applyWidescreenStatus(payload))
                        root.requestPreviewEndpoint("sfx?name=error")
                })
    }

    function applyWidescreenHackStatus(payload) {
        if (!payload || payload.hackEnabled === undefined) return false
        widescreenHackEnabled = Boolean(payload.hackEnabled)
        api.memory.set("emufusionWidescreenHack", widescreenHackEnabled)
        return true
    }

    function refreshWidescreenHack() {
        requestPreviewJson("settings/widescreen-hack", function(payload) {
            root.widescreenHackPending = false
            root.applyWidescreenHackStatus(payload)
        })
    }

    function setWidescreenHack(enabled) {
        if (widescreenHackPending) return
        widescreenHackPending = true
        requestPreviewJson("settings/widescreen-hack?enabled=" + (enabled ? "1" : "0"),
                function(payload) {
                    root.widescreenHackPending = false
                    if (!root.applyWidescreenHackStatus(payload))
                        root.requestPreviewEndpoint("sfx?name=error")
                })
    }

    function normalizedFrameGenerationMode(value) {
        value = String(value || "").toLowerCase()
        return value === "built-in-alpha" || value === "lsfg" ? value : "off"
    }

    function frameGenerationModeLabel() {
        if (frameGenerationMode === "built-in-alpha") return "BUILT-IN (ALPHA)"
        if (frameGenerationMode === "lsfg") return "LSFG"
        return "OFF"
    }

    function setFrameGenerationMode(mode) {
        var requested = normalizedFrameGenerationMode(mode)
        frameGenerationRequestSequence += 1
        var sequence = frameGenerationRequestSequence
        frameGenerationModePending = true
        frameGenerationModeConfirmed = false
        frameGenerationRequestedMode = requested
        var request = new XMLHttpRequest()
        request.onreadystatechange = function() {
            if (request.readyState !== XMLHttpRequest.DONE ||
                    sequence !== root.frameGenerationRequestSequence)
                return
            var confirmed = ""
            if (request.status === 200) {
                try {
                    var status = JSON.parse(request.responseText)
                    confirmed = normalizedFrameGenerationMode(
                            status.frameGenerationMode)
                } catch (error) {
                    confirmed = ""
                }
            }
            root.frameGenerationModePending = false
            if (confirmed !== requested) {
                root.frameGenerationModeConfirmed = false
                root.frameGenerationPendingLaunch = null
                root.requestPreviewEndpoint("sfx?name=error")
                root.refreshFrameGenerationStatus()
                return
            }
            root.frameGenerationMode = confirmed
            root.frameGenerationModeConfirmed = true
            api.memory.set("lucentFrameGenerationModeV3", confirmed)
            api.memory.set("lucentFrameGenerationThreeModeV3", true)
            var pendingGame = root.frameGenerationPendingLaunch
            root.frameGenerationPendingLaunch = null
            if (pendingGame) root.launchConfirmed(pendingGame)
        }
        request.open("GET", "http://127.0.0.1:43821/settings/frame-generation?mode=" +
                     requested, true)
        request.send()
    }

    function cycleFrameGenerationMode(direction) {
        if (frameGenerationModePending) return
        var modes = ["off", "built-in-alpha", "lsfg"]
        var current = modes.indexOf(frameGenerationMode)
        if (current < 0) current = 0
        var step = direction < 0 ? -1 : 1
        setFrameGenerationMode(modes[(current + step + modes.length) % modes.length])
    }

    function refreshFrameGenerationStatus() {
        frameGenerationRequestSequence += 1
        var sequence = frameGenerationRequestSequence
        frameGenerationModePending = true
        frameGenerationModeConfirmed = false
        var request = new XMLHttpRequest()
        request.onreadystatechange = function() {
            if (request.readyState !== XMLHttpRequest.DONE ||
                    sequence !== root.frameGenerationRequestSequence)
                return
            root.frameGenerationModePending = false
            if (request.status !== 200) {
                root.frameGenerationModeConfirmed = false
                root.frameGenerationPendingLaunch = null
                return
            }
            try {
                var status = JSON.parse(request.responseText)
                if (status.frameGenerationMode === undefined) return
                var confirmed = normalizedFrameGenerationMode(
                        status.frameGenerationMode)
                root.frameGenerationMode = confirmed
                root.frameGenerationModeConfirmed = true
                api.memory.set("lucentFrameGenerationModeV3", confirmed)
                var pendingGame = root.frameGenerationPendingLaunch
                root.frameGenerationPendingLaunch = null
                if (pendingGame) root.launchConfirmed(pendingGame)
            } catch (error) {
                root.frameGenerationModeConfirmed = false
                root.frameGenerationPendingLaunch = null
            }
        }
        request.open("GET", "http://127.0.0.1:43821/settings/frame-generation", true)
        request.send()
    }

    function setScreensaverEnabled(enabled) {
        screensaverEnabled = Boolean(enabled)
        api.memory.set("lucentScreensaverEnabled", screensaverEnabled)
        if (!screensaverEnabled && screensaverActive)
            stopScreensaver()
        screensaverTopStillSince = Date.now()
    }

    function noteScreensaverVisualChange() {
        screensaverTopStillSince = Date.now()
    }

    function shuffledScreensaverGames() {
        // Build from the complete video library, not the current system or the
        // lower screen's current selection. A source is included once even if
        // duplicate metadata rows point at the same file.
        var games = []
        var seen = ({})
        for (var index = 0; index < api.allGames.count; ++index) {
            var game = api.allGames.get(index)
            var source = videoSource(game)
            if (source === "" || seen[source]) continue
            seen[source] = true
            games.push(game)
        }
        // Fisher-Yates gives every ordering the same probability. Picking one
        // random start and scanning forward made the same nearby title recur.
        for (var remaining = games.length - 1; remaining > 0; --remaining) {
            var chosen = Math.floor(Math.random() * (remaining + 1))
            var swap = games[remaining]
            games[remaining] = games[chosen]
            games[chosen] = swap
        }
        var last = api.memory.has("lucentScreensaverLastVideo") ?
                String(api.memory.get("lucentScreensaverLastVideo")) : ""
        if (games.length > 1 && videoSource(games[0]) === last) {
            var replacement = 1 + Math.floor(Math.random() * (games.length - 1))
            var first = games[0]
            games[0] = games[replacement]
            games[replacement] = first
        }
        return games
    }

    function nextScreensaverGame(newActivation) {
        if (newActivation || screensaverDeckIndex >= screensaverDeck.length) {
            screensaverDeck = shuffledScreensaverGames()
            screensaverDeckIndex = 0
        }
        if (screensaverDeckIndex >= screensaverDeck.length) return null
        return screensaverDeck[screensaverDeckIndex++]
    }

    function peekScreensaverVideo() {
        return screensaverDeckIndex < screensaverDeck.length ?
                    videoSource(screensaverDeck[screensaverDeckIndex]) : ""
    }

    function screensaverSystemName(game) {
        var index = systemIndexForGame(game)
        return index >= 0 && index < systemModel.count ?
                    String(systemModel.get(index).name || "") : ""
    }

    function requestScreensaverGame(game, initial, generation) {
        if (gameplayActive || !game || screensaverRequestPending) return
        var source = videoSource(game)
        if (source === "") return
        var title = displayTitle(game)
        var system = screensaverSystemName(game)
        var score = scoreText(game)
        var art = artwork(game)
        var preloadNext = peekScreensaverVideo()
        screensaverRequestPending = true
        var request = new XMLHttpRequest()
        request.onreadystatechange = function() {
            if (request.readyState !== XMLHttpRequest.DONE) return
            if (generation !== root.screensaverGeneration) return
            root.screensaverRequestPending = false
            if (request.status !== 200 || !root.screensaverEnabled || root.gameplayActive) {
                if (!root.gameplayActive && !initial && root.screensaverActive)
                    screensaverAdvanceRetry.restart()
                return
            }
            root.screensaverPendingGame = game
            root.screensaverPendingSlot = root.screensaverCurrentSlot === 0 ? 1 : 0
            if (root.screensaverPendingSlot === 0)
                root.screensaverSourceA = source
            else
                root.screensaverSourceB = source
            root.screensaverActive = true
        }
        request.open("GET", "http://127.0.0.1:43821/screensaver/play?video=" +
                     encodeURIComponent(source) +
                     "&art=" + encodeURIComponent(art) +
                     "&title=" + encodeURIComponent(title) +
                     "&system=" + encodeURIComponent(system) +
                     "&score=" + encodeURIComponent(score) +
                     "&preload_next=" + encodeURIComponent(preloadNext), true)
        request.send()
    }

    function promoteScreensaverSlot(slot) {
        if (!screensaverActive || slot !== screensaverPendingSlot ||
                !screensaverPendingGame) return
        screensaverCurrentSlot = slot
        screensaverGame = screensaverPendingGame
        screensaverPendingGame = null
        screensaverPendingSlot = -1
        api.memory.set("lucentScreensaverLastVideo", videoSource(screensaverGame))
    }

    function advanceScreensaverVideo() {
        if (gameplayActive || !screensaverActive || screensaverRequestPending ||
                screensaverPendingSlot >= 0) return
        var game = nextScreensaverGame(false)
        if (!game) return
        requestScreensaverGame(game, false, screensaverGeneration)
    }

    function screensaverPlaybackFinished() {
        if (gameplayActive || !screensaverActive || screensaverRequestPending ||
                screensaverPendingSlot >= 0 || screensaverCurrentSlot < 0)
            return false
        var player = screensaverCurrentSlot === 0 ?
                    screensaverVideoA : screensaverVideoB
        if (!player || player.source === "") return false
        // Some Qt/Android media backends reach EndOfMedia and retain the final
        // decoded frame without delivering Video.onStopped. Position is an
        // independent bounded fallback for those backends. Never use a generic
        // Stopped state here: a decoder preparing or buffering the next random
        // item is not evidence that the current item completed.
        if (player.status === MediaPlayer.EndOfMedia) return true
        return player.duration > 0 && player.position >= player.duration - 250
    }

    function beginScreensaver(payload) {
        if (!screensaverEnabled || screensaverActive || screensaverRequestPending ||
                gameplayActive || Qt.application.state !== Qt.ApplicationActive)
            return
        if (!payload || payload.browserActive || payload.gameplay || !payload.available)
            return
        var topStill = Date.now() - screensaverTopStillSince
        var lowerStill = Number(payload.visualIdleMs || 0)
        // A dual-screen session is idle only when BOTH displays have been
        // still for the full timeout.  Using && here meant one stale lower
        // panel defeated fresh top-panel input: the five-second watchdog could
        // immediately restart the screensaver and randomize the active game
        // row while the user was navigating on top (physical N64 r5-r7).
        if (topStill < screensaverStillTimeoutMs || lowerStill < screensaverStillTimeoutMs)
            return

        // Every activation starts a freshly shuffled deck. It intentionally
        // ignores payload.video: mirroring the current lower preview is what
        // made the screensaver start on the same selected game every time.
        var game = nextScreensaverGame(true)
        if (!game) return
        ++screensaverGeneration
        requestScreensaverGame(game, true, screensaverGeneration)
    }

    function stopScreensaver(resumePreview) {
        if (!screensaverActive && !screensaverRequestPending) return
        screensaverActive = false
        screensaverRequestPending = false
        ++screensaverGeneration
        screensaverDeck = []
        screensaverDeckIndex = 0
        screensaverGame = null
        screensaverPendingGame = null
        screensaverCurrentSlot = -1
        screensaverPendingSlot = -1
        screensaverSourceA = ""
        screensaverSourceB = ""
        screensaverTopStillSince = Date.now()
        // Restore the current library selection and the user's normal preview
        // placement. Off returns the lower display to black; Bottom/Automatic
        // restores its title chrome and warm neighbours.
        if (resumePreview !== false && !gameplayActive)
            Qt.callLater(function() { root.refreshCurrentPreview() })
    }

    function pollScreensaverStatus() {
        if (!screensaverEnabled || screensaverActive || screensaverRequestPending ||
                gameplayActive || Qt.application.state !== Qt.ApplicationActive)
            return
        requestPreviewJson("screensaver/status", function(payload) {
            root.beginScreensaver(payload)
        })
    }

    function setSoundEffectsEnabled(enabled) {
        soundEffectsEnabled = Boolean(enabled)
        api.memory.set("lucentSoundEffects", soundEffectsEnabled)
        requestPreviewEndpoint("settings/sfx?enabled=" +
                (soundEffectsEnabled ? "1" : "0"))
    }

    function setSingleScreenMediaSwapped(swapped) {
        if (dualScreenDevice) return
        singleScreenMediaSwapped = Boolean(swapped)
        api.memory.set("lucentSingleScreenMediaSwapped", singleScreenMediaSwapped)
    }

    function validatedCoverRowOrder(value) {
        var candidate = value
        if (typeof value === "string") {
            try { candidate = JSON.parse(value) } catch (error) { candidate = [] }
        }
        if (!candidate || candidate.length === undefined) candidate = []
        var output = []
        for (var index = 0; index < candidate.length; ++index) {
            var zone = Number(candidate[index])
            if (zone >= 0 && zone <= 7 && output.indexOf(zone) < 0)
                output.push(zone)
        }
        for (var missing = 0; missing <= 7; ++missing) {
            if (output.indexOf(missing) < 0) output.push(missing)
        }
        return output
    }

    // Lists must show whole rows only: a half-drawn row at a viewport edge
    // reads as a rendering fault. These two answer "how many rows fit" and
    // "how tall may they then be", so reclaimed height becomes another row --
    // or taller rows once no further row fits -- and never a gap beneath the
    // last one. A list whose stride is fixed by a paging contract passes the
    // same value for minimum and maximum, so only its row count adapts.
    function listRowCount(available, minimum, spacing) {
        return Math.max(1, Math.floor((available + spacing) / (minimum + spacing)))
    }

    function listRowHeight(available, minimum, maximum, spacing) {
        var rows = listRowCount(available, minimum, spacing)
        return Math.max(minimum, Math.min(maximum,
                Math.floor((available + spacing) / rows) - spacing))
    }

    function setCoverViewRowCount(value) {
        coverViewRowCount = Math.max(1, Math.min(3, Math.round(Number(value))))
        api.memory.set("lucentCoverViewRowCount", coverViewRowCount)
    }

    function coverZonePosition(zone) {
        var position = coverRowOrder.indexOf(Number(zone))
        return position < 0 ? Number(zone) : position
    }

    function coverWindowStart() {
        var rows = Math.max(1, Math.min(3, coverViewRowCount))
        var position = coverZonePosition(homeZone)
        var centered = position - Math.floor((rows - 1) / 2)
        return Math.max(0, Math.min(8 - rows, centered))
    }

    function coverZoneVisible(zone) {
        if (page !== "home" || homeViewMode !== "covers") return false
        var position = coverZonePosition(zone)
        var start = coverWindowStart()
        return position >= start && position < start + coverViewRowCount
    }

    function stepCoverZone(direction) {
        var position = coverZonePosition(homeZone)
        var next = Math.max(0, Math.min(coverRowOrder.length - 1,
                                       position + (direction < 0 ? -1 : 1)))
        focusHomeZone(Number(coverRowOrder[next]))
    }

    function coverRowName(zone) {
        if (zone === 0) return "SYSTEMS"
        return homeShelfName(zone)
    }

    function coverVerticalNavigationText() {
        var position = coverZonePosition(homeZone)
        var directions = []
        if (position > 0)
            directions.push("UP  ↑  " + coverRowName(Number(coverRowOrder[position - 1])))
        if (position < coverRowOrder.length - 1)
            directions.push("DOWN  ↓  " + coverRowName(Number(coverRowOrder[position + 1])))
        return directions.join("      •      ")
    }

    function openCoverOrderEditor() {
        coverOrderEditorIndex = Math.max(0, coverZonePosition(homeZone))
        coverOrderEditorOpen = true
        settingsOpen = false
    }

    function moveCoverOrderItem(direction) {
        var target = Math.max(0, Math.min(coverRowOrder.length - 1,
                                         coverOrderEditorIndex + direction))
        if (target === coverOrderEditorIndex) return
        var updated = coverRowOrder.slice(0)
        var held = updated[coverOrderEditorIndex]
        updated[coverOrderEditorIndex] = updated[target]
        updated[target] = held
        coverRowOrder = updated
        coverOrderEditorIndex = target
        api.memory.set("lucentCoverRowOrder", JSON.stringify(coverRowOrder))
    }

    function previewPlacementLabel() {
        if (previewPlacementMode === "bottom") return "LOWER DISPLAY"
        if (previewPlacementMode === "top") return "TOP-RIGHT PIP"
        if (previewPlacementMode === "off") return "OFF"
        return dualScreenDevice ? "AUTOMATIC (LOWER)" : "AUTOMATIC (PIP)"
    }

    function pollUpdateStatus() {
        var request = new XMLHttpRequest()
        request.onreadystatechange = function() {
            if (request.readyState !== XMLHttpRequest.DONE || request.status !== 200)
                return
            try {
                var payload = JSON.parse(request.responseText)
                root.updateStatusMessage = String(payload.message || "")
                if (Boolean(payload.installReady) && !root.updatePromptDismissed) {
                    root.updatePromptChoice = 0
                    root.updatePromptOpen = true
                    root.forceActiveFocus()
                }
            } catch (error) {
                // The updater is optional while an older package is migrating.
            }
        }
        request.open("GET", "http://127.0.0.1:43821/update/status", true)
        request.send()
    }

    function installReadyUpdate() {
        updatePromptOpen = false
        requestPreviewEndpoint("update/install")
    }

    function dismissReadyUpdate() {
        updatePromptDismissed = true
        updatePromptOpen = false
        root.forceActiveFocus()
    }

    function voiceFeedbackContextTitle() {
        return root.activeGame ? root.displayTitle(root.activeGame) : ""
    }

    function voiceFeedbackContextSystem() {
        if (root.displaySystemIndex < 0 || root.displaySystemIndex >= systemModel.count)
            return ""
        return String(systemModel.get(root.displaySystemIndex).name || "")
    }

    function startVoiceFeedback() {
        root.endSearch()
        root.voiceFeedbackOpen = true
        root.voiceFeedbackState = "requesting-permission"
        root.voiceFeedbackTranscript = ""
        root.voiceFeedbackMessage = "Waiting for microphone permission…"
        root.voiceFeedbackGithubOpened = false
        root.voiceFeedbackChoice = 0
        var request = new XMLHttpRequest()
        request.onreadystatechange = function() {
            if (request.readyState !== XMLHttpRequest.DONE) return
            if (request.status !== 202) {
                root.voiceFeedbackState = "error"
                root.voiceFeedbackMessage = "Voice recording could not start. Tap Redo to try again."
            }
            root.pollVoiceFeedback()
        }
        request.open("GET", "http://127.0.0.1:43821/feedback/record?title=" +
                     encodeURIComponent(voiceFeedbackContextTitle()) + "&system=" +
                     encodeURIComponent(voiceFeedbackContextSystem()) + "&page=" +
                     encodeURIComponent(String(root.page || "library")), true)
        request.send()
        voiceFeedbackStatusPoll.restart()
        root.forceActiveFocus()
    }

    function pollVoiceFeedback() {
        var request = new XMLHttpRequest()
        request.onreadystatechange = function() {
            if (request.readyState !== XMLHttpRequest.DONE || request.status !== 200)
                return
            try {
                var payload = JSON.parse(request.responseText)
                root.voiceFeedbackState = String(payload.state || "idle")
                root.voiceFeedbackTranscript = String(payload.transcript || "")
                root.voiceFeedbackMessage = String(payload.message || "")
                root.voiceFeedbackGithubOpened = Boolean(payload.githubComposerOpened)
                if (root.voiceFeedbackState === "requesting-permission" ||
                        root.voiceFeedbackState === "listening")
                    voiceFeedbackStatusPoll.restart()
            } catch (error) {
                root.voiceFeedbackState = "error"
                root.voiceFeedbackMessage = "The feedback service returned an invalid response."
            }
        }
        request.open("GET", "http://127.0.0.1:43821/feedback/status", true)
        request.send()
    }

    function sendVoiceFeedback() {
        if (root.voiceFeedbackState !== "ready" &&
                root.voiceFeedbackState !== "github-review") return
        root.voiceFeedbackMessage = "Opening GitHub's secure issue review…"
        var request = new XMLHttpRequest()
        request.onreadystatechange = function() {
            if (request.readyState !== XMLHttpRequest.DONE) return
            try {
                var payload = JSON.parse(request.responseText)
                root.voiceFeedbackState = String(payload.state ||
                        (request.status === 202 ? "github-review" : "error"))
                root.voiceFeedbackMessage = String(payload.message ||
                        (request.status === 202 ? "GitHub opened for final confirmation." :
                         "GitHub could not be opened."))
                root.voiceFeedbackGithubOpened = Boolean(payload.githubComposerOpened)
            } catch (error) {
                root.voiceFeedbackState = "error"
                root.voiceFeedbackMessage = "GitHub could not be opened. The transcription is still here."
            }
        }
        request.open("GET", "http://127.0.0.1:43821/feedback/send?transcript=" +
                     encodeURIComponent(root.voiceFeedbackTranscript), true)
        request.send()
    }

    function closeVoiceFeedback() {
        if (root.voiceFeedbackState === "requesting-permission" ||
                root.voiceFeedbackState === "listening")
            requestPreviewEndpoint("feedback/cancel")
        root.voiceFeedbackOpen = false
        voiceFeedbackStatusPoll.stop()
        Qt.inputMethod.hide()
        root.forceActiveFocus()
    }

    function colorByteHex(value) {
        var text = Math.max(0, Math.min(255, Math.round(value * 255))).toString(16)
        return text.length < 2 ? "0" + text : text
    }

    function selectedLedColor() {
        // Exactly the resolved accent the chrome is drawn with - family,
        // system, or the game's precomputed wallpaper complement - so the
        // sticks are never an approximation of what is on screen.
        return colorByteHex(accent.r) + colorByteHex(accent.g) + colorByteHex(accent.b)
    }

    function applySystemLedColor() {
        if (!systemLedEnabled) return
        var hardwareBrightness = Math.round(255 * systemLedBrightness / 100)
        requestPreviewEndpoint("led?enabled=1&brightness=" +
                hardwareBrightness +
                "&color=" + selectedLedColor())
    }

    function setSystemLedEnabled(enabled) {
        systemLedEnabled = Boolean(enabled)
        api.memory.set("lucentSystemLedEnabled", systemLedEnabled)
        if (systemLedEnabled)
            systemLedCommit.restart()
        else
            requestPreviewEndpoint("led?enabled=0")
    }

    function setSystemLedBrightness(value) {
        var clamped = Math.max(1, Math.min(100, Number(value)))
        systemLedBrightness = Math.round(clamped)
        api.memory.set("lucentSystemLedBrightness", systemLedBrightness)
        if (systemLedEnabled)
            systemLedCommit.restart()
    }

    function setSystemLedUseDeviceBrightness(enabled) {
        // Compatibility target for the inert legacy row. The active UI always
        // uses the explicit one-percent-through-100-percent control.
        systemLedUseDeviceBrightness = false
        if (enabled) setSystemLedBrightness(1)
    }

    function startViewOptions() {
        var options = ["cover", "list", "all"]
        for (var index = 1; index < systemModel.count; ++index)
            options.push("system:" + String(systemModel.get(index).folder))
        return options
    }

    function startViewLabel(value) {
        if (value === "cover") return "COVER VIEW"
        if (value === "list") return "LIST VIEW"
        if (value === "all") return "ALL SYSTEMS VIEW"
        if (String(value).indexOf("system:") === 0) {
            var folder = String(value).substring(7)
            for (var index = 1; index < systemModel.count; ++index) {
                if (String(systemModel.get(index).folder) === folder)
                    return String(systemModel.get(index).name) + " VIEW"
            }
        }
        return "COVER VIEW"
    }

    function cycleStartView(direction) {
        var options = startViewOptions()
        var current = options.indexOf(startViewPreference)
        if (current < 0) current = 0
        var step = direction < 0 ? -1 : 1
        startViewPreference = options[(current + step + options.length) % options.length]
        api.memory.set("lucentStartView", startViewPreference)
    }

    function configuredStartSystemIndex() {
        if (String(startViewPreference).indexOf("system:") !== 0) return 0
        var folder = String(startViewPreference).substring(7)
        for (var index = 1; index < systemModel.count; ++index) {
            if (String(systemModel.get(index).folder) === folder) return index
        }
        return 0
    }

    function applyConfiguredStartView() {
        if (startViewPreference === "list") {
            page = "home"
            homeViewMode = "list"
            homeZone = 1
            homeListCategory = 1
            homeListFocusColumn = 0
            systemRail.currentIndex = 0
            return
        }
        if (startViewPreference === "all" ||
                String(startViewPreference).indexOf("system:") === 0) {
            activeSystemIndex = configuredStartSystemIndex()
            allSystemsActive = activeSystemIndex === 0
            activeCollection = allSystemsActive ? null : collectionAtSystem(activeSystemIndex)
            systemRail.currentIndex = activeSystemIndex
            activateCachedSystemSort()
            page = "games"
            gameRail.currentIndex = 0
            return
        }
        page = "home"
        homeViewMode = "covers"
        homeZone = 0
    }

    function homeSystemStatsText() {
        var index = Math.max(0, systemRail.currentIndex)
        if (index === 0)
            return romGameCount() + " TITLES  •  " + Math.max(0, systemModel.count - 1) +
                    " SYSTEMS  •  ONE UNIFIED LIBRARY"
        return systemGameCount(index) + " TITLES  •  " +
                String(systemModel.get(index).years) + "  •  DIRECT LAUNCH READY"
    }

    function homeSystemInstructionText() {
        if (homeListFocusColumn === 0)
            return homeShelfName(homeListCategory) +
                    "  •  RANDOM PREVIEW  •  A  SELECT SYSTEM"
        return homeShelfName(homeListCategory) +
                "  •  A  PLAY  •  B  BACK TO SYSTEM LIST"
    }

    function useWhiteBrandLogo(index) {
        if (brandSlugForSystem(index) !== "nintendo") return false
        // The red wordmark only needs replacing when it would actually vanish,
        // so measure the distance to it rather than testing a hand-tuned box.
        // The old r>0.62 && g<0.42 && b<0.42 test caught accents that merely
        // leaned warm -- the NES sat inside it and lost its red mark while
        // every other Nintendo system kept one, which read as a bug rather
        // than as contrast protection.
        var color = root.accent
        var dr = color.r - 0.90   // Nintendo red, #e60012
        var dg = color.g - 0.00
        var db = color.b - 0.07
        return Math.sqrt(dr * dr + dg * dg + db * db) < 0.30
    }

    function setRightStickViewSwitching(enabled) {
        rightStickViewSwitchingEnabled = Boolean(enabled)
        api.memory.set("lucentRightStickViewSwitching",
                       rightStickViewSwitchingEnabled)
    }

    function setViewTransitions(enabled) {
        viewTransitionsEnabled = Boolean(enabled)
        api.memory.set("lucentViewTransitions", viewTransitionsEnabled)
    }

    function showCoverView() {
        page = "home"
        homeViewMode = "covers"
        homeZone = 0
        homeListFocusColumn = 0
        api.memory.set("thoriumHomeView", homeViewMode)
        scheduleNavigationPersistence()
        chooseSystemWallpaper(systemRail.currentIndex)
        Qt.callLater(function() { root.activateHomePreview(false) })
        root.forceActiveFocus()
    }

    function showListView() {
        page = "home"
        homeViewMode = "list"
        homeListCategory = Math.max(1, Math.min(7, homeListCategory))
        homeZone = homeListCategory
        homeListFocusColumn = 0
        api.memory.set("thoriumHomeView", homeViewMode)
        scheduleNavigationPersistence()
        rebuildHomeList()
        root.forceActiveFocus()
    }

    function showAllSystemsView() {
        openSystemInPlace(0)
        page = "games"
        root.forceActiveFocus()
    }

    function handleRightStickViewKey(event) {
        if (!rightStickViewSwitchingEnabled) return false
        if (event.key === Qt.Key_F1) {
            showCoverView()
            return true
        }
        if (event.key === Qt.Key_F2) {
            showListView()
            return true
        }
        if (event.key === Qt.Key_F3 || event.key === Qt.Key_F4) {
            if (page !== "games")
                showAllSystemsView()
            else
                stepOpenSystem(event.key === Qt.Key_F3 ? -1 : 1)
            return true
        }
        return false
    }

    function stepHomeListPage(direction) {
        if (homeListFocusColumn === 0) {
            var systemPage = 9
            systemRail.currentIndex = Math.max(0, Math.min(systemModel.count - 1,
                    systemRail.currentIndex + (direction < 0 ? -systemPage : systemPage)))
            return
        }
        if (homeListEntries.length <= 0) return
        var gamePage = 7
        homeListRail.currentIndex = Math.max(0, Math.min(homeListEntries.length - 1,
                homeListRail.currentIndex + (direction < 0 ? -gamePage : gamePage)))
    }

    // Absolute row index -> slot. Slots 0-15 are common, slot 16 is the
    // single-screen-only PIP row, and slots 17+ are the tail that must stay at
    // the bottom on both device types. Without this the tail would land on top
    // of the PIP row on a dual-screen device.
    function settingSlot(index) {
        if (index < baseSettingsOptionCount) return index
        return Number(settingsTailSlots[index - baseSettingsOptionCount])
    }

    function settingTitle(index) {
        var titles = ["SYSTEM WALLPAPER MODE", "GAME PREVIEW PLACEMENT",
                "PREVIEW VIDEO SOUND", "LIQUID GLASS",
                "ACCENT COLOR GROUPING", "CUSTOMIZE ACCENT COLORS",
                "SYSTEM-MATCHED STICK LEDS", "STICK LED BRIGHTNESS",
                "START VIEW", "COVER VIEW ROWS", "COVER ROW ORDER",
                "RIGHT STICK VIEW SWITCHING", "VIEW TRANSITIONS",
                "SOUND EFFECTS", "ABOUT EMUFUSION", "UPDATE LIBRARY & EMUFUSION",
                "PIP / BOX ART ORDER", "EMULATOR FOR EACH SYSTEM",
                "LEGAL NOTICE", "GAMES WITH NO BOX ART", "VIDEO SCREENSAVER",
                "FRAME GENERATION", "WIDESCREEN ENHANCEMENTS",
                "WIDESCREEN HACK", "PRIVATE DIAGNOSTICS"]
        return titles[settingSlot(index)]
    }

    function settingDescription(index) {
        if (settingSlot(index) === 24) return privateDiagnosticsConfigured ?
                "Opt in: share build, system and error categories; no device IDs or raw logs. Off clears unsent reports." :
                "Private receiver not configured. No reports are collected or sent."
        var descriptions = [
            "Preloaded static angle; rerolls only after you leave",
            "Automatic detects the screen count; choose PIP or Off manually",
            "Sound follows the visible preview; preloaded neighbors stay silent",
            "Optional refractive blur and wallpaper distortion for controls",
            "By platform family, per system, or each game's wallpaper complement",
            "Choose any hue, saturation, and lightness for each active group",
            "Instantly matches the accent of the highlighted system",
            "Manual hardware level from 1–100%; defaults to a subtle 2%",
            "Choose the layout or detected system shown on a fresh launch",
            "Show one large shelf by default, or expose two or three at once",
            "Reorder Systems, Continue, Most Played, Recently Added, and score shelves",
            "Up: Cover  •  Down: List  •  Left/Right: All Systems then systems",
            "Optional slide, fade, and scale motion when changing EmuFusion views",
            "Quiet blips while moving, choosing, and going back in menus",
            "Pegasus attribution, licenses, trademarks, and EmuFusion version",
            "Scan games and check GitHub for app and theme updates",
            "Swap the video and box-art positions on single-screen devices",
            "Run each system built in, or hand it to a standalone emulator",
            "Trademarks, third-party content, and your responsibilities",
            "Choose once per game: keep it, hide it, or delete the ROM",
            "After two still minutes, play one synchronized preview on both screens",
            "Off is a true direct bypass; Built-in is experimental; LSFG is the private beta",
            "Use verified built-in emulator 16:9 options; unsupported systems are unchanged",
            "Off by default: true 16:9 geometry for N64, PS1, PS2, GC, Wii, Dreamcast, PSP"
        ]
        return descriptions[settingSlot(index)]
    }

    function settingValue(index) {
        index = settingSlot(index)
        if (index === 17) return emulatorRoutesSummary()
        if (index === 24) return privateDiagnosticsPending ? "SAVING…" :
                (!privateDiagnosticsConfigured ? "UNAVAILABLE" :
                 (privateDiagnosticsEnabled ? "ON" : "OFF"))
        if (index === 18) return "READ"
        if (index === 19) return artworkReviewCount > 0 ?
                artworkReviewCount + (artworkReviewCount === 1 ? " GAME" : " GAMES") :
                (artworkReviewLoaded ? "NONE" : "CHECK")
        if (index === 20) return screensaverEnabled ? "ON" : "OFF"
        if (index === 21) return frameGenerationModeLabel()
        if (index === 22) return widescreenEnhancementsPending ? "SAVING…" :
                (widescreenEnhancementsEnabled ? "ON" : "OFF")
        if (index === 23) return widescreenHackPending ? "SAVING…" :
                (widescreenHackEnabled ? "ON" : "OFF")
        if (index === 0) return "STATIC"
        if (index === 1) return previewPlacementLabel()
        if (index === 2) return previewSoundEnabled ? "ON" : "OFF"
        if (index === 3) return liquidGlassEnabled ? "ON" : "OFF"
        if (index === 4) return accentGrouping === "system" ? "BY SYSTEM" :
                (accentGrouping === "wallpaper" ? "BY WALLPAPER" : "BY PLATFORM FAMILY")
        if (index === 5) return "EDIT"
        if (index === 6) return systemLedEnabled ? "ON" : "OFF"
        if (index === 7) return systemLedBrightness + "%"
        if (index === 8) return startViewLabel(startViewPreference)
        if (index === 9) return coverViewRowCount + (coverViewRowCount === 1 ? " ROW" : " ROWS")
        if (index === 10) return "EDIT"
        if (index === 11) return rightStickViewSwitchingEnabled ? "ON" : "OFF"
        if (index === 12) return viewTransitionsEnabled ? "ON" : "OFF"
        if (index === 13) return soundEffectsEnabled ? "ON" : "OFF"
        if (index === 14) return "VIEW"
        if (index === 15) return "RUN"
        if (index === 16 && !dualScreenDevice)
            return singleScreenMediaSwapped ? "BOX LEFT  •  VIDEO RIGHT" :
                                              "VIDEO LEFT  •  BOX RIGHT"
        return ""
    }

    function activateSetting(direction) {
        var slot = settingSlot(settingsIndex)
        if (slot === 24) {
            togglePrivateDiagnostics()
            return
        }
        if (slot === 17) {
            openEmulatorRoutes()
            return
        }
        if (slot === 18) {
            openLegalNotice()
            return
        }
        if (slot === 19) {
            openArtworkReview()
            return
        }
        if (slot === 20) {
            setScreensaverEnabled(!screensaverEnabled)
            return
        }
        if (slot === 21) {
            cycleFrameGenerationMode(direction)
            return
        }
        if (slot === 22) {
            setWidescreenEnhancements(!widescreenEnhancementsEnabled)
            return
        }
        if (slot === 23) {
            setWidescreenHack(!widescreenHackEnabled)
            return
        }
        if (settingsIndex === 0) {
            // Static, predecoded system artwork is the sole supported mode.
            systemMotionEnabled = false
            api.memory.set("thoriumSystemMotion", false)
        } else if (settingsIndex === 1) {
            cyclePreviewPlacement(direction === 0 ? 1 : direction)
        } else if (settingsIndex === 2) {
            setPreviewSoundEnabled(!previewSoundEnabled)
        } else if (settingsIndex === 3) {
            liquidGlassEnabled = !liquidGlassEnabled
            api.memory.set("thoriumLiquidGlassEnabled", liquidGlassEnabled)
        } else if (settingsIndex === 4) {
            cycleAccentGrouping(direction === 0 ? 1 : direction)
        } else if (settingsIndex === 5) {
            openAccentEditor()
        } else if (settingsIndex === 6) {
            setSystemLedEnabled(!systemLedEnabled)
        } else if (settingsIndex === 7) {
            setSystemLedBrightness(systemLedBrightness + (direction < 0 ? -1 : 1))
        } else if (settingsIndex === 8) {
            cycleStartView(direction === 0 ? 1 : direction)
        } else if (settingsIndex === 9) {
            var rowStep = direction < 0 ? -1 : 1
            setCoverViewRowCount(((coverViewRowCount - 1 + rowStep + 3) % 3) + 1)
        } else if (settingsIndex === 10) {
            openCoverOrderEditor()
        } else if (settingsIndex === 11) {
            setRightStickViewSwitching(!rightStickViewSwitchingEnabled)
        } else if (settingsIndex === 12) {
            setViewTransitions(!viewTransitionsEnabled)
        } else if (settingsIndex === 13) {
            setSoundEffectsEnabled(!soundEffectsEnabled)
        } else if (settingsIndex === 14) {
            aboutOpen = true
        } else if (settingsIndex === 15) {
            updatePromptDismissed = false
            importState = "idle"
            importStatusInitialized = true
            importToastVisible = true
            startImportScan()
            requestPreviewEndpoint("update/check")
        } else if (settingsIndex === 16 && !dualScreenDevice) {
            setSingleScreenMediaSwapped(!singleScreenMediaSwapped)
        }
    }

    // ---- Emulator routing, legal notice -----------------------------------
    function refreshPrivateDiagnostics() {
        requestPreviewJson("private-diagnostics/status", function(status) {
            root.privateDiagnosticsConfigured = !!status && status.configured === true
            root.privateDiagnosticsEnabled = root.privateDiagnosticsConfigured && status.enabled === true
        })
    }

    function togglePrivateDiagnostics() {
        if (privateDiagnosticsPending || !privateDiagnosticsConfigured) return
        privateDiagnosticsPending = true
        requestPreviewJson("settings/private-diagnostics?enabled=" +
                (privateDiagnosticsEnabled ? "0" : "1"), function(status) {
            root.privateDiagnosticsPending = false
            root.privateDiagnosticsConfigured = !!status && status.configured === true
            root.privateDiagnosticsEnabled = root.privateDiagnosticsConfigured && status.enabled === true
        })
    }

    // Every one of these is demand-driven: opened on a key press, re-read after
    // a change. Nothing here polls. The companion's control port is on the same
    // device as the frontend, and a timer against it is what previously wedged
    // Qt's network thread during gameplay.

    function requestPreviewJson(endpoint, handler) {
        var request = new XMLHttpRequest()
        request.onreadystatechange = function() {
            if (request.readyState !== XMLHttpRequest.DONE) return
            var parsed = null
            if (request.status === 200) {
                try { parsed = JSON.parse(request.responseText) }
                catch (error) { parsed = null }
            }
            handler(parsed)
        }
        request.open("GET", "http://127.0.0.1:43821/" + endpoint, true)
        request.send()
    }

    // ---- Missing box art review -------------------------------------------
    // Read on demand, exactly like the emulator routes above: the list only
    // changes when a maintenance scan runs or the owner answers a row, and a
    // timer against the companion's port is what once wedged Qt's network
    // thread during gameplay.

    function loadArtworkReview(handler) {
        requestPreviewJson("artwork/missing", function(payload) {
            var games = payload && payload.games ? payload.games : []
            root.artworkReviewGames = games
            root.artworkReviewCount = games.length
            root.artworkReviewLoaded = true
            root.artworkReviewIndex = Math.max(0,
                    Math.min(root.artworkReviewIndex, games.length - 1))
            if (handler) handler(games.length)
        })
    }

    function openArtworkReview() {
        artworkReviewIndex = 0
        artworkReviewChoice = 0
        artworkReviewConfirming = false
        artworkReviewBusy = false
        artworkReviewMessage = ""
        artworkReviewOpen = true
        loadArtworkReview(null)
    }

    function closeArtworkReview() {
        artworkReviewOpen = false
        artworkReviewConfirming = false
        artworkReviewBusy = false
    }

    function artworkReviewGame(index) {
        if (index < 0 || index >= artworkReviewGames.length) return null
        return artworkReviewGames[index]
    }

    function artworkReviewChoiceKey(choice) {
        if (choice === 1) return "hide"
        if (choice === 2) return "delete-rom"
        return "leave"
    }

    function artworkReviewChoiceLabel(choice) {
        if (choice === 1) return "REMOVE FROM MENUS"
        if (choice === 2) return "DELETE ROM FILE"
        return "LEAVE AS IS"
    }

    function artworkReviewChoiceDetail(choice) {
        if (choice === 1)
            return "Hidden from every EmuFusion menu. The ROM file stays on storage."
        if (choice === 2)
            return "Permanently erases the ROM file from storage. This cannot be undone."
        return "Stays in the library with a blank cover. You will not be asked again."
    }

    function artworkReviewMoveChoice(direction) {
        if (artworkReviewBusy) return
        // Stepping away from the destructive option must also drop the armed
        // confirmation, so a second A press can never land on it by accident.
        artworkReviewConfirming = false
        artworkReviewChoice = Math.max(0, Math.min(2, artworkReviewChoice + direction))
    }

    function artworkReviewMoveRow(direction) {
        if (artworkReviewBusy) return
        var target = Math.max(0, Math.min(artworkReviewGames.length - 1,
                                          artworkReviewIndex + direction))
        if (target === artworkReviewIndex) return
        artworkReviewIndex = target
        artworkReviewChoice = 0
        artworkReviewConfirming = false
        artworkReviewMessage = ""
    }

    function submitArtworkChoice() {
        if (artworkReviewBusy) return
        var game = artworkReviewGame(artworkReviewIndex)
        if (!game) return
        // Deleting a ROM is the only answer that destroys data, so it is the
        // only one that has to be pressed twice.
        if (artworkReviewChoice === 2 && !artworkReviewConfirming) {
            artworkReviewConfirming = true
            artworkReviewMessage = "PRESS A AGAIN TO PERMANENTLY DELETE THIS ROM"
            return
        }
        var choice = artworkReviewChoiceKey(artworkReviewChoice)
        var key = String(game.key || "")
        if (key === "") return
        artworkReviewBusy = true
        artworkReviewConfirming = false
        artworkReviewMessage = choice === "delete-rom" ? "DELETING ROM FILE…" : "SAVING CHOICE…"
        var request = new XMLHttpRequest()
        request.onreadystatechange = function() {
            if (request.readyState !== XMLHttpRequest.DONE) return
            root.artworkReviewBusy = false
            if (request.status !== 200) {
                root.artworkReviewMessage = "THAT CHOICE COULD NOT BE SAVED"
                return
            }
            root.artworkReviewMessage = choice === "delete-rom" ? "ROM FILE DELETED" :
                    (choice === "hide" ? "REMOVED FROM THE MENUS" : "LEFT AS IS")
            root.artworkReviewChoice = 0
            // The companion has already dropped the row, so re-reading is what
            // keeps this list and the library in step.
            root.loadArtworkReview(function(remaining) {
                if (choice !== "leave") {
                    root.libraryMutationRevision += 1
                    root.libraryIndexReady = false
                    root.loadLibraryIndex()
                }
                if (remaining === 0) root.artworkReviewMessage = "NOTHING LEFT TO REVIEW"
            })
        }
        request.open("GET", "http://127.0.0.1:43821/artwork/decide?key=" +
                     encodeURIComponent(key) + "&choice=" + encodeURIComponent(choice), true)
        request.send()
    }

    function emulatorRoutesSummary() {
        if (!emulatorRouteSystems || emulatorRouteSystems.length === 0) return "NO GAMES YET"
        var internal = 0
        var external = 0
        for (var index = 0; index < emulatorRouteSystems.length; ++index) {
            if (emulatorRouteSystems[index].route === "external") external += 1
            else internal += 1
        }
        return internal + " BUILT-IN  •  " + external + " EXTERNAL"
    }

    function openEmulatorRoutes() {
        settingsOpen = false
        emulatorRoutesOpen = true
        emulatorRoutesIndex = 0
        emulatorRoutesNotice = ""
        loadEmulatorRoutes()
    }

    function loadEmulatorRoutes() {
        emulatorRoutesLoading = true
        requestPreviewJson("route/systems", function(data) {
            root.emulatorRoutesLoading = false
            if (!data || !data.systems) {
                root.emulatorRoutesNotice = "Could not read the emulator list."
                return
            }
            // The service deliberately returns only systems represented by an
            // indexed game. Keep the same fail-closed filter here so an older
            // companion cannot repopulate Settings with catalog-only rows.
            var visible = []
            for (var index = 0; index < data.systems.length; ++index) {
                var row = data.systems[index]
                if (row.active === true) visible.push(row)
            }
            root.emulatorRouteSystems = visible
            root.emulatorRoutesIndex = Math.max(0, Math.min(
                    root.emulatorRouteSystems.length - 1, root.emulatorRoutesIndex))
        })
    }

    function currentRouteSystem() {
        if (!emulatorRouteSystems || emulatorRoutesIndex < 0 ||
                emulatorRoutesIndex >= emulatorRouteSystems.length) return null
        return emulatorRouteSystems[emulatorRoutesIndex]
    }

    // Left/Right on the list is the fast path: flip a system between built-in
    // and external without opening its picker. It is refused, out loud, when
    // there is no built-in engine -- silently doing nothing is the behaviour
    // this whole screen exists to replace.
    function toggleEmulatorRoute(direction) {
        var system = currentRouteSystem()
        if (!system || emulatorRoutesLoading) return
        var wantInternal = direction < 0
        if (wantInternal && !system.internalAvailable) {
            emulatorRoutesNotice = system.collection +
                    " has no built-in engine yet, so it runs externally."
            requestPreviewEndpoint("sfx?name=error")
            return
        }
        if (!wantInternal && system.route === "external") {
            // Already external: open the picker rather than no-op.
            openEmulatorPicker(system.system, system.collection)
            return
        }
        if (wantInternal && system.route === "internal") return
        emulatorRoutesNotice = ""
        requestPreviewJson("route/set?system=" + encodeURIComponent(system.system) +
                "&route=" + (wantInternal ? "internal" : "external"), function(data) {
            if (!data)
                root.emulatorRoutesNotice = "Could not reach the emulator service."
            else if (data.ok === false)
                root.emulatorRoutesNotice = data.reason ? data.reason :
                        "That route could not be selected."
            root.loadEmulatorRoutes()
        })
    }

    function openEmulatorPicker(system, label) {
        emulatorPickerSystem = system
        emulatorPickerLabel = label
        emulatorPickerIndex = 0
        emulatorPickerNotice = ""
        emulatorPickerBusy = false
        emulatorPickerOpen = true
        loadEmulatorPicker()
    }

    function loadEmulatorPicker() {
        emulatorPickerLoading = true
        requestPreviewJson("route/options?system=" +
                encodeURIComponent(emulatorPickerSystem), function(data) {
            root.emulatorPickerLoading = false
            if (!data) {
                root.emulatorPickerNotice =
                        "Could not read this system's emulator settings."
                root.emulatorPickerData = null
                root.emulatorPickerRowList = []
                return
            }
            root.emulatorPickerData = data
            root.rebuildEmulatorPickerRows()
        })
    }

    // One flat list so a D-pad only ever moves up and down: automatic default,
    // the built-in row (when there is an engine), catalogued emulators in
    // catalog order, then Custom. The order is fixed so a learned row does not
    // move under the user between visits.
    function rebuildEmulatorPickerRows() {
        var rows = []
        var data = emulatorPickerData
        if (!data) { emulatorPickerRowList = rows; return }
        rows.push({
            kind: "default",
            id: "",
            name: "Automatic default",
            detail: data.internalAvailable ?
                    "Uses EmuFusion's built-in engine unless you choose otherwise" :
                    "Uses the first available external emulator for this system",
            state: data.explicit ? "RESTORE" : "",
            selected: data.explicit !== true
        })
        if (data.internalAvailable) {
            rows.push({
                kind: "internal",
                id: "",
                name: "Built-in engine",
                detail: "Runs inside EmuFusion. Recommended.",
                state: "",
                selected: data.explicit === true && data.route === "internal"
            })
        }
        var options = data.options ? data.options : []
        for (var index = 0; index < options.length; ++index) {
            var option = options[index]
            rows.push({
                kind: "option",
                id: option.id,
                name: option.name,
                detail: option.installed ?
                        (option.deliveryLabel ? option.deliveryLabel : "Installed") :
                        (option.install && option.install.kind === "play" ?
                         "Not installed — opens the Play Store" :
                         "Not installed — opens its download page"),
                state: option.installed ? "INSTALLED" : "GET",
                selected: data.route === "external" && option.selected
            })
        }
        var custom = data.custom ? data.custom : {}
        rows.push({
            kind: "custom",
            id: "custom",
            name: custom.configured && custom.name ?
                    ("Custom — " + custom.name) : "Custom emulator",
            detail: custom.configured ?
                    (custom.resolves ? custom.package :
                     "Set up, but that app is no longer installed") :
                    "Point EmuFusion at an emulator that is not listed",
            state: custom.configured ? (custom.resolves ? "EDIT" : "FIX") : "SET UP",
            selected: data.route === "external" && custom.selected === true
        })
        emulatorPickerRowList = rows
        emulatorPickerIndex = Math.max(0, Math.min(rows.length - 1, emulatorPickerIndex))
    }

    function currentPickerRow() {
        if (!emulatorPickerRowList || emulatorPickerIndex < 0 ||
                emulatorPickerIndex >= emulatorPickerRowList.length) return null
        return emulatorPickerRowList[emulatorPickerIndex]
    }

    function restoredRouteDescription(data) {
        if (!data || !data.route) return ""
        if (data.route === "internal") return "Built-in engine"
        if (data.emulatorName) return "External — " + data.emulatorName
        return "External"
    }

    // "Automatic" is not another route value. It removes this system's
    // explicit override and then asks /route/resolve what the backend chose.
    // The read-back matters: systems without an internal engine default to an
    // external emulator, while qualified systems default back to built-in.
    function restoreAutomaticEmulatorRoute() {
        if (emulatorPickerBusy || emulatorPickerSystem === "") return
        emulatorPickerBusy = true
        emulatorPickerNotice = "Restoring the automatic default…"
        requestPreviewJson("route/clear?system=" +
                encodeURIComponent(emulatorPickerSystem), function(cleared) {
            if (!cleared || cleared.ok !== true) {
                root.emulatorPickerBusy = false
                root.emulatorPickerNotice = cleared && cleared.reason ?
                        cleared.reason : "The automatic route could not be restored."
                requestPreviewEndpoint("sfx?name=error")
                return
            }
            requestPreviewJson("route/resolve?system=" +
                    encodeURIComponent(root.emulatorPickerSystem), function(resolved) {
                root.emulatorPickerBusy = false
                var description = root.restoredRouteDescription(resolved)
                if (description === "") {
                    root.emulatorPickerNotice =
                            "The route was reset, but its default could not be read."
                    requestPreviewEndpoint("sfx?name=error")
                } else {
                    root.emulatorPickerNotice =
                            "Automatic default restored — " + description + "."
                }
                root.loadEmulatorPicker()
                root.loadEmulatorRoutes()
            })
        })
    }

    // The tap. Java decides what it means: an installed emulator gets bound to
    // this system, a missing one opens its store or download page and binds
    // nothing, so pressing A again after installing is what links it.
    function activateEmulatorPickerRow() {
        if (emulatorPickerBusy) return
        var row = currentPickerRow()
        if (!row) return
        if (row.kind === "default") {
            restoreAutomaticEmulatorRoute()
            return
        }
        if (row.kind === "internal") {
            emulatorPickerNotice = ""
            requestPreviewJson("route/set?system=" +
                    encodeURIComponent(emulatorPickerSystem) + "&route=internal",
                    function(data) {
                if (!data)
                    root.emulatorPickerNotice =
                            "Could not reach the emulator service."
                else if (data.ok === false)
                    root.emulatorPickerNotice = data.reason ? data.reason :
                            "The built-in engine could not be selected."
                root.loadEmulatorPicker()
                root.loadEmulatorRoutes()
            })
            return
        }
        if (row.kind === "custom") {
            openCustomEmulator()
            return
        }
        emulatorPickerNotice = "Checking " + row.name + "…"
        requestPreviewJson("route/link?system=" +
                encodeURIComponent(emulatorPickerSystem) +
                "&emulator=" + encodeURIComponent(row.id), function(data) {
            if (!data) {
                root.emulatorPickerNotice = "Could not reach the emulator service."
                return
            }
            if (data.authorizationRequired) {
                root.emulatorPickerNotice = data.authorizationOpened ?
                        "Enable EmuFusion external game return in Android Accessibility, then come back and press A again." :
                        "Open Android Accessibility settings, enable EmuFusion external game return, then press A again."
            } else if (data.linked) {
                root.emulatorPickerNotice = data.name +
                        " now runs this system."
            } else if (data.ok && data.opened) {
                root.emulatorPickerNotice = "Install " + data.name +
                        ", then come back and press A on it again."
            } else if (data.ok) {
                root.emulatorPickerNotice = data.name +
                        " is not installed, and its download page could not be opened."
            } else {
                root.emulatorPickerNotice = data.reason ? data.reason :
                        "That emulator could not be selected."
            }
            root.loadEmulatorPicker()
            root.loadEmulatorRoutes()
        })
    }

    function openCustomEmulator() {
        var custom = emulatorPickerData && emulatorPickerData.custom ?
                emulatorPickerData.custom : {}
        customEmulatorPackage = custom.package ? custom.package : ""
        customEmulatorActivity = custom.component ? custom.component : ""
        customEmulatorDelivery = custom.delivery ? custom.delivery : "file-path"
        customEmulatorKey = custom.romExtraKey ? custom.romExtraKey : ""
        customEmulatorConfigured = custom.configured === true
        customEmulatorProblems = []
        customEmulatorNotice = ""
        customEmulatorIndex = 0
        customEmulatorOpen = true
    }

    function customEmulatorNeedsKey() {
        return customEmulatorDelivery === "file-path"
    }

    function customEmulatorRowCount() {
        // package, screen, delivery, [value name], save, [remove]
        return 4 + (customEmulatorNeedsKey() ? 1 : 0) +
                (customEmulatorConfigured ? 1 : 0)
    }

    // Row index -> field id, so an absent "value name" row does not shift the
    // meaning of the rows under it.
    function customEmulatorField(index) {
        var fields = ["package", "activity", "delivery"]
        if (customEmulatorNeedsKey()) fields.push("romExtraKey")
        fields.push("save")
        if (customEmulatorConfigured) fields.push("remove")
        return index >= 0 && index < fields.length ? fields[index] : ""
    }

    function customEmulatorProblemFor(field) {
        var problems = customEmulatorProblems
        if (!problems) return ""
        for (var index = 0; index < problems.length; ++index)
            if (problems[index].field === field) return problems[index].message
        return ""
    }

    function cycleCustomEmulatorDelivery(direction) {
        var kinds = ["file-path", "action-view", "content-uri"]
        var current = kinds.indexOf(customEmulatorDelivery)
        if (current < 0) current = 0
        customEmulatorDelivery = kinds[
                (current + (direction < 0 ? -1 : 1) + kinds.length) % kinds.length]
        customEmulatorIndex = Math.min(customEmulatorIndex,
                                       customEmulatorRowCount() - 1)
    }

    function customEmulatorDeliveryLabel() {
        if (customEmulatorDelivery === "action-view") return "OPENS THE FILE"
        if (customEmulatorDelivery === "content-uri") return "SHARED LINK"
        return "FILE PATH"
    }

    function customEmulatorDeliveryHelp() {
        if (customEmulatorDelivery === "action-view")
            return "EmuFusion asks the app to open the game file. Most simple emulators."
        if (customEmulatorDelivery === "content-uri")
            return "For emulators that cannot read storage directly, such as Switch and Wii U."
        return "EmuFusion sends the file path under a name the emulator expects."
    }

    function saveCustomEmulator() {
        customEmulatorNotice = "Checking…"
        requestPreviewJson("route/custom?system=" +
                encodeURIComponent(emulatorPickerSystem) +
                "&package=" + encodeURIComponent(customEmulatorPackage) +
                "&activity=" + encodeURIComponent(customEmulatorActivity) +
                "&delivery=" + encodeURIComponent(customEmulatorDelivery) +
                "&romExtraKey=" + encodeURIComponent(customEmulatorKey),
                function(data) {
            if (!data) {
                root.customEmulatorNotice = "Could not reach the emulator service."
                return
            }
            root.customEmulatorProblems = data.problems ? data.problems : []
            if (data.ok && data.authorizationRequired) {
                root.customEmulatorNotice = data.authorizationOpened ?
                        "Enable EmuFusion external game return in Android Accessibility, then come back and save again." :
                        "Open Android Accessibility settings, enable EmuFusion external game return, then save again."
            } else if (data.ok) {
                root.customEmulatorNotice = ""
                root.customEmulatorOpen = false
                root.emulatorPickerNotice =
                        "Your custom emulator now runs this system."
                root.loadEmulatorPicker()
                root.loadEmulatorRoutes()
            } else {
                root.customEmulatorNotice = root.customEmulatorProblems.length > 0 ?
                        "Fix the highlighted fields." :
                        "That emulator could not be set up."
                requestPreviewEndpoint("sfx?name=error")
            }
        })
    }

    function clearCustomEmulator() {
        requestPreviewJson("route/custom?clear=1&system=" +
                encodeURIComponent(emulatorPickerSystem), function(data) {
            if (!data || data.ok !== true) {
                root.customEmulatorNotice = data && data.reason ? data.reason :
                        "The custom emulator could not be removed."
                requestPreviewEndpoint("sfx?name=error")
                return
            }
            root.customEmulatorOpen = false
            root.emulatorPickerNotice = "Custom emulator removed."
            root.loadEmulatorPicker()
            root.loadEmulatorRoutes()
        })
    }

    function activateCustomEmulatorRow() {
        var field = customEmulatorField(customEmulatorIndex)
        if (field === "save") saveCustomEmulator()
        else if (field === "remove") clearCustomEmulator()
        else if (field === "delivery") cycleCustomEmulatorDelivery(1)
        else customEmulatorEditor.beginEditing(field)
    }

    function openLegalNotice() {
        settingsOpen = false
        legalOpen = true
        legalScroll = 0
        // Always re-read: the wording lives in one place on the Java side, and
        // a cached copy in QML is exactly the drift this is meant to prevent.
        requestPreviewJson("legal/notice", function(data) {
            if (!data || !data.paragraphs) {
                root.legalParagraphs = ["The legal notice could not be loaded."]
                return
            }
            root.legalTitle = data.title ? data.title : "Legal Notice"
            root.legalParagraphs = data.paragraphs
        })
    }

    function scrollLegalNotice(direction) {
        var maximum = Math.max(0, legalBodyHeight - legalViewportHeight)
        legalScroll = Math.max(0, Math.min(maximum, legalScroll + direction * 90))
    }

    function detectPreviewCapabilities() {
        var request = new XMLHttpRequest()
        request.onreadystatechange = function() {
            if (request.readyState !== XMLHttpRequest.DONE || request.status !== 200)
                return
            try {
                var capabilities = JSON.parse(request.responseText)
                var detectedDualScreen = Boolean(capabilities.dualScreen)
                if (root.dualScreenDevice !== detectedDualScreen) {
                    root.dualScreenDevice = detectedDualScreen
                    if (root.page === "home" && root.homeViewMode === "list")
                        root.activateHomeListPreview()
                    else if (root.page === "home" && root.homeZone === 0)
                        root.activateHomePreview(false)
                    else if (root.page === "games")
                        root.activateGamePreview()
                    else
                        root.activateShelfPreview(root.homeZone)
                }
            } catch (error) {
                // Default to Thor's physical lower display if an older
                // companion does not expose capability discovery yet.
            }
        }
        request.open("GET", "http://127.0.0.1:43821/capabilities", true)
        request.send()
    }

    function singleSource(index) {
        if (index === 0) return singleSourceA
        if (index === 1) return singleSourceB
        return singleSourceC
    }

    function singlePlayer(index) {
        if (index === 0) return singleVideoA
        if (index === 1) return singleVideoB
        return singleVideoC
    }

    function setSingleSource(index, source) {
        source = String(source || "")
        if (singleSource(index) === source) return
        if (index === 0) singleSourceA = source
        else if (index === 1) singleSourceB = source
        else singleSourceC = source
    }

    function findSingleSource(source) {
        source = String(source || "")
        for (var index = 0; index < 3; ++index) {
            if (source !== "" && singleSource(index) === source)
                return index
        }
        return -1
    }

    function ensureSingleWarm(source, protectedA, protectedB) {
        source = String(source || "")
        if (source === "") return -1
        var existing = findSingleSource(source)
        if (existing >= 0) return existing
        for (var index = 0; index < 3; ++index) {
            if (index !== protectedA && index !== protectedB) {
                setSingleSource(index, source)
                return index
            }
        }
        return -1
    }

    function promoteSingleVideo(index) {
        if (index !== singleTargetSlot) return
        singleCurrentSlot = index
        singleTargetSlot = -1
    }

    function setSingleScreenPreview(current, previous, next) {
        current = String(current || "")
        if (current === "") {
            singleTargetSlot = -1
            singleCurrentSlot = -1
            return
        }
        var currentSlot = findSingleSource(current)
        if (currentSlot < 0) {
            currentSlot = (singleCurrentSlot + 1 + 3) % 3
            setSingleSource(currentSlot, current)
        }
        singleTargetSlot = currentSlot
        var previousSlot = ensureSingleWarm(previous, currentSlot, -1)
        ensureSingleWarm(next, currentSlot, previousSlot)
        var player = singlePlayer(currentSlot)
        if (player.position > 0 || player.status === MediaPlayer.Buffered)
            promoteSingleVideo(currentSlot)
    }

    function hideBottomPreview() {
        var request = new XMLHttpRequest()
        request.open("GET", "http://127.0.0.1:43821/hide", true)
        request.send()
    }

    function blankBottomPreviewNow() {
        // Run before the system rail paints its next selection. This prevents
        // the outgoing system's final decoded frame from surviving beneath
        // the new system while its random preview is being selected/decoded.
        var request = new XMLHttpRequest()
        try {
            previewRequestSequence += 1
            request.open("GET", "http://127.0.0.1:43821/transition?seq=" +
                         previewRequestSequence, true)
            request.send()
        } catch (error) {
            // The preview companion is optional; navigation must stay usable.
        }
    }

    function sendPreviewHeartbeat() {
        if (Qt.application.state !== Qt.ApplicationActive &&
                Qt.application.state !== Qt.ApplicationInactive) return
        var sequence = ++previewHeartbeatSequence
        var request = new XMLHttpRequest()
        // The heartbeat is the one poll that must survive gameplay, because it
        // is how the frontend learns gameplay has ended. Reading its reply adds
        // no extra request and drives every other poller's gate.
        request.onreadystatechange = function() {
            if (request.readyState !== XMLHttpRequest.DONE) return
            if (request.status !== 200) return
            try {
                var payload = JSON.parse(request.responseText)
                if (sequence <= root.previewHeartbeatAppliedSequence ||
                        typeof payload.gameplay !== "boolean") return
                root.previewHeartbeatAppliedSequence = sequence
                root.gameplayActive = payload.gameplay
            } catch (error) {
                // A malformed reply is not evidence that the game has ended.
            }
        }
        // Qt can be inactive while the same Android process hosts a game.
        // The inactive query must be read-only: /heartbeat can resurrect the
        // lower preview when no game is active, including over Android Home.
        var endpoint = Qt.application.state === Qt.ApplicationActive ?
                    "heartbeat" : "screensaver/status"
        request.open("GET", "http://127.0.0.1:43821/" + endpoint, true)
        request.send()
    }

    function applyImportStatus(payload) {
        if (!payload) return
        var previousState = importState
        var establishSilentBaseline = !importStatusInitialized &&
                ((payload.state || "idle") === "complete" ||
                 (payload.state || "idle") === "idle")
        importStatusInitialized = true
        var fingerprint = String(payload.state || "idle") + "|" +
                String(payload.progress || 0) + "|" + String(payload.message || "") + "|" +
                String(payload.detail || "") + "|" + String(payload.current || 0) + "|" +
                String(payload.total || 0) + "|" +
                String(payload.identified || 0) + "|" + String(payload.added || 0) + "|" +
                String(Boolean(payload.needsReload))
        var changed = fingerprint !== lastImportFingerprint
        lastImportFingerprint = fingerprint
        importState = payload.state || "idle"
        importProgress = Number(payload.progress || 0)
        importMessage = payload.message || ""
        importDetail = payload.detail || ""
        importCurrent = Number(payload.current || 0)
        importTotal = Number(payload.total || 0)
        importTitles = payload.titles || []
        importIdentified = Number(payload.identified || 0)
        importAdded = Number(payload.added || 0)
        importNeedsReload = Boolean(payload.needsReload)
        if (importState !== "complete" && importState !== "idle")
            importReloadRequested = false
        if (establishSilentBaseline) {
            importToastVisible = false
            return
        }
        if (importState === "complete") {
            // Status polling can continue returning "complete" forever. Show
            // the result once on the state transition, then dismiss it on an
            // absolute timer that later polls cannot restart.
            if (previousState !== "complete") {
                importToastVisible = true
                importToastDismiss.restart()
                if (importNeedsReload && !importReloadRequested) {
                    importReloadRequested = true
                    importedLibraryReload.restart()
                }
            }
        } else if (importState === "error") {
            if (previousState !== "error") {
                importToastVisible = true
                importToastDismiss.restart()
            }
        } else if (importState !== "idle") {
            importToastVisible = true
        } else if (changed) {
            importToastVisible = false
        }
    }

    function requestImport(endpoint) {
        var request = new XMLHttpRequest()
        request.onreadystatechange = function() {
            if (request.readyState !== XMLHttpRequest.DONE || request.status < 200 || request.status >= 300)
                return
            try {
                root.applyImportStatus(JSON.parse(request.responseText))
            } catch (error) {
                // Import status must never interfere with navigation.
            }
        }
        request.open("GET", "http://127.0.0.1:43821/import/" + endpoint, true)
        request.send()
    }

    function startImportScan() {
        requestImport("scan")
    }

    function startMaintenanceRescan() {
        endSearch()
        updatePromptDismissed = false
        importState = "scanning"
        importProgress = 0.01
        importMessage = "Starting full library maintenance…"
        importDetail = "Checking storage, Downloads, game media, and EmuFusion updates"
        importStatusInitialized = true
        importToastVisible = true

        var request = new XMLHttpRequest()
        request.onreadystatechange = function() {
            if (request.readyState !== XMLHttpRequest.DONE ||
                    request.status < 200 || request.status >= 300)
                return
            try {
                root.applyImportStatus(JSON.parse(request.responseText))
            } catch (error) {
                // The normal status poll will recover the visible state.
            }
        }
        request.open("GET", "http://127.0.0.1:43821/maintenance/rescan", true)
        request.send()
    }

    function openLucentBrowser() {
        endSearch()
        requestPreviewEndpoint("browser/open")
    }

    function pollImportStatus() {
        requestImport("status")
    }

    function usesBottomScreen(game) {
        var index = systemIndexForGame(game)
        if (index < 0) return false
        var folder = systemModel.get(index).folder
        return folder === "nds" || folder === "n3ds" || folder === "wiiu"
    }

    function stopBottomPreviewForLaunch(game) {
        // Never block the Qt input/render thread at launch. The old synchronous
        // localhost request froze the selected menu frame until PreviewService
        // answered, which made even a fast core look hung. ACTION_GAMEPLAY is a
        // second authoritative blank request when the Android game layer
        // attaches, so this early request can be best-effort and asynchronous.
        var endpoint = usesBottomScreen(game) ? "hide" : "blank"
        var request = new XMLHttpRequest()
        try {
            request.open("GET", "http://127.0.0.1:43821/" + endpoint, true)
            request.send()
        } catch (error) {
            // Launching the game is still preferable if the optional preview
            // companion is temporarily unavailable.
        }
    }

    function wrappedSystemIndex(index) {
        var count = systemModel.count
        if (count <= 0) return -1
        return (index % count + count) % count
    }

    function collectionAtSystem(index) {
        var wrapped = wrappedSystemIndex(index)
        if (wrapped < 0) return null
        return collectionNamed(systemModel.get(wrapped).collectionName)
    }

    function homePreviewCandidates(systemIndex) {
        var wrapped = wrappedSystemIndex(systemIndex)
        if (wrapped < 0) return []
        var cached = homePreviewCandidatesBySystem[wrapped]
        if (cached) return cached
        var collection = collectionAtSystem(wrapped)
        var videoMatches = []
        var artworkMatches = []
        if (systemModel.get(wrapped).folder === "all") {
            for (var allIndex = 0; allIndex < api.allGames.count; ++allIndex) {
                var allCandidate = api.allGames.get(allIndex)
                if (!allCandidate || systemIndexForGame(allCandidate) <= 0) continue
                if (allCandidate.assets.video)
                    videoMatches.push(allCandidate)
                else if (artwork(allCandidate))
                    artworkMatches.push(allCandidate)
            }
        } else if (collection) {
            for (var index = 0; index < collection.games.count; ++index) {
                var candidate = collection.games.get(index)
                if (!candidate) continue
                if (candidate.assets.video)
                    videoMatches.push(candidate)
                else if (artwork(candidate))
                    artworkMatches.push(candidate)
            }
        }
        cached = videoMatches.length > 0 ? videoMatches : artworkMatches
        homePreviewCandidatesBySystem[wrapped] = cached
        return cached
    }

    function randomHomeVideoGame(systemIndex, avoidGame) {
        var candidates = homePreviewCandidates(systemIndex)
        if (candidates.length === 0) return null
        if (candidates.length === 1) return candidates[0]
        var selected = candidates[Math.floor(Math.random() * candidates.length)]
        if (selected === avoidGame) {
            var current = candidates.indexOf(selected)
            selected = candidates[(current + 1 + Math.floor(Math.random() *
                       (candidates.length - 1))) % candidates.length]
        }
        return selected
    }

    function randomVideoGame(collection, avoidGame) {
        if (!collection || collection.games.count <= 0) return null
        var videoMatches = []
        var artworkMatches = []
        for (var i = 0; i < collection.games.count; ++i) {
            var candidate = collection.games.get(i)
            if (!candidate || candidate === avoidGame)
                continue
            if (candidate.assets.video)
                videoMatches.push(candidate)
            else if (artwork(candidate))
                artworkMatches.push(candidate)
        }
        var matches = videoMatches.length > 0 ? videoMatches : artworkMatches
        if (matches.length === 0 && avoidGame)
            return avoidGame
        if (matches.length === 0)
            return collection.games.get(Math.floor(Math.random() * collection.games.count))
        return matches[Math.floor(Math.random() * matches.length)]
    }

    function previewSlots() {
        return [previewA, previewB, previewC]
    }

    function slotFor(mode, systemIndex, gameIndex) {
        var slots = previewSlots()
        for (var i = 0; i < slots.length; ++i) {
            if (slots[i].previewMode === mode &&
                    slots[i].systemIndex === systemIndex &&
                    slots[i].gameIndex === gameIndex)
                return slots[i]
        }
        return null
    }

    function freeSlot(excludedA, excludedB) {
        var slots = previewSlots()
        for (var i = 0; i < slots.length; ++i) {
            if (slots[i] !== excludedA && slots[i] !== excludedB)
                return slots[i]
        }
        return slots[0]
    }

    function assignSlot(slot, mode, systemIndex, gameIndex, game) {
        if (!slot) return
        if (slot.previewMode === mode && slot.systemIndex === systemIndex &&
                slot.gameIndex === gameIndex && slot.previewGame === game)
            return
        slot.previewMode = mode
        slot.systemIndex = systemIndex
        slot.gameIndex = gameIndex
        slot.previewGame = game
    }

    function prepareHomeNeighbor(systemIndex, reservedSlot) {
        var wrapped = wrappedSystemIndex(systemIndex)
        var existing = slotFor("home", wrapped, -1)
        if (existing && existing !== activePreviewSlot)
            return existing
        var slot = freeSlot(activePreviewSlot, reservedSlot)
        var selected = lastHomeGameBySystem[wrapped] ||
                randomHomeVideoGame(wrapped, null)
        lastHomeGameBySystem[wrapped] = selected
        assignSlot(slot, "home", wrapped, -1,
                   selected)
        return slot
    }

    function activateHomePreview(forceReroll) {
        if (!previewReady) return
        var index = wrappedSystemIndex(systemRail.currentIndex)
        if (lastSystemPreviewIndex >= 0 && lastSystemPreviewIndex !== index) {
            departedSystemIndex = lastSystemPreviewIndex
            rerollDepartedPreview.restart()
        }
        lastSystemPreviewIndex = index
        var current = slotFor("home", index, -1) || freeSlot(null, null)
        var avoid = lastHomeGameBySystem[index] || null
        var selected = !forceReroll && avoid ? avoid :
                randomHomeVideoGame(index, avoid)
        assignSlot(current, "home", index, -1, selected)
        lastHomeGameBySystem[index] = selected
        activePreviewSlot = current
        homePreviewGame = current.previewGame
        var previous = prepareHomeNeighbor(index - 1, null)
        var next = prepareHomeNeighbor(index + 1, previous)
        sendBottomPreview(homePreviewGame,
                          previous ? previous.previewGame : null,
                          next ? next.previewGame : null, null)
    }

    function gameAt(collection, index) {
        if (!collection || collection.games.count <= 0) return null
        var wrapped = (index % collection.games.count + collection.games.count) % collection.games.count
        return collection.games.get(wrapped)
    }

    function prepareGameNeighbor(systemIndex, collection, gameIndex, reservedSlot) {
        if ((!allSystemsActive && !collection) || activeGameCount <= 1) return null
        var wrapped = (gameIndex % activeGameCount + activeGameCount) % activeGameCount
        var expectedGame = gameAtDisplayIndex(wrapped)
        var existing = slotFor("game", systemIndex, wrapped)
        if (existing && existing !== activePreviewSlot &&
                existing.previewGame === expectedGame)
            return existing
        var slot = existing && existing !== activePreviewSlot ? existing :
                   freeSlot(activePreviewSlot, reservedSlot)
        assignSlot(slot, "game", systemIndex, wrapped, expectedGame)
        return slot
    }

    function activateGamePreview() {
        if (!previewReady || page !== "games") return
        var collection = activeCollection
        var systemIndex = allSystemsActive ? activeGameSystemIndex : activeSystemIndex
        var gameIndex = gameRail.currentIndex
        if ((!allSystemsActive && !collection) || activeGameCount <= 0) {
            homePreviewGame = null
            var emptySlot = activePreviewSlot || previewA
            assignSlot(emptySlot, "game", systemIndex, -1, null)
            activePreviewSlot = emptySlot
            // An empty collection has no selected game. Explicitly clear the
            // secondary display instead of leaving the departed system's last
            // decoded frame running underneath it.
            if (useBottomPreview())
                requestPreviewEndpoint("blank")
            else
                setSingleScreenPreview("", "", "")
            return
        }

        var expectedGame = gameAtDisplayIndex(gameIndex)
        var current = slotFor("game", systemIndex, gameIndex)
        if (!current) {
            current = freeSlot(null, null)
        }
        // A sort changes the game represented by an index without changing
        // the index itself. Never reuse the old movie merely because the row
        // number matches.
        assignSlot(current, "game", systemIndex, gameIndex, expectedGame)
        activePreviewSlot = current
        var previous = prepareGameNeighbor(systemIndex, collection, gameIndex - 1, null)
        var next = prepareGameNeighbor(systemIndex, collection, gameIndex + 1, previous)
        queueUpperArtwork(current.previewGame,
                          previous ? previous.previewGame : null,
                          next ? next.previewGame : null)
        queueBoxArtwork(current.previewGame,
                        previous ? previous.previewGame : null,
                        next ? next.previewGame : null)
        var homeAux = lastHomeGameBySystem[systemIndex]
        if (!homeAux) {
            homeAux = randomHomeVideoGame(systemIndex, current.previewGame)
            lastHomeGameBySystem[systemIndex] = homeAux
        }
        sendBottomPreview(current.previewGame,
                          previous ? previous.previewGame : null,
                          next ? next.previewGame : null, homeAux)
    }

    function activateShelfPreview(zone) {
        if (!previewReady) return
        var model = homeShelfModel(zone)
        var rail = homeShelfRail(zone)
        if (!model || model.count <= 0) return
        var game = homeShelfGameAt(zone, rail.currentIndex)
        var slot = freeSlot(null, null)
        assignSlot(slot, "shelf" + zone, -1, rail.currentIndex, game)
        activePreviewSlot = slot
        var previous = homeShelfGameAt(zone,
                (rail.currentIndex - 1 + model.count) % model.count)
        var next = homeShelfGameAt(zone, (rail.currentIndex + 1) % model.count)
        queueUpperArtwork(game, previous, next)
        queueBoxArtwork(game, previous, next)
        sendBottomPreview(game, previous, next, null)
    }

    function activateHomeListPreview() {
        if (!previewReady || page !== "home" || homeViewMode !== "list") return
        if (homeListEntries.length <= 0 || homeListPreviewRow() < 0) {
            homePreviewGame = null
            currentBottomPreviewGame = null
            currentBottomPreviewSequence = 0
            requestPreviewEndpoint("blank")
            return
        }
        var selectedIndex = homeListPreviewRow()
        var game = homeListGameAt(selectedIndex)
        var slot = freeSlot(null, null)
        assignSlot(slot, "home-list-" + homeListCategory,
                   systemRail.currentIndex, selectedIndex, game)
        activePreviewSlot = slot
        var previous = homeListGameAt((selectedIndex - 1 + homeListEntries.length) %
                                      homeListEntries.length)
        var next = homeListGameAt((selectedIndex + 1) % homeListEntries.length)
        queueUpperArtwork(game, previous, next)
        queueBoxArtwork(game, previous, next)
        sendBottomPreview(game, previous, next, null)
    }

    function activateRecentPreview() {
        activateShelfPreview(1)
    }

    function launch(game) {
        if (!game) return
        if (frameGenerationModePending || !frameGenerationModeConfirmed) {
            frameGenerationPendingLaunch = game
            if (!frameGenerationModePending) refreshFrameGenerationStatus()
            return
        }
        launchConfirmed(game)
    }

    function launchConfirmed(game) {
        if (!game) return
        navigationPersistence.stop()
        api.memory.set("thoriumSystem", page === "games" ? activeSystemIndex : systemRail.currentIndex)
        api.memory.set("thoriumGame", gameRail.currentIndex)
        api.memory.set("thoriumPage", page)
        // launch() deliberately cancels the delayed persistence timer.  The
        // sort/view tuple must therefore be committed here as part of the
        // same atomic navigation snapshot.  Otherwise a fast launch after a
        // sort change stores the selected row under the PREVIOUS sort; when
        // the QML scene reconstructs on in-window return, index 0 can name a
        // completely different game (physical N64 QA returned from TWINE to
        // Ocarina for exactly this reason).
        api.memory.set("thoriumSortMode", sortMode)
        api.memory.set("thoriumGameView", gameViewMode)
        api.memory.set("thoriumHomeView", homeViewMode)
        // Qt reconstructs this scene when some emulators release the display.
        // Persisting this one-shot marker distinguishes that return from a
        // genuine Pegasus startup, where the Downloads scan should run.
        api.memory.set("parallaxReturningFromGame", true)
        stopBottomPreviewForLaunch(game)
        game.launch()
    }

    function scheduleNavigationPersistence() {
        navigationPersistencePending = true
        navigationPersistence.restart()
    }

    function flushNavigationPersistence() {
        if (!navigationPersistencePending) return
        navigationPersistencePending = false
        api.memory.set("thoriumSystem", page === "games" ?
                       activeSystemIndex : systemRail.currentIndex)
        api.memory.set("thoriumGame", page === "games" ? gameRail.currentIndex : 0)
        api.memory.set("thoriumPage", page)
        api.memory.set("thoriumSortMode", sortMode)
        api.memory.set("thoriumGameView", gameViewMode)
        api.memory.set("thoriumHomeView", homeViewMode)
    }

    function enterCollection() {
        // Pay the model/sort cost only when the user opens this collection.
        // Resolve directly from the highlighted index in this event turn. A
        // derived selectedCollection binding may not have re-evaluated yet
        // after very fast D-pad navigation.
        activeSystemIndex = systemRail.currentIndex
        allSystemsActive = activeSystemIndex === 0
        activeCollection = allSystemsActive ? null : collectionAtSystem(activeSystemIndex)
        activateCachedSystemSort()
        page = "games"
        gameRail.currentIndex = 0
        scheduleNavigationPersistence()
        Qt.callLater(function() { root.activateGamePreview() })
        root.forceActiveFocus()
    }

    function returnHome() {
        systemRail.currentIndex = activeSystemIndex
        page = "home"
        homeZone = 0
        scheduleNavigationPersistence()
        chooseSystemWallpaper(systemRail.currentIndex)
        systemRail.positionViewAtIndex(systemRail.currentIndex, ListView.Center)
        Qt.callLater(function() { root.activateHomePreview(false) })
        systemRail.forceActiveFocus()
    }

    function openSystemInPlace(index) {
        var target = wrappedSystemIndex(index)
        if (target < 0) return
        // Rebind the collection before moving the shared system rail. Its
        // currentIndex callback used to observe the old model and submit one
        // stale preview whenever L2/R2 changed platform.
        activeSystemIndex = target
        allSystemsActive = target === 0
        activeCollection = allSystemsActive ? null : collectionAtSystem(target)
        activateCachedSystemSort()
        systemRail.currentIndex = target
        gameRail.currentIndex = 0
        scheduleNavigationPersistence()
        // Keep the root, rather than a delegate that is about to be destroyed
        // by the source-model swap, as the key owner. Losing focus during that
        // swap was what made the first opposite-trigger press disappear.
        root.forceActiveFocus()
        systemOpenCommit.restart()
    }

    function stepOpenSystem(direction) {
        openSystemInPlace(activeSystemIndex + (direction < 0 ? -1 : 1))
    }

    function isLeftTrigger(event) {
        // AYN's Odin Controller exposes L2 both as Android BUTTON_L2 and Linux
        // BTN_TL2. Qt versions used by Pegasus disagree on whether that arrives
        // as a Qt gamepad enum, an Android virtual key, or only a scan code.
        return event.key === 0x01000086 || event.key === 1048581 || event.key === 104 ||
               event.nativeVirtualKey === 104 || event.nativeScanCode === 312
    }

    function isRightTrigger(event) {
        return event.key === 0x01000087 || event.key === 1048584 || event.key === 105 ||
               event.nativeVirtualKey === 105 || event.nativeScanCode === 313
    }

    function triggerDirection(event) {
        // Prefer the Thor's unambiguous Linux scan codes before Pegasus'
        // generic PageUp/PageDown aliases. Some Qt builds cache the previous
        // alias for one event when the user reverses trigger direction.
        if (event.nativeScanCode === 312) return -1
        if (event.nativeScanCode === 313) return 1
        if (isLeftTrigger(event)) return -1
        if (isRightTrigger(event)) return 1
        return 0
    }

    // Qt occasionally drops the pressed edge of the first opposite trigger
    // after a collection model swap, even though Android still delivers its
    // released edge. Track handled presses per physical trigger so release can
    // perform exactly one fallback step without doubling ordinary presses.
    property bool leftTriggerPressHandled: false
    property bool rightTriggerPressHandled: false

    function rememberHandledTrigger(direction) {
        if (direction < 0)
            leftTriggerPressHandled = true
        else if (direction > 0)
            rightTriggerPressHandled = true
    }

    function focusHomeZone(zone) {
        homeZone = Math.max(0, Math.min(7, zone))
        if (homeZone === 0) {
            chooseSystemWallpaper(systemRail.currentIndex)
            activateHomePreview(false)
            systemRail.forceActiveFocus()
        } else {
            activateShelfPreview(homeZone)
            homeShelfRail(homeZone).forceActiveFocus()
        }
    }

    function stepHomeShelf(direction) {
        var rail = homeShelfRail(homeZone)
        if (!rail) return
        if (direction < 0)
            rail.decrementCurrentIndex()
        else
            rail.incrementCurrentIndex()
    }

    function stepSystem(direction) {
        var count = systemModel.count
        if (count <= 0) return
        // Match the game rail's cheap navigation path. ApplyRange centers the
        // selected delegate itself; forcing positionViewAtIndex here caused a
        // synchronous relayout on every D-pad press.
        if (direction < 0)
            systemRail.decrementCurrentIndex()
        else
            systemRail.incrementCurrentIndex()
    }

    function updateClock() {
        var now = new Date()
        var hours = now.getHours()
        var minutes = now.getMinutes()
        var suffix = hours >= 12 ? "PM" : "AM"
        hours = hours % 12
        if (hours === 0) hours = 12
        clockText = hours + ":" + (minutes < 10 ? "0" : "") + minutes + " " + suffix
    }

    function escapedSearchPattern(value) {
        var text = String(value || "")
        var special = "\\^$.*+?()[]{}|"
        var result = ""
        for (var i = 0; i < text.length; ++i) {
            var character = text.charAt(i)
            result += special.indexOf(character) >= 0 ? "\\" + character : character
        }
        return result
    }

    function beginSearch() {
        // Search the complete library from home. When invoked inside a system,
        // preserve that system as the search scope.
        if (page === "home") {
            activeSystemIndex = 0
            allSystemsActive = true
            activeCollection = null
            systemRail.currentIndex = 0
            page = "games"
            gameRail.currentIndex = 0
        }
        searchOpen = true
        Qt.callLater(function() {
            searchField.forceActiveFocus()
            Qt.inputMethod.show()
        })
    }

    function endSearch() {
        Qt.inputMethod.reset()
        searchOpen = false
        searchQuery = ""
        searchField.text = ""
        searchField.focus = false
        Qt.inputMethod.hide()
        gameRail.currentIndex = 0
        searchChangeCommit.restart()
        root.forceActiveFocus()
    }

    Component.onCompleted: {
        rebuildRecentlyAddedModel()
        rebuildVisibleSystems()
        detectPreviewCapabilities()
        systemMotionEnabled = false
        api.memory.set("thoriumSystemMotion", false)
        previewPlacementMode = api.memory.has("thoriumPreviewPlacement") ?
                api.memory.get("thoriumPreviewPlacement") : "auto"
        singleScreenMediaSwapped = api.memory.has("lucentSingleScreenMediaSwapped") ?
                Boolean(api.memory.get("lucentSingleScreenMediaSwapped")) : false
        coverViewRowCount = api.memory.has("lucentCoverViewRowCount") ?
                Math.max(1, Math.min(3, Number(api.memory.get("lucentCoverViewRowCount")))) : 1
        coverRowOrder = validatedCoverRowOrder(api.memory.has("lucentCoverRowOrder") ?
                String(api.memory.get("lucentCoverRowOrder")) : "[0,1,2,3,4,5,6,7]")
        // The refractive shader remains available as an explicit visual
        // preference, but the calm, undistorted surface is the default.
        liquidGlassEnabled = api.memory.has("thoriumLiquidGlassEnabled") ?
                Boolean(api.memory.get("thoriumLiquidGlassEnabled")) : false
        rightStickViewSwitchingEnabled =
                api.memory.has("lucentRightStickViewSwitching") ?
                Boolean(api.memory.get("lucentRightStickViewSwitching")) : true
        viewTransitionsEnabled = api.memory.has("lucentViewTransitions") ?
                Boolean(api.memory.get("lucentViewTransitions")) : false
        accentGrouping = api.memory.has("lucentAccentGrouping") ?
                normalizedAccentGrouping(String(api.memory.get("lucentAccentGrouping"))) :
                "system"
        try {
            customFamilyAccents = api.memory.has("lucentCustomFamilyAccents") ?
                    JSON.parse(String(api.memory.get("lucentCustomFamilyAccents"))) : ({})
        } catch (familyError) { customFamilyAccents = ({}) }
        try {
            customSystemAccents = api.memory.has("lucentCustomSystemAccents") ?
                    JSON.parse(String(api.memory.get("lucentCustomSystemAccents"))) : ({})
        } catch (systemError) { customSystemAccents = ({}) }
        try {
            removedHomeCategoryGameIds = api.memory.has("lucentRemovedHomeCategoryGameIds") ?
                    JSON.parse(String(api.memory.get("lucentRemovedHomeCategoryGameIds"))) :
                    ({ "1": {}, "2": {}, "3": {} })
        } catch (removedListError) {
            removedHomeCategoryGameIds = ({ "1": {}, "2": {}, "3": {} })
        }
        rebuildRecentlyAddedModel()
        applyAccentPalette()
        systemLedEnabled = api.memory.has("lucentSystemLedEnabled") ?
                Boolean(api.memory.get("lucentSystemLedEnabled")) : true
        systemLedBrightness = api.memory.has("lucentSystemLedBrightness") ?
                Math.max(1, Math.min(100,
                    Number(api.memory.get("lucentSystemLedBrightness")))) : 2
        // Split the old combined SYSTEM/manual row into independent enabled
        // and brightness preferences. Migrate every existing install once to
        // the requested safe default: enabled, system-matched, one percent.
        if (!api.memory.has("lucentSplitLedControlsV1")) {
            systemLedEnabled = true
            systemLedBrightness = 2
            api.memory.set("lucentSystemLedEnabled", true)
            api.memory.set("lucentSystemLedBrightness", 2)
            api.memory.set("lucentSplitLedControlsV1", true)
        }
        // Existing 3.0.40/3.0.41 installs were intentionally migrated to 1%.
        // Move that exact old default to the newly requested 2% once without
        // overwriting a brightness the user had already customized.
        if (!api.memory.has("lucentLedDefaultTwoPercentV1")) {
            if (systemLedBrightness === 1) {
                systemLedBrightness = 2
                api.memory.set("lucentSystemLedBrightness", 2)
            }
            api.memory.set("lucentLedDefaultTwoPercentV1", true)
        }
        startViewPreference = api.memory.has("lucentStartView") ?
                String(api.memory.get("lucentStartView")) : "cover"
        // Reset the former default-ON behavior once on upgrade. The marker is
        // separate from the preference so a user who subsequently enables
        // preview sound keeps that choice across every later launch/update.
        if (!api.memory.has("emufusionPreviewSoundDefaultOffV2")) {
            previewSoundEnabled = false
            api.memory.set("thoriumPreviewSound", false)
            api.memory.set("emufusionPreviewSoundDefaultOffV2", true)
        } else {
            previewSoundEnabled = api.memory.has("thoriumPreviewSound") ?
                    Boolean(api.memory.get("thoriumPreviewSound")) : false
        }
        requestPreviewEndpoint("settings/sound?enabled=" +
                (previewSoundEnabled ? "1" : "0"))
        // The companion owns the durable launch preference. Existing and new
        // installations default to the verified built-in 16:9 profile.
        widescreenEnhancementsEnabled = api.memory.has(
                "emufusionWidescreenEnhancements") ?
                Boolean(api.memory.get("emufusionWidescreenEnhancements")) : true
        refreshWidescreenEnhancements()
        // The geometry hack is opt-in on every installation; the companion
        // stores the durable value and per-system overrides.
        widescreenHackEnabled = api.memory.has("emufusionWidescreenHack") ?
                Boolean(api.memory.get("emufusionWidescreenHack")) : false
        refreshWidescreenHack()
        // This selector supersedes both old automatic/Boolean settings. Force
        // one safe OFF migration so an existing install cannot retain a hidden
        // qualification backend after updating.
        if (!api.memory.has("lucentFrameGenerationThreeModeV3")) {
            frameGenerationMode = "off"
            frameGenerationModeConfirmed = false
            setFrameGenerationMode("off")
        } else {
            frameGenerationMode = api.memory.has("lucentFrameGenerationModeV3") ?
                    normalizedFrameGenerationMode(
                            api.memory.get("lucentFrameGenerationModeV3")) : "off"
            refreshFrameGenerationStatus()
        }
        // Burn-in protection is on unless the owner explicitly turned it off.
        screensaverEnabled = api.memory.has("lucentScreensaverEnabled") ?
                Boolean(api.memory.get("lucentScreensaverEnabled")) : true
        screensaverTopStillSince = Date.now()
        // Menu sound effects are on by default; only an explicit OFF persists.
        soundEffectsEnabled = api.memory.has("lucentSoundEffects") ?
                Boolean(api.memory.get("lucentSoundEffects")) : true
        requestPreviewEndpoint("settings/sfx?enabled=" +
                (soundEffectsEnabled ? "1" : "0"))
        systemLedCommit.restart()
        var rememberedSystem = api.memory.has("thoriumSystem") ? api.memory.get("thoriumSystem") : 0
        // Version 1 inserts All Systems ahead of the old Arcade index. Shift a
        // saved pre-aggregate selection once so it still points to the same
        // physical platform after the model gains its new first item.
        if (!api.memory.has("thoriumAllSystemsIndexV1") && api.memory.has("thoriumSystem")) {
            rememberedSystem += 1
            api.memory.set("thoriumAllSystemsIndexV1", true)
        }
        systemRail.currentIndex = Math.max(0, Math.min(systemModel.count - 1, rememberedSystem))
        var rememberedGame = api.memory.has("thoriumGame") ? api.memory.get("thoriumGame") : 0
        var rememberedPage = api.memory.has("thoriumPage") ? api.memory.get("thoriumPage") : "home"
        if (!api.memory.has("thoriumCriticSortDefaultV3")) {
            sortMode = "critic"
            api.memory.set("thoriumSortMode", sortMode)
            api.memory.set("thoriumCriticSortDefaultV3", true)
        } else {
            sortMode = api.memory.has("thoriumSortMode") ? api.memory.get("thoriumSortMode") : "user"
        }
        gameViewMode = api.memory.has("thoriumGameView") ?
                api.memory.get("thoriumGameView") : "covers"
        homeViewMode = api.memory.has("thoriumHomeView") ?
                api.memory.get("thoriumHomeView") : "covers"
        if (rememberedPage === "games") {
            activeSystemIndex = systemRail.currentIndex
            allSystemsActive = activeSystemIndex === 0
            activeCollection = allSystemsActive ? null : collectionAtSystem(activeSystemIndex)
            activateCachedSystemSort()
            page = "games"
        } else {
            page = "home"
            homeZone = 0
        }
        initializeHardwarePhotos()
        updateClock()
        previewReady = true
        var returningFromGame = api.memory.has("parallaxReturningFromGame") &&
                Boolean(api.memory.get("parallaxReturningFromGame"))
        api.memory.set("parallaxReturningFromGame", false)
        if (!returningFromGame)
            applyConfiguredStartView()
        if (!returningFromGame)
            Qt.callLater(function() { root.startImportScan() })
        else
            Qt.callLater(function() { root.pollImportStatus() })
        Qt.callLater(function() {
            if (root.page === "games") {
                gameRail.currentIndex = Math.max(0,
                        Math.min(activeGameCount - 1, rememberedGame))
                if (root.gameViewMode === "list")
                    root.positionGameListAtIndex(gameRail.currentIndex)
                else
                    gameRail.positionViewAtIndex(gameRail.currentIndex, ListView.Center)
                root.activateGamePreview()
            } else {
                if (root.homeViewMode === "list") {
                    root.homeListCategory = 1
                    root.rebuildHomeList()
                } else {
                    systemRail.positionViewAtIndex(systemRail.currentIndex, ListView.Center)
                    root.activateHomePreview(true)
                }
            }
        })
        root.forceActiveFocus()
    }

    Keys.onPressed: {
        // Volume and other platform keys must fall straight through, before any
        // branch below can run: almost every branch ends in event.accepted =
        // true regardless of which key arrived, so a volume press was being
        // swallowed here and Android's own handling never saw it. That is the
        // whole reason tapping volume did nothing while holding it worked --
        // only the auto-repeat path escaped. Android raises, unmutes and shows
        // the slider correctly on its own, so the only job here is to not eat
        // the key.
        if (root.isPlatformVolumeKey(event)) {
            event.accepted = false
            return
        }
        if (root.screensaverActive || root.screensaverRequestPending) {
            root.stopScreensaver()
            event.accepted = true
            return
        }
        root.noteScreensaverVisualChange()
        if (voiceFeedbackOpen) {
            if (event.key === Qt.Key_Left || event.key === Qt.Key_Right ||
                    event.key === Qt.Key_Up || event.key === Qt.Key_Down)
                voiceFeedbackChoice = voiceFeedbackChoice === 0 ? 1 : 0
            else if (api.keys.isAccept(event)) {
                if (voiceFeedbackChoice === 0) sendVoiceFeedback()
                else startVoiceFeedback()
            } else if (api.keys.isCancel(event) || event.key === Qt.Key_Back ||
                       event.key === Qt.Key_Escape) {
                closeVoiceFeedback()
            }
            event.accepted = true
        } else if (updatePromptOpen) {
            if (event.key === Qt.Key_Left || event.key === Qt.Key_Right ||
                    event.key === Qt.Key_Up || event.key === Qt.Key_Down)
                updatePromptChoice = updatePromptChoice === 0 ? 1 : 0
            else if (api.keys.isAccept(event)) {
                if (updatePromptChoice === 0) installReadyUpdate()
                else dismissReadyUpdate()
            } else if (api.keys.isCancel(event) || event.key === Qt.Key_Back ||
                       event.key === Qt.Key_Escape) {
                dismissReadyUpdate()
            }
            event.accepted = true
        } else if (aboutOpen) {
            if (api.keys.isAccept(event) || api.keys.isCancel(event) ||
                    event.key === Qt.Key_Back || event.key === Qt.Key_Escape ||
                    api.keys.isDetails(event))
                aboutOpen = false
            event.accepted = true
        } else if (accentEditorOpen) {
            if (api.keys.isCancel(event) || event.key === Qt.Key_Back ||
                    event.key === Qt.Key_Escape) {
                accentEditorOpen = false
            } else if (event.key === Qt.Key_Up) {
                accentEditorChannel = Math.max(0, accentEditorChannel - 1)
            } else if (event.key === Qt.Key_Down) {
                accentEditorChannel = Math.min(3, accentEditorChannel + 1)
            } else if (event.key === Qt.Key_Left) {
                adjustAccentEditor(-1)
            } else if (event.key === Qt.Key_Right) {
                adjustAccentEditor(1)
            } else if (api.keys.isFilters(event)) {
                resetAccentEditorColor()
            } else if (api.keys.isAccept(event)) {
                storeAccentEditorColor()
                accentEditorOpen = false
            }
            event.accepted = true
        } else if (gameActionOpen) {
            if (gameActionMode === "rename" && renameField.activeFocus) {
                if (api.keys.isCancel(event) || event.key === Qt.Key_Back || event.key === Qt.Key_Escape) {
                    Qt.inputMethod.reset()
                    Qt.inputMethod.hide()
                    renameField.focus = false
                    gameActionMode = "menu"
                    root.forceActiveFocus()
                }
                event.accepted = true
            } else if (gameActionMode === "menu") {
                if (api.keys.isCancel(event) || event.key === Qt.Key_Back || event.key === Qt.Key_Escape) {
                    closeGameActions()
                } else if (event.key === Qt.Key_Up || event.key === Qt.Key_Down ||
                           event.key === Qt.Key_Left || event.key === Qt.Key_Right) {
                    moveGameActionSelection(
                                event.key === Qt.Key_Up || event.key === Qt.Key_Left ? -1 : 1)
                } else if (api.keys.isAccept(event)) {
                    if (gameActionIndex === 0) beginRenameGame()
                    else if (gameActionIndex === gameActionCheatsOptionIndex())
                        openGameActionCheats()
                    else if (gameActionAllowsRemoveFromList() &&
                             gameActionIndex === gameActionRemoveOptionIndex())
                        gameActionMode = "confirm-remove"
                    else if (gameActionIndex === gameActionMultiplayerOptionIndex())
                        openGameActionMultiplayer()
                    else gameActionMode = "confirm-delete"
                }
                event.accepted = true
            } else if (gameActionMode === "cheats") {
                if (api.keys.isCancel(event) || event.key === Qt.Key_Back ||
                        event.key === Qt.Key_Escape) {
                    gameActionMode = "menu"
                } else if (event.key === Qt.Key_Up || event.key === Qt.Key_Down) {
                    moveGameActionCheatSelection(event.key === Qt.Key_Up ? -1 : 1)
                } else if (api.keys.isAccept(event)) {
                    toggleGameActionCheat(gameActionCheatIndex)
                }
                event.accepted = true
            } else if (gameActionMode === "confirm-remove") {
                if (api.keys.isCancel(event) || event.key === Qt.Key_Back || event.key === Qt.Key_Escape) gameActionMode = "menu"
                else if (api.keys.isAccept(event)) submitRemoveFromList()
                event.accepted = true
            } else if (gameActionMode === "confirm-delete") {
                if (api.keys.isCancel(event) || event.key === Qt.Key_Back || event.key === Qt.Key_Escape) gameActionMode = "menu"
                else if (api.keys.isAccept(event)) submitDeleteGame()
                event.accepted = true
            } else if (gameActionMode === "multiplayer") {
                if (api.keys.isCancel(event) || event.key === Qt.Key_Back || event.key === Qt.Key_Escape) {
                    gameActionMode = "menu"
                } else if (api.keys.isAccept(event)) {
                    setGameActionMultiplayerWant(!gameActionMultiplayerWant)
                }
                event.accepted = true
            } else if (gameActionMode !== "working") {
                if (api.keys.isAccept(event) || api.keys.isCancel(event) || event.key === Qt.Key_Back || event.key === Qt.Key_Escape) closeGameActions()
                event.accepted = true
            } else {
                event.accepted = true
            }
        } else if (searchField.activeFocus) {
            // Text and IME key events must never fall through to Pegasus's
            // controller aliases (for example, the letter A as Accept).
            if (event.nativeScanCode === 305 || event.key === Qt.Key_Back ||
                    event.key === Qt.Key_Escape) {
                endSearch()
                event.accepted = true
            } else {
                event.accepted = false
            }
        } else if (searchOpen && (api.keys.isCancel(event) ||
                                  event.key === Qt.Key_Back ||
                                  event.key === Qt.Key_Escape)) {
            endSearch()
            event.accepted = true
        } else if (legalOpen) {
            // Readable, scrollable text. Unlike the first-launch popup there is
            // no scroll gate and no checkbox here: this copy exists to be
            // re-read, not to be accepted again.
            if (event.key === Qt.Key_Up) scrollLegalNotice(-1)
            else if (event.key === Qt.Key_Down) scrollLegalNotice(1)
            else if (api.keys.isPrevPage(event)) scrollLegalNotice(-4)
            else if (api.keys.isNextPage(event)) scrollLegalNotice(4)
            else if (api.keys.isCancel(event) || event.key === Qt.Key_Back ||
                     event.key === Qt.Key_Escape || api.keys.isAccept(event) ||
                     api.keys.isDetails(event)) {
                legalOpen = false
                settingsOpen = true
            }
            event.accepted = true
        } else if (customEmulatorOpen) {
            if (customEmulatorEditor.editing) {
                // The on-screen keyboard owns the keys while a field is open;
                // only Back and Accept end the edit.
                if (api.keys.isCancel(event) || event.key === Qt.Key_Back ||
                        event.key === Qt.Key_Escape)
                    customEmulatorEditor.endEditing(false)
                else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter)
                    customEmulatorEditor.endEditing(true)
                else { event.accepted = false; return }
                event.accepted = true
                return
            }
            if (api.keys.isCancel(event) || event.key === Qt.Key_Back ||
                    event.key === Qt.Key_Escape) {
                customEmulatorOpen = false
            } else if (event.key === Qt.Key_Up) {
                customEmulatorIndex = Math.max(0, customEmulatorIndex - 1)
            } else if (event.key === Qt.Key_Down) {
                customEmulatorIndex = Math.min(customEmulatorRowCount() - 1,
                                               customEmulatorIndex + 1)
            } else if (event.key === Qt.Key_Left) {
                if (customEmulatorField(customEmulatorIndex) === "delivery")
                    cycleCustomEmulatorDelivery(-1)
            } else if (event.key === Qt.Key_Right) {
                if (customEmulatorField(customEmulatorIndex) === "delivery")
                    cycleCustomEmulatorDelivery(1)
            } else if (api.keys.isAccept(event)) {
                activateCustomEmulatorRow()
            }
            event.accepted = true
        } else if (emulatorPickerOpen) {
            if (api.keys.isCancel(event) || event.key === Qt.Key_Back ||
                    event.key === Qt.Key_Escape) {
                emulatorPickerOpen = false
                emulatorPickerNotice = ""
            } else if (event.key === Qt.Key_Up) {
                emulatorPickerIndex = Math.max(0, emulatorPickerIndex - 1)
            } else if (event.key === Qt.Key_Down) {
                emulatorPickerIndex = Math.min(
                        emulatorPickerRowList.length - 1, emulatorPickerIndex + 1)
            } else if (api.keys.isAccept(event)) {
                activateEmulatorPickerRow()
            }
            event.accepted = true
        } else if (emulatorRoutesOpen) {
            if (api.keys.isCancel(event) || event.key === Qt.Key_Back ||
                    event.key === Qt.Key_Escape || api.keys.isDetails(event)) {
                emulatorRoutesOpen = false
                settingsOpen = true
            } else if (event.key === Qt.Key_Up) {
                emulatorRoutesIndex = Math.max(0, emulatorRoutesIndex - 1)
            } else if (event.key === Qt.Key_Down) {
                emulatorRoutesIndex = Math.min(emulatorRouteSystems.length - 1,
                                               emulatorRoutesIndex + 1)
            } else if (api.keys.isPrevPage(event)) {
                // Fifty-odd systems is too many to walk one row at a time, and
                // Left/Right is already spoken for by the route toggle.
                emulatorRoutesIndex = Math.max(0,
                        emulatorRoutesIndex - routesPageSize)
            } else if (api.keys.isNextPage(event)) {
                emulatorRoutesIndex = Math.min(emulatorRouteSystems.length - 1,
                        emulatorRoutesIndex + routesPageSize)
            } else if (event.key === Qt.Key_Left) {
                toggleEmulatorRoute(-1)
            } else if (event.key === Qt.Key_Right) {
                toggleEmulatorRoute(1)
            } else if (api.keys.isAccept(event)) {
                var routeSystem = currentRouteSystem()
                if (routeSystem)
                    openEmulatorPicker(routeSystem.system, routeSystem.collection)
            }
            event.accepted = true
        } else if (artworkReviewOpen) {
            if (api.keys.isCancel(event) || event.key === Qt.Key_Back ||
                    event.key === Qt.Key_Escape || api.keys.isDetails(event)) {
                // A back press while the delete is armed disarms it instead of
                // leaving, so the destructive option can always be backed out
                // of with the same button that backs out of everything else.
                if (artworkReviewConfirming) {
                    artworkReviewConfirming = false
                    artworkReviewMessage = ""
                } else {
                    closeArtworkReview()
                    settingsOpen = true
                }
            } else if (event.key === Qt.Key_Up) {
                artworkReviewMoveRow(-1)
            } else if (event.key === Qt.Key_Down) {
                artworkReviewMoveRow(1)
            } else if (event.key === Qt.Key_Left) {
                artworkReviewMoveChoice(-1)
            } else if (event.key === Qt.Key_Right) {
                artworkReviewMoveChoice(1)
            } else if (api.keys.isAccept(event)) {
                submitArtworkChoice()
            }
            event.accepted = true
        } else if (coverOrderEditorOpen) {
            if (api.keys.isCancel(event) || event.key === Qt.Key_Back ||
                    event.key === Qt.Key_Escape || api.keys.isDetails(event)) {
                coverOrderEditorOpen = false
                settingsOpen = true
            } else if (event.key === Qt.Key_Up) {
                coverOrderEditorIndex = Math.max(0, coverOrderEditorIndex - 1)
            } else if (event.key === Qt.Key_Down) {
                coverOrderEditorIndex = Math.min(coverRowOrder.length - 1,
                                                 coverOrderEditorIndex + 1)
            } else if (event.key === Qt.Key_Left) {
                moveCoverOrderItem(-1)
            } else if (event.key === Qt.Key_Right || api.keys.isAccept(event)) {
                moveCoverOrderItem(1)
            }
            event.accepted = true
        } else if (settingsOpen) {
            if (api.keys.isCancel(event) || event.key === Qt.Key_Back ||
                    event.key === Qt.Key_Escape || api.keys.isDetails(event)) {
                settingsOpen = false
            } else if (event.key === Qt.Key_Up) {
                settingsIndex = Math.max(0, settingsIndex - 1)
            } else if (event.key === Qt.Key_Down) {
                settingsIndex = Math.min(settingsOptionCount - 1,
                                         settingsIndex + 1)
            } else if (event.key === Qt.Key_Left) {
                activateSetting(-1)
            } else if (event.key === Qt.Key_Right) {
                activateSetting(1)
            } else if (api.keys.isAccept(event)) {
                activateSetting(0)
            }
            event.accepted = true
        } else if (handleRightStickViewKey(event)) {
            event.accepted = true
        } else if (page === "home") {
            if (api.keys.isDetails(event)) {
                settingsOpen = true
                settingsIndex = 0
                event.accepted = true
            } else if (api.keys.isFilters(event)) {
                toggleHomeView()
                event.accepted = true
            } else if (homeViewMode === "list") {
                var homeSystemDirection = triggerDirection(event)
                if (api.keys.isCancel(event) || event.key === Qt.Key_Back ||
                        event.key === Qt.Key_Escape) {
                    if (homeListFocusColumn === 1) {
                        homeListFocusColumn = 0
                        rebuildHomeList()
                    }
                } else if (homeSystemDirection !== 0) {
                    rememberHandledTrigger(homeSystemDirection)
                    stepSystem(homeSystemDirection)
                } else if (api.keys.isPrevPage(event)) {
                    cycleHomeListCategory(-1)
                } else if (api.keys.isNextPage(event)) {
                    cycleHomeListCategory(1)
                } else if (event.key === Qt.Key_Left) {
                    stepHomeListPage(-1)
                } else if (event.key === Qt.Key_Right) {
                    stepHomeListPage(1)
                } else if (event.key === Qt.Key_Up) {
                    if (homeListFocusColumn === 0)
                        stepSystem(-1)
                    else if (homeListEntries.length > 0)
                        homeListRail.decrementCurrentIndex()
                } else if (event.key === Qt.Key_Down) {
                    if (homeListFocusColumn === 0)
                        stepSystem(1)
                    else if (homeListEntries.length > 0)
                        homeListRail.incrementCurrentIndex()
                } else if (api.keys.isAccept(event)) {
                    if (homeListFocusColumn === 0)
                        enterHomeListGames()
                    else
                        launch(activeGame)
                }
                event.accepted = true
            } else {
                var coverSystemDirection = triggerDirection(event)
                if (coverSystemDirection !== 0) {
                    rememberHandledTrigger(coverSystemDirection)
                    stepSystem(coverSystemDirection)
                    event.accepted = true
                } else if (api.keys.isPrevPage(event)) {
                    stepCoverZone(-1)
                    event.accepted = true
                } else if (api.keys.isNextPage(event)) {
                    stepCoverZone(1)
                    event.accepted = true
                } else if (event.key === Qt.Key_Up) {
                stepCoverZone(-1)
                event.accepted = true
                } else if (event.key === Qt.Key_Down) {
                stepCoverZone(1)
                event.accepted = true
                } else if (event.key === Qt.Key_Left) {
                if (homeZone === 0)
                    root.stepSystem(-1)
                else
                    root.stepHomeShelf(-1)
                event.accepted = true
                } else if (event.key === Qt.Key_Right) {
                if (homeZone === 0)
                    root.stepSystem(1)
                else
                    root.stepHomeShelf(1)
                event.accepted = true
                } else if (api.keys.isAccept(event)) {
                if (homeZone === 0)
                    enterCollection()
                else
                    launch(homeShelfGame(homeZone))
                event.accepted = true
                }
            }
        } else {
            var openSystemDirection = triggerDirection(event)
            // Raw Thor trigger identity must win over every generic Pegasus
            // alias. On the first press after reversing L2/R2, this Qt build
            // can briefly retain the previous semantic alias; checking
            // Cancel/PageUp first swallowed that otherwise valid scan code.
            if (api.keys.isDetails(event)) {
                settingsOpen = true
                settingsIndex = 0
                event.accepted = true
            } else if (api.keys.isFilters(event)) {
                toggleGameView()
                event.accepted = true
            } else if (openSystemDirection !== 0) {
                rememberHandledTrigger(openSystemDirection)
                stepOpenSystem(openSystemDirection)
                event.accepted = true
            } else if (api.keys.isCancel(event) || event.key === Qt.Key_Back ||
                       event.key === Qt.Key_Escape) {
                returnHome()
                event.accepted = true
            } else if (event.key === 1048576 &&
                       (api.keys.isPageUp(event) || api.keys.isPageDown(event))) {
                // Thor's Qt input plugin reports the same generic pressed key
                // for both triggers and can retain the previous direction's
                // semantic alias. Consume that ambiguous edge; the released
                // edge below carries the correct physical identity.
                event.accepted = true
            } else if (api.keys.isPageUp(event)) {
                stepOpenSystem(-1)
                event.accepted = true
            } else if (api.keys.isPageDown(event)) {
                stepOpenSystem(1)
                event.accepted = true
            } else if (api.keys.isPrevPage(event)) {
                cycleSort(-1)
                event.accepted = true
            } else if (api.keys.isNextPage(event)) {
                cycleSort(1)
                event.accepted = true
            } else if (event.key === Qt.Key_Left) {
                if (gameViewMode === "list")
                    gameRail.currentIndex = Math.max(0, gameRail.currentIndex - 8)
                else
                    gameRail.decrementCurrentIndex()
                event.accepted = true
            } else if (event.key === Qt.Key_Right) {
                if (gameViewMode === "list")
                    gameRail.currentIndex = Math.min(gameRail.count - 1, gameRail.currentIndex + 8)
                else
                    gameRail.incrementCurrentIndex()
                event.accepted = true
            } else if (event.key === Qt.Key_Up) {
                if (gameViewMode === "list")
                    gameRail.decrementCurrentIndex()
                else
                    gameRail.currentIndex = Math.max(0, gameRail.currentIndex - 6)
                event.accepted = true
            } else if (event.key === Qt.Key_Down) {
                if (gameViewMode === "list")
                    gameRail.incrementCurrentIndex()
                else
                    gameRail.currentIndex = Math.min(gameRail.count - 1, gameRail.currentIndex + 6)
                event.accepted = true
            } else if (api.keys.isAccept(event)) {
                launch(activeGame)
                event.accepted = true
            }
        }
    }

    Keys.onReleased: {
        // See Keys.onPressed: the platform owns these, and a swallowed release
        // leaves Android with a half-delivered key.
        if (root.isPlatformVolumeKey(event)) {
            event.accepted = false
            return
        }
        if (searchField.activeFocus || root.settingsOpen ||
                (root.page !== "games" && root.page !== "home"))
            return
        var direction = root.triggerDirection(event)
        if (direction < 0) {
            if (!root.leftTriggerPressHandled)
                root.page === "games" ? root.stepOpenSystem(-1) : root.stepSystem(-1)
            root.leftTriggerPressHandled = false
            event.accepted = true
        } else if (direction > 0) {
            if (!root.rightTriggerPressHandled)
                root.page === "games" ? root.stepOpenSystem(1) : root.stepSystem(1)
            root.rightTriggerPressHandled = false
            event.accepted = true
        }
    }

    Timer {
        id: importPollTimer
        interval: 1200
        // Import progress is frontend chrome; it cannot be seen behind a game.
        // The scan itself keeps running -- only the polling of it stops.
        running: !root.gameplayActive
        repeat: true
        onTriggered: root.pollImportStatus()
    }

    Timer {
        id: screensaverWatch
        interval: 5000
        repeat: true
        running: root.screensaverEnabled && !root.gameplayActive
        triggeredOnStart: false
        onTriggered: root.pollScreensaverStatus()
    }

    Timer {
        id: screensaverAdvanceRetry
        interval: 1000
        repeat: false
        onTriggered: root.advanceScreensaverVideo()
    }

    Timer {
        id: screensaverCompletionWatch
        interval: 500
        repeat: true
        running: root.screensaverActive && !root.gameplayActive
        onTriggered: if (root.screensaverPlaybackFinished())
                         root.advanceScreensaverVideo()
    }

    Timer {
        id: importToastDismiss
        interval: root.importState === "error" ? 12000 :
                  (root.importAdded > 0 || root.importNeedsReload ? 7000 : 4200)
        repeat: false
        onTriggered: root.importToastVisible = false
    }

    Timer {
        id: importedLibraryReload
        interval: 900
        repeat: false
        onTriggered: root.requestPreviewEndpoint("import/reload")
    }

    Rectangle {
        id: importToast
        z: 300
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.topMargin: 108
        anchors.rightMargin: 46
        width: 430
        height: root.importDetail !== "" ? 148 : (root.importIdentified > 0 ? 126 : 96)
        visible: root.importToastVisible
        color: "#ee0b0f16"
        border.width: 1
        border.color: root.importState === "error" ? "#ff6d70" : root.accent
        radius: 4

        Rectangle {
            x: 16
            y: 18
            width: 4
            height: 36
            color: root.importState === "error" ? "#ff6d70" : root.accent
        }

        Text {
            x: 34
            y: 15
            width: parent.width - 50
            text: root.importState === "complete" ? "LIBRARY UPDATE COMPLETE" :
                  root.importState === "error" ? "LIBRARY UPDATE PAUSED" :
                  "UPDATING GAME LIBRARY"
            color: "#f2f4f8"
            font.family: global.fonts.condensed
            font.pixelSize: 16
            font.weight: Font.Bold
            font.letterSpacing: 1.6
        }

        Text {
            x: 34
            y: 42
            width: parent.width - 50
            text: root.importMessage
            color: "#aeb7c8"
            elide: Text.ElideRight
            font.family: global.fonts.sans
            font.pixelSize: 12
        }

        Text {
            x: 34
            y: 66
            width: parent.width - 50
            visible: root.importDetail === "" && root.importIdentified > 0
            text: {
                var shown = root.importTitles.slice(0, 2).join("  •  ")
                if (root.importTitles.length > 2)
                    shown += "  •  +" + (root.importTitles.length - 2) + " more"
                return shown
            }
            color: root.accent
            elide: Text.ElideRight
            font.family: global.fonts.sans
            font.pixelSize: 11
            font.weight: Font.DemiBold
        }

        Text {
            x: 34
            y: 68
            width: parent.width - 50
            visible: root.importDetail !== ""
            text: root.importDetail
            color: root.accent
            elide: Text.ElideMiddle
            font.family: global.fonts.sans
            font.pixelSize: 11
            font.weight: Font.DemiBold
        }

        Text {
            x: 34
            y: 91
            width: parent.width - 50
            visible: root.importDetail !== "" && root.importTotal > 0
            text: root.importCurrent + " OF " + root.importTotal
            color: "#aeb7c8"
            font.family: global.fonts.sans
            font.pixelSize: 10
            font.letterSpacing: 1.2
        }

        Rectangle {
            x: 34
            y: parent.height - 18
            width: parent.width - 50
            height: 3
            color: "#26303e"

            Rectangle {
                width: parent.width * Math.max(0, Math.min(1, root.importProgress))
                height: parent.height
                color: root.importState === "error" ? "#ff6d70" : root.accent
                Behavior on width { NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }
            }
        }
    }

    Timer {
        // Never stops: this is the only poll that can observe gameplay ending.
        // It backs off while a game runs so the emulator keeps the CPU.
        interval: root.gameplayActive || Qt.application.state !== Qt.ApplicationActive ? 2000 : 700
        repeat: true
        running: true
        triggeredOnStart: true
        onTriggered: {
            var applicationActive = Qt.application.state === Qt.ApplicationActive
            if (applicationActive) {
                if (!root.applicationWasActive && root.previewReady) {
                    // Rebuild the complete warm set after launch/resume. A
                    // current-only refresh would evict the preloaded neighbors
                    // and reintroduce a black frame on the very first move.
                    if (root.page === "home" && root.homeViewMode === "list")
                        root.activateHomeListPreview()
                    else if (root.page === "home" && root.homeZone === 0)
                        root.activateHomePreview(false)
                    else if (root.page === "games")
                        root.activateGamePreview()
                    else
                        root.activateShelfPreview(root.homeZone)
                }
            }
            root.sendPreviewHeartbeat()
            root.applicationWasActive = applicationActive
        }
    }

    Timer {
        interval: 180
        repeat: true
        // Nothing on the lower display can request a launch while a game is
        // already running, so this poll has nothing to learn during one.
        running: !root.gameplayActive
        onTriggered: root.pollBottomLaunchRequest()
    }

    Timer {
        interval: 30000
        repeat: true
        // The clock is the last poller that still dirtied the scene graph
        // during gameplay, and a scene-graph change is a full Qt Quick render
        // pass underneath a running emulator. triggeredOnStart puts the real
        // time back on screen the instant gameplay ends, so nothing is stale
        // by the time it can be read.
        running: !root.gameplayActive
        triggeredOnStart: true
        onTriggered: root.updateClock()
    }

    Timer {
        interval: 1800
        repeat: true
        // An update banner cannot be seen behind a game; poll again on return.
        running: !root.gameplayActive
        triggeredOnStart: true
        onTriggered: root.pollUpdateStatus()
    }

    Timer {
        id: voiceFeedbackStatusPoll
        interval: 320
        repeat: false
        onTriggered: root.pollVoiceFeedback()
    }

    Timer {
        id: libraryIndexRetry
        interval: 900
        repeat: false
        onTriggered: root.loadLibraryIndex()
    }

    Timer {
        id: libraryIndexBuildTimer
        interval: 1
        repeat: false
        onTriggered: root.continueLibraryIndexBuild()
    }

    Timer {
        id: systemLedCommit
        interval: 12
        repeat: false
        onTriggered: root.applySystemLedColor()
    }

    // Stock Thor controls can reapply their static LED color after focus or
    // power-state changes. Reassert the selected system color at low frequency;
    // the companion preserves any externally changed AYN brightness value.
    Timer {
        // Backed off rather than stopped during gameplay: stock firmware can
        // still reset the LEDs mid-game, and letting them revert to the stock
        // colour would be a visible regression. A quarter of the poll rate
        // still reasserts well within a user's notice.
        interval: root.gameplayActive ? 3000 : 750
        repeat: true
        running: root.systemLedEnabled
        onTriggered: root.applySystemLedColor()
    }

    Timer {
        id: navigationPersistence
        interval: 220
        repeat: false
        onTriggered: root.flushNavigationPersistence()
    }

    // Keep preview selection out of the D-pad event turn. Fast presses update
    // the rail immediately and only the settled selection starts a movie.
    Timer {
        id: systemChangeCommit
        interval: 24
        repeat: false
        onTriggered: {
            if (root.page !== "home" || root.homeZone !== 0)
                return
            root.activateHomePreview(false)
        }
    }

    Timer {
        id: homeListRebuild
        interval: 1
        repeat: false
        onTriggered: root.rebuildHomeList()
    }

    Timer {
        id: sortChangeCommit
        interval: 1
        repeat: false
        onTriggered: {
            if (root.page !== "games")
                return
            gameRail.currentIndex = 0
            if (root.gameViewMode === "list")
                gameListRail.positionViewAtIndex(0, ListView.Beginning)
            else
                gameRail.positionViewAtIndex(0, ListView.Beginning)
            root.activateGamePreview()
            root.forceActiveFocus()
        }
    }

    Timer {
        id: searchChangeCommit
        interval: 80
        repeat: false
        onTriggered: {
            if (root.page !== "games")
                return
            gameRail.currentIndex = 0
            if (activeGameCount > 0) {
                if (root.gameViewMode === "list")
                    gameListRail.positionViewAtIndex(0, ListView.Beginning)
                else
                    gameRail.positionViewAtIndex(0, ListView.Beginning)
            }
            root.activateGamePreview()
        }
    }

    // A collection source changes synchronously, but its native sorted proxy
    // settles on the next event-loop turn. Coalesce rapid L2/R2 presses and
    // submit the lower-screen selection only after the final platform's row 0
    // exists. This prevents a one-request flash from the departed system.
    Timer {
        id: systemOpenCommit
        interval: 1
        repeat: false
        onTriggered: {
            if (root.page !== "games")
                return
            gameRail.currentIndex = 0
            if (root.gameViewMode === "list")
                gameListRail.positionViewAtIndex(0, ListView.Beginning)
            else
                gameRail.positionViewAtIndex(0, ListView.Beginning)
            root.activateGamePreview()
            root.forceActiveFocus()
        }
    }

    // Once the user settles on a new system, quietly replace the system they
    // just left with another random preview. Fast backtracking stays instant;
    // a later revisit gets a different game instead of item zero every time.
    Timer {
        id: rerollDepartedPreview
        interval: 700
        repeat: false
        onTriggered: {
            var departed = root.departedSystemIndex
            if (departed < 0 || root.page !== "home")
                return
            var oldGame = root.lastHomeGameBySystem[departed] || null
            var replacement = root.randomHomeVideoGame(departed, oldGame)
            root.lastHomeGameBySystem[departed] = replacement
            var slot = root.slotFor("home", departed, -1)
            if (slot && slot !== root.activePreviewSlot)
                root.assignSlot(slot, "home", departed, -1, replacement)
            root.departedSystemIndex = -1
            // The slot above is already refreshed. Do not re-run the current
            // selection and HTTP update merely because a neighbor rerolled.
        }
    }

    ListModel {
        id: systemModel
        // All Systems is always present. Physical system cards are appended
        // from the catalog only when Pegasus actually found ROMs for them.
        ListElement { name: "ALL SYSTEMS"; years: "FULL LIBRARY"; mark: "ALL"; collectionName: ""; folder: "all"; family: ""; accent: "#dce4f2" }
    }

    ListModel {
        id: systemCatalog
        // Chronological by first retail release. Years describe the primary
        // hardware/product lifecycle rather than online-service availability.
        ListElement { name: "ALL SYSTEMS"; years: "FULL LIBRARY"; mark: "ALL"; collectionName: ""; folder: "all"; family: ""; accent: "#dce4f2" }
        ListElement { name: "ARCADE"; years: "1971–PRESENT"; mark: "AR"; collectionName: "Arcade"; folder: "arcade"; family: "arcade"; accent: "#35d0e6" }
        ListElement { name: "APPLE II"; years: "1977–1993"; mark: "AII"; collectionName: "Apple II"; folder: "apple2"; family: "apple"; accent: "#a8b2c1" }
        ListElement { name: "ATARI 2600"; years: "1977–1992"; mark: "2600"; collectionName: "Atari 2600"; folder: "atari2600"; family: "atari"; accent: "#ff5964" }
        ListElement { name: "MAGNAVOX ODYSSEY²"; years: "1978–1984"; mark: "O²"; collectionName: "Magnavox Odyssey²"; folder: "odyssey2"; family: "magnavox"; accent: "#c7f464" }
        ListElement { name: "MATTEL INTELLIVISION"; years: "1979–1990"; mark: "INTV"; collectionName: "Mattel Intellivision"; folder: "intellivision"; family: "mattel"; accent: "#48cae4" }
        ListElement { name: "ATARI 8-BIT"; years: "1979–1992"; mark: "A8"; collectionName: "Atari 8-bit"; folder: "atari800"; family: "atari"; accent: "#ff5964" }
        ListElement { name: "DOS"; years: "1981–2000"; mark: "DOS"; collectionName: "DOS"; folder: "dos"; family: "microsoft"; accent: "#4aa3ff" }
        ListElement { name: "ATARI 5200"; years: "1982–1984"; mark: "5200"; collectionName: "Atari 5200"; folder: "atari5200"; family: "atari"; accent: "#ff5964" }
        ListElement { name: "COLECOVISION"; years: "1982–1985"; mark: "CV"; collectionName: "ColecoVision"; folder: "colecovision"; family: "coleco"; accent: "#f72585" }
        ListElement { name: "COMMODORE 64"; years: "1982–1994"; mark: "C64"; collectionName: "Commodore 64"; folder: "c64"; family: "commodore"; accent: "#23c9b8" }
        ListElement { name: "ZX SPECTRUM"; years: "1982–1992"; mark: "ZX"; collectionName: "Sinclair ZX Spectrum"; folder: "zxspectrum"; family: "sinclair"; accent: "#e63946" }
        ListElement { name: "NINTENDO ENTERTAINMENT SYSTEM"; years: "1983–2003"; mark: "NES"; collectionName: "Nintendo Entertainment System"; folder: "nes"; family: "nintendo"; accent: "#ff9f43" }
        ListElement { name: "SEGA SG-1000"; years: "1983–1985"; mark: "SG"; collectionName: "Sega SG-1000"; folder: "sg1000"; family: "sega"; accent: "#4fd17f" }
        ListElement { name: "MSX"; years: "1983–1995"; mark: "MSX"; collectionName: "Microsoft MSX"; folder: "msx"; family: "microsoft"; accent: "#4aa3ff" }
        ListElement { name: "AMSTRAD CPC"; years: "1984–1990"; mark: "CPC"; collectionName: "Amstrad CPC"; folder: "amstradcpc"; family: "amstrad"; accent: "#00b4d8" }
        ListElement { name: "COMMODORE AMIGA"; years: "1985–1996"; mark: "AMIGA"; collectionName: "Commodore Amiga"; folder: "amiga"; family: "commodore"; accent: "#23c9b8" }
        ListElement { name: "ATARI ST"; years: "1985–1993"; mark: "ST"; collectionName: "Atari ST"; folder: "atarist"; family: "atari"; accent: "#ff5964" }
        ListElement { name: "SEGA MASTER SYSTEM"; years: "1985–1996"; mark: "SMS"; collectionName: "Sega Master System"; folder: "mastersystem"; family: "sega"; accent: "#4fd17f" }
        ListElement { name: "ATARI 7800"; years: "1986–1992"; mark: "7800"; collectionName: "Atari 7800"; folder: "atari7800"; family: "atari"; accent: "#ff5964" }
        ListElement { name: "NEC PC ENGINE"; years: "1987–1994"; mark: "PCE"; collectionName: "NEC PC Engine"; folder: "pcengine"; family: "nec"; accent: "#ef6cff" }
        ListElement { name: "NEC PC ENGINE CD"; years: "1988–1999"; mark: "PCECD"; collectionName: "NEC PC Engine CD"; folder: "pcenginecd"; family: "nec"; accent: "#ef6cff" }
        ListElement { name: "SEGA GENESIS"; years: "1988–1997"; mark: "GEN"; collectionName: "Sega Genesis"; folder: "megadrive"; family: "sega"; accent: "#4fd17f" }
        ListElement { name: "GAME BOY"; years: "1989–2003"; mark: "GB"; collectionName: "Nintendo Game Boy"; folder: "gb"; family: "nintendo"; accent: "#ff9f43" }
        ListElement { name: "SEGA GAME GEAR"; years: "1990–1997"; mark: "GG"; collectionName: "Sega Game Gear"; folder: "gamegear"; family: "sega"; accent: "#4fd17f" }
        ListElement { name: "SNK NEO GEO"; years: "1990–2004"; mark: "NEO"; collectionName: "SNK Neo Geo"; folder: "neogeo"; family: "snk"; accent: "#ffd166" }
        ListElement { name: "SUPER NINTENDO"; years: "1990–2003"; mark: "SNES"; collectionName: "Super Nintendo Entertainment System"; folder: "snes"; family: "nintendo"; accent: "#ff9f43" }
        ListElement { name: "SEGA CD"; years: "1991–1996"; mark: "SCD"; collectionName: "Sega CD"; folder: "segacd"; family: "sega"; accent: "#4fd17f" }
        ListElement { name: "3DO"; years: "1993–1996"; mark: "3DO"; collectionName: "3DO Interactive Multiplayer"; folder: "3do"; family: "3do"; accent: "#b8f2e6" }
        ListElement { name: "AMIGA CD32"; years: "1993–1994"; mark: "CD32"; collectionName: "Commodore Amiga CD32"; folder: "amigacd32"; family: "commodore"; accent: "#23c9b8" }
        ListElement { name: "ATARI JAGUAR"; years: "1993–1996"; mark: "JAG"; collectionName: "Atari Jaguar"; folder: "jaguar"; family: "atari"; accent: "#ff5964" }
        ListElement { name: "SEGA 32X"; years: "1994–1996"; mark: "32X"; collectionName: "Sega 32X"; folder: "sega32x"; family: "sega"; accent: "#4fd17f" }
        ListElement { name: "SEGA SATURN"; years: "1994–2000"; mark: "SAT"; collectionName: "Sega Saturn"; folder: "saturn"; family: "sega"; accent: "#4fd17f" }
        ListElement { name: "PLAYSTATION"; years: "1994–2006"; mark: "PS1"; collectionName: "Sony PlayStation"; folder: "psx"; family: "sony"; accent: "#a987ff" }
        ListElement { name: "NEO GEO CD"; years: "1994–1997"; mark: "NGCD"; collectionName: "SNK Neo Geo CD"; folder: "neogeocd"; family: "snk"; accent: "#ffd166" }
        ListElement { name: "VIRTUAL BOY"; years: "1995–1996"; mark: "VB"; collectionName: "Nintendo Virtual Boy"; folder: "virtualboy"; family: "nintendo"; accent: "#ff9f43" }
        ListElement { name: "NINTENDO 64"; years: "1996–2002"; mark: "N64"; collectionName: "Nintendo 64"; folder: "n64"; family: "nintendo"; accent: "#ff9f43" }
        ListElement { name: "SEGA DREAMCAST"; years: "1998–2001"; mark: "DC"; collectionName: "Sega Dreamcast"; folder: "dreamcast"; family: "sega"; accent: "#4fd17f" }
        ListElement { name: "GAME BOY COLOR"; years: "1998–2003"; mark: "GBC"; collectionName: "Nintendo Game Boy Color"; folder: "gbc"; family: "nintendo"; accent: "#ff9f43" }
        ListElement { name: "NEO GEO POCKET"; years: "1998–1999"; mark: "NGP"; collectionName: "SNK Neo Geo Pocket"; folder: "ngp"; family: "snk"; accent: "#ffd166" }
        ListElement { name: "BANDAI WONDERSWAN"; years: "1999–2003"; mark: "WS"; collectionName: "Bandai WonderSwan"; folder: "wonderswan"; family: "bandai"; accent: "#ff7d3a" }
        ListElement { name: "PLAYSTATION 2"; years: "2000–2013"; mark: "PS2"; collectionName: "Sony PlayStation 2"; folder: "ps2"; family: "sony"; accent: "#a987ff" }
        ListElement { name: "WONDERSWAN COLOR"; years: "2000–2003"; mark: "WSC"; collectionName: "Bandai WonderSwan Color"; folder: "wonderswancolor"; family: "bandai"; accent: "#ff7d3a" }
        ListElement { name: "GAME BOY ADVANCE"; years: "2001–2010"; mark: "GBA"; collectionName: "Nintendo Game Boy Advance"; folder: "gba"; family: "nintendo"; accent: "#ff9f43" }
        ListElement { name: "NINTENDO GAMECUBE"; years: "2001–2007"; mark: "GC"; collectionName: "Nintendo GameCube"; folder: "gc"; family: "nintendo"; accent: "#ff9f43" }
        ListElement { name: "MICROSOFT XBOX"; years: "2001–2009"; mark: "XBOX"; collectionName: "Microsoft Xbox"; folder: "xbox"; family: "microsoft"; accent: "#4aa3ff" }
        ListElement { name: "NINTENDO DS"; years: "2004–2014"; mark: "NDS"; collectionName: "Nintendo DS"; folder: "nds"; family: "nintendo"; accent: "#ff9f43" }
        ListElement { name: "PLAYSTATION PORTABLE"; years: "2004–2014"; mark: "PSP"; collectionName: "Sony PlayStation Portable"; folder: "psp"; family: "sony"; accent: "#a987ff" }
        ListElement { name: "XBOX 360"; years: "2005–2016"; mark: "X360"; collectionName: "Microsoft Xbox 360"; folder: "xbox360"; family: "microsoft"; accent: "#4aa3ff" }
        ListElement { name: "PLAYSTATION 3"; years: "2006–2017"; mark: "PS3"; collectionName: "Sony PlayStation 3"; folder: "ps3"; family: "sony"; accent: "#a987ff" }
        ListElement { name: "NINTENDO WII"; years: "2006–2017"; mark: "WII"; collectionName: "Nintendo Wii"; folder: "wii"; family: "nintendo"; accent: "#ff9f43" }
        ListElement { name: "NINTENDO 3DS"; years: "2011–2020"; mark: "3DS"; collectionName: "Nintendo 3DS"; folder: "n3ds"; family: "nintendo"; accent: "#ff9f43" }
        ListElement { name: "PLAYSTATION VITA"; years: "2011–2019"; mark: "VITA"; collectionName: "Sony PlayStation Vita"; folder: "psvita"; family: "sony"; accent: "#a987ff" }
        ListElement { name: "NINTENDO WII U"; years: "2012–2017"; mark: "WIIU"; collectionName: "Nintendo Wii U"; folder: "wiiu"; family: "nintendo"; accent: "#ff9f43" }
        ListElement { name: "WINDOWS"; years: "1985–PRESENT"; mark: "WIN"; collectionName: "Microsoft Windows"; folder: "windows"; family: "microsoft"; accent: "#4aa3ff" }
        ListElement { name: "NINTENDO SWITCH"; years: "2017–PRESENT"; mark: "NSW"; collectionName: "Nintendo Switch"; folder: "switch"; family: "nintendo"; accent: "#ff9f43" }
    }

    // Predecode official platform logotypes used by the rail. Full-resolution system
    // wallpapers are held by the persistent layers below.
    Repeater {
        model: systemModel.count
        Item {
            x: -2000
            y: -2000
            width: 1
            height: 1
            opacity: 0

            Image {
                source: systemModel.get(index).folder === "all" ?
                        Qt.resolvedUrl("assets/hardware-cutouts/all/0.png") :
                        Qt.resolvedUrl("assets/logos-png/" +
                                       systemModel.get(index).folder + ".png")
                // These are packaged local assets and the system model is
                // intentionally small. Decode once at startup so delegate
                // recycling can never produce a blank logo frame.
                asynchronous: false
                cache: true
                sourceSize.width: 700
                sourceSize.height: 300
            }
        }
    }

    // The header uses platform-family marks rather than console marks. Decode
    // those independently as well; preloading only logos-png left a visible
    // blank frame the first time Nintendo/Sega/Sony/Microsoft appeared.
    Repeater {
        model: root.availableBrandSlugs
        Image {
            x: -2000
            y: -2000
            width: 1
            height: 1
            opacity: 0
            source: modelData === "arcade" ?
                    Qt.resolvedUrl("assets/logos-png/arcade.png") :
                    Qt.resolvedUrl("assets/brands/" + modelData + ".png")
            asynchronous: false
            cache: true
            sourceSize.width: 760
            sourceSize.height: 224
        }
    }

    SortFilterProxyModel {
        id: recentModel
        sourceModel: api.allGames
        sorters: RoleSorter { roleName: "lastPlayed"; sortOrder: Qt.DescendingOrder }
        filters: [
            RangeFilter { roleName: "playCount"; minimumValue: 1 },
            ExpressionFilter {
                expression: root.isLucentLibraryGame(api.allGames.get(index)) &&
                            root.gameVisibleAfterMutation(api.allGames.get(index)) &&
                            root.gameVisibleInHomeCategory(api.allGames.get(index), 1)
            }
        ]
    }

    SortFilterProxyModel {
        id: mostPlayedModel
        sourceModel: api.allGames
        sorters: [
            RoleSorter { roleName: "playCount"; sortOrder: Qt.DescendingOrder },
            RoleSorter { roleName: "lastPlayed"; sortOrder: Qt.DescendingOrder }
        ]
        filters: [
            RangeFilter { roleName: "playCount"; minimumValue: 1 },
            ExpressionFilter {
                expression: root.isLucentLibraryGame(api.allGames.get(index)) &&
                            root.gameVisibleAfterMutation(api.allGames.get(index)) &&
                            root.gameVisibleInHomeCategory(api.allGames.get(index), 2)
            }
        ]
    }

    // Pegasus has no built-in "date added" role. Lucent writes an immutable
    // x-added-at timestamp when a ROM first enters its registry, then builds a
    // compact source-index rail here. Existing registry rows are backfilled
    // from the ROM mtime during the companion update.
    ListModel {
        id: recentlyAddedModel
    }

    // Filter the aggregate library only once, then keep four native sort
    // indexes over that shared base. This avoids four rounds of interpreted
    // visibility checks during startup while preserving instant sort swaps.
    SortFilterProxyModel {
        id: allLibraryFilterModel
        sourceModel: api.allGames
        filters: [
            ExpressionFilter {
                expression: root.isLucentLibraryGame(api.allGames.get(index)) &&
                            root.gameVisibleAfterMutation(api.allGames.get(index))
            }
        ]
    }

    SortFilterProxyModel {
        id: allCriticSortModel
        sourceModel: allLibraryFilterModel
        sorters: RoleSorter {
            roleName: "rating"
            sortOrder: Qt.DescendingOrder
        }
    }

    SortFilterProxyModel {
        id: allUserSortModel
        sourceModel: allLibraryFilterModel
        sorters: RoleSorter {
            roleName: "sortBy"
            sortOrder: Qt.AscendingOrder
        }
    }

    SortFilterProxyModel {
        id: allAlphaSortModel
        sourceModel: allLibraryFilterModel
        sorters: RoleSorter {
            roleName: "title"
            sortOrder: Qt.AscendingOrder
        }
    }

    SortFilterProxyModel {
        id: allReleaseSortModel
        sourceModel: allLibraryFilterModel
        sorters: RoleSorter {
            roleName: "release"
            sortOrder: Qt.DescendingOrder
        }
    }

    SortFilterProxyModel {
        id: systemGameSortModel
        // This proxy is only a startup fallback. Once the companion's native
        // per-system indexes are ready, leaving it attached made every L2/R2
        // move re-filter and re-sort the newly selected collection even
        // though the visible rails were already using activeSystemGames.
        // All Systems felt instant because it never triggered that hidden
        // rebuild. Detach here so every physical system swaps the same kind of
        // precomputed sorted index instead of doing duplicate work.
        sourceModel: !root.libraryIndexReady && root.searchQuery === "" &&
                     root.activeCollection ? root.activeCollection.games : null
        filters: [
            ExpressionFilter {
                expression: root.gameVisibleAfterMutation(
                    root.activeCollection ? root.activeCollection.games.get(index) : null)
            }
        ]
        sorters: RoleSorter {
            roleName: root.sortMode === "critic" ? "rating" :
                      root.sortMode === "user" ? "sortBy" :
                      root.sortMode === "release" ? "release" : "title"
            sortOrder: root.sortMode === "critic" || root.sortMode === "release" ?
                       Qt.DescendingOrder : Qt.AscendingOrder
        }
    }

    // Search is the only genuinely dynamic filter. Keep these proxies detached
    // during normal browsing so typing does not invalidate all warm caches.
    SortFilterProxyModel {
        id: allGamesSearchSortModel
        sourceModel: root.searchQuery !== "" ? api.allGames : null
        filters: [
            RegExpFilter {
                roleName: "title"
                pattern: root.escapedSearchPattern(root.searchQuery)
                caseSensitivity: Qt.CaseInsensitive
            },
            ExpressionFilter {
                expression: root.isLucentLibraryGame(api.allGames.get(index))
            },
            ExpressionFilter {
                expression: root.gameVisibleAfterMutation(api.allGames.get(index))
            }
        ]
        sorters: RoleSorter {
            roleName: root.sortMode === "critic" ? "rating" :
                      root.sortMode === "user" ? "sortBy" :
                      root.sortMode === "release" ? "release" : "title"
            sortOrder: root.sortMode === "critic" || root.sortMode === "release" ?
                       Qt.DescendingOrder : Qt.AscendingOrder
        }
    }

    SortFilterProxyModel {
        id: systemGameSearchSortModel
        sourceModel: root.searchQuery !== "" && root.activeCollection ?
                     root.activeCollection.games : null
        filters: [
            RegExpFilter {
                roleName: "title"
                pattern: root.escapedSearchPattern(root.searchQuery)
                caseSensitivity: Qt.CaseInsensitive
            },
            ExpressionFilter {
                expression: root.gameVisibleAfterMutation(
                    root.activeCollection ? root.activeCollection.games.get(index) : null)
            }
        ]
        sorters: RoleSorter {
            roleName: root.sortMode === "critic" ? "rating" :
                      root.sortMode === "user" ? "sortBy" :
                      root.sortMode === "release" ? "release" : "title"
            sortOrder: root.sortMode === "critic" || root.sortMode === "release" ?
                       Qt.DescendingOrder : Qt.AscendingOrder
        }
    }

    Component {
        id: homeShelfCard

        Item {
            id: shelfCard
            property var game: root.homeShelfGameAt(ListView.view.zone, index)
            property bool isSelected: ListView.isCurrentItem &&
                    root.homeZone === ListView.view.zone
            property var packageSize: root.packageDimensionsForGame(game)
            property real packageScale: root.coverShelfPixelsPerMillimetre()
            property real coverAreaHeight: Math.max(108, height -
                    root.coverShelfCaptionHeight)
            property real desiredCoverWidth: packageSize.width * packageScale
            property real desiredCoverHeight: packageSize.height * packageScale
            property real maximumCoverWidth: root.coverViewRowCount === 1 ? 520 :
                    (root.coverViewRowCount === 2 ? 310 : 220)
            property real packageFit: Math.min(1,
                    coverAreaHeight / Math.max(1, desiredCoverHeight),
                    maximumCoverWidth / Math.max(1, desiredCoverWidth))
            property real coverWidth: desiredCoverWidth * packageFit
            property real coverHeight: desiredCoverHeight * packageFit
            width: Math.max(root.coverViewRowCount === 1 ? 180 :
                    (root.coverViewRowCount === 2 ? 150 : 130), coverWidth + 22)
            height: Math.max(184, root.coverRowSlotHeight -
                    root.coverShelfLabelHeight - 8)
            // Selection is communicated by the accent frame, not by changing
            // package scale. That keeps every adjacent case in the same real-
            // world proportion even while focus moves across the shelf.
            scale: 1.0
            opacity: isSelected ? 1.0 : 0.84
            Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
            Behavior on opacity { NumberAnimation { duration: 150 } }

            Rectangle {
                x: shelfCover.x - 7
                y: shelfCover.y - 7
                width: shelfCover.width + 14
                height: shelfCover.height + 14
                radius: 7
                color: shelfCard.isSelected ?
                       Qt.darker(root.accentForGame(game), 4.5) : "transparent"
                border.width: shelfCard.isSelected ? 5 : 0
                border.color: root.accentForGame(game)
            }

            Image {
                id: shelfCover
                x: (parent.width - parent.coverWidth) / 2
                y: 2 + (parent.coverAreaHeight - parent.coverHeight) / 2
                width: parent.coverWidth
                height: parent.coverHeight
                source: game ? (game.assets.boxFront || "") : ""
                fillMode: Image.PreserveAspectFit
                asynchronous: true
                cache: true
                smooth: true
                mipmap: true
            }

            Text {
                id: shelfTitle
                x: 8
                y: parent.coverAreaHeight +
                   (root.coverViewRowCount === 1 ? 10 :
                    (root.coverViewRowCount === 2 ? 8 : 6))
                width: parent.width - 16
                height: root.coverViewRowCount === 1 ? 56 :
                        (root.coverViewRowCount === 2 ? 44 : 34)
                text: root.displayTitle(game)
                color: "#eef1f7"
                elide: Text.ElideRight
                wrapMode: Text.Wrap
                maximumLineCount: 2
                // Shrink-to-fit rather than truncate. A long name scrolled
                // past at speed is the case that used to lose its tail, and
                // an unreadably small name is a worse answer than a slightly
                // smaller one, so the floor is generous.
                fontSizeMode: Text.Fit
                minimumPixelSize: root.coverViewRowCount === 1 ? 17 :
                                  (root.coverViewRowCount === 2 ? 14 : 11)
                font.family: global.fonts.sans
                font.pixelSize: root.coverViewRowCount === 1 ? 26 :
                                (root.coverViewRowCount === 2 ? 21 : 16)
                font.weight: Font.Bold
                style: Text.Outline
                styleColor: "#d0000000"
            }

            Text {
                x: 8
                // Follow the title instead of hugging the bottom of the card.
                // This keeps ratings visually paired with the game name in
                // every Cover View shelf and at every configured row count.
                y: shelfTitle.y +
                   Math.min(shelfTitle.height, shelfTitle.paintedHeight) +
                   (root.coverViewRowCount === 3 ? 2 : 4)
                width: parent.width - 16
                height: root.coverViewRowCount === 1 ? 34 :
                        (root.coverViewRowCount === 2 ? 28 : 24)
                text: root.scoreText(game)
                color: root.accentForGame(game)
                wrapMode: Text.NoWrap
                maximumLineCount: 1
                fontSizeMode: Text.HorizontalFit
                minimumPixelSize: 11
                font.family: global.fonts.sans
                font.pixelSize: root.coverViewRowCount === 1 ? 18 :
                                (root.coverViewRowCount === 2 ? 15 : 12)
                font.weight: Font.Bold
                font.letterSpacing: 0
                style: Text.Outline
                styleColor: "#d0000000"
            }

            MouseArea {
                anchors.fill: parent
                pressAndHoldInterval: 800
                onPressAndHold: {
                    ListView.view.currentIndex = index
                    root.focusHomeZone(ListView.view.zone)
                    root.openGameActions(game, index)
                }
                onClicked: {
                    if (root.gameActionOpen) return
                    ListView.view.currentIndex = index
                    root.focusHomeZone(ListView.view.zone)
                    root.launch(game)
                }
            }
        }
    }

    Rectangle {
        anchors.fill: parent
        color: "#07090d"
    }

    // The home backdrop is code-native: no generated image can leak back in.
    // Real product photography sits above this restrained accent field.
    Rectangle {
        anchors.fill: parent
        visible: root.showSystemBackdrop
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#07090d" }
            GradientStop { position: 0.58; color: "#0a0e15" }
            GradientStop { position: 1.0; color: Qt.darker(root.accent, 4.2) }
        }
    }

    LinearGradient {
        anchors.fill: parent
        visible: root.showSystemBackdrop
        start: Qt.point(0, height * 0.50)
        end: Qt.point(width, height * 0.50)
        gradient: Gradient {
            GradientStop { position: 0.0; color: "transparent" }
            GradientStop {
                position: 0.38
                color: Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.04)
            }
            GradientStop {
                position: 0.70
                color: Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.15)
            }
            GradientStop {
                position: 1.0
                color: Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.28)
            }
        }
    }

    // Each system owns a persistent, decoded layer. Its real product photo is
    // rerolled only after that system becomes invisible, so returning to it is
    // instantaneous and never reveals the previous image first. The accent
    // field deliberately reaches far beyond the product instead of collapsing
    // into a tight halo on an otherwise black wallpaper.
    Repeater {
        model: systemModel.count
        Item {
            x: 0
            y: 0
            width: 1920
            height: 1080
            opacity: root.showSystemBackdrop &&
                     systemRail.currentIndex === index ? 1.0 : 0

            RadialGradient {
                x: 360
                y: -340
                width: 1920
                height: 1480
                horizontalRadius: width * 0.50
                verticalRadius: height * 0.50
                gradient: Gradient {
                    GradientStop {
                        position: 0.0
                        color: Qt.rgba(systemModel.get(index).accent.r,
                                       systemModel.get(index).accent.g,
                                       systemModel.get(index).accent.b, 0.58)
                    }
                    GradientStop {
                        position: 0.28
                        color: Qt.rgba(systemModel.get(index).accent.r,
                                       systemModel.get(index).accent.g,
                                       systemModel.get(index).accent.b, 0.39)
                    }
                    GradientStop {
                        position: 0.58
                        color: Qt.rgba(systemModel.get(index).accent.r,
                                       systemModel.get(index).accent.g,
                                       systemModel.get(index).accent.b, 0.22)
                    }
                    GradientStop {
                        position: 0.82
                        color: Qt.rgba(systemModel.get(index).accent.r,
                                       systemModel.get(index).accent.g,
                                       systemModel.get(index).accent.b, 0.11)
                    }
                    GradientStop { position: 1.0; color: "transparent" }
                }
            }

            Image {
                id: systemHardwareImage
                x: 1010
                y: 88
                width: 850
                height: 350
                source: root.hardwarePhotoBySystem[index] || ""
                fillMode: Image.PreserveAspectFit
                asynchronous: true
                cache: true
                sourceSize.width: 838
                sourceSize.height: 338
            }
        }
    }

    // Two-buffer artwork swap. The old game remains visible until the new
    // image reports Ready; the two invisible loaders keep both D-pad
    // destinations decoded in advance. This also covers sort changes.
    Item {
        anchors.fill: parent
        visible: !root.showSystemBackdrop

        Image {
            id: upperArtworkA
            anchors.fill: parent
            fillMode: Image.PreserveAspectCrop
            // Neighbor art is decoded by the preloaders below. Make the
            // cache-hit promotion synchronous so title, row, and wallpaper
            // all change in the same selection event.
            asynchronous: false
            cache: true
            sourceSize.width: 1920
            sourceSize.height: 1080
            opacity: root.upperArtworkSlot === 0 ? 1.0 : 0.0
            onStatusChanged: if (status === Image.Ready) root.promoteUpperArtwork(0)
        }

        Image {
            id: upperArtworkB
            anchors.fill: parent
            fillMode: Image.PreserveAspectCrop
            asynchronous: false
            cache: true
            sourceSize.width: 1920
            sourceSize.height: 1080
            opacity: root.upperArtworkSlot === 1 ? 1.0 : 0.0
            onStatusChanged: if (status === Image.Ready) root.promoteUpperArtwork(1)
        }

        Image {
            id: upperArtworkPreloadPrevious
            x: -4
            y: -4
            width: 2
            height: 2
            asynchronous: true
            cache: true
            sourceSize.width: 1920
            sourceSize.height: 1080
            opacity: 0
        }

        Image {
            id: upperArtworkPreloadNext
            x: -4
            y: -4
            width: 2
            height: 2
            asynchronous: true
            cache: true
            sourceSize.width: 1920
            sourceSize.height: 1080
            opacity: 0
        }

        Image {
            id: upperArtworkPreloadEntry
            x: -4
            y: -4
            width: 2
            height: 2
            asynchronous: true
            cache: true
            sourceSize.width: 1920
            sourceSize.height: 1080
            opacity: 0
        }
    }

    Item {
        anchors.fill: parent
        visible: !root.showSystemBackdrop &&
                 (!root.activeGame || !root.artwork(root.activeGame))

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            y: 130
            text: systemModel.get(root.displaySystemIndex).mark
            color: root.accent
            opacity: 0.13
            font.family: global.fonts.condensed
            font.pixelSize: 430
            font.weight: Font.Bold
        }

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            y: 650
            width: 1380
            text: root.activeGame ? root.displayTitle(root.activeGame) : systemModel.get(root.displaySystemIndex).name
            color: "#dce2ee"
            opacity: 0.22
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
            maximumLineCount: 2
            font.family: global.fonts.condensed
            font.pixelSize: 74
            font.weight: Font.DemiBold
        }
    }

    // Preserve the changing light and texture in the upper half of each
    // wallpaper while fully burying its original low-positioned hardware
    // beneath the navigation and card contrast field.
    Rectangle {
        x: 0
        y: 286
        width: parent.width
        height: parent.height - y
        visible: root.showSystemBackdrop
        gradient: Gradient {
            // Ramps to its darkest well ABOVE the footer line and then eases
            // back off, so the very bottom of the screen is wallpaper again.
            // Running this to full opacity at position 1.0 put a hard black
            // slab across the bottom of every system view -- which reads as a
            // background bar behind the button legend no matter that no plate
            // is drawn there. The top of the screen has no such slab behind
            // the clock and battery, and the two edges have to match.
            GradientStop { position: 0.0; color: "#1207090d" }
            GradientStop { position: 0.18; color: "#9807090d" }
            GradientStop { position: 0.52; color: "#b407090d" }
            GradientStop { position: 0.82; color: "#5807090d" }
            GradientStop { position: 1.0; color: "#0c07090d" }
        }
    }

    QtObject {
        id: previewA
        property string previewMode: ""
        property int systemIndex: -1
        property int gameIndex: -1
        property var previewGame: null
    }

    QtObject {
        id: previewB
        property string previewMode: ""
        property int systemIndex: -1
        property int gameIndex: -1
        property var previewGame: null
    }

    QtObject {
        id: previewC
        property string previewMode: ""
        property int systemIndex: -1
        property int gameIndex: -1
        property var previewGame: null
    }

    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            // Symmetric, and monotonic on each half. What reads as "a
            // background behind the legend" is an EDGE, not darkness: the old
            // curve peaked at 0.72 and then released to nearly nothing by the
            // bottom, which drew a visible seam across the artwork and left the
            // legend stranded on bare wallpaper at 1.08:1 contrast. The top of
            // the screen carries its clock and battery over a 60% wash that
            // nobody reads as a bar, because it fades over 350 px with no edge
            // anywhere. The bottom now gets exactly the same treatment, mirrored
            // -- same depth, same ramp length, same absence of an edge.
            GradientStop { position: 0.0; color: "#99070a10" }
            GradientStop { position: 0.34; color: "#30070a10" }
            GradientStop { position: 0.66; color: "#30070a10" }
            GradientStop { position: 1.0; color: "#99070a10" }
        }
    }

    Rectangle {
        anchors.fill: parent
        color: "#28000000"
    }

    // A quiet technical grid gives empty systems a deliberate visual state.
    Repeater {
        model: 12
        Rectangle {
            x: index * root.width / 11
            width: 1
            height: root.height
            color: "#12ffffff"
        }
    }
    Repeater {
        model: 7
        Rectangle {
            y: index * root.height / 6
            width: root.width
            height: 1
            color: "#0dffffff"
        }
    }

    // Fallback for conventional one-display Android handhelds. On the Thor
    // this entire PIP and its decoders remain disabled; the native player owns
    // the physical lower screen instead.
    Item {
        id: singleScreenPip
        z: 80
        // Single-screen list mode reserves the upper-right quadrant for the
        // preview. The list gives up two rows (nine -> seven), so the movie can
        // be substantially larger without covering a title, score, sort
        // control, or game row. Dual-screen Thor geometry is untouched because
        // this item is disabled there.
        property bool compactHomeList: root.page === "home" && root.homeViewMode === "list"
        property bool compactGameList: root.page === "games" && root.gameViewMode === "list"
        property bool swapHomeList: compactHomeList && !root.dualScreenDevice &&
                                    root.singleScreenMediaSwapped
        property bool swapGameList: compactGameList && !root.dualScreenDevice &&
                                    root.singleScreenMediaSwapped
        x: swapHomeList ? parent.width - width - 56 :
           (swapGameList ? listViewPanel.x :
            (compactHomeList ? parent.width - width - 226 : parent.width - width - 56))
        y: swapGameList ? listViewPanel.y - 76 + (600 - height) / 2 :
           (compactHomeList ? 112 : 102)
        width: compactHomeList ? 330 :
               (compactGameList ? (swapGameList ? 600 : 624) : 392)
        height: Math.round(width * 9 / 16)
        visible: root.previewPlacementMode !== "off" &&
                 !root.useBottomPreview() && root.singleCurrentSlot >= 0 &&
                 !root.gameplayActive
        clip: true

        Rectangle {
            anchors.fill: parent
            color: "#e8070a0f"
            border.width: 2
            border.color: root.accent
            radius: 8
        }

        Image {
            anchors.fill: parent
            anchors.margins: 3
            source: root.artwork(root.activeGame)
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
            cache: true
        }

        Video {
            id: singleVideoA
            anchors.fill: parent
            anchors.margins: 3
            // Cleared while a game runs. An unset source stops the decoder
            // outright; hiding the PIP does not, and a looping preview keeps
            // calling update() on this item whether or not anything can see
            // it -- which is a full Qt Quick render pass, at video rate, for
            // as long as the emulator is on screen. autoPlay restarts it from
            // the restored source when the library comes back.
            source: root.gameplayActive ? "" : root.singleSourceA
            fillMode: VideoOutput.PreserveAspectCrop
            muted: !root.previewSoundEnabled || root.singleCurrentSlot !== 0
            loops: root.randomHomePreviewActive() ? 1 : MediaPlayer.Infinite
            autoPlay: source !== ""
            opacity: root.singleCurrentSlot === 0 ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 85 } }
            onPositionChanged: if (position > 0) root.promoteSingleVideo(0)
            onStopped: if (root.singleCurrentSlot === 0 && root.randomHomePreviewActive())
                           Qt.callLater(function() { root.advanceRandomHomePreview() })
        }

        Video {
            id: singleVideoB
            anchors.fill: parent
            anchors.margins: 3
            source: root.gameplayActive ? "" : root.singleSourceB
            fillMode: VideoOutput.PreserveAspectCrop
            muted: !root.previewSoundEnabled || root.singleCurrentSlot !== 1
            loops: root.randomHomePreviewActive() ? 1 : MediaPlayer.Infinite
            autoPlay: source !== ""
            opacity: root.singleCurrentSlot === 1 ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 85 } }
            onPositionChanged: if (position > 0) root.promoteSingleVideo(1)
            onStopped: if (root.singleCurrentSlot === 1 && root.randomHomePreviewActive())
                           Qt.callLater(function() { root.advanceRandomHomePreview() })
        }

        Video {
            id: singleVideoC
            anchors.fill: parent
            anchors.margins: 3
            source: root.gameplayActive ? "" : root.singleSourceC
            fillMode: VideoOutput.PreserveAspectCrop
            muted: !root.previewSoundEnabled || root.singleCurrentSlot !== 2
            loops: root.randomHomePreviewActive() ? 1 : MediaPlayer.Infinite
            autoPlay: source !== ""
            opacity: root.singleCurrentSlot === 2 ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 85 } }
            onPositionChanged: if (position > 0) root.promoteSingleVideo(2)
            onStopped: if (root.singleCurrentSlot === 2 && root.randomHomePreviewActive())
                           Qt.callLater(function() { root.advanceRandomHomePreview() })
        }
    }

    Rectangle {
        id: screensaverLayer
        z: 2000
        anchors.fill: parent
        visible: root.screensaverActive && !root.gameplayActive
        color: "black"

        Video {
            id: screensaverVideoA
            anchors.fill: parent
            source: root.gameplayActive ? "" : root.screensaverSourceA
            // The Thor upper panel is 16:9. A 16:9 preview therefore displays
            // its complete wide frame here, while PreviewActivity independently
            // crops that same source to fill the differently shaped lower panel.
            fillMode: VideoOutput.PreserveAspectCrop
            muted: true
            loops: 1
            autoPlay: source !== ""
            opacity: root.screensaverCurrentSlot === 0 ? 1 : 0
            Behavior on opacity {
                NumberAnimation { duration: root.screensaverCrossfadeMs }
            }
            onPositionChanged: if (position > 0) root.promoteScreensaverSlot(0)
            onStopped: if (root.screensaverActive &&
                               root.screensaverCurrentSlot === 0)
                           Qt.callLater(function() { root.advanceScreensaverVideo() })
        }

        Video {
            id: screensaverVideoB
            anchors.fill: parent
            source: root.gameplayActive ? "" : root.screensaverSourceB
            fillMode: VideoOutput.PreserveAspectCrop
            muted: true
            loops: 1
            autoPlay: source !== ""
            opacity: root.screensaverCurrentSlot === 1 ? 1 : 0
            Behavior on opacity {
                NumberAnimation { duration: root.screensaverCrossfadeMs }
            }
            onPositionChanged: if (position > 0) root.promoteScreensaverSlot(1)
            onStopped: if (root.screensaverActive &&
                               root.screensaverCurrentSlot === 1)
                           Qt.callLater(function() { root.advanceScreensaverVideo() })
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 184
            color: "#98000000"
        }

        Text {
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.leftMargin: 54
            anchors.topMargin: 42
            visible: root.screensaverGame !== null
            text: root.screensaverSystemName(root.screensaverGame).toUpperCase()
            color: "white"
            font.pixelSize: 26
            font.bold: true
            font.letterSpacing: 3
            style: Text.Outline
            styleColor: "#b0000000"
        }

        Column {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.leftMargin: 54
            anchors.rightMargin: 54
            anchors.bottomMargin: 38
            spacing: 10
            visible: root.screensaverGame !== null

            Text {
                width: parent.width
                text: root.displayTitle(root.screensaverGame)
                color: "white"
                font.pixelSize: 42
                font.bold: true
                elide: Text.ElideRight
                style: Text.Outline
                styleColor: "#b0000000"
            }

            Text {
                width: parent.width
                text: root.scoreText(root.screensaverGame)
                color: "#f2f5f8"
                font.pixelSize: 23
                font.bold: true
                font.letterSpacing: 1.4
                elide: Text.ElideRight
                style: Text.Outline
                styleColor: "#b0000000"
            }
        }

        MouseArea {
            anchors.fill: parent
            onClicked: root.stopScreensaver()
        }
    }

    Item {
        id: chrome
        anchors.fill: parent

        Item {
            id: topBar
            x: 56
            y: 34
            width: parent.width - 112
            height: 58

            Item {
                x: 0
                anchors.verticalCenter: parent.verticalCenter
                width: 230
                height: 64
                property bool leftAnchoredMark:
                        root.brandSlugForSystem(root.displaySystemIndex) === "microsoft"
                visible: !root.showAvailableBrandRow &&
                         root.brandSlugForSystem(root.displaySystemIndex) !== "" &&
                         root.displaySystemIndex > 0

                Image {
                    id: activeBrandLogo
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    width: parent.leftAnchoredMark ? 64 : parent.width
                    height: parent.height
                    source: root.brandLogoForSystem(root.displaySystemIndex)
                    fillMode: Image.PreserveAspectFit
                    horizontalAlignment: Image.AlignLeft
                    asynchronous: false
                    cache: true
                    sourceSize.width: 760
                    sourceSize.height: 224
                }

                ColorOverlay {
                    anchors.fill: activeBrandLogo
                    source: activeBrandLogo
                    color: "white"
                    visible: root.useWhiteBrandLogo(root.displaySystemIndex)
                    cached: true
                }

                // Console marks are used nominatively to identify which system
                // a game belongs to. This states plainly that the trademark
                // holders neither endorse nor are connected with EmuFusion.
                //
                // Positioned from the logo's PAINTED box, not from the Item:
                // every mark keeps its own aspect inside a fixed 230x64 slot,
                // so the drawn artwork is a different width and height for each
                // one. Anchoring to the Item would centre this under empty
                // space and sit a different distance below Nintendo than below
                // Sega. paintedWidth/paintedHeight track the artwork itself, so
                // the line stays centred on the mark and always the same gap
                // beneath it.
                Text {
                    id: brandDisclaimer
                    x: activeBrandLogo.x +
                       (activeBrandLogo.paintedWidth - width) / 2
                    y: activeBrandLogo.y +
                       (activeBrandLogo.height + activeBrandLogo.paintedHeight) / 2 + 7
                    text: "No affiliation or endorsement."
                    color: "#9099a3"
                    opacity: 0.5
                    font.family: global.fonts.sans
                    font.pixelSize: 10
                    font.letterSpacing: 0.15
                }
            }

            // Same disclaimer for the all-systems row. One line under the row
            // rather than under each mark: repeating it beneath every small
            // logo would crowd the header without saying anything more.
            Text {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                anchors.verticalCenterOffset: 36
                text: "No affiliation or endorsement."
                color: "#9099a3"
                opacity: 0.5
                font.family: global.fonts.sans
                font.pixelSize: 10
                font.letterSpacing: 0.15
                visible: root.showAvailableBrandRow
            }

            Row {
                x: 0
                anchors.verticalCenter: parent.verticalCenter
                height: 58
                spacing: 22
                visible: root.showAvailableBrandRow

                Repeater {
                    model: root.availableBrandSlugs

                    Item {
                        width: modelData === "arcade" ? 122 :
                               (modelData === "sony" ? 130 :
                               (modelData === "microsoft" ? 58 : 160))
                        height: 58

                        Image {
                            anchors.fill: parent
                            anchors.margins: 0
                            source: modelData === "arcade" ?
                                    Qt.resolvedUrl("assets/logos-png/arcade.png") :
                                    Qt.resolvedUrl("assets/brands/" + modelData + ".png")
                            fillMode: Image.PreserveAspectFit
                            horizontalAlignment: Image.AlignLeft
                            asynchronous: false
                            cache: true
                            smooth: true
                            mipmap: true
                        }
                    }
                }
            }

            Rectangle {
                id: searchControl
                anchors.right: clockStatus.left
                anchors.rightMargin: 22
                anchors.verticalCenter: parent.verticalCenter
                width: root.searchOpen ? 520 : 46
                height: 46
                color: root.searchOpen ? "#e00a0e16" : "transparent"
                border.width: root.searchOpen ? 1 : 0
                border.color: root.searchOpen ? root.accent : "#42ffffff"
                radius: 23
                clip: true

                Behavior on width {
                    NumberAnimation { duration: 180; easing.type: Easing.OutCubic }
                }

                TextInput {
                    id: searchField
                    x: 20
                    anchors.verticalCenter: parent.verticalCenter
                    width: parent.width - (searchClear.visible ? 142 : 76)
                    visible: root.searchOpen
                    text: ""
                    color: "white"
                    selectionColor: root.accent
                    selectedTextColor: "#05070b"
                    font.family: global.fonts.sans
                    font.pixelSize: 21
                    clip: true
                    selectByMouse: true
                    inputMethodHints: Qt.ImhNoPredictiveText
                    function syncSearchQuery() {
                        var completeValue = String(text) + String(preeditText || "")
                        if (root.searchQuery === completeValue)
                            return
                        root.searchQuery = completeValue
                        searchChangeCommit.restart()
                    }
                    onTextChanged: syncSearchQuery()
                    onPreeditTextChanged: syncSearchQuery()
                    onAccepted: {
                        // Keep the editor focused until this Enter event has fully
                        // unwound. Otherwise Android can deliver the same event to
                        // the game list as A/Play after the keyboard disappears.
                        root.searchKeyboardAccepting = true
                        Qt.inputMethod.hide()
                        Qt.callLater(function() {
                            searchField.focus = false
                            root.forceActiveFocus()
                            root.searchKeyboardAccepting = false
                        })
                    }
                }

                Text {
                    x: 20
                    anchors.verticalCenter: parent.verticalCenter
                    visible: root.searchOpen && searchField.text.length === 0 &&
                             searchField.preeditText.length === 0
                    text: "SEARCH GAMES"
                    color: "#7f899b"
                    font.family: global.fonts.sans
                    font.pixelSize: 18
                    font.letterSpacing: 1.2
                }

                Item {
                    id: searchClear
                    anchors.right: searchMagnifier.left
                    anchors.rightMargin: 0
                    anchors.verticalCenter: parent.verticalCenter
                    // Keep the restrained 17px glyph, but give it a generous
                    // 58x46 touch target so it is easy to hit on a handheld.
                    width: 58
                    height: 46
                    visible: root.searchOpen && root.searchQuery !== ""

                    Rectangle {
                        anchors.centerIn: parent
                        width: 17
                        height: 2
                        radius: 1
                        rotation: 45
                        color: "#cbd2df"
                    }

                    Rectangle {
                        anchors.centerIn: parent
                        width: 17
                        height: 2
                        radius: 1
                        rotation: -45
                        color: "#cbd2df"
                    }

                    MouseArea {
                        x: -4
                        y: -2
                        width: parent.width + 8
                        height: parent.height + 4
                        onClicked: root.endSearch()
                    }
                }

                Item {
                    id: searchMagnifier
                    anchors.right: parent.right
                    anchors.rightMargin: 8
                    anchors.verticalCenter: parent.verticalCenter
                    width: 38
                    height: 38

                    Image {
                        anchors.centerIn: parent
                        width: 30
                        height: 30
                        source: Qt.resolvedUrl("assets/search-white.png")
                        fillMode: Image.PreserveAspectFit
                        smooth: true
                        mipmap: true
                        cache: true
                    }

                    MouseArea {
                        anchors.fill: parent
                        onClicked: {
                            if (!root.searchOpen)
                                root.beginSearch()
                            else {
                                searchField.forceActiveFocus()
                                Qt.inputMethod.show()
                            }
                        }
                    }
                }
            }

            Item {
                id: lucentSettingsButton
                anchors.right: searchControl.left
                // Keep the two icons visually and physically distinct. The old
                // expanded gear hit target nearly touched the search target.
                anchors.rightMargin: 30
                anchors.verticalCenter: parent.verticalCenter
                width: 38
                height: 38

                Image {
                    anchors.centerIn: parent
                    width: 30
                    height: 30
                    source: Qt.resolvedUrl("assets/settings-gear.svg")
                    fillMode: Image.PreserveAspectFit
                    smooth: true
                    mipmap: true
                    opacity: root.settingsOpen ? 0.68 : 1.0
                }

                MouseArea {
                    anchors.fill: parent
                    onClicked: {
                        root.endSearch()
                        root.settingsOpen = true
                        root.settingsIndex = 0
                        root.forceActiveFocus()
                    }
                }
            }

            Item {
                id: lucentBrowserButton
                anchors.right: lucentSettingsButton.left
                anchors.rightMargin: 24
                anchors.verticalCenter: parent.verticalCenter
                width: 42
                height: 42

                Image {
                    anchors.centerIn: parent
                    width: 31
                    height: 31
                    source: Qt.resolvedUrl("assets/globe-white.svg")
                    fillMode: Image.PreserveAspectFit
                    smooth: true
                    mipmap: true
                    opacity: 0.96
                }

                MouseArea {
                    anchors.fill: parent
                    onClicked: root.openLucentBrowser()
                }
            }

            Item {
                id: lucentRescanButton
                anchors.right: lucentBrowserButton.left
                anchors.rightMargin: 24
                anchors.verticalCenter: parent.verticalCenter
                width: 42
                height: 42

                Image {
                    id: lucentRescanIcon
                    anchors.centerIn: parent
                    width: 31
                    height: 31
                    source: Qt.resolvedUrl("assets/rescan-white.svg")
                    fillMode: Image.PreserveAspectFit
                    smooth: true
                    mipmap: true
                    opacity: root.importState !== "idle" &&
                             root.importState !== "complete" &&
                             root.importState !== "error" ? 0.62 : 0.96

                    RotationAnimation on rotation {
                        // Import polling pauses during gameplay, so its last
                        // busy status can remain stale. Do not keep rendering
                        // this hidden spinner underneath the emulator.
                        running: !root.gameplayActive && root.importState !== "idle" &&
                                 root.importState !== "complete" &&
                                 root.importState !== "error"
                        from: 0
                        to: 360
                        loops: Animation.Infinite
                        duration: 900
                    }
                }

                MouseArea {
                    anchors.fill: parent
                    onClicked: root.startMaintenanceRescan()
                }
            }

            Item {
                id: voiceFeedbackButton
                anchors.right: lucentRescanButton.left
                anchors.rightMargin: 24
                anchors.verticalCenter: parent.verticalCenter
                width: 42
                height: 42

                Image {
                    anchors.centerIn: parent
                    width: 31
                    height: 31
                    source: Qt.resolvedUrl("assets/raised-hand-white.svg")
                    fillMode: Image.PreserveAspectFit
                    smooth: true
                    mipmap: true
                    opacity: root.voiceFeedbackOpen ? 0.66 : 0.96
                }

                MouseArea {
                    anchors.fill: parent
                    onClicked: root.startVoiceFeedback()
                }
            }

            Connections {
                target: Qt.inputMethod
                onVisibleChanged: {
                    // Closing Gboard by its chevron must hand the D-pad back
                    // to Pegasus even though Android keeps the edit session.
                    if (!root.searchKeyboardAccepting &&
                            !Qt.inputMethod.visible && root.searchOpen &&
                            searchField.activeFocus) {
                        searchField.focus = false
                        root.forceActiveFocus()
                    }
                }
            }

            Text {
                id: clockStatus
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                text: root.clockText + "     " + (isNaN(api.device.batteryPercent) ? "" : Math.round(api.device.batteryPercent * 100) + "%")
                color: "#aeb6c8"
                font.family: global.fonts.sans
                font.pixelSize: 20
                font.letterSpacing: 1
            }
        }

        Item {
            id: homePage
            anchors.fill: parent
            opacity: root.page === "home" ? 1 : 0
            scale: root.page === "home" ? 1 : 0.985
            visible: opacity > 0
            Behavior on opacity {
                NumberAnimation { duration: root.viewTransitionsEnabled ? 240 : 0;
                                  easing.type: Easing.OutCubic }
            }
            Behavior on scale {
                NumberAnimation { duration: root.viewTransitionsEnabled ? 260 : 0;
                                  easing.type: Easing.OutCubic }
            }
            transform: Translate {
                x: root.page === "home" ? 0 : -72
                Behavior on x {
                    NumberAnimation { duration: root.viewTransitionsEnabled ? 260 : 0;
                                      easing.type: Easing.OutCubic }
                }
            }

            Text {
                x: 58
                y: 150
                width: !root.dualScreenDevice && root.homeViewMode === "covers" ?
                       singleScreenPip.x - x - 28 : parent.width - 116
                visible: root.homeZone === 0
                text: systemModel.get(systemRail.currentIndex).name
                color: "white"
                font.family: global.fonts.condensed
                font.pixelSize: 66
                minimumPixelSize: 38
                fontSizeMode: Text.HorizontalFit
                font.weight: Font.Bold
                font.letterSpacing: 1
            }

            Text {
                x: 62
                y: 225
                visible: root.homeZone === 0
                text: systemRail.currentIndex === 0 ?
                      root.romGameCount() + " TITLES ACROSS EVERY SYSTEM" :
                      (root.selectedCollection ? root.selectedCollection.games.count + " TITLES" : "READY FOR YOUR LIBRARY")
                color: root.accent
                font.family: global.fonts.sans
                font.pixelSize: 18
                font.weight: Font.DemiBold
                font.letterSpacing: 3
            }

            Text {
                x: 62
                y: 267
                width: 780
                visible: root.homeZone === 0
                text: systemRail.currentIndex === 0 ?
                      "ONE LIBRARY  •  EVERY GAME  •  SCORES, RELEASES, AND DIRECT LAUNCH" :
                      (root.selectedCollection ? "SELECT TO BROWSE  •  GAMES LAUNCH DIRECTLY" :
                       "ADD GAMES TO  /GAMES/" + systemModel.get(systemRail.currentIndex).folder)
                color: "#aeb6c8"
                font.family: global.fonts.sans
                font.pixelSize: 18
                font.letterSpacing: 1
            }

            Text {
                x: 58
                y: 148
                width: root.homeViewMode === "list" ?
                       ((!root.dualScreenDevice ?
                         Math.min(singleScreenPip.x, homeListBoxArt.x) :
                         homeListBoxArt.x) - x - 28) :
                       ((!root.dualScreenDevice ? singleScreenPip.x : parent.width - 58) - x - 28)
                visible: root.homeZone > 0
                text: root.homeListBrowsingSystems ?
                      systemModel.get(systemRail.currentIndex).name :
                      (root.activeGame ? root.displayTitle(root.activeGame) : "CONTINUE PLAYING")
                color: "white"
                font.family: global.fonts.condensed
                font.pixelSize: 60
                minimumPixelSize: 36
                fontSizeMode: Text.HorizontalFit
                font.weight: Font.Bold
                maximumLineCount: 1
            }

            Text {
                x: 62
                y: 224
                visible: root.homeZone > 0
                text: root.homeListBrowsingSystems ?
                      root.homeSystemStatsText() : root.gameFactsText(root.activeGame)
                color: root.accent
                font.family: global.fonts.sans
                font.pixelSize: 22
                font.weight: Font.Bold
                font.letterSpacing: 1.1
            }

            Text {
                x: 62
                y: 262
                visible: root.homeZone > 0
                text: root.homeViewMode === "list" ?
                      root.homeSystemInstructionText() :
                      root.homeShelfName(root.homeZone) + "     A  PLAY"
                color: "#aeb6c8"
                font.family: global.fonts.sans
                font.pixelSize: 17
                font.letterSpacing: 2
            }

            // Which shelf lies above and below the focused one. This used to
            // float on its own line inside the shelf band, where tall cards
            // reached over it; it now shares the footer line with the view
            // name and the button legend, which costs the shelves nothing.
            Text {
                id: coverNavigationHint
                z: 90
                x: 240
                y: root.footerY
                visible: root.homeViewMode === "covers" &&
                         !root.settingsOpen && root.coverVerticalNavigationText() !== ""
                text: root.coverVerticalNavigationText()
                color: root.accent
                font.family: global.fonts.sans
                font.pixelSize: root.footerFontSize - 1
                font.weight: Font.DemiBold
                font.letterSpacing: 1.8
            }

            ListView {
                id: systemRail
                visible: root.coverZoneVisible(0)
                x: 48
                // Systems have no heading of their own, so the rail is placed
                // straight from the band computed at the top of the file.
                y: root.coverSystemRailTop +
                   (root.coverZonePosition(0) - root.coverWindowStart()) *
                   root.coverRowSlotHeight
                width: parent.width - 96
                height: root.coverSystemCardHeight
                orientation: ListView.Horizontal
                model: systemModel
                spacing: 14
                // The selected delegate grows beyond its nominal height. The
                // rail has ample vertical breathing room, so do not cut its
                // top rim at the ListView boundary.
                clip: false
                // No half-screen end spacers: the first/last cards clamp to
                // the 48 px safe edge while middle selections remain centered.
                focus: root.homeZone === 0
                // Keep the selected platform centered, but visibly translate
                // the entire rail in the direction of travel. The short,
                // retargetable duration preserves rapid D-pad response while
                // making every one-step system change spatially legible.
                highlightMoveDuration: 165
                highlightRangeMode: ListView.ApplyRange
                // The rail spans the full display. The preferred position is
                // the selected delegate's leading edge, so offset by half its
                // width to center it on the physical screen precisely.
                preferredHighlightBegin: (width - root.coverSystemCardWidth) / 2
                preferredHighlightEnd: preferredHighlightBegin
                keyNavigationWraps: true
                keyNavigationEnabled: false
                onCurrentIndexChanged: {
                    if (root.previewReady) {
                        if (root.page === "home" && root.homeViewMode === "list") {
                            root.chooseSystemWallpaper(systemRail.currentIndex)
                            homeListRebuild.restart()
                        } else if (root.page === "home" && root.homeZone === 0) {
                            // Keep the D-pad event turn identical to gameRail:
                            // update selection now, coalesce expensive visual
                            // and preview work immediately afterward.
                            // The destination layer is already decoded. Swap
                            // immediately, then reroll only the departed layer.
                            root.chooseSystemWallpaper(systemRail.currentIndex)
                            systemChangeCommit.restart()
                        }
                    }
                }

                delegate: Item {
                    id: systemCard
                    property bool isSelected: ListView.isCurrentItem && root.homeZone === 0
                    width: root.coverSystemCardWidth
                    height: root.coverSystemCardHeight
                    scale: isSelected ? 1.10 : 0.88
                    opacity: isSelected ? 1.0 : 0.46
                    Behavior on scale { NumberAnimation { duration: 145; easing.type: Easing.OutCubic } }
                    Behavior on opacity { NumberAnimation { duration: 125 } }

                    Rectangle {
                        anchors.fill: parent
                        color: systemCard.isSelected ?
                               Qt.darker(model.accent, 4.5) : "#9b11141b"
                        border.width: systemCard.isSelected ? 5 : 1
                        border.color: systemCard.isSelected ? model.accent : "#42ffffff"
                        radius: 7
                    }

                    Rectangle {
                        x: 18
                        y: 18
                        width: root.coverViewRowCount === 1 ? 80 : 46
                        height: systemCard.isSelected ? 7 : 4
                        color: model.accent
                    }

                    Image {
                        id: systemLogo
                        x: 12
                        // Vertically center the wordmark in the clear space
                        // between the accent stroke and the year label.
                        y: 28
                        width: parent.width - 24
                        height: parent.height - 72
                        source: model.folder === "all" ? "" :
                                Qt.resolvedUrl("assets/logos-png/" + model.folder + ".png")
                        visible: model.folder !== "all" && status !== Image.Error
                        fillMode: Image.PreserveAspectFit
                        horizontalAlignment: model.folder === "windows" ?
                                Image.AlignLeft : Image.AlignHCenter
                        asynchronous: false
                        cache: true
                        smooth: true
                        mipmap: true
                        sourceSize.width: 840
                        sourceSize.height: 360
                    }

                    Text {
                        x: 12
                        y: 30
                        width: parent.width - 24
                        height: parent.height - 74
                        visible: model.folder === "all" || systemLogo.status === Image.Error
                        text: model.folder === "all" ? "ALL\nSYSTEMS" : model.mark
                        color: "#f4f7fc"
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        lineHeight: 0.82
                        font.family: global.fonts.condensed
                        font.pixelSize: root.coverViewRowCount === 1 ? 66 : 40
                        font.weight: Font.Black
                        font.letterSpacing: 2
                    }

                    Text {
                        x: 18
                        y: parent.height - (root.coverViewRowCount === 1 ? 34 : 28)
                        width: parent.width - 34
                        text: model.years
                        color: model.accent
                        font.family: global.fonts.sans
                        font.pixelSize: root.coverViewRowCount === 1 ? 17 : 12
                        font.weight: Font.DemiBold
                        font.letterSpacing: 2
                    }

                    MouseArea {
                        anchors.fill: parent
                        onClicked: {
                            systemRail.currentIndex = index
                            root.homeZone = 0
                            root.enterCollection()
                        }
                    }
                }
            }

            Rectangle {
                visible: false
                x: 58
                y: 580
                width: parent.width - 116
                height: 1
                color: "#35ffffff"
            }

            Item {
                id: shelfViewport
                opacity: root.homeViewMode === "covers" ? 1 : 0
                visible: opacity > 0
                x: 0
                y: root.coverContentTop
                width: parent.width
                height: root.coverContentHeight
                clip: true
                Behavior on opacity {
                    NumberAnimation { duration: root.viewTransitionsEnabled ? 220 : 0 }
                }

                Item {
                    id: shelfStack
                    width: parent.width
                    height: root.coverRowSlotHeight * 8
                    y: -root.coverWindowStart() * root.coverRowSlotHeight
                    Behavior on y { NumberAnimation { duration: 210; easing.type: Easing.OutCubic } }

                    Item {
                        y: root.coverZonePosition(1) * root.coverRowSlotHeight
                        width: parent.width
                        height: root.coverRowSlotHeight

                        Text {
                            x: 58
                            y: 10
                            text: "CONTINUE PLAYING"
                            color: root.homeZone === 1 ? "white" : "#8f98aa"
                            font.family: global.fonts.sans
                            font.pixelSize: 18
                            font.weight: Font.DemiBold
                            font.letterSpacing: 3
                        }

                        ListView {
                            id: recentRail
                            property int zone: 1
                            x: 48
                            y: root.coverShelfLabelHeight
                            width: parent.width - 96
                            // Its own slot, not the whole stack: the rail is a
                            // Flickable, and one eight-slots-tall rail reaches
                            // over every shelf below it.
                            height: parent.height - root.coverShelfLabelHeight - 2
                            orientation: ListView.Horizontal
                            model: recentModel
                            delegate: homeShelfCard
                            spacing: 18
                            clip: false
                            focus: root.homeZone === 1
                            highlightMoveDuration: 180
                            highlightRangeMode: ListView.ApplyRange
                            preferredHighlightBegin: (width - root.coverShelfCardWidth) / 2
                            preferredHighlightEnd: preferredHighlightBegin
                            keyNavigationWraps: true
                            keyNavigationEnabled: false
                            onCurrentIndexChanged: if (root.previewReady && root.page === "home" && root.homeZone === 1) root.activateShelfPreview(1)
                        }
                    }

                    Item {
                        y: root.coverZonePosition(2) * root.coverRowSlotHeight
                        width: parent.width
                        height: root.coverRowSlotHeight

                        Text {
                            x: 58
                            y: 10
                            text: "MOST PLAYED"
                            color: root.homeZone === 2 ? "white" : "#8f98aa"
                            font.family: global.fonts.sans
                            font.pixelSize: 18
                            font.weight: Font.DemiBold
                            font.letterSpacing: 3
                        }

                        ListView {
                            id: mostPlayedRail
                            property int zone: 2
                            x: 48
                            y: root.coverShelfLabelHeight
                            width: parent.width - 96
                            // Its own slot, not the whole stack: the rail is a
                            // Flickable, and one eight-slots-tall rail reaches
                            // over every shelf below it.
                            height: parent.height - root.coverShelfLabelHeight - 2
                            orientation: ListView.Horizontal
                            model: mostPlayedModel
                            delegate: homeShelfCard
                            spacing: 18
                            clip: false
                            focus: root.homeZone === 2
                            highlightMoveDuration: 180
                            highlightRangeMode: ListView.ApplyRange
                            preferredHighlightBegin: (width - root.coverShelfCardWidth) / 2
                            preferredHighlightEnd: preferredHighlightBegin
                            keyNavigationWraps: true
                            keyNavigationEnabled: false
                            onCurrentIndexChanged: if (root.previewReady && root.page === "home" && root.homeZone === 2) root.activateShelfPreview(2)
                        }
                    }

                    Item {
                        y: root.coverZonePosition(3) * root.coverRowSlotHeight
                        width: parent.width
                        height: root.coverRowSlotHeight

                        Text {
                            x: 58
                            y: 10
                            text: "RECENTLY ADDED"
                            color: root.homeZone === 3 ? "white" : "#8f98aa"
                            font.family: global.fonts.sans
                            font.pixelSize: 18
                            font.weight: Font.DemiBold
                            font.letterSpacing: 3
                        }

                        ListView {
                            id: recentlyAddedRail
                            property int zone: 3
                            x: 48
                            y: root.coverShelfLabelHeight
                            width: parent.width - 96
                            // Its own slot, not the whole stack: the rail is a
                            // Flickable, and one eight-slots-tall rail reaches
                            // over every shelf below it.
                            height: parent.height - root.coverShelfLabelHeight - 2
                            orientation: ListView.Horizontal
                            model: recentlyAddedModel
                            delegate: homeShelfCard
                            spacing: 18
                            clip: false
                            focus: root.homeZone === 3
                            highlightMoveDuration: 180
                            highlightRangeMode: ListView.ApplyRange
                            preferredHighlightBegin: (width - root.coverShelfCardWidth) / 2
                            preferredHighlightEnd: preferredHighlightBegin
                            keyNavigationWraps: true
                            keyNavigationEnabled: false
                            onCurrentIndexChanged: if (root.previewReady && root.page === "home" && root.homeZone === 3) root.activateShelfPreview(3)
                        }
                    }

                    Item {
                        y: root.coverZonePosition(4) * root.coverRowSlotHeight
                        width: parent.width
                        height: root.coverRowSlotHeight

                        Text {
                            x: 58
                            y: 10
                            text: "CRITIC SCORE"
                            color: root.homeZone === 4 ? "white" : "#8f98aa"
                            font.family: global.fonts.sans
                            font.pixelSize: 18
                            font.weight: Font.DemiBold
                            font.letterSpacing: 3
                        }

                        ListView {
                            id: criticRail
                            property int zone: 4
                            x: 48
                            y: root.coverShelfLabelHeight
                            width: parent.width - 96
                            // Its own slot, not the whole stack: the rail is a
                            // Flickable, and one eight-slots-tall rail reaches
                            // over every shelf below it.
                            height: parent.height - root.coverShelfLabelHeight - 2
                            orientation: ListView.Horizontal
                            model: allCriticSortModel
                            delegate: homeShelfCard
                            spacing: 18
                            clip: false
                            focus: root.homeZone === 4
                            highlightMoveDuration: 180
                            highlightRangeMode: ListView.ApplyRange
                            preferredHighlightBegin: (width - root.coverShelfCardWidth) / 2
                            preferredHighlightEnd: preferredHighlightBegin
                            keyNavigationWraps: true
                            keyNavigationEnabled: false
                            onCurrentIndexChanged: if (root.previewReady && root.page === "home" && root.homeZone === 4) root.activateShelfPreview(4)
                        }
                    }

                    Item {
                        y: root.coverZonePosition(5) * root.coverRowSlotHeight
                        width: parent.width
                        height: root.coverRowSlotHeight

                        Text {
                            x: 58; y: 10
                            text: "USER SCORE"
                            color: root.homeZone === 5 ? "white" : "#8f98aa"
                            font.family: global.fonts.sans
                            font.pixelSize: 18
                            font.weight: Font.DemiBold
                            font.letterSpacing: 3
                        }

                        ListView {
                            id: userRail
                            property int zone: 5
                            x: 48; y: root.coverShelfLabelHeight
                            width: parent.width - 96
                            // Its own slot, not the whole stack: the rail is a
                            // Flickable, and one eight-slots-tall rail reaches
                            // over every shelf below it.
                            height: parent.height - root.coverShelfLabelHeight - 2
                            orientation: ListView.Horizontal
                            model: allUserSortModel
                            delegate: homeShelfCard
                            spacing: 18; clip: false
                            focus: root.homeZone === 5
                            highlightMoveDuration: 180
                            highlightRangeMode: ListView.ApplyRange
                            preferredHighlightBegin: (width - root.coverShelfCardWidth) / 2
                            preferredHighlightEnd: preferredHighlightBegin
                            keyNavigationWraps: true
                            keyNavigationEnabled: false
                            onCurrentIndexChanged: if (root.previewReady && root.page === "home" && root.homeZone === 5) root.activateShelfPreview(5)
                        }
                    }

                    Item {
                        y: root.coverZonePosition(6) * root.coverRowSlotHeight
                        width: parent.width
                        height: root.coverRowSlotHeight

                        Text {
                            x: 58; y: 10
                            text: "A–Z"
                            color: root.homeZone === 6 ? "white" : "#8f98aa"
                            font.family: global.fonts.sans
                            font.pixelSize: 18
                            font.weight: Font.DemiBold
                            font.letterSpacing: 3
                        }

                        ListView {
                            id: alphaRail
                            property int zone: 6
                            x: 48; y: root.coverShelfLabelHeight
                            width: parent.width - 96
                            // Its own slot, not the whole stack: the rail is a
                            // Flickable, and one eight-slots-tall rail reaches
                            // over every shelf below it.
                            height: parent.height - root.coverShelfLabelHeight - 2
                            orientation: ListView.Horizontal
                            model: allAlphaSortModel
                            delegate: homeShelfCard
                            spacing: 18; clip: false
                            focus: root.homeZone === 6
                            highlightMoveDuration: 180
                            highlightRangeMode: ListView.ApplyRange
                            preferredHighlightBegin: (width - root.coverShelfCardWidth) / 2
                            preferredHighlightEnd: preferredHighlightBegin
                            keyNavigationWraps: true
                            keyNavigationEnabled: false
                            onCurrentIndexChanged: if (root.previewReady && root.page === "home" && root.homeZone === 6) root.activateShelfPreview(6)
                        }
                    }

                    Item {
                        y: root.coverZonePosition(7) * root.coverRowSlotHeight
                        width: parent.width
                        height: root.coverRowSlotHeight

                        Text {
                            x: 58; y: 10
                            text: "RELEASE DATE"
                            color: root.homeZone === 7 ? "white" : "#8f98aa"
                            font.family: global.fonts.sans
                            font.pixelSize: 18
                            font.weight: Font.DemiBold
                            font.letterSpacing: 3
                        }

                        ListView {
                            id: releaseRail
                            property int zone: 7
                            x: 48; y: root.coverShelfLabelHeight
                            width: parent.width - 96
                            // Its own slot, not the whole stack: the rail is a
                            // Flickable, and one eight-slots-tall rail reaches
                            // over every shelf below it.
                            height: parent.height - root.coverShelfLabelHeight - 2
                            orientation: ListView.Horizontal
                            model: allReleaseSortModel
                            delegate: homeShelfCard
                            spacing: 18; clip: false
                            focus: root.homeZone === 7
                            highlightMoveDuration: 180
                            highlightRangeMode: ListView.ApplyRange
                            preferredHighlightBegin: (width - root.coverShelfCardWidth) / 2
                            preferredHighlightEnd: preferredHighlightBegin
                            keyNavigationWraps: true
                            keyNavigationEnabled: false
                            onCurrentIndexChanged: if (root.previewReady && root.page === "home" && root.homeZone === 7) root.activateShelfPreview(7)
                        }
                    }
                }
            }

            Item {
                id: homeListBoxArt
                visible: root.homeViewMode === "list" &&
                         root.homeListFocusColumn === 1 && root.activeGame
                x: !root.dualScreenDevice && root.singleScreenMediaSwapped ?
                   parent.width - 330 - 226 : parent.width - width - 58
                // Pin the visible artwork column to the category controls.
                // Using their actual geometry avoids drift if either header
                // layout changes and works for both Thor and single-screen UI.
                y: homeListPanel.y + homeCategoryTabs.y +
                   homeCategoryTabs.height - height
                // On dual-screen hardware the tab strip now ends beside this
                // column, so artwork can occupy the complete header height
                // instead of being squeezed above Release. Keep conventional
                // one-screen geometry compact so it never collides with PIP.
                width: root.dualScreenDevice ? 246 : 150
                height: root.dualScreenDevice ? 274 : 198
                z: 82

                Image {
                    id: homeListBoxArtA
                    anchors.fill: parent
                    source: root.boxArtworkSourceA
                    fillMode: Image.PreserveAspectFit
                    horizontalAlignment: Image.AlignRight
                    verticalAlignment: Image.AlignBottom
                    asynchronous: false
                    cache: true
                    smooth: true
                    mipmap: true
                    opacity: root.boxArtworkSlot === 0 ? 1 : 0
                    onStatusChanged: if (status === Image.Ready) root.promoteBoxArtwork(0)
                }

                Image {
                    id: homeListBoxArtB
                    anchors.fill: parent
                    source: root.boxArtworkSourceB
                    fillMode: Image.PreserveAspectFit
                    horizontalAlignment: Image.AlignRight
                    verticalAlignment: Image.AlignBottom
                    asynchronous: false
                    cache: true
                    smooth: true
                    mipmap: true
                    opacity: root.boxArtworkSlot === 1 ? 1 : 0
                    onStatusChanged: if (status === Image.Ready) root.promoteBoxArtwork(1)
                }

                Image {
                    id: boxArtworkPreloadPrevious
                    x: -4; y: -4; width: 2; height: 2; opacity: 0
                    asynchronous: true
                    cache: true
                    sourceSize.width: 640
                    sourceSize.height: 900
                }

                Image {
                    id: boxArtworkPreloadNext
                    x: -4; y: -4; width: 2; height: 2; opacity: 0
                    asynchronous: true
                    cache: true
                    sourceSize.width: 640
                    sourceSize.height: 900
                }

                Image {
                    id: boxArtworkPreloadEntry
                    x: -4; y: -4; width: 2; height: 2; opacity: 0
                    asynchronous: true
                    cache: true
                    sourceSize.width: 640
                    sourceSize.height: 900
                }
            }

            Item {
                id: homeListPanel
                x: 48
                y: 324
                width: parent.width - 96
                height: root.contentBottom - y
                opacity: root.homeViewMode === "list" ? 1 : 0
                visible: opacity > 0
                scale: root.homeViewMode === "list" ? 1 : 0.985
                Behavior on opacity {
                    NumberAnimation { duration: root.viewTransitionsEnabled ? 230 : 0 }
                }
                Behavior on scale {
                    NumberAnimation { duration: root.viewTransitionsEnabled ? 240 : 0;
                                      easing.type: Easing.OutCubic }
                }

                Rectangle {
                    x: 0
                    y: 0
                    width: 560
                    height: parent.height
                    color: "transparent"
                    border.width: 0

                    ListView {
                        id: homeSystemList
                        x: 10
                        y: 0
                        width: parent.width - 20
                        // Whole rows only. Nothing else on this page competes
                        // for the height, so the reclaimed strip is spent on
                        // taller rows -- and larger logos and labels with them
                        // -- rather than on a tenth row that would not fit.
                        property real rowSpacing: 4
                        property real rowHeight: root.listRowHeight(
                                parent.height, 70, 80, rowSpacing)
                        height: root.listRowCount(parent.height, 70, rowSpacing) *
                                (rowHeight + rowSpacing) - rowSpacing
                        model: systemModel
                        currentIndex: systemRail.currentIndex
                        spacing: rowSpacing
                        clip: true
                        cacheBuffer: height * 2
                        snapMode: ListView.SnapToItem
                        boundsBehavior: Flickable.StopAtBounds
                        keyNavigationEnabled: false
                        highlightMoveDuration: 110
                        highlightRangeMode: ListView.ApplyRange
                        preferredHighlightBegin: (height - rowHeight) / 2
                        preferredHighlightEnd: (height - rowHeight) / 2

                        delegate: Rectangle {
                            id: homeSystemRow
                            property bool isSelected: ListView.isCurrentItem
                            width: homeSystemList.width
                            height: homeSystemList.rowHeight
                            color: isSelected ? model.accent :
                                   (index % 2 === 0 ? "#66060a10" : "#76060a10")
                            border.width: 0
                            radius: 6

                            Image {
                                id: homeSystemLogo
                                x: 14
                                anchors.verticalCenter: parent.verticalCenter
                                width: 122
                                height: 48
                                source: model.folder === "all" ?
                                        Qt.resolvedUrl("assets/hardware-cutouts/all/0.png") :
                                        Qt.resolvedUrl("assets/logos-png/" + model.folder + ".png")
                                visible: status !== Image.Error
                                fillMode: Image.PreserveAspectFit
                                horizontalAlignment: Image.AlignLeft
                                asynchronous: false
                                cache: true
                                smooth: true
                                mipmap: true
                            }

                            Text {
                                x: 14
                                anchors.verticalCenter: parent.verticalCenter
                                width: 122
                                visible: homeSystemLogo.status === Image.Error
                                text: model.mark
                                color: homeSystemRow.isSelected ? "#071016" : "white"
                                horizontalAlignment: Text.AlignHCenter
                                font.family: global.fonts.condensed
                                font.pixelSize: model.folder === "all" ? 18 : 27
                                font.weight: Font.Black
                            }

                            // Name over years as one block centred on the row,
                            // so a change in row height moves both together
                            // instead of stranding them against the top edge.
                            Text {
                                x: 152
                                y: parent.height / 2 - height - 1
                                width: parent.width - 252
                                text: model.name
                                color: homeSystemRow.isSelected ? "#071016" : "#eef1f6"
                                fontSizeMode: Text.HorizontalFit
                                minimumPixelSize: 15
                                font.family: global.fonts.sans
                                font.pixelSize: 21
                                font.weight: Font.Bold
                            }

                            Text {
                                x: 152
                                y: parent.height / 2 + 3
                                text: model.years
                                color: homeSystemRow.isSelected ? "#18251f" : model.accent
                                font.family: global.fonts.sans
                                font.pixelSize: 13
                                font.weight: Font.Bold
                                font.letterSpacing: 1.2
                            }

                            Text {
                                anchors.right: parent.right
                                anchors.rightMargin: 16
                                anchors.verticalCenter: parent.verticalCenter
                                text: root.systemGameCount(index)
                                color: homeSystemRow.isSelected ? "#071016" : "#aeb6c8"
                                font.family: global.fonts.condensed
                                font.pixelSize: 24
                                font.weight: Font.Bold
                            }

                            MouseArea {
                                anchors.fill: parent
                                onClicked: {
                                    systemRail.currentIndex = index
                                    root.homeListFocusColumn = 0
                                    root.rebuildHomeList()
                                }
                            }
                        }
                    }
                }

                Item {
                    // Twelve pixels of separation from the system column is
                    // sufficient and gives the seven-category strip more room.
                    x: 572
                    y: 0
                    width: parent.width - x
                    height: parent.height

                    Row {
                        id: homeCategoryTabs
                        x: 0
                        y: 0
                        // Keep every tab's geometry fixed while focus or the
                        // selected system changes. All Systems intentionally
                        // leaves the reserved box-art column empty instead of
                        // making seven controls jump wider for one state.
                        width: root.dualScreenDevice ?
                               Math.max(700, homeListBoxArt.x - homeListPanel.x -
                                        parent.x - 24) : parent.width
                        height: 58
                        spacing: 6

                        Repeater {
                            model: ["CONTINUE", "MOST PLAYED", "RECENTLY ADDED",
                                    "CRITIC", "USER", "A–Z", "RELEASE"]
                            Rectangle {
                                property int category: index + 1
                                property bool isSelected: root.homeListCategory === category
                                width: (homeCategoryTabs.width - 36) / 7
                                height: 58
                                color: isSelected ?
                                       Qt.rgba(root.accent.r, root.accent.g,
                                               root.accent.b, 0.90) : "#76060a10"
                                border.width: isSelected ? 2 : 1
                                border.color: isSelected ?
                                              Qt.lighter(root.accent, 1.15) :
                                              "#30ffffff"
                                radius: 7

                                Text {
                                    anchors.centerIn: parent
                                    width: parent.width - 14
                                    text: modelData
                                    color: parent.isSelected ? "#071016" : "#e3e7ef"
                                    horizontalAlignment: Text.AlignHCenter
                                    fontSizeMode: Text.HorizontalFit
                                    minimumPixelSize: 10
                                    font.family: global.fonts.sans
                                    font.pixelSize: 13
                                    font.weight: Font.Bold
                                    font.letterSpacing: 0.45
                                }

                                MouseArea {
                                    anchors.fill: parent
                                    onClicked: {
                                        root.homeListCategory = parent.category
                                        root.homeListFocusColumn = 1
                                        root.rebuildHomeList()
                                    }
                                }
                            }
                        }
                    }

                    ListView {
                        id: homeListRail
                        x: 0
                        y: 76
                        width: parent.width
                        // Whole rows only, and the reclaimed height buys an
                        // eighth game rather than padding under the seventh.
                        property real rowSpacing: 4
                        property real rowHeight: root.listRowHeight(
                                parent.height - y, 76, 88, rowSpacing)
                        height: root.listRowCount(parent.height - y, 76, rowSpacing) *
                                (rowHeight + rowSpacing) - rowSpacing
                        model: root.homeListEntries
                        spacing: rowSpacing
                        clip: true
                        cacheBuffer: height * 2
                        snapMode: ListView.SnapToItem
                        boundsBehavior: Flickable.StopAtBounds
                        keyNavigationEnabled: false
                        highlightMoveDuration: 100
                        highlightRangeMode: ListView.ApplyRange
                        preferredHighlightBegin: (height - rowHeight) / 2
                        preferredHighlightEnd: (height - rowHeight) / 2
                        onCurrentIndexChanged: {
                            if (root.previewReady && root.page === "home" &&
                                    root.homeViewMode === "list")
                                root.activateHomeListPreview()
                        }

                        delegate: Rectangle {
                            id: homeGameRow
                            property bool isSelected: ListView.isCurrentItem &&
                                    root.homeListFocusColumn === 1
                            property var game: root.homeListGameAt(index)
                            width: homeListRail.width
                            height: homeListRail.rowHeight
                            color: isSelected ? root.homeListAccentForGame(game) :
                                   (index % 2 === 0 ? "#78060a10" : "#86060a10")
                            border.width: 0
                            radius: 7

                            Text {
                                x: 20
                                anchors.verticalCenter: parent.verticalCenter
                                width: 54
                                text: (index < 9 ? "0" : "") + (index + 1)
                                color: homeGameRow.isSelected ? "#03050a" : "#647087"
                                font.family: global.fonts.condensed
                                font.pixelSize: 19
                                font.weight: Font.Bold
                            }

                            Text {
                                x: 78
                                anchors.verticalCenter: parent.verticalCenter
                                width: parent.width - 580
                                text: root.displayTitle(game)
                                color: homeGameRow.isSelected ? "#03050a" : "#eef1f6"
                                // Shrink before truncating: a long name read
                                // at a smaller size beats one whose tail is
                                // cut off as the list scrolls past it.
                                elide: Text.ElideRight
                                fontSizeMode: Text.HorizontalFit
                                minimumPixelSize: 18
                                font.family: global.fonts.sans
                                font.pixelSize: 26
                                font.weight: homeGameRow.isSelected ? Font.Bold : Font.DemiBold
                            }

                            Text {
                                anchors.right: parent.right
                                anchors.rightMargin: 20
                                anchors.verticalCenter: parent.verticalCenter
                                width: 480
                                text: root.gameFactsText(game)
                                color: homeGameRow.isSelected ? "#03050a" :
                                       root.homeListAccentForGame(game)
                                horizontalAlignment: Text.AlignRight
                                fontSizeMode: Text.HorizontalFit
                                minimumPixelSize: 14
                                font.family: global.fonts.sans
                                font.pixelSize: 18
                                font.weight: Font.Bold
                            }

                            MouseArea {
                                anchors.fill: parent
                                pressAndHoldInterval: 800
                                onPressAndHold: root.openGameActions(game, index)
                                onClicked: {
                                    if (root.gameActionOpen) return
                                    homeListRail.currentIndex = index
                                    root.homeListFocusColumn = 1
                                    root.launch(game)
                                }
                            }
                        }
                    }

                    Text {
                        anchors.centerIn: homeListRail
                        visible: root.homeListEntries.length === 0
                        text: "NO " + root.homeShelfName(root.homeListCategory) +
                              " GAMES FOR " + systemModel.get(systemRail.currentIndex).name
                        color: "#aeb6c8"
                        font.family: global.fonts.sans
                        font.pixelSize: 22
                        font.weight: Font.DemiBold
                        font.letterSpacing: 1.2
                    }
                }
            }
        }

        Item {
            id: gamesPage
            anchors.fill: parent
            opacity: root.page === "games" ? 1 : 0
            scale: root.page === "games" ? 1 : 0.985
            visible: opacity > 0
            Behavior on opacity {
                NumberAnimation { duration: root.viewTransitionsEnabled ? 240 : 0;
                                  easing.type: Easing.OutCubic }
            }
            Behavior on scale {
                NumberAnimation { duration: root.viewTransitionsEnabled ? 260 : 0;
                                  easing.type: Easing.OutCubic }
            }
            transform: Translate {
                x: root.page === "games" ? 0 : 72
                Behavior on x {
                    NumberAnimation { duration: root.viewTransitionsEnabled ? 260 : 0;
                                      easing.type: Easing.OutCubic }
                }
            }

            Text {
                id: allSystemsLibraryLabel
                x: 58
                y: 130
                visible: root.allSystemsActive
                text: "ALL SYSTEMS"
                color: "white"
                font.family: global.fonts.condensed
                font.pixelSize: 31
                font.weight: Font.Bold
                font.letterSpacing: 2.6
            }

            Rectangle {
                x: 282
                y: 135
                width: 2
                height: 27
                visible: root.allSystemsActive
                color: root.accent
            }

            Text {
                x: root.allSystemsActive ? 304 : 58
                y: root.allSystemsActive ? 139 : 142
                text: systemModel.get(root.displaySystemIndex).name
                color: root.accent
                font.family: global.fonts.sans
                font.pixelSize: root.allSystemsActive ? 20 : 22
                font.weight: Font.DemiBold
                font.letterSpacing: 3
            }

            Text {
                x: 58
                y: 180
                // On a one-screen handheld, reserve the top-right preview's
                // footprint so long game titles and facts never render under
                // the PIP, including the larger single-screen list preview.
                width: !root.dualScreenDevice ?
                       ((root.singleScreenMediaSwapped && root.gameViewMode === "list" ?
                         parent.width - 624 - 56 : singleScreenPip.x) - x - 28) :
                       parent.width - 116
                height: 68
                text: root.activeGame ? root.displayTitle(root.activeGame) :
                      (root.searchQuery !== "" ? "NO MATCHING GAMES" : "NO GAMES YET")
                color: "white"
                font.family: global.fonts.condensed
                font.pixelSize: 58
                minimumPixelSize: 34
                fontSizeMode: Text.HorizontalFit
                font.weight: Font.Bold
                maximumLineCount: 1
            }

            Text {
                x: 62
                y: 253
                text: root.gameFactsText(root.activeGame)
                color: root.accent
                font.family: global.fonts.sans
                font.pixelSize: 22
                font.weight: Font.Bold
                font.letterSpacing: 1.1
            }

            Text {
                x: 62
                y: 286
                text: (root.allSystemsActive || root.activeCollection) ?
                      (activeGameCount > 0 ? gameRail.currentIndex + 1 : 0) +
                      " / " + activeGameCount +
                      "     SELECT TO PLAY" :
                      "ADD GAMES TO  /GAMES/" + systemModel.get(root.activeSystemIndex).folder
                color: "#aeb6c8"
                font.family: global.fonts.sans
                font.pixelSize: 17
                font.letterSpacing: 2
            }

            Rectangle {
                x: 58
                y: 326
                width: 460
                height: 2
                color: root.accent
            }

            Row {
                x: 48
                y: 350
                spacing: 8

                Repeater {
                    model: ["critic", "user", "alpha", "release"]
                    Rectangle {
                        width: 142
                        height: 44
                        color: "transparent"
                        clip: true
                        border.width: 1
                        border.color: root.sortMode === modelData ?
                                      Qt.lighter(root.accent, 1.18) : "#38ffffff"
                        radius: 7

                        ShaderEffectSource {
                            id: sortGlassSource
                            anchors.fill: parent
                            sourceItem: root.upperArtworkSlot === 0 ? upperArtworkA : upperArtworkB
                            sourceRect: Qt.rect(48 + index * 150 - 16, 350 - 16,
                                                142 + 32, 44 + 32)
                            textureSize: Qt.size(142 + 32, 44 + 32)
                            live: true
                            smooth: true
                            visible: false
                        }

                        Rectangle {
                            anchors.fill: parent
                            visible: !root.liquidGlassEnabled
                            color: root.sortMode === modelData ?
                                   Qt.rgba(root.accent.r, root.accent.g,
                                           root.accent.b, 0.90) : "#76060a10"
                            radius: 7
                        }

                        ShaderEffect {
                            anchors.fill: parent
                            visible: root.liquidGlassEnabled
                            property variant source: sortGlassSource
                            property size glassSize: Qt.size(width, height)
                            property real cornerRadius: 7
                            property real edgeThickness: 14
                            property real distortionStrength: 11.0
                            property real scatterRadius: 2.8
                            property real samplePadding: 16
                            property color glassTint: root.sortMode === modelData ?
                                Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.80) :
                                Qt.rgba(0.025, 0.04, 0.07, 0.38)
                            fragmentShader: root.liquidGlassFragmentShader
                        }

                        Rectangle {
                            anchors.fill: parent
                            anchors.margins: 2
                            color: "transparent"
                            border.width: 1
                            border.color: root.sortMode === modelData ?
                                          "#42ffffff" : "#20ffffff"
                            radius: 5
                        }

                        Text {
                            anchors.centerIn: parent
                            text: root.sortLabel(modelData)
                            color: root.sortMode === modelData ? "#071016" : "#e3e7ef"
                            font.family: global.fonts.sans
                            font.pixelSize: 15
                            font.weight: Font.Bold
                            font.letterSpacing: 0.55
                        }

                        MouseArea {
                            anchors.fill: parent
                            onClicked: {
                                root.sortMode = modelData
                                root.scheduleNavigationPersistence()
                                gameRail.currentIndex = 0
                                sortChangeCommit.restart()
                            }
                        }
                    }
                }
            }

            ListView {
                id: gameRail
                x: 48
                y: 450
                width: parent.width - 96
                // Runs to the content floor. Cards scale under selection, so
                // the rail keeps a card-and-a-bit of slack at both ends; it
                // still may not render behind the view label or controls.
                height: root.contentBottom - y
                orientation: ListView.Horizontal
                model: activeGameModel
                spacing: 22
                clip: false
                focus: root.page === "games"
                highlightMoveDuration: 230
                highlightRangeMode: ListView.ApplyRange
                preferredHighlightBegin: (width - root.gameCardWidth) / 2
                preferredHighlightEnd: (width - root.gameCardWidth) / 2
                keyNavigationWraps: true
                keyNavigationEnabled: false
                opacity: root.gameViewMode === "covers" ? 1 : 0
                visible: opacity > 0
                Behavior on opacity {
                    NumberAnimation { duration: root.viewTransitionsEnabled ? 210 : 0 }
                }
                onCurrentIndexChanged: {
                    if (root.gameViewMode === "list")
                        root.positionGameListAtIndex(currentIndex)
                    if (root.previewReady && root.page === "games") {
                        root.activateGamePreview()
                    }
                }

                delegate: Item {
                    id: gameCard
                    property bool isSelected: ListView.isCurrentItem
                    property var game: root.gameAtDisplayIndex(index)
                    property real coverAspect: gameCover.status === Image.Ready &&
                            gameCover.sourceSize.height > 0 ?
                            gameCover.sourceSize.width / gameCover.sourceSize.height : 0.72
                    // The caption is a fixed block -- accent rule, two title
                    // lines, two fact lines -- and the artwork viewport is
                    // whatever the card has left over. Height reclaimed from
                    // the navigation bar therefore becomes cover art and not
                    // padding. Contain every aspect ratio inside that
                    // viewport; the selected-card scale must stay below the
                    // sort row and above the footer.
                    property real captionHeight: 138
                    property real artTop: 12
                    property real artHeight: height - artTop - captionHeight
                    property real artWidth: width - 26
                    property real boxHeight: Math.min(artHeight, artWidth / coverAspect)
                    property real boxWidth: boxHeight * coverAspect
                    width: root.gameCardWidth
                    height: gameRail.height - 46
                    scale: ListView.isCurrentItem ? 1.08 : 0.91
                    opacity: ListView.isCurrentItem ? 1.0 : 0.82
                    Behavior on scale { NumberAnimation { duration: 230; easing.type: Easing.OutCubic } }
                    Behavior on opacity { NumberAnimation { duration: 180 } }

                    Image {
                        id: gameCover
                        x: (parent.width - parent.boxWidth) / 2
                        y: parent.artTop + (parent.artHeight - parent.boxHeight) / 2
                        width: parent.boxWidth
                        height: parent.boxHeight
                        source: game ? (game.assets.boxFront || "") : ""
                        fillMode: Image.PreserveAspectFit
                        asynchronous: true
                        smooth: true
                        mipmap: true
                    }

                    Rectangle {
                        x: 12
                        y: parent.artTop + parent.artHeight + 14
                        width: 36
                        height: 3
                        color: root.accent
                    }

                    Text {
                        x: 12
                        y: parent.artTop + parent.artHeight + 30
                        width: parent.width - 24
                        height: 64
                        text: root.displayTitle(game)
                        color: "#f1f3f8"
                        wrapMode: Text.Wrap
                        maximumLineCount: 2
                        elide: Text.ElideRight
                        // Two lines at the nominal size cover almost every
                        // title; anything longer shrinks to fit rather than
                        // losing its tail while the rail is being scrolled.
                        fontSizeMode: Text.Fit
                        minimumPixelSize: 16
                        font.family: global.fonts.sans
                        font.pixelSize: gameCard.isSelected ? 26 : 23
                        font.weight: Font.Bold
                        style: Text.Outline
                        styleColor: "#d0000000"
                    }

                    Text {
                        x: 12
                        y: parent.artTop + parent.artHeight + 98
                        width: parent.width - 24
                        height: 40
                        text: root.scoreText(game) + "\nRELEASE  " + root.releaseYear(game)
                        color: root.accent
                        wrapMode: Text.Wrap
                        maximumLineCount: 2
                        fontSizeMode: Text.HorizontalFit
                        minimumPixelSize: 12
                        font.family: global.fonts.sans
                        font.pixelSize: 17
                        font.weight: Font.Bold
                        font.letterSpacing: 0
                        style: Text.Outline
                        styleColor: "#d0000000"
                    }

                    MouseArea {
                        anchors.fill: parent
                        pressAndHoldInterval: 800
                        onPressAndHold: root.openGameActions(game, index)
                        onClicked: {
                            if (root.gameActionOpen) return
                            gameRail.currentIndex = index
                            root.launch(game)
                        }
                    }
                }
            }

            Item {
                id: listViewPanel
                x: 48
                // Thor starts just above the sort row, which sits to the left
                // of the list and never collides with it; a single-screen
                // device must clear its top-right preview instead.
                y: !root.dualScreenDevice ? 480 : 316
                width: parent.width - 96
                // Runs to the content floor. The list quantises itself to
                // whole rows inside this, and the cover claims the rest.
                height: root.contentBottom - y
                opacity: root.gameViewMode === "list" ? 1 : 0
                visible: opacity > 0
                Behavior on opacity {
                    NumberAnimation { duration: root.viewTransitionsEnabled ? 210 : 0 }
                }

                Item {
                    id: selectedGameArtPanel
                    property bool swappedSingleScreen: !root.dualScreenDevice &&
                            root.singleScreenMediaSwapped
                    x: swappedSingleScreen ?
                       root.width - 624 - 56 - listViewPanel.x : 0
                    // The Flip's list begins lower to reserve room for PIP,
                    // but its cover should not begin with that list. Give the
                    // single-screen cover its own square viewport between the
                    // sort controls and the bottom edge. A square cover then
                    // receives exactly 18 px on all four sides.
                    // Thor: the sort row ends at y=394 and this parent begins
                    // at y=316, so 90 px clears it, and the cover then runs
                    // the whole way down to the content floor.
                    // The Flip retains its separate single-screen correction.
                    y: swappedSingleScreen ? 102 - listViewPanel.y :
                       (!root.dualScreenDevice ? -76 : 90)
                    width: swappedSingleScreen ? 624 : 600
                    height: swappedSingleScreen ? Math.round(624 * 9 / 16) :
                            (!root.dualScreenDevice ? 540 : parent.height - 90)
                    // Use equal outer padding on every side and center within
                    // the entire list panel. The former 106 px top inset made
                    // every cover appear visibly low on a single-screen Flip.
                    property real coverWidth: Math.max(1, width - 36)
                    property real coverHeight: Math.max(1, height - 36)

                    Image {
                        id: listCover
                        anchors.centerIn: parent
                        width: parent.coverWidth
                        height: parent.coverHeight
                        source: root.boxArtworkSourceA
                        fillMode: Image.PreserveAspectFit
                        asynchronous: false
                        cache: true
                        smooth: true
                        mipmap: true
                        opacity: root.boxArtworkSlot === 0 ? 1 : 0
                    }

                    Image {
                        anchors.centerIn: parent
                        width: parent.coverWidth
                        height: parent.coverHeight
                        source: root.boxArtworkSourceB
                        fillMode: Image.PreserveAspectFit
                        asynchronous: false
                        cache: true
                        smooth: true
                        mipmap: true
                        opacity: root.boxArtworkSlot === 1 ? 1 : 0
                    }

                    Text {
                        anchors.centerIn: parent
                        width: parent.width - 80
                        visible: root.activeGame && !root.activeGame.assets.boxFront
                        text: root.activeGame ? root.displayTitle(root.activeGame) : ""
                        color: "#e8ebf2"
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.Wrap
                        font.family: global.fonts.condensed
                        font.pixelSize: 44
                        font.weight: Font.DemiBold
                    }
                }

                ListView {
                    id: gameListRail
                    x: 634
                    y: 0
                    width: parent.width - x
                    // Eight rows is what this panel holds: a ninth needs 716 px
                    // and only 695 are available, so asking for one would have
                    // to shave the rows below their 76 px floor. The reclaimed
                    // strip is therefore spent making each row TALLER instead
                    // of leaving it as a band under the eighth -- the row box
                    // grows from 76 to 83 px and the list bottoms out on the
                    // content floor. The stride is no longer a constant: the
                    // paging jump and highlight band below are both expressed
                    // in whole strides, so they read it from here.
                    property real rowSpacing: 4
                    property real rowHeight: root.listRowHeight(
                            parent.height, 76, 92, rowSpacing)
                    readonly property real rowStride: rowHeight + rowSpacing
                    height: root.listRowCount(parent.height, 76, rowSpacing) *
                            (rowHeight + rowSpacing) - rowSpacing
                    orientation: ListView.Vertical
                    model: activeGameModel
                    currentIndex: gameRail.currentIndex
                    spacing: rowSpacing
                    clip: true
                    cacheBuffer: height * 2
                    snapMode: ListView.SnapToItem
                    boundsBehavior: Flickable.StopAtBounds
                    focus: false
                    keyNavigationEnabled: false
                    highlightMoveDuration: 100
                    highlightRangeMode: ListView.ApplyRange
                    // Three whole strides down from the top of the viewport,
                    // so centering can never expose half a row. Derived from
                    // the stride rather than written as a literal, so a taller
                    // row cannot drift the band off a row boundary.
                    preferredHighlightBegin: 3 * rowStride
                    preferredHighlightEnd: 3 * rowStride

                    delegate: Rectangle {
                        id: gameListRow
                        property bool isSelected: ListView.isCurrentItem
                        property var game: root.gameAtDisplayIndex(index)
                        width: gameListRail.width
                        height: gameListRail.rowHeight
                        color: "transparent"
                        clip: true
                        border.width: ListView.isCurrentItem ? 2 : 1
                        border.color: ListView.isCurrentItem ?
                                      Qt.lighter(root.accent, 1.18) : "#38ffffff"
                        radius: 7

                        ShaderEffectSource {
                            id: rowGlassSource
                            anchors.fill: parent
                            sourceItem: root.upperArtworkSlot === 0 ? upperArtworkA : upperArtworkB
                            sourceRect: Qt.rect(listViewPanel.x + gameListRail.x - 28,
                                                listViewPanel.y + gameListRow.y -
                                                gameListRail.contentY - 28,
                                                gameListRow.width + 56,
                                                gameListRow.height + 56)
                            textureSize: Qt.size(gameListRow.width + 56,
                                                 gameListRow.height + 56)
                            live: true
                            smooth: true
                            visible: false
                        }

                        Rectangle {
                            anchors.fill: parent
                            visible: !root.liquidGlassEnabled
                            color: gameListRow.isSelected ?
                                   Qt.rgba(root.accent.r, root.accent.g,
                                           root.accent.b, 0.92) :
                                   (index % 2 === 0 ? "#78060a10" : "#86060a10")
                            radius: 7
                        }

                        ShaderEffect {
                            anchors.fill: parent
                            visible: root.liquidGlassEnabled
                            property variant source: rowGlassSource
                            property size glassSize: Qt.size(width, height)
                            property real cornerRadius: 7
                            property real edgeThickness: 23
                            property real distortionStrength: 20.0
                            property real scatterRadius: 4.2
                            property real samplePadding: 28
                            property color glassTint: gameListRow.isSelected ?
                                Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.86) :
                                (index % 2 === 0 ? Qt.rgba(0.025, 0.04, 0.07, 0.40) :
                                                  Qt.rgba(0.025, 0.04, 0.07, 0.45))
                            fragmentShader: root.liquidGlassFragmentShader
                        }

                        Rectangle {
                            anchors.fill: parent
                            anchors.margins: gameListRow.isSelected ? 2 : 1
                            color: "transparent"
                            border.width: 1
                            border.color: gameListRow.isSelected ? "#46ffffff" : "#20ffffff"
                            radius: 5
                        }

                        Text {
                            x: 20
                            anchors.verticalCenter: parent.verticalCenter
                            width: 54
                            text: (index < 9 ? "0" : "") + (index + 1)
                            color: gameListRow.isSelected ? "#03050a" : "#647087"
                            font.family: global.fonts.condensed
                            font.pixelSize: 19
                            font.weight: Font.Bold
                        }

                        Text {
                            x: 78
                            anchors.verticalCenter: parent.verticalCenter
                            width: parent.width - 590
                            text: root.displayTitle(game)
                            color: gameListRow.isSelected ? "#03050a" : "#eef1f6"
                            // Shrink before truncating: a long name read at a
                            // smaller size beats one whose tail is cut off as
                            // the list scrolls past it.
                            elide: Text.ElideRight
                            fontSizeMode: Text.HorizontalFit
                            minimumPixelSize: 18
                            font.family: global.fonts.sans
                            font.pixelSize: 27
                            font.weight: gameListRow.isSelected ? Font.Bold : Font.DemiBold
                        }

                        Text {
                            anchors.right: parent.right
                            anchors.rightMargin: 22
                            anchors.verticalCenter: parent.verticalCenter
                            width: 480
                            text: root.gameFactsText(game)
                            color: gameListRow.isSelected ? "#03050a" : root.accent
                            horizontalAlignment: Text.AlignRight
                            elide: Text.ElideRight
                            font.family: global.fonts.sans
                            font.pixelSize: 19
                            font.weight: Font.Bold
                            font.letterSpacing: 0.1
                        }

                        MouseArea {
                            anchors.fill: parent
                            pressAndHoldInterval: 800
                            onPressAndHold: root.openGameActions(game, index)
                            onClicked: {
                                if (root.gameActionOpen) return
                                gameRail.currentIndex = index
                                root.launch(game)
                            }
                        }
                    }
                }
            }

            // No plate behind the legend, and none needed: the backdrop wash is
            // symmetric top to bottom, so this sits on exactly the treatment
            // the clock and battery sit on at the other edge.
            Text {
                id: gamesLegend
                z: 81
                anchors.right: parent.right
                anchors.rightMargin: root.footerSideMargin
                y: root.footerY
                width: Math.max(0, parent.width - root.footerSideMargin - root.footerLegendLeft)
                horizontalAlignment: Text.AlignRight
                fontSizeMode: Text.HorizontalFit
                minimumPixelSize: 9
                readonly property string fullLegend:
                    "L1 / R1  SORT     L2 / R2  SYSTEM     LEFT / RIGHT  PAGE     Y  VIEW: " + root.gameViewMode.toUpperCase() +
                    "     X  SETTINGS     RIGHT STICK  VIEWS     B  BACK     A  PLAY     HOLD GAME  OPTIONS"
                // Narrow windows keep the essential controls at a readable size.
                text: gamesLegendMetrics.advanceWidth <= width ? fullLegend :
                      "L1 / R1  SORT     Y  VIEW: " + root.gameViewMode.toUpperCase() +
                      "     X  SETTINGS     B  BACK     A  PLAY     HOLD GAME  OPTIONS"
                color: root.footerColor
                font.family: global.fonts.sans
                font.pixelSize: root.footerFontSize
                font.letterSpacing: 1

                // TextMetrics is not an Item: name the legend, "parent" is not it.
                TextMetrics {
                    id: gamesLegendMetrics
                    font: gamesLegend.font
                    text: gamesLegend.fullLegend
                }
            }
        }
    }

    Text {
        id: displaySettingsHint
        z: 90
        anchors.right: parent.right
        anchors.rightMargin: root.footerSideMargin
        y: root.footerY
        width: Math.max(0, parent.width - root.footerSideMargin - root.footerLegendLeft)
        horizontalAlignment: Text.AlignRight
        fontSizeMode: Text.HorizontalFit
        minimumPixelSize: 9
        visible: root.page === "home" && !root.settingsOpen
        readonly property string fullLegend: root.homeViewMode === "list" ?
              "L1 / R1  CATEGORY     L2 / R2  SYSTEM     LEFT / RIGHT  PAGE     UP / DOWN  SELECT     Y  LAYOUT     X  SETTINGS     RIGHT STICK  VIEWS     B  SYSTEM LIST     A  PLAY" :
              "L1 / R1  CATEGORY     L2 / R2  SYSTEM     Y  LAYOUT     X  SETTINGS     D-PAD  NAVIGATE     RIGHT STICK  VIEWS     A  OPEN"
        // Narrow windows keep the essential controls at a readable size.
        text: homeLegendMetrics.advanceWidth <= width ? fullLegend :
              (root.homeViewMode === "list" ?
               "L1 / R1  CATEGORY     L2 / R2  SYSTEM     Y  LAYOUT     X  SETTINGS     B  SYSTEM LIST     A  PLAY" :
               "L1 / R1  CATEGORY     L2 / R2  SYSTEM     Y  LAYOUT     X  SETTINGS     A  OPEN")
        color: root.footerColor
        font.family: global.fonts.sans
        font.pixelSize: root.footerFontSize
        font.letterSpacing: 1

        TextMetrics {
            id: homeLegendMetrics
            font: displaySettingsHint.font
            text: displaySettingsHint.fullLegend
        }

        MouseArea {
            // Only the painted legend is a tap target, as before it got a width.
            anchors.right: parent.right
            anchors.rightMargin: -18
            anchors.verticalCenter: parent.verticalCenter
            width: parent.paintedWidth + 36
            height: parent.height + 36
            onClicked: {
                root.settingsOpen = true
                root.settingsIndex = 0
            }
        }
    }

    Text {
        id: footerViewName
        z: 90
        anchors.left: parent.left
        anchors.leftMargin: root.footerSideMargin
        y: root.footerY
        visible: !root.settingsOpen
        text: root.currentViewName
        color: root.footerColor
        font.family: global.fonts.sans
        font.pixelSize: root.footerFontSize
        font.weight: Font.DemiBold
        font.letterSpacing: 1
    }

    Rectangle {
        id: updatePromptOverlay
        z: 850
        anchors.fill: parent
        visible: root.updatePromptOpen
        color: "#db04070c"

        MouseArea { anchors.fill: parent }

        Rectangle {
            anchors.centerIn: parent
            width: 760
            height: 390
            color: "#f20a0e16"
            border.width: 2
            border.color: root.accent
            radius: 12

            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                y: 54
                text: "EMUFUSION UPDATE READY"
                color: "white"
                font.family: global.fonts.condensed
                font.pixelSize: 48
                font.weight: Font.Bold
                font.letterSpacing: 1.4
            }

            Text {
                x: 60
                y: 130
                width: parent.width - 120
                text: root.updateStatusMessage !== "" ? root.updateStatusMessage :
                      "A new signed EmuFusion package has been downloaded."
                color: "#b8c1d1"
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                font.family: global.fonts.sans
                font.pixelSize: 20
            }

            Row {
                anchors.horizontalCenter: parent.horizontalCenter
                y: 238
                spacing: 24

                Repeater {
                    model: ["INSTALL", "LATER"]
                    Rectangle {
                        width: 270
                        height: 82
                        color: root.updatePromptChoice === index ? root.accent : "#7e121925"
                        border.width: root.updatePromptChoice === index ? 3 : 1
                        border.color: root.updatePromptChoice === index ?
                                      Qt.lighter(root.accent, 1.18) : "#42ffffff"
                        radius: 8

                        Text {
                            anchors.centerIn: parent
                            text: modelData
                            color: root.updatePromptChoice === index ? "#05070b" : "white"
                            font.family: global.fonts.sans
                            font.pixelSize: 24
                            font.weight: Font.Bold
                            font.letterSpacing: 1.4
                        }

                        MouseArea {
                            anchors.fill: parent
                            onClicked: {
                                root.updatePromptChoice = index
                                if (index === 0) root.installReadyUpdate()
                                else root.dismissReadyUpdate()
                            }
                        }
                    }
                }
            }

            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                y: 344
                text: "LEFT / RIGHT  CHOOSE     A  CONFIRM     B  LATER"
                color: "#7f899c"
                font.family: global.fonts.sans
                font.pixelSize: 14
                font.letterSpacing: 1
            }
        }
    }

    Rectangle {
        id: voiceFeedbackOverlay
        z: 870
        anchors.fill: parent
        visible: root.voiceFeedbackOpen
        color: "#e604070c"

        MouseArea { anchors.fill: parent }

        Rectangle {
            anchors.centerIn: parent
            width: Math.min(980, root.width - 120)
            height: Math.min(700, root.height - 100)
            color: "#fb0a0e16"
            border.width: 2
            border.color: root.accent
            radius: 12

            Text {
                x: 52
                y: 38
                width: parent.width - 104
                text: "VOICE FEEDBACK"
                color: "white"
                font.family: global.fonts.condensed
                font.pixelSize: 45
                font.weight: Font.Bold
                font.letterSpacing: 1.4
            }

            Text {
                x: 54
                y: 98
                width: parent.width - 108
                text: "Only the transcription is kept. Remove personal details before Send. " +
                      "Only app version and emulated system are attached—no device details or logs. " +
                      "GitHub issues are public and identify your GitHub account; this is not anonymous diagnostics."
                color: "#9ba6b8"
                wrapMode: Text.Wrap
                font.family: global.fonts.sans
                font.pixelSize: 17
                lineHeight: 1.18
            }

            Rectangle {
                x: 54
                y: 174
                width: parent.width - 108
                height: parent.height - 370
                color: "#b60e141e"
                border.width: 1
                border.color: "#38ffffff"
                radius: 8

                TextEdit {
                    id: voiceFeedbackEditor
                    anchors.fill: parent
                    anchors.margins: 24
                    text: root.voiceFeedbackTranscript
                    color: "white"
                    wrapMode: Text.Wrap
                    font.family: global.fonts.sans
                    font.pixelSize: 23
                    selectByMouse: true
                    activeFocusOnPress: true
                    selectionColor: root.accent
                    selectedTextColor: "#05070b"
                    inputMethodHints: Qt.ImhNone
                    clip: true
                    onTextChanged: {
                        if (!activeFocus || root.voiceFeedbackTranscript === text)
                            return
                        root.voiceFeedbackTranscript = text
                        if (String(text).trim() !== "") {
                            root.voiceFeedbackState = "ready"
                            root.voiceFeedbackMessage =
                                    "Review the edited transcription before sending."
                        }
                    }
                    onActiveFocusChanged: {
                        if (activeFocus) Qt.inputMethod.show()
                    }
                }

                Text {
                    anchors.fill: parent
                    anchors.margins: 24
                    visible: voiceFeedbackEditor.text.length === 0 &&
                             !voiceFeedbackEditor.activeFocus
                    text: root.voiceFeedbackState === "listening" ?
                          "Listening…" : "Your transcription will appear here. Tap to type."
                    color: "#687487"
                    wrapMode: Text.Wrap
                    font.family: global.fonts.sans
                    font.pixelSize: 23
                    lineHeight: 1.2
                }
            }

            Text {
                x: 54
                y: parent.height - 178
                width: parent.width - 108
                text: root.voiceFeedbackMessage
                color: root.voiceFeedbackState === "error" ? "#ff9d91" : root.accent
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                font.family: global.fonts.sans
                font.pixelSize: 17
                font.weight: Font.DemiBold
            }

            Row {
                anchors.horizontalCenter: parent.horizontalCenter
                y: parent.height - 116
                spacing: 24

                Repeater {
                    model: ["SEND", "REDO"]
                    Rectangle {
                        property bool sendEnabled: index !== 0 ||
                                root.voiceFeedbackState === "ready" ||
                                root.voiceFeedbackState === "github-review"
                        width: 300
                        height: 72
                        color: !sendEnabled ? "#3b414b" :
                               (root.voiceFeedbackChoice === index ? root.accent : "#7e121925")
                        border.width: root.voiceFeedbackChoice === index ? 3 : 1
                        border.color: root.voiceFeedbackChoice === index ?
                                      Qt.lighter(root.accent, 1.18) : "#42ffffff"
                        radius: 8
                        opacity: sendEnabled ? 1 : 0.56

                        Text {
                            anchors.centerIn: parent
                            text: modelData
                            color: parent.sendEnabled && root.voiceFeedbackChoice === index ?
                                   "#05070b" : "white"
                            font.family: global.fonts.sans
                            font.pixelSize: 23
                            font.weight: Font.Bold
                            font.letterSpacing: 1.4
                        }

                        MouseArea {
                            anchors.fill: parent
                            enabled: parent.sendEnabled
                            onClicked: {
                                root.voiceFeedbackChoice = index
                                if (index === 0) root.sendVoiceFeedback()
                                else root.startVoiceFeedback()
                            }
                        }
                    }
                }
            }

            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                y: parent.height - 30
                text: "GitHub provides the final account-authenticated Create confirmation     •     B  CLOSE"
                color: "#758095"
                font.family: global.fonts.sans
                font.pixelSize: 14
                font.letterSpacing: 0.8
            }

            MouseArea {
                anchors.right: parent.right
                anchors.top: parent.top
                width: 72
                height: 72
                onClicked: root.closeVoiceFeedback()

                Text {
                    anchors.centerIn: parent
                    text: "×"
                    color: "#b8c1d1"
                    font.pixelSize: 34
                }
            }
        }
    }

    Rectangle {
        id: gameActionOverlay
        z: 700
        anchors.fill: parent
        visible: root.gameActionOpen
        color: "#e805080d"

        MouseArea {
            anchors.fill: parent
            onClicked: root.closeGameActions()
        }

        Rectangle {
            id: gameActionPanel
            anchors.centerIn: parent
            // Sized against the panel rather than the old 1025 px floor. The
            // extra height goes to taller option rows and to the cheat list,
            // which could previously show barely three of a game's entries.
            // Grown by one more row-step (108px) to fit the MULTIPLAYER row
            // appended below DELETE; every other mode just gets extra
            // bottom padding from the taller shared chrome.
            width: 880
            height: 808
            color: "#fb0d121a"
            border.width: 2
            border.color: root.accent
            radius: 10

            // Swallow taps on empty dialog space; only the dimmed area outside
            // the panel dismisses it. Controls declared below remain on top.
            MouseArea { anchors.fill: parent }

            Text {
                x: 44
                y: 42
                width: parent.width - 88
                text: root.displayTitle(root.gameActionGame)
                color: "white"
                elide: Text.ElideRight
                font.family: global.fonts.condensed
                font.pixelSize: 42
                font.weight: Font.Bold
            }

            Text {
                x: 46
                y: 100
                text: root.gameActionMode === "menu" ? "GAME OPTIONS" :
                      root.gameActionMode === "rename" ? "RENAME GAME" :
                      root.gameActionMode === "cheats" ? "CHEATS" :
                      root.gameActionMode === "multiplayer" ? "MULTIPLAYER (ALPHA)" :
                      root.gameActionMode === "confirm-remove" ? "CONFIRM REMOVE FROM LIST" :
                      root.gameActionMode === "confirm-delete" ? "CONFIRM DELETE" : "EMUFUSION LIBRARY"
                color: root.accent
                font.family: global.fonts.sans
                font.pixelSize: 17
                font.weight: Font.Bold
                font.letterSpacing: 2
            }

            Item {
                anchors.fill: parent
                visible: root.gameActionMode === "menu"

                Rectangle {
                    x: 44
                    y: 146
                    width: parent.width - 88
                    height: 92
                    color: root.gameActionIndex === 0 ? root.accent : "#b3121822"
                    border.width: root.gameActionIndex === 0 ? 2 : 1
                    border.color: root.gameActionIndex === 0 ? Qt.lighter(root.accent, 1.18) : "#42ffffff"
                    radius: 7

                    Text {
                        anchors.centerIn: parent
                        text: "RENAME"
                        color: root.gameActionIndex === 0 ? "#05070b" : "white"
                        font.family: global.fonts.sans
                        font.pixelSize: 26
                        font.weight: Font.Bold
                        font.letterSpacing: 1.2
                    }
                    MouseArea {
                        anchors.fill: parent
                        onClicked: { root.gameActionIndex = 0; root.beginRenameGame() }
                    }
                }

                Rectangle {
                    property int cheatsIndex: root.gameActionCheatsOptionIndex()
                    property bool offered: root.gameActionHasCheats()
                    x: 44
                    y: 254
                    width: parent.width - 88
                    height: 92
                    // Held in place rather than hidden while the answer is
                    // still in flight, so the options below it never move.
                    opacity: offered ? 1 : 0.45
                    color: root.gameActionIndex === cheatsIndex && offered ?
                               root.accent : "#b3121822"
                    border.width: root.gameActionIndex === cheatsIndex && offered ? 2 : 1
                    border.color: root.gameActionIndex === cheatsIndex && offered ?
                                      Qt.lighter(root.accent, 1.18) : "#42ffffff"
                    radius: 7

                    Text {
                        anchors.centerIn: parent
                        text: root.gameActionCheatsLabel()
                        color: root.gameActionIndex === parent.cheatsIndex && parent.offered ?
                                   "#05070b" : "white"
                        font.family: global.fonts.sans
                        font.pixelSize: 24
                        font.weight: Font.Bold
                        font.letterSpacing: 1.2
                    }
                    MouseArea {
                        anchors.fill: parent
                        enabled: parent.offered
                        onClicked: {
                            root.gameActionIndex = parent.cheatsIndex
                            root.openGameActionCheats()
                        }
                    }
                }

                Rectangle {
                    property int removeIndex: root.gameActionRemoveOptionIndex()
                    x: 44
                    y: 362
                    width: parent.width - 88
                    height: 92
                    visible: root.gameActionAllowsRemoveFromList()
                    color: root.gameActionIndex === removeIndex ? root.accent : "#b3121822"
                    border.width: root.gameActionIndex === removeIndex ? 2 : 1
                    border.color: root.gameActionIndex === removeIndex ? Qt.lighter(root.accent, 1.18) : "#42ffffff"
                    radius: 7

                    Text {
                        anchors.centerIn: parent
                        text: "REMOVE FROM " + root.homeShelfName(root.gameActionCategory)
                        color: root.gameActionIndex === parent.removeIndex ? "#05070b" : "white"
                        font.family: global.fonts.sans
                        font.pixelSize: 24
                        font.weight: Font.Bold
                        font.letterSpacing: 1.2
                    }
                    MouseArea {
                        anchors.fill: parent
                        onClicked: {
                            root.gameActionIndex = parent.removeIndex
                            root.gameActionMode = "confirm-remove"
                        }
                    }
                }

                Rectangle {
                    property int deleteIndex: root.gameActionDeleteOptionIndex()
                    x: 44
                    y: root.gameActionAllowsRemoveFromList() ? 470 : 362
                    width: parent.width - 88
                    height: 92
                    color: root.gameActionIndex === deleteIndex ? "#ff6d70" : "#b3121822"
                    border.width: root.gameActionIndex === deleteIndex ? 2 : 1
                    border.color: root.gameActionIndex === deleteIndex ? "#ff9b9d" : "#42ffffff"
                    radius: 7

                    Text {
                        anchors.centerIn: parent
                        text: "DELETE ROM FILE"
                        color: root.gameActionIndex === parent.deleteIndex ? "#120405" : "white"
                        font.family: global.fonts.sans
                        font.pixelSize: 24
                        font.weight: Font.Bold
                        font.letterSpacing: 1.2
                    }
                    MouseArea {
                        anchors.fill: parent
                        onClicked: {
                            root.gameActionIndex = parent.deleteIndex
                            root.gameActionMode = "confirm-delete"
                        }
                    }
                }

                Rectangle {
                    property int multiplayerIndex: root.gameActionMultiplayerOptionIndex()
                    x: 44
                    y: root.gameActionAllowsRemoveFromList() ? 578 : 470
                    width: parent.width - 88
                    height: 92
                    color: root.gameActionIndex === multiplayerIndex ? root.accent : "#b3121822"
                    border.width: root.gameActionIndex === multiplayerIndex ? 2 : 1
                    border.color: root.gameActionIndex === multiplayerIndex ? Qt.lighter(root.accent, 1.18) : "#42ffffff"
                    radius: 7

                    Text {
                        anchors.centerIn: parent
                        text: "MULTIPLAYER (ALPHA)"
                        color: root.gameActionIndex === parent.multiplayerIndex ? "#05070b" : "white"
                        font.family: global.fonts.sans
                        font.pixelSize: 24
                        font.weight: Font.Bold
                        font.letterSpacing: 1.2
                    }
                    MouseArea {
                        anchors.fill: parent
                        onClicked: {
                            root.gameActionIndex = parent.multiplayerIndex
                            root.openGameActionMultiplayer()
                        }
                    }
                }

                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: 758
                    text: "TAP AN OPTION  •  B TO CANCEL"
                    color: "#8e98aa"
                    font.family: global.fonts.sans
                    font.pixelSize: 15
                    font.letterSpacing: 1.4
                }
            }

            Item {
                anchors.fill: parent
                visible: root.gameActionMode === "cheats"

                ListView {
                    id: cheatList
                    x: 44
                    y: 146
                    width: parent.width - 88
                    // Five whole 76 px rows plus four 10 px gaps.
                    height: 420
                    clip: true
                    spacing: 10
                    // The delegate draws the selection from gameActionCheatIndex
                    // directly, so currentIndex exists only to scroll a row
                    // below the fold into view. It is assigned rather than
                    // bound because replacing the model after a toggle resets
                    // it, which would silently drop a binding.
                    model: root.gameActionCheats
                    onCurrentIndexChanged: positionViewAtIndex(currentIndex,
                                                               ListView.Contain)

                    delegate: Rectangle {
                        width: cheatList.width
                        height: 76
                        color: index === root.gameActionCheatIndex ? root.accent : "#b3121822"
                        border.width: index === root.gameActionCheatIndex ? 2 : 1
                        border.color: index === root.gameActionCheatIndex ?
                                          Qt.lighter(root.accent, 1.18) : "#42ffffff"
                        radius: 7

                        Text {
                            x: 22
                            anchors.verticalCenter: parent.verticalCenter
                            width: parent.width - 150
                            elide: Text.ElideRight
                            text: modelData.name
                            color: index === root.gameActionCheatIndex ? "#05070b" : "white"
                            font.family: global.fonts.sans
                            font.pixelSize: 24
                            font.weight: Font.Bold
                        }

                        Text {
                            anchors.right: parent.right
                            anchors.rightMargin: 22
                            anchors.verticalCenter: parent.verticalCenter
                            text: modelData.enabled ? "ON" : "OFF"
                            color: index === root.gameActionCheatIndex ? "#05070b" :
                                   modelData.enabled ? root.accent : "#8e98aa"
                            font.family: global.fonts.sans
                            font.pixelSize: 22
                            font.weight: Font.Bold
                            font.letterSpacing: 1.4
                        }

                        MouseArea {
                            anchors.fill: parent
                            onClicked: {
                                root.gameActionCheatIndex = index
                                root.toggleGameActionCheat(index)
                            }
                        }
                    }
                }

                Text {
                    x: 46
                    y: 580
                    width: parent.width - 92
                    height: 48
                    wrapMode: Text.Wrap
                    maximumLineCount: 2
                    elide: Text.ElideRight
                    text: root.gameActionCheatIndex < root.gameActionCheats.length &&
                          root.gameActionCheats[root.gameActionCheatIndex] ?
                              String(root.gameActionCheats[root.gameActionCheatIndex].description || "") : ""
                    color: "#c3cbd8"
                    font.family: global.fonts.sans
                    font.pixelSize: 18
                }

                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: 650
                    text: "A TOGGLES  •  B TO GO BACK  •  APPLIES ON LAUNCH"
                    color: "#8e98aa"
                    font.family: global.fonts.sans
                    font.pixelSize: 15
                    font.letterSpacing: 1.4
                }
            }

            Item {
                anchors.fill: parent
                visible: root.gameActionMode === "multiplayer"

                Rectangle {
                    id: multiplayerToggleRow
                    x: 44
                    y: 146
                    width: parent.width - 88
                    height: 92
                    opacity: root.gameActionMultiplayerPending ? 0.6 : 1
                    color: root.gameActionMultiplayerWant ? root.accent : "#b3121822"
                    border.width: root.gameActionMultiplayerWant ? 2 : 1
                    border.color: root.gameActionMultiplayerWant ?
                                      Qt.lighter(root.accent, 1.18) : "#42ffffff"
                    radius: 7

                    Text {
                        x: 22
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width - 150
                        elide: Text.ElideRight
                        text: "AVAILABLE FOR MULTIPLAYER (ALPHA)"
                        color: root.gameActionMultiplayerWant ? "#05070b" : "white"
                        font.family: global.fonts.sans
                        font.pixelSize: 22
                        font.weight: Font.Bold
                        font.letterSpacing: 1.1
                    }

                    Text {
                        anchors.right: parent.right
                        anchors.rightMargin: 22
                        anchors.verticalCenter: parent.verticalCenter
                        text: root.gameActionMultiplayerPending ? "…" :
                              (root.gameActionMultiplayerWant ? "ON" : "OFF")
                        color: root.gameActionMultiplayerWant ? "#05070b" : root.accent
                        font.family: global.fonts.sans
                        font.pixelSize: 22
                        font.weight: Font.Bold
                        font.letterSpacing: 1.4
                    }

                    MouseArea {
                        anchors.fill: parent
                        enabled: !root.gameActionMultiplayerPending
                        onClicked: root.setGameActionMultiplayerWant(!root.gameActionMultiplayerWant)
                    }
                }

                Text {
                    x: 46
                    y: 258
                    text: "WHO ELSE WANTS TO PLAY"
                    color: root.accent
                    font.family: global.fonts.sans
                    font.pixelSize: 15
                    font.weight: Font.Bold
                    font.letterSpacing: 2
                }

                ListView {
                    id: multiplayerRosterList
                    x: 44
                    y: 292
                    width: parent.width - 88
                    height: 420
                    clip: true
                    spacing: 10
                    // Pre-sorted by the endpoint itself (wants above wanted) --
                    // rendered in the order the roster answer already gives.
                    model: root.gameActionMultiplayerRoster

                    delegate: Rectangle {
                        width: multiplayerRosterList.width
                        height: 76
                        color: "#b3121822"
                        border.width: 1
                        border.color: "#42ffffff"
                        radius: 7

                        Text {
                            x: 22
                            anchors.verticalCenter: parent.verticalCenter
                            width: parent.width - 220
                            elide: Text.ElideRight
                            text: String(modelData.nickname || "UNKNOWN PLAYER")
                            color: "white"
                            font.family: global.fonts.sans
                            font.pixelSize: 22
                            font.weight: Font.Bold
                        }

                        Text {
                            anchors.right: parent.right
                            anchors.rightMargin: 22
                            anchors.verticalCenter: parent.verticalCenter
                            text: modelData.state === "wants" ? "WANTS" :
                                  modelData.state === "wanted" ? "WANTED" :
                                      String(modelData.state || "")
                            color: modelData.state === "wants" ? root.accent : "#8e98aa"
                            font.family: global.fonts.sans
                            font.pixelSize: 20
                            font.weight: Font.Bold
                            font.letterSpacing: 1.2
                        }
                    }

                    Text {
                        anchors.centerIn: parent
                        visible: multiplayerRosterList.count === 0
                        text: root.gameActionMultiplayerState === "loading" ? "CHECKING…" :
                              root.gameActionMultiplayerState === "error" ? "ROSTER UNAVAILABLE" :
                                  "NO ONE ELSE HAS SIGNALED YET"
                        color: "#8e98aa"
                        font.family: global.fonts.sans
                        font.pixelSize: 18
                    }
                }

                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: 758
                    text: "A TOGGLES AVAILABILITY  •  B TO GO BACK  •  2-PLAYER ONLY FOR NOW"
                    color: "#8e98aa"
                    font.family: global.fonts.sans
                    font.pixelSize: 15
                    font.letterSpacing: 1.4
                }
            }

            Item {
                anchors.fill: parent
                visible: root.gameActionMode === "confirm-remove"

                Text {
                    x: 54
                    y: 190
                    width: parent.width - 108
                    text: "Hide this game from " + root.homeShelfName(root.gameActionCategory) +
                          " only? The ROM file and complete library entries will remain untouched."
                    color: "#e9edf4"
                    wrapMode: Text.Wrap
                    horizontalAlignment: Text.AlignHCenter
                    font.family: global.fonts.sans
                    font.pixelSize: 25
                }

                Row {
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: 400
                    spacing: 20
                    Rectangle {
                        width: 330; height: 82; color: "#b3121822"; border.width: 1
                        border.color: "#52ffffff"; radius: 7
                        Text { anchors.centerIn: parent; text: "CANCEL"; color: "white"; font.pixelSize: 23; font.bold: true }
                        MouseArea { anchors.fill: parent; onClicked: root.gameActionMode = "menu" }
                    }
                    Rectangle {
                        width: 330; height: 82; color: root.accent; radius: 7
                        Text { anchors.centerIn: parent; text: "REMOVE FROM LIST"; color: "#05070b"; font.pixelSize: 22; font.bold: true }
                        MouseArea { anchors.fill: parent; onClicked: root.submitRemoveFromList() }
                    }
                }
            }

            Item {
                anchors.fill: parent
                visible: root.gameActionMode === "rename"

                Rectangle {
                    x: 44
                    y: 196
                    width: parent.width - 88
                    height: 80
                    color: "#d9080c13"
                    border.width: 2
                    border.color: root.accent
                    radius: 7

                    TextInput {
                        id: renameField
                        anchors.fill: parent
                        anchors.leftMargin: 22
                        anchors.rightMargin: 22
                        verticalAlignment: TextInput.AlignVCenter
                        color: "white"
                        selectionColor: root.accent
                        selectedTextColor: "#05070b"
                        font.family: global.fonts.sans
                        font.pixelSize: 25
                        selectByMouse: true
                        inputMethodHints: Qt.ImhNoPredictiveText
                        onAccepted: root.submitRenameGame()
                    }
                }

                Rectangle {
                    x: 44
                    y: 324
                    width: parent.width - 88
                    height: 92
                    color: root.accent
                    radius: 7
                    Text {
                        anchors.centerIn: parent
                        text: "SAVE NAME"
                        color: "#05070b"
                        font.family: global.fonts.sans
                        font.pixelSize: 24
                        font.weight: Font.Bold
                    }
                    MouseArea { anchors.fill: parent; onClicked: root.submitRenameGame() }
                }
            }

            Item {
                anchors.fill: parent
                visible: root.gameActionMode === "confirm-delete"

                Text {
                    x: 54
                    y: 190
                    width: parent.width - 108
                    text: "Permanently delete the actual ROM/game file from device storage and remove it from EmuFusion? This cannot be undone."
                    color: "#e9edf4"
                    wrapMode: Text.Wrap
                    horizontalAlignment: Text.AlignHCenter
                    font.family: global.fonts.sans
                    font.pixelSize: 25
                }

                Row {
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: 400
                    spacing: 20
                    Rectangle {
                        width: 330; height: 82; color: "#b3121822"; border.width: 1
                        border.color: "#52ffffff"; radius: 7
                        Text { anchors.centerIn: parent; text: "CANCEL"; color: "white"; font.pixelSize: 23; font.bold: true }
                        MouseArea { anchors.fill: parent; onClicked: root.gameActionMode = "menu" }
                    }
                    Rectangle {
                        width: 330; height: 82; color: "#ff6d70"; radius: 7
                        Text { anchors.centerIn: parent; text: "DELETE GAME"; color: "#150405"; font.pixelSize: 23; font.bold: true }
                        MouseArea { anchors.fill: parent; onClicked: root.submitDeleteGame() }
                    }
                }
            }

            Item {
                anchors.fill: parent
                visible: root.gameActionMode === "working" ||
                         root.gameActionMode === "success" || root.gameActionMode === "error"
                Text {
                    anchors.centerIn: parent
                    width: parent.width - 110
                    text: root.gameActionMessage
                    color: root.gameActionMode === "error" ? "#ff8588" : root.accent
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    font.family: global.fonts.condensed
                    font.pixelSize: 34
                    font.weight: Font.Bold
                }
                MouseArea {
                    anchors.fill: parent
                    enabled: root.gameActionMode !== "working"
                    onClicked: root.closeGameActions()
                }
            }
        }
    }

    Rectangle {
        id: settingsOverlay
        z: 500
        anchors.fill: parent
        visible: root.settingsOpen
        color: "#e905080d"

        // Four explicit dismissal zones avoid Qt's full-screen mouse catcher
        // competing with the modal and its row controls on touch devices.
        Item {
            z: 1
            anchors.fill: parent

            MouseArea {
                x: 0; y: 0
                width: parent.width; height: settingsPanel.y
                onClicked: { root.settingsOpen = false; root.forceActiveFocus() }
            }
            MouseArea {
                x: 0; y: settingsPanel.y + settingsPanel.height
                width: parent.width; height: parent.height - y
                onClicked: { root.settingsOpen = false; root.forceActiveFocus() }
            }
            MouseArea {
                x: 0; y: settingsPanel.y
                width: settingsPanel.x; height: settingsPanel.height
                onClicked: { root.settingsOpen = false; root.forceActiveFocus() }
            }
            MouseArea {
                x: settingsPanel.x + settingsPanel.width; y: settingsPanel.y
                width: parent.width - x; height: settingsPanel.height
                onClicked: { root.settingsOpen = false; root.forceActiveFocus() }
            }
        }

        Rectangle {
            id: settingsPanel
            z: 2
            anchors.centerIn: parent
            width: 980
            // Grows with the panel: the extra height buys taller rows, which
            // on a handheld means larger touch targets, not more of them --
            // the page size is what keeps every row spacious.
            height: root.height - 80
            color: "#f20d121a"
            border.width: 1
            border.color: root.accent
            radius: 8

            // Consume taps inside the modal itself. Individual setting rows,
            // declared later, remain above this catcher and keep their own
            // actions; only the dimmed area outside dismisses the sheet.
            MouseArea { anchors.fill: parent }

            Text {
                x: 48
                y: 38
                text: "DISPLAY, LIBRARY & LIGHTING"
                color: "white"
                font.family: global.fonts.condensed
                font.pixelSize: 42
                font.weight: Font.Bold
                font.letterSpacing: 2
            }

            Text {
                x: 50
                y: 94
                text: "EMUFUSION " + root.lucentVersion +
                      "  •  Display changes apply instantly; updates run automatically at startup"
                color: "#9da7b8"
                font.family: global.fonts.sans
                font.pixelSize: 17
            }

            // Keep the legacy row declarations inert for source compatibility;
            // the compact settings sheet below is the active settings UI.
            Item {
                visible: false
                anchors.fill: parent

            Rectangle {
                x: 44
                y: 150
                width: parent.width - 88
                height: 112
                color: root.settingsIndex === 0 ? "#261f2a38" : "#9b111720"
                border.width: root.settingsIndex === 0 ? 2 : 1
                border.color: root.settingsIndex === 0 ? root.accent : "#30ffffff"
                radius: 5

                Text {
                    x: 28
                    y: 22
                    text: "SYSTEM WALLPAPER MODE"
                    color: "white"
                    font.family: global.fonts.sans
                    font.pixelSize: 21
                    font.weight: Font.Bold
                    font.letterSpacing: 1
                }
                Text {
                    x: 28
                    y: 60
                    text: "Preloaded static angle; rerolls only after you leave"
                    color: "#9da7b8"
                    font.family: global.fonts.sans
                    font.pixelSize: 16
                }
                Text {
                    anchors.right: parent.right
                    anchors.rightMargin: 28
                    anchors.verticalCenter: parent.verticalCenter
                    text: "STATIC"
                    color: root.accent
                    font.family: global.fonts.condensed
                    font.pixelSize: 30
                    font.weight: Font.Bold
                }
                MouseArea {
                    anchors.fill: parent
                    onClicked: { root.settingsIndex = 0; root.activateSetting(0) }
                }
            }

            Rectangle {
                x: 44
                y: 278
                width: parent.width - 88
                height: 112
                color: root.settingsIndex === 1 ? "#261f2a38" : "#9b111720"
                border.width: root.settingsIndex === 1 ? 2 : 1
                border.color: root.settingsIndex === 1 ? root.accent : "#30ffffff"
                radius: 5

                Text {
                    x: 28
                    y: 22
                    text: "GAME PREVIEW PLACEMENT"
                    color: "white"
                    font.family: global.fonts.sans
                    font.pixelSize: 21
                    font.weight: Font.Bold
                    font.letterSpacing: 1
                }
                Text {
                    x: 28
                    y: 60
                    text: "Automatic detects the screen count; choose PIP or Off manually"
                    color: "#9da7b8"
                    font.family: global.fonts.sans
                    font.pixelSize: 16
                }
                Text {
                    anchors.right: parent.right
                    anchors.rightMargin: 28
                    anchors.verticalCenter: parent.verticalCenter
                    text: root.previewPlacementLabel()
                    color: root.accent
                    font.family: global.fonts.condensed
                    font.pixelSize: 30
                    font.weight: Font.Bold
                }
                MouseArea {
                    anchors.fill: parent
                    onClicked: { root.settingsIndex = 1; root.activateSetting(1) }
                }
            }

            Rectangle {
                x: 44
                y: 406
                width: parent.width - 88
                height: 112
                color: root.settingsIndex === 2 ? "#261f2a38" : "#9b111720"
                border.width: root.settingsIndex === 2 ? 2 : 1
                border.color: root.settingsIndex === 2 ? root.accent : "#30ffffff"
                radius: 5

                Text {
                    x: 28
                    y: 22
                    text: "PREVIEW VIDEO SOUND"
                    color: "white"
                    font.family: global.fonts.sans
                    font.pixelSize: 21
                    font.weight: Font.Bold
                    font.letterSpacing: 1
                }
                Text {
                    x: 28
                    y: 60
                    text: "Sound follows the visible preview; preloaded neighbors stay silent"
                    color: "#9da7b8"
                    font.family: global.fonts.sans
                    font.pixelSize: 16
                }
                Text {
                    anchors.right: parent.right
                    anchors.rightMargin: 28
                    anchors.verticalCenter: parent.verticalCenter
                    text: root.previewSoundEnabled ? "ON" : "OFF"
                    color: root.accent
                    font.family: global.fonts.condensed
                    font.pixelSize: 30
                    font.weight: Font.Bold
                }
                MouseArea {
                    anchors.fill: parent
                    onClicked: { root.settingsIndex = 2; root.activateSetting(0) }
                }
            }

            Rectangle {
                x: 44
                y: 534
                width: parent.width - 88
                height: 112
                color: root.settingsIndex === 3 ? "#261f2a38" : "#9b111720"
                border.width: root.settingsIndex === 3 ? 2 : 1
                border.color: root.settingsIndex === 3 ? root.accent : "#30ffffff"
                radius: 5

                Text {
                    x: 28
                    y: 22
                    text: "LIQUID GLASS"
                    color: "white"
                    font.family: global.fonts.sans
                    font.pixelSize: 21
                    font.weight: Font.Bold
                    font.letterSpacing: 1
                }
                Text {
                    x: 28
                    y: 60
                    text: "Optional refractive blur and wallpaper distortion for controls"
                    color: "#9da7b8"
                    font.family: global.fonts.sans
                    font.pixelSize: 16
                }
                Text {
                    anchors.right: parent.right
                    anchors.rightMargin: 28
                    anchors.verticalCenter: parent.verticalCenter
                    text: root.liquidGlassEnabled ? "ON" : "OFF"
                    color: root.accent
                    font.family: global.fonts.condensed
                    font.pixelSize: 30
                    font.weight: Font.Bold
                }
                MouseArea {
                    anchors.fill: parent
                    onClicked: { root.settingsIndex = 3; root.activateSetting(0) }
                }
            }

            Rectangle {
                x: 44
                y: 662
                width: parent.width - 88
                height: 112
                color: root.settingsIndex === 4 ? "#261f2a38" : "#9b111720"
                border.width: root.settingsIndex === 4 ? 2 : 1
                border.color: root.settingsIndex === 4 ? root.accent : "#30ffffff"
                radius: 5

                Text {
                    x: 28
                    y: 22
                    text: "SYSTEM-MATCHED STICK LEDS"
                    color: "white"
                    font.family: global.fonts.sans
                    font.pixelSize: 21
                    font.weight: Font.Bold
                    font.letterSpacing: 1
                }
                Text {
                    x: 28
                    y: 60
                    text: "Uses AYN brightness by default; left / right selects manual 1–100%"
                    color: "#9da7b8"
                    font.family: global.fonts.sans
                    font.pixelSize: 16
                }

                Rectangle {
                    anchors.right: ledBrightnessValue.left
                    anchors.rightMargin: 12
                    anchors.verticalCenter: parent.verticalCenter
                    width: 48
                    height: 48
                    color: "#221f2a38"
                    border.width: 1
                    border.color: "#45ffffff"
                    radius: 24

                    Text {
                        anchors.centerIn: parent
                        text: "−"
                        color: "white"
                        font.family: global.fonts.sans
                        font.pixelSize: 27
                        font.weight: Font.Bold
                    }
                    MouseArea {
                        anchors.fill: parent
                        onClicked: {
                            root.settingsIndex = 4
                            var base = root.systemLedUseDeviceBrightness ? 2 :
                                       root.systemLedBrightness
                            root.setSystemLedBrightness(base - 1)
                        }
                    }
                }

                Text {
                    id: ledBrightnessValue
                    anchors.right: ledBrightnessPlus.left
                    anchors.rightMargin: 12
                    anchors.verticalCenter: parent.verticalCenter
                    width: 124
                    horizontalAlignment: Text.AlignHCenter
                    text: !root.systemLedEnabled ? "OFF" :
                          (root.systemLedUseDeviceBrightness ? "ON  SYSTEM" :
                           "ON  " + root.systemLedBrightness + "%")
                    color: root.accent
                    font.family: global.fonts.condensed
                    font.pixelSize: 27
                    font.weight: Font.Bold
                    MouseArea {
                        anchors.fill: parent
                        onClicked: {
                            root.settingsIndex = 4
                            root.setSystemLedUseDeviceBrightness(true)
                        }
                    }
                }

                Rectangle {
                    id: ledBrightnessPlus
                    anchors.right: parent.right
                    anchors.rightMargin: 24
                    anchors.verticalCenter: parent.verticalCenter
                    width: 48
                    height: 48
                    color: "#221f2a38"
                    border.width: 1
                    border.color: "#45ffffff"
                    radius: 24

                    Text {
                        anchors.centerIn: parent
                        text: "+"
                        color: "white"
                        font.family: global.fonts.sans
                        font.pixelSize: 27
                        font.weight: Font.Bold
                    }
                    MouseArea {
                        anchors.fill: parent
                        onClicked: {
                            root.settingsIndex = 4
                            var base = root.systemLedUseDeviceBrightness ? 9 :
                                       root.systemLedBrightness
                            root.setSystemLedBrightness(base + 1)
                        }
                    }
                }
                MouseArea {
                    x: 0
                    y: 0
                    width: parent.width - 270
                    height: parent.height
                    onClicked: { root.settingsIndex = 4; root.activateSetting(0) }
                }
            }

            Rectangle {
                x: 44
                y: 790
                width: parent.width - 88
                height: 112
                color: root.settingsIndex === 5 ? "#261f2a38" : "#9b111720"
                border.width: root.settingsIndex === 5 ? 2 : 1
                border.color: root.settingsIndex === 5 ? root.accent : "#30ffffff"
                radius: 5

                Text {
                    x: 28
                    y: 22
                    text: "UPDATE LIBRARY & EMUFUSION"
                    color: "white"
                    font.family: global.fonts.sans
                    font.pixelSize: 21
                    font.weight: Font.Bold
                    font.letterSpacing: 1
                }
                Text {
                    x: 28
                    y: 60
                    text: "Scan games and check GitHub for app and theme updates"
                    color: "#9da7b8"
                    font.family: global.fonts.sans
                    font.pixelSize: 16
                }
                Text {
                    anchors.right: parent.right
                    anchors.rightMargin: 28
                    anchors.verticalCenter: parent.verticalCenter
                    text: "RUN"
                    color: root.accent
                    font.family: global.fonts.condensed
                    font.pixelSize: 30
                    font.weight: Font.Bold
                }
                MouseArea {
                    anchors.fill: parent
                    onClicked: { root.settingsIndex = 5; root.activateSetting(0) }
                }
            }

            }

            Text {
                anchors.right: parent.right
                anchors.rightMargin: 48
                y: 44
                text: "PAGE " + (root.settingsPage + 1) + " / " +
                      Math.ceil(root.settingsOptionCount / root.settingsPageSize)
                color: root.accent
                font.family: global.fonts.sans
                font.pixelSize: 16
                font.weight: Font.Bold
                font.letterSpacing: 1.2
            }

            Repeater {
                // As many spacious rows as the panel actually holds. Up/Down
                // crosses page boundaries automatically, so touch and
                // controller users get one unified settings surface without
                // compressed text or tiny targets. The count and the stride
                // both come from the shared list helpers, so the reclaimed
                // height became another row rather than a band under the last.
                model: root.settingsPageSize

                Rectangle {
                    property int setting: root.settingsPage * root.settingsPageSize + index
                    visible: setting < root.settingsOptionCount
                    x: 44
                    y: root.settingsListTop +
                       index * (root.settingsRowHeight + root.settingsListSpacing)
                    width: settingsPanel.width - 88
                    height: root.settingsRowHeight
                    color: root.settingsIndex === setting ? "#261f2a38" : "#9b111720"
                    border.width: root.settingsIndex === setting ? 2 : 1
                    border.color: root.settingsIndex === setting ? root.accent : "#30ffffff"
                    radius: 7

                    // The title and its description are centred as a pair, so a
                    // row that grows or shrinks with the panel keeps them
                    // optically centred instead of pinned to the top edge.
                    Text {
                        x: 24
                        y: Math.round((parent.height - 62) / 2)
                        text: root.settingTitle(parent.setting)
                        color: "white"
                        font.family: global.fonts.sans
                        font.pixelSize: 21
                        font.weight: Font.Bold
                        font.letterSpacing: 0.9
                    }

                    Text {
                        x: 24
                        y: Math.round((parent.height - 62) / 2) + 42
                        width: parent.width - 370
                        text: root.settingDescription(parent.setting)
                        color: "#a7b0c1"
                        elide: Text.ElideRight
                        font.family: global.fonts.sans
                        font.pixelSize: 16
                    }

                    Text {
                        anchors.right: parent.right
                        anchors.rightMargin: parent.setting === 7 ? 92 : 24
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.setting === 8 ? 340 : 286
                        horizontalAlignment: Text.AlignRight
                        text: root.settingValue(parent.setting)
                        color: root.accent
                        elide: Text.ElideRight
                        font.family: global.fonts.condensed
                        font.pixelSize: parent.setting === 8 ? 25 : 29
                        font.weight: Font.Bold
                    }

                    Rectangle {
                        visible: parent.setting === 7
                        anchors.right: parent.right
                        anchors.rightMargin: 24
                        anchors.verticalCenter: parent.verticalCenter
                        width: 48
                        height: 48
                        radius: 24
                        color: "#221f2a38"
                        border.width: 1
                        border.color: "#45ffffff"
                        Text { anchors.centerIn: parent; text: "+"; color: "white";
                               font.pixelSize: 27; font.bold: true }
                        MouseArea {
                            anchors.fill: parent
                            onClicked: {
                                root.settingsIndex = 7
                                root.setSystemLedBrightness(root.systemLedBrightness + 1)
                            }
                        }
                    }

                    Rectangle {
                        visible: parent.setting === 7
                        anchors.right: parent.right
                        anchors.rightMargin: 184
                        anchors.verticalCenter: parent.verticalCenter
                        width: 48
                        height: 48
                        radius: 24
                        color: "#221f2a38"
                        border.width: 1
                        border.color: "#45ffffff"
                        Text { anchors.centerIn: parent; text: "−"; color: "white";
                               font.pixelSize: 27; font.bold: true }
                        MouseArea {
                            anchors.fill: parent
                            onClicked: {
                                root.settingsIndex = 7
                                root.setSystemLedBrightness(root.systemLedBrightness - 1)
                            }
                        }
                    }

                    MouseArea {
                        x: 0
                        y: 0
                        width: parent.setting === 7 ? parent.width - 244 : parent.width
                        height: parent.height
                        onClicked: {
                            root.settingsIndex = parent.setting
                            root.activateSetting(0)
                        }
                    }
                }
            }

            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                y: parent.height - root.footerLineHeight - 24
                text: "UP / DOWN  SELECT & PAGE     LEFT / RIGHT  CHANGE     B  CLOSE"
                color: "#7f899c"
                font.family: global.fonts.sans
                font.pixelSize: root.footerFontSize
                font.letterSpacing: 1
            }
        }
    }

    Rectangle {
        id: coverOrderEditorOverlay
        z: 815
        anchors.fill: parent
        visible: root.coverOrderEditorOpen
        color: "#e905080d"

        MouseArea { anchors.fill: parent }

        Rectangle {
            anchors.centerIn: parent
            width: 820
            height: 820
            color: "#f20d121a"
            border.width: 1
            border.color: root.accent
            radius: 8

            Text {
                x: 44; y: 34
                text: "COVER ROW ORDER"
                color: "white"
                font.family: global.fonts.condensed
                font.pixelSize: 40
                font.weight: Font.Bold
                font.letterSpacing: 2
            }

            Text {
                x: 46; y: 86
                text: "UP / DOWN SELECT  •  LEFT / RIGHT MOVE"
                color: "#9da7b8"
                font.family: global.fonts.sans
                font.pixelSize: 15
                font.letterSpacing: 1.3
            }

            Repeater {
                model: 8

                Rectangle {
                    property int orderZone: Number(root.coverRowOrder[index])
                    x: 42
                    y: 126 + index * 78
                    width: 736
                    height: 66
                    color: root.coverOrderEditorIndex === index ?
                           Qt.darker(root.accent, 3.6) : "#9b111720"
                    border.width: root.coverOrderEditorIndex === index ? 3 : 1
                    border.color: root.coverOrderEditorIndex === index ?
                                  root.accent : "#30ffffff"
                    radius: 5

                    Text {
                        x: 20
                        anchors.verticalCenter: parent.verticalCenter
                        text: (index < 9 ? "0" : "") + String(index + 1)
                        color: root.accent
                        font.family: global.fonts.condensed
                        font.pixelSize: 23
                        font.weight: Font.Bold
                    }

                    Text {
                        x: 82
                        anchors.verticalCenter: parent.verticalCenter
                        text: root.coverRowName(parent.orderZone)
                        color: "white"
                        font.family: global.fonts.sans
                        font.pixelSize: 21
                        font.weight: Font.Bold
                    }

                    Text {
                        anchors.right: parent.right
                        anchors.rightMargin: 22
                        anchors.verticalCenter: parent.verticalCenter
                        text: "←  MOVE  →"
                        color: root.coverOrderEditorIndex === index ?
                               "white" : "#778196"
                        font.family: global.fonts.sans
                        font.pixelSize: 16
                        font.weight: Font.DemiBold
                        font.letterSpacing: 1
                    }

                    MouseArea {
                        anchors.fill: parent
                        onClicked: root.coverOrderEditorIndex = index
                    }
                }
            }

            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                y: 770
                text: "B  BACK TO SETTINGS"
                color: "#7f899c"
                font.family: global.fonts.sans
                font.pixelSize: 15
                font.letterSpacing: 1
            }
        }
    }

    // ---- Games with no box art --------------------------------------------
    // One row per game the companion could find no artwork for, and three
    // answers per row. The answer is sent once and remembered on the device,
    // so a game only ever appears here until it is answered for.
    Rectangle {
        id: artworkReviewOverlay
        z: 818
        anchors.fill: parent
        visible: root.artworkReviewOpen
        color: "#ec05080d"

        MouseArea { anchors.fill: parent }

        Text {
            x: root.screenMargin
            y: 58
            text: "GAMES WITH NO BOX ART"
            color: "white"
            font.family: global.fonts.condensed
            font.pixelSize: 46
            font.weight: Font.Bold
            font.letterSpacing: 2
        }

        Text {
            x: root.screenMargin
            y: 118
            width: root.width - root.screenMargin * 2
            text: root.artworkReviewGames.length === 0 ?
                  "Every game in your library has box art. Nothing to decide." :
                  "No catalog on any platform has a cover for these. Choose once " +
                  "per game — your answer is remembered and you will not be asked again."
            color: "#9da7b8"
            wrapMode: Text.Wrap
            font.family: global.fonts.sans
            font.pixelSize: 18
            font.letterSpacing: 0.6
        }

        ListView {
            id: artworkReviewList
            x: root.screenMargin
            y: 178
            width: root.width - root.screenMargin * 2
            property real rowSpacing: 10
            // Same contract as every other list in EmuFusion: the row count and
            // the stride are decided together from the space available, so the
            // last row lands on the content floor instead of leaving a band.
            property real rowHeight: root.listRowHeight(
                    root.contentBottom - y, 108, 146, rowSpacing)
            height: root.listRowCount(root.contentBottom - y, 108, rowSpacing) *
                    (rowHeight + rowSpacing) - rowSpacing
            spacing: rowSpacing
            clip: true
            model: root.artworkReviewGames
            currentIndex: root.artworkReviewIndex
            boundsBehavior: Flickable.StopAtBounds
            snapMode: ListView.SnapToItem
            highlightMoveDuration: 110
            highlightRangeMode: ListView.ApplyRange
            preferredHighlightBegin: rowHeight + rowSpacing
            preferredHighlightEnd: rowHeight + rowSpacing
            keyNavigationEnabled: false
            focus: false

            delegate: Rectangle {
                id: artworkReviewRow
                // The choice Repeater below has an index of its own, so the
                // row's own index is named here rather than reached for from
                // inside it.
                property int rowIndex: index
                property bool isSelected: rowIndex === root.artworkReviewIndex
                width: ListView.view.width
                height: ListView.view.rowHeight
                color: isSelected ? Qt.darker(root.accent, 4.2) : "#9b111720"
                border.width: isSelected ? 3 : 1
                border.color: isSelected ? root.accent : "#30ffffff"
                radius: 6

                Text {
                    id: artworkReviewTitle
                    x: 22
                    y: 14
                    width: parent.width - 44
                    text: String(modelData.title || "")
                    color: "white"
                    elide: Text.ElideRight
                    font.family: global.fonts.sans
                    font.pixelSize: 24
                    font.weight: Font.Bold
                }

                Text {
                    x: 22
                    y: artworkReviewTitle.y + 30
                    width: parent.width - 44
                    text: String(modelData.collection || modelData.system || "") + "   •   " +
                          String(modelData.romName || "") + "   •   " +
                          String(modelData.note || "")
                    color: "#8e98aa"
                    elide: Text.ElideRight
                    font.family: global.fonts.sans
                    font.pixelSize: 15
                }

                Row {
                    x: 22
                    y: artworkReviewRow.height - 40
                    spacing: 10
                    visible: artworkReviewRow.isSelected

                    Repeater {
                        model: 3

                        Rectangle {
                            id: choicePill
                            property int choice: index
                            property bool active: choice === root.artworkReviewChoice
                            property bool destructive: choice === 2
                            // Only the destructive answer is ever red, and it
                            // is red whether or not it is the selected one, so
                            // the option that erases a file is never a surprise.
                            readonly property color danger: "#ff5964"
                            width: choiceLabel.implicitWidth + 30
                            height: 30
                            radius: 4
                            color: active ? (destructive ? danger : root.accent) : "transparent"
                            border.width: active ? 0 : 1
                            border.color: destructive ? danger : "#4dffffff"

                            Text {
                                id: choiceLabel
                                anchors.centerIn: parent
                                text: root.artworkReviewChoiceLabel(choicePill.choice)
                                color: choicePill.active ? "#0a0d14" :
                                       (choicePill.destructive ? choicePill.danger : "#c3ccdb")
                                font.family: global.fonts.sans
                                font.pixelSize: 14
                                font.weight: Font.Bold
                                font.letterSpacing: 1
                            }

                            MouseArea {
                                anchors.fill: parent
                                onClicked: {
                                    root.artworkReviewIndex = artworkReviewRow.rowIndex
                                    root.artworkReviewChoice = choicePill.choice
                                    root.artworkReviewConfirming = false
                                }
                            }
                        }
                    }
                }

                MouseArea {
                    anchors.fill: parent
                    z: -1
                    onClicked: {
                        root.artworkReviewIndex = artworkReviewRow.rowIndex
                        root.artworkReviewChoice = 0
                        root.artworkReviewConfirming = false
                    }
                }
            }
        }

        Text {
            x: root.screenMargin
            y: root.contentBottom + 6
            width: root.width - root.screenMargin * 2
            text: root.artworkReviewBusy ? root.artworkReviewMessage :
                  (root.artworkReviewConfirming ? root.artworkReviewMessage :
                   (root.artworkReviewMessage !== "" ? root.artworkReviewMessage :
                    root.artworkReviewChoiceDetail(root.artworkReviewChoice)))
            color: root.artworkReviewConfirming ? "#ff5964" :
                   (root.artworkReviewChoice === 2 ? "#ff9aa2" : "#9da7b8")
            elide: Text.ElideRight
            font.family: global.fonts.sans
            font.pixelSize: 17
            font.weight: root.artworkReviewConfirming ? Font.Bold : Font.Normal
        }

        Text {
            x: root.screenMargin
            y: root.footerY
            text: "UP / DOWN GAME   •   LEFT / RIGHT CHOICE   •   A CONFIRM   •   B BACK"
            color: "#7f899c"
            font.family: global.fonts.sans
            font.pixelSize: root.footerFontSize
            font.letterSpacing: 1
        }
    }

    Rectangle {
        id: accentEditorOverlay
        z: 820
        anchors.fill: parent
        visible: root.accentEditorOpen
        color: "#e805080d"

        MouseArea { anchors.fill: parent }

        Rectangle {
            anchors.centerIn: parent
            width: 900
            height: 630
            color: "#fa0d121a"
            border.width: 2
            border.color: root.accentEditorColor()
            radius: 10

            Text {
                x: 48; y: 36
                text: "CUSTOM ACCENT COLORS"
                color: "white"
                font.family: global.fonts.condensed
                font.pixelSize: 40
                font.weight: Font.Bold
                font.letterSpacing: 2
            }
            Text {
                x: 50; y: 88
                text: root.accentGrouping === "wallpaper" ?
                      "Games use their wallpaper complement; edit the system fallback" :
                      (root.accentGrouping === "system" ?
                       "Each installed system keeps its own color" :
                       "Systems share the color assigned to their platform family")
                color: "#9da7b8"
                font.family: global.fonts.sans
                font.pixelSize: 17
            }

            Rectangle {
                x: 596; y: 132; width: 248; height: 248
                color: root.accentEditorColor()
                radius: 124
                border.width: 4
                border.color: "#c8ffffff"
            }

            Repeater {
                model: 4
                Rectangle {
                    property int channel: index
                    x: 48
                    y: 132 + index * 92
                    width: 500
                    height: 72
                    color: root.accentEditorChannel === channel ?
                           "#323d4656" : "#8c111720"
                    border.width: root.accentEditorChannel === channel ? 2 : 1
                    border.color: root.accentEditorChannel === channel ?
                                  root.accentEditorColor() : "#30ffffff"
                    radius: 6

                    Text {
                        x: 22
                        anchors.verticalCenter: parent.verticalCenter
                        text: ["TARGET", "HUE", "SATURATION", "LIGHTNESS"][parent.channel]
                        color: "#aeb6c8"
                        font.family: global.fonts.sans
                        font.pixelSize: 17
                        font.weight: Font.Bold
                        font.letterSpacing: 1.2
                    }
                    Text {
                        anchors.right: parent.right
                        anchors.rightMargin: 22
                        anchors.verticalCenter: parent.verticalCenter
                        width: 300
                        horizontalAlignment: Text.AlignRight
                        text: {
                            var targets = root.accentTargets()
                            if (parent.channel === 0)
                                return targets.length ? root.accentTargetLabel(
                                        targets[root.accentEditorTargetIndex]) : "NO SYSTEMS"
                            if (parent.channel === 1)
                                return Math.round(root.accentEditorHue * 360) + "°"
                            if (parent.channel === 2)
                                return Math.round(root.accentEditorSaturation * 100) + "%"
                            return Math.round(root.accentEditorLightness * 100) + "%"
                        }
                        color: root.accentEditorColor()
                        font.family: global.fonts.condensed
                        font.pixelSize: 25
                        fontSizeMode: Text.Fit
                        minimumPixelSize: 14
                        font.weight: Font.Bold
                        elide: Text.ElideNone
                    }
                    MouseArea {
                        anchors.fill: parent
                        onClicked: root.accentEditorChannel = parent.channel
                    }
                }
            }

            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                y: 550
                text: "UP / DOWN  FIELD     LEFT / RIGHT  ADJUST     Y  RESET     A  SAVE     B  CLOSE"
                color: "#8f99aa"
                font.family: global.fonts.sans
                font.pixelSize: 14
                font.letterSpacing: 1
            }
        }
    }

    Rectangle {
        id: aboutOverlay
        z: 830
        anchors.fill: parent
        visible: root.aboutOpen
        color: "#e805080d"

        MouseArea {
            anchors.fill: parent
            onClicked: { root.aboutOpen = false; root.forceActiveFocus() }
        }

        Rectangle {
            anchors.centerIn: parent
            width: 980
            height: 650
            color: "#fa0d121a"
            border.width: 2
            border.color: root.accent
            radius: 10

            MouseArea { anchors.fill: parent }

            Text {
                x: 56; y: 42
                text: "EMUFUSION  " + root.lucentVersion
                color: "white"
                font.family: global.fonts.condensed
                font.pixelSize: 48
                font.weight: Font.Bold
                font.letterSpacing: 2
            }
            Text {
                x: 58; y: 116; width: parent.width - 116
                text: "A complete Android game library and a standalone theme, built on Pegasus Frontend."
                wrapMode: Text.WordWrap
                color: "#d8deea"
                font.family: global.fonts.sans
                font.pixelSize: 21
                lineHeight: 1.3
            }
            Text {
                x: 58; y: 214; width: parent.width - 116
                text: "PEGASUS FRONTEND\nCreated by Mátyás M. and contributors\nLicensed under GNU GPL version 3\nBase source: github.com/mmatyas/pegasus-frontend/tree/6b322063\n\nEMUFUSION APP\nModified Pegasus distribution licensed under GPLv3. Complete source and build scripts are available from the EmuFusion GitHub repository.\n\nEMUFUSION THEME\nAlso available independently under the MIT License. Other Pegasus themes remain supported."
                wrapMode: Text.WordWrap
                color: "#aeb7c8"
                font.family: global.fonts.sans
                font.pixelSize: 19
                lineHeight: 1.35
            }
            Text {
                x: 58; y: 522; width: parent.width - 116
                text: "Platform names and logos are identification marks belonging to their respective owners. Their appearance does not imply sponsorship or endorsement."
                wrapMode: Text.WordWrap
                color: "#8f99aa"
                font.family: global.fonts.sans
                font.pixelSize: 16
                lineHeight: 1.3
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                y: 604
                text: "A / B  CLOSE"
                color: root.accent
                font.family: global.fonts.sans
                font.pixelSize: 15
                font.weight: Font.Bold
                font.letterSpacing: 1.2
            }
        }
    }

    // ---- Emulator for each system -----------------------------------------
    // Three stacked sheets, all sharing the settings panel's envelope so they
    // read as one surface: the system list, one system's emulators, and the
    // guided custom setup. Every row is reachable with the D-pad alone.

    Rectangle {
        id: emulatorRoutesOverlay
        z: 840
        anchors.fill: parent
        visible: root.emulatorRoutesOpen
        color: "#e905080d"

        MouseArea {
            anchors.fill: parent
            onClicked: {
                root.emulatorRoutesOpen = false
                root.settingsOpen = true
            }
        }

        Rectangle {
            anchors.centerIn: parent
            width: 980
            height: root.settingsPanelHeight
            color: "#f20d121a"
            border.width: 1
            border.color: root.accent
            radius: 8

            MouseArea { anchors.fill: parent }

            Text {
                x: 48; y: 38
                text: "EMULATOR FOR EACH SYSTEM"
                color: "white"
                font.family: global.fonts.condensed
                font.pixelSize: 42
                font.weight: Font.Bold
                font.letterSpacing: 2
            }

            Text {
                x: 50; y: 94
                width: parent.width - 380
                // Kept short enough to sit beside the page counter without
                // eliding; the footer carries the controls.
                text: root.emulatorRoutesNotice !== "" ? root.emulatorRoutesNotice :
                      "Only systems represented in your game library appear here."
                color: root.emulatorRoutesNotice !== "" ? "#ffb4a2" : "#9da7b8"
                elide: Text.ElideRight
                font.family: global.fonts.sans
                font.pixelSize: 17
            }

            Text {
                anchors.right: parent.right
                anchors.rightMargin: 48
                y: 44
                visible: root.emulatorRouteSystems.length > 0
                text: "PAGE " + (root.routesPage + 1) + " / " +
                      Math.max(1, Math.ceil(root.emulatorRouteSystems.length /
                                            root.routesPageSize))
                color: root.accent
                font.family: global.fonts.sans
                font.pixelSize: 16
                font.weight: Font.Bold
                font.letterSpacing: 1.2
            }

            Text {
                anchors.centerIn: parent
                visible: root.emulatorRouteSystems.length === 0
                text: root.emulatorRoutesLoading ? "Reading systems…" :
                      "Add a game to reveal its emulator settings."
                color: "#9da7b8"
                font.family: global.fonts.sans
                font.pixelSize: 22
            }

            Repeater {
                // Row count and stride both come from the shared helpers, so
                // the last row lands on the panel floor.
                model: root.routesPageSize

                Rectangle {
                    property int rowIndex: root.routesPage * root.routesPageSize + index
                    property var entry: rowIndex >= 0 &&
                            rowIndex < root.emulatorRouteSystems.length ?
                            root.emulatorRouteSystems[rowIndex] : null
                    visible: entry !== null
                    x: 44
                    y: root.settingsListTop +
                       index * (root.routesRowHeight + root.settingsListSpacing)
                    width: parent.width - 88
                    height: root.routesRowHeight
                    color: root.emulatorRoutesIndex === rowIndex ? "#261f2a38" : "#9b111720"
                    border.width: root.emulatorRoutesIndex === rowIndex ? 2 : 1
                    border.color: root.emulatorRoutesIndex === rowIndex ?
                                  root.accent : "#30ffffff"
                    radius: 7

                    Text {
                        x: 24
                        y: Math.round((parent.height - 54) / 2)
                        width: parent.width - 400
                        elide: Text.ElideRight
                        text: parent.entry ? parent.entry.collection : ""
                        color: "white"
                        font.family: global.fonts.sans
                        font.pixelSize: 21
                        font.weight: Font.Bold
                        font.letterSpacing: 0.9
                    }

                    Text {
                        x: 24
                        y: Math.round((parent.height - 54) / 2) + 34
                        width: parent.width - 400
                        elide: Text.ElideRight
                        text: !parent.entry ? "" :
                              (!parent.entry.ready ?
                               "Emulator not installed — open this system to fix it" :
                               (!parent.entry.internalAvailable ?
                                "Runs with an external emulator" : ""))
                        color: parent.entry && !parent.entry.ready ? "#ffb4a2" : "#8a94a6"
                        font.family: global.fonts.sans
                        font.pixelSize: 15
                    }

                    Text {
                        anchors.right: parent.right
                        anchors.rightMargin: 24
                        y: Math.round((parent.height - 54) / 2)
                        width: 330
                        horizontalAlignment: Text.AlignRight
                        text: !parent.entry ? "" :
                              (parent.entry.route === "internal" ? "BUILT-IN" : "EXTERNAL")
                        color: root.accent
                        font.family: global.fonts.condensed
                        font.pixelSize: 27
                        font.weight: Font.Bold
                    }

                    Text {
                        anchors.right: parent.right
                        anchors.rightMargin: 24
                        y: Math.round((parent.height - 54) / 2) + 34
                        width: 330
                        horizontalAlignment: Text.AlignRight
                        elide: Text.ElideRight
                        text: parent.entry && parent.entry.route === "external" ?
                              (parent.entry.emulatorName ?
                               parent.entry.emulatorName : "Choose an emulator") : ""
                        color: "#8a94a6"
                        font.family: global.fonts.sans
                        font.pixelSize: 15
                    }

                    MouseArea {
                        anchors.fill: parent
                        onClicked: {
                            root.emulatorRoutesIndex = parent.rowIndex
                            if (parent.entry)
                                root.openEmulatorPicker(parent.entry.system,
                                                        parent.entry.collection)
                        }
                    }
                }
            }

            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                y: parent.height - root.footerLineHeight - 24
                text: "LEFT  BUILT-IN     RIGHT  EXTERNAL     A  CHOOSE EMULATOR     L / R  PAGE     B  BACK"
                color: "#7f899c"
                font.family: global.fonts.sans
                font.pixelSize: root.footerFontSize
                font.letterSpacing: 1
            }
        }
    }

    Rectangle {
        id: emulatorPickerOverlay
        z: 845
        anchors.fill: parent
        visible: root.emulatorPickerOpen
        color: "#ef05080d"

        MouseArea {
            anchors.fill: parent
            onClicked: root.emulatorPickerOpen = false
        }

        Rectangle {
            anchors.centerIn: parent
            width: 980
            height: root.settingsPanelHeight
            color: "#f70d121a"
            border.width: 2
            border.color: root.accent
            radius: 8

            MouseArea { anchors.fill: parent }

            Text {
                x: 48; y: 38
                width: parent.width - 96
                elide: Text.ElideRight
                text: root.emulatorPickerLabel.toUpperCase()
                color: "white"
                font.family: global.fonts.condensed
                font.pixelSize: 42
                font.weight: Font.Bold
                font.letterSpacing: 2
            }

            Text {
                x: 50; y: 94
                width: parent.width - 100
                wrapMode: Text.NoWrap
                elide: Text.ElideRight
                text: root.emulatorPickerNotice !== "" ? root.emulatorPickerNotice :
                      (root.emulatorPickerData && root.emulatorPickerData.unsupportedReason ?
                       root.emulatorPickerData.unsupportedReason :
                       "Press A to use one. Not installed yet? A opens its store page — install it, then press A again.")
                color: root.emulatorPickerNotice !== "" ? root.accent : "#9da7b8"
                font.family: global.fonts.sans
                font.pixelSize: 17
            }

            Text {
                anchors.centerIn: parent
                visible: root.emulatorPickerRowList.length === 0
                text: root.emulatorPickerLoading ? "Reading emulators…" :
                      "No emulator is available for this system."
                color: "#9da7b8"
                font.family: global.fonts.sans
                font.pixelSize: 22
            }

            Repeater {
                model: root.emulatorPickerRowList.length

                Rectangle {
                    property var row: root.emulatorPickerRowList[index]
                    x: 44
                    y: root.pickerListTop + index * (root.pickerRowHeight + 12)
                    width: parent.width - 88
                    height: root.pickerRowHeight
                    color: root.emulatorPickerIndex === index ? "#2c1f2a38" : "#9b111720"
                    border.width: root.emulatorPickerIndex === index ? 2 : 1
                    border.color: root.emulatorPickerIndex === index ?
                                  root.accent : "#30ffffff"
                    radius: 7

                    Text {
                        x: 24
                        y: Math.round((parent.height - 54) / 2)
                        width: parent.width - 330
                        elide: Text.ElideRight
                        text: parent.row ? parent.row.name : ""
                        color: "white"
                        font.family: global.fonts.sans
                        font.pixelSize: 21
                        font.weight: Font.Bold
                    }

                    Text {
                        x: 24
                        y: Math.round((parent.height - 54) / 2) + 34
                        width: parent.width - 330
                        elide: Text.ElideRight
                        text: parent.row ? parent.row.detail : ""
                        color: "#8a94a6"
                        font.family: global.fonts.sans
                        font.pixelSize: 15
                    }

                    // The current choice is stated, not merely highlighted:
                    // the highlight already means "where the cursor is".
                    Text {
                        anchors.right: parent.right
                        anchors.rightMargin: 24
                        y: Math.round((parent.height - 54) / 2)
                        width: 260
                        horizontalAlignment: Text.AlignRight
                        text: parent.row && parent.row.selected ? "IN USE" :
                              (parent.row ? parent.row.state : "")
                        color: parent.row && parent.row.selected ? root.accent : "#c8d0de"
                        font.family: global.fonts.condensed
                        font.pixelSize: 25
                        font.weight: Font.Bold
                    }

                    MouseArea {
                        anchors.fill: parent
                        onClicked: {
                            root.emulatorPickerIndex = index
                            root.activateEmulatorPickerRow()
                        }
                    }
                }
            }

            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                y: parent.height - root.footerLineHeight - 24
                text: "UP / DOWN  SELECT     A  USE, INSTALL, OR RESTORE DEFAULT     B  BACK"
                color: "#7f899c"
                font.family: global.fonts.sans
                font.pixelSize: root.footerFontSize
                font.letterSpacing: 1
            }
        }
    }

    Rectangle {
        id: customEmulatorOverlay
        z: 850
        anchors.fill: parent
        visible: root.customEmulatorOpen
        color: "#f405080d"

        MouseArea {
            anchors.fill: parent
            onClicked: root.customEmulatorOpen = false
        }

        Rectangle {
            anchors.centerIn: parent
            width: 1000
            height: root.settingsPanelHeight
            color: "#fa0d121a"
            border.width: 2
            border.color: root.accent
            radius: 8

            MouseArea { anchors.fill: parent }

            Text {
                x: 48; y: 34
                text: "CUSTOM EMULATOR"
                color: "white"
                font.family: global.fonts.condensed
                font.pixelSize: 40
                font.weight: Font.Bold
                font.letterSpacing: 2
            }

            Text {
                x: 50; y: 86
                width: parent.width - 100
                wrapMode: Text.WordWrap
                text: root.customEmulatorNotice !== "" ? root.customEmulatorNotice :
                      "Point " + root.emulatorPickerLabel + " at an emulator that is not listed. " +
                      "Install it first — EmuFusion checks it is really there before saving."
                color: root.customEmulatorNotice !== "" ? "#ffb4a2" : "#9da7b8"
                font.family: global.fonts.sans
                font.pixelSize: 17
                lineHeight: 1.25
            }

            Repeater {
                model: root.customEmulatorRowCount()

                Rectangle {
                    property string field: root.customEmulatorField(index)
                    property string problem: root.customEmulatorProblemFor(field)
                    property bool isAction: field === "save" || field === "remove"
                    x: 44
                    y: root.customFormTop + index * (root.customRowHeight + 10)
                    width: parent.width - 88
                    height: root.customRowHeight
                    color: root.customEmulatorIndex === index ? "#2c1f2a38" : "#9b111720"
                    border.width: root.customEmulatorIndex === index ? 2 : 1
                    border.color: problem !== "" ? "#e8836b" :
                                  (root.customEmulatorIndex === index ?
                                   root.accent : "#30ffffff")
                    radius: 7

                    Text {
                        x: 22
                        y: Math.round((parent.height - 52) / 2)
                        text: parent.field === "package" ? "APP ID" :
                              parent.field === "activity" ? "SCREEN TO OPEN" :
                              parent.field === "delivery" ? "HOW IT RECEIVES THE GAME" :
                              parent.field === "romExtraKey" ? "NAME FOR THE GAME PATH" :
                              parent.field === "save" ? "SAVE AND USE THIS EMULATOR" :
                              "REMOVE THIS CUSTOM EMULATOR"
                        color: "white"
                        font.family: global.fonts.sans
                        font.pixelSize: 20
                        font.weight: Font.Bold
                        font.letterSpacing: 0.8
                    }

                    // Every field carries its own worked example. A raw text
                    // box with no guidance is exactly what this replaces.
                    Text {
                        x: 22
                        y: Math.round((parent.height - 52) / 2) + 30
                        width: parent.width - 400
                        // A validation message that is cut off is no better
                        // than no message, so these wrap rather than elide.
                        // Two lines is what the row height affords.
                        wrapMode: Text.WordWrap
                        maximumLineCount: 2
                        elide: Text.ElideRight
                        text: parent.problem !== "" ? parent.problem :
                              (parent.field === "package" ?
                               "The emulator's Android app ID, like com.example.emulator" :
                               parent.field === "activity" ?
                               "Its launch screen, like .EmulationActivity" :
                               parent.field === "delivery" ?
                               root.customEmulatorDeliveryHelp() :
                               parent.field === "romExtraKey" ?
                               "The name the emulator expects, like bootPath or ROM" :
                               parent.field === "save" ?
                               "Checks the app is installed and the screen can be opened" :
                               "Puts this system back on the listed emulators")
                        color: parent.problem !== "" ? "#ffb4a2" : "#8a94a6"
                        font.family: global.fonts.sans
                        font.pixelSize: 15
                    }

                    Text {
                        anchors.right: parent.right
                        anchors.rightMargin: 22
                        anchors.verticalCenter: parent.verticalCenter
                        width: 350
                        horizontalAlignment: Text.AlignRight
                        elide: Text.ElideLeft
                        text: parent.field === "package" ?
                              (root.customEmulatorPackage !== "" ?
                               root.customEmulatorPackage : "NOT SET") :
                              parent.field === "activity" ?
                              (root.customEmulatorActivity !== "" ?
                               root.customEmulatorActivity : "NOT SET") :
                              parent.field === "delivery" ?
                              root.customEmulatorDeliveryLabel() :
                              parent.field === "romExtraKey" ?
                              (root.customEmulatorKey !== "" ?
                               root.customEmulatorKey : "NOT SET") :
                              parent.field === "save" ? "SAVE" : "REMOVE"
                        color: parent.isAction ? root.accent :
                               ((parent.field === "package" && root.customEmulatorPackage === "") ||
                                (parent.field === "activity" && root.customEmulatorActivity === "") ||
                                (parent.field === "romExtraKey" && root.customEmulatorKey === "") ?
                                "#6d778a" : "#dfe5f0")
                        font.family: global.fonts.condensed
                        font.pixelSize: 24
                        font.weight: Font.Bold
                    }

                    MouseArea {
                        anchors.fill: parent
                        onClicked: {
                            root.customEmulatorIndex = index
                            root.activateCustomEmulatorRow()
                        }
                    }
                }
            }

            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                y: parent.height - root.footerLineHeight - 24
                text: "UP / DOWN  SELECT     A  EDIT OR RUN     LEFT / RIGHT  CHANGE     B  BACK"
                color: "#7f899c"
                font.family: global.fonts.sans
                font.pixelSize: root.footerFontSize
                font.letterSpacing: 1
            }
        }

        // One field at a time, full width, with the platform keyboard. A
        // per-row inline caret is unusable on a handheld held at arm's length.
        Item {
            id: customEmulatorEditor
            anchors.fill: parent
            visible: editing
            z: 5

            property bool editing: false
            property string field: ""

            function labelFor(name) {
                if (name === "package") return "APP ID"
                if (name === "activity") return "SCREEN TO OPEN"
                if (name === "romExtraKey") return "NAME FOR THE GAME PATH"
                return ""
            }

            function exampleFor(name) {
                if (name === "package") return "com.github.stenzek.duckstation"
                if (name === "activity") return ".EmulationActivity"
                if (name === "romExtraKey") return "bootPath"
                return ""
            }

            function valueFor(name) {
                if (name === "package") return root.customEmulatorPackage
                if (name === "activity") return root.customEmulatorActivity
                if (name === "romExtraKey") return root.customEmulatorKey
                return ""
            }

            function beginEditing(name) {
                if (name !== "package" && name !== "activity" &&
                        name !== "romExtraKey") return
                field = name
                customEmulatorInput.text = valueFor(name)
                editing = true
                customEmulatorInput.forceActiveFocus()
                customEmulatorInput.cursorPosition = customEmulatorInput.text.length
                Qt.inputMethod.show()
            }

            // Same teardown the search field uses, and for the same reason:
            // the editor has to stay focused until the Enter that closed it has
            // fully unwound. Releasing focus inside the key handler leaves
            // Android's input session alive -- Gboard stays up in its
            // fullscreen extract mode and swallows the D-pad, so the form stops
            // responding to anything but the on-screen keyboard.
            property bool closing: false

            function endEditing(commit) {
                if (!editing || closing) return
                closing = true
                var value = customEmulatorInput.text.trim()
                Qt.inputMethod.hide()
                Qt.callLater(function() {
                    customEmulatorInput.focus = false
                    customEmulatorEditor.editing = false
                    root.forceActiveFocus()
                    customEmulatorEditor.closing = false
                })
                if (commit) {
                    if (field === "package") root.customEmulatorPackage = value
                    else if (field === "activity") root.customEmulatorActivity = value
                    else if (field === "romExtraKey") root.customEmulatorKey = value
                    // Clear the stale complaint for the field just edited, so
                    // the form does not keep accusing a value the user fixed.
                    var kept = []
                    var problems = root.customEmulatorProblems
                    for (var index = 0; index < problems.length; ++index)
                        if (problems[index].field !== field) kept.push(problems[index])
                    root.customEmulatorProblems = kept
                }
            }

            Rectangle {
                anchors.fill: parent
                color: "#e005080d"
                MouseArea {
                    anchors.fill: parent
                    onClicked: customEmulatorEditor.endEditing(false)
                }
            }

            Connections {
                target: Qt.inputMethod
                onVisibleChanged: {
                    // Closing Gboard by its chevron must hand the D-pad back,
                    // exactly as the search field does; Android otherwise keeps
                    // the edit session open with no keyboard to type into.
                    if (customEmulatorEditor.editing &&
                            !customEmulatorEditor.closing && !Qt.inputMethod.visible)
                        customEmulatorEditor.endEditing(true)
                }
            }

            Rectangle {
                // Pinned near the top rather than centred: Gboard claims the
                // bottom half of a 1080-high panel, and a centred sheet puts
                // the field and its example under the keys the user is about
                // to press.
                anchors.horizontalCenter: parent.horizontalCenter
                y: 70
                width: 880
                height: 300
                color: "#fc0d121a"
                border.width: 2
                border.color: root.accent
                radius: 10

                MouseArea { anchors.fill: parent }

                Text {
                    x: 44; y: 38
                    text: customEmulatorEditor.labelFor(customEmulatorEditor.field)
                    color: "white"
                    font.family: global.fonts.condensed
                    font.pixelSize: 32
                    font.weight: Font.Bold
                    font.letterSpacing: 1.6
                }

                Text {
                    x: 46; y: 84
                    text: "For example:  " +
                          customEmulatorEditor.exampleFor(customEmulatorEditor.field)
                    color: "#8a94a6"
                    font.family: global.fonts.sans
                    font.pixelSize: 16
                }

                Rectangle {
                    x: 44; y: 126
                    width: parent.width - 88
                    height: 72
                    color: "#22ffffff"
                    border.width: 2
                    border.color: root.accent
                    radius: 6

                    TextInput {
                        id: customEmulatorInput
                        anchors.fill: parent
                        anchors.leftMargin: 18
                        anchors.rightMargin: 18
                        verticalAlignment: TextInput.AlignVCenter
                        color: "white"
                        selectionColor: root.accent
                        font.family: global.fonts.sans
                        font.pixelSize: 26
                        clip: true
                        selectByMouse: true
                        inputMethodHints: Qt.ImhNoPredictiveText
                        onAccepted: customEmulatorEditor.endEditing(true)
                    }
                }

                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: 232
                    text: "ENTER  SAVE FIELD     B  CANCEL"
                    color: root.accent
                    font.family: global.fonts.sans
                    font.pixelSize: 15
                    font.weight: Font.Bold
                    font.letterSpacing: 1.2
                }
            }
        }
    }

    Rectangle {
        id: legalOverlay
        z: 855
        anchors.fill: parent
        visible: root.legalOpen
        color: "#f005080d"

        MouseArea {
            anchors.fill: parent
            onClicked: {
                root.legalOpen = false
                root.settingsOpen = true
            }
        }

        Rectangle {
            anchors.centerIn: parent
            width: 1020
            height: root.settingsPanelHeight
            color: "#fa0d121a"
            border.width: 2
            border.color: root.accent
            radius: 10

            MouseArea { anchors.fill: parent }

            Text {
                x: 56; y: 40
                // Straight from LegalNotice.TITLE: the wording has exactly one
                // home, and this screen is a reader for it, not a second copy.
                text: root.legalTitle.toUpperCase()
                color: "white"
                font.family: global.fonts.condensed
                font.pixelSize: 44
                font.weight: Font.Bold
                font.letterSpacing: 2
            }

            Text {
                x: 58; y: 98
                text: "EmuFusion " + root.lucentVersion
                color: "#8a94a6"
                font.family: global.fonts.sans
                font.pixelSize: 16
            }

            Item {
                id: legalViewport
                x: 56
                y: 140
                width: parent.width - 112
                height: root.legalViewportHeight
                clip: true

                Column {
                    id: legalColumn
                    width: parent.width
                    y: -root.legalScroll
                    spacing: 22
                    onHeightChanged: root.legalBodyHeight = height

                    Repeater {
                        model: root.legalParagraphs.length

                        Text {
                            width: legalColumn.width
                            text: root.legalParagraphs[index]
                            wrapMode: Text.WordWrap
                            color: "#c8d0de"
                            font.family: global.fonts.sans
                            font.pixelSize: 20
                            lineHeight: 1.35
                        }
                    }
                }
            }

            // Only drawn when there is something below the fold, so a notice
            // that already fits is not decorated with a dead scrollbar.
            Rectangle {
                visible: root.legalBodyHeight > root.legalViewportHeight
                x: parent.width - 40
                y: 140
                width: 4
                height: root.legalViewportHeight
                radius: 2
                color: "#26ffffff"

                Rectangle {
                    width: parent.width
                    radius: 2
                    color: root.accent
                    height: Math.max(40, parent.height *
                            (root.legalViewportHeight / Math.max(1, root.legalBodyHeight)))
                    y: (parent.height - height) * (root.legalScroll /
                            Math.max(1, root.legalBodyHeight - root.legalViewportHeight))
                }
            }

            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                y: parent.height - root.footerLineHeight - 24
                text: "UP / DOWN  SCROLL     L / R  PAGE     A / B  CLOSE"
                color: "#7f899c"
                font.family: global.fonts.sans
                font.pixelSize: root.footerFontSize
                font.letterSpacing: 1
            }
        }
    }


}
