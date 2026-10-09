"""Execute actual theme JS callbacks; QML binding checks are not device-render proof."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]


class FrontendGameplayQuiescenceTest(unittest.TestCase):
    def test_rescan_rotation_stops_with_stale_busy_status_during_gameplay(self):
        node = shutil.which("node")
        self.assertIsNotNone(node)
        script = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const source = fs.readFileSync(process.argv[1], 'utf8');
const block = source.split('RotationAnimation on rotation {')[1];
assert(block, 'rescan rotation exists');
const expression = block.split('running:')[1].split('from:')[0].trim();
for (const importState of ['idle', 'complete', 'error', 'scanning', 'copying', 'indexing']) {
    const root = {gameplayActive: true, importState};
    assert.strictEqual(vm.runInNewContext(expression, {root}), false,
        'hidden spinner runs for stale ' + importState);
    root.gameplayActive = false;
    assert.strictEqual(vm.runInNewContext(expression, {root}),
        !['idle', 'complete', 'error'].includes(importState),
        'visible spinner must retain existing status behavior');
}
'''
        result = subprocess.run([node, "-e", script, str(ROOT / "theme/theme.qml")],
                                capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_actual_theme_callbacks_reject_late_preview_and_heartbeat_work(self):
        node = shutil.which("node")
        self.assertIsNotNone(node)
        script = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const source = fs.readFileSync(process.argv[1], 'utf8');
function extract(name) {
    const start = source.indexOf('function ' + name + '(');
    assert(start >= 0, name);
    let pos = source.indexOf('{', start), depth = 1, end = pos + 1;
    while (depth) { depth += (source[end] === '{') - (source[end] === '}'); ++end; }
    return source.slice(start, end);
}
let requests = [], later = [], restored = 0;
const state = {
    gameplayActive: false, previewHeartbeatSequence: 0, previewHeartbeatAppliedSequence: 0,
    screensaverActive: true, screensaverRequestPending: false, screensaverGeneration: 2,
    screensaverSourceA: 'movie-a', screensaverSourceB: 'movie-b',
    screensaverEnabled: true, screensaverCurrentSlot: 0, screensaverPendingSlot: -1,
    screensaverDeck: ['a'], screensaverDeckIndex: 0,
    screensaverGame: {}, screensaverPendingGame: {}, screensaverTopStillSince: 0,
    previewPlacementMode: 'bottom', page: 'home', homeViewMode: 'list', homeListFocusColumn: 0,
    launchPollPending: false, currentBottomPreviewGame: {}, currentBottomPreviewSequence: 3,
    useBottomPreview: () => true, videoSource: () => 'movie', displayTitle: () => 'title',
    screensaverSystemName: () => 'system', scoreText: () => 'score', artwork: () => 'art',
    peekScreensaverVideo: () => '', Date, console,
    Qt: {callLater: action => later.push(action), ApplicationActive: 4,
         ApplicationInactive: 2, application: {state: 4}},
    activateHomeListPreview: () => ++restored,
    screensaverAdvanceRetry: {restart: () => {throw Error('unexpected retry')}},
    nextScreensaverGame: () => {throw Error('unexpected deck work')},
    requestPreviewEndpoint: () => {throw Error('unexpected preview request')},
    launch: () => {throw Error('unexpected duplicate launch')},
};
function Request() { requests.push(this); }
Request.DONE = 4;
Request.prototype.open = function(method, url) { this.url = url; };
Request.prototype.send = function() {};
state.XMLHttpRequest = Request; state.root = state;
vm.createContext(state);
for (const name of ['handleGameplayActiveChanged', 'stopScreensaver', 'sendPreviewHeartbeat',
    'randomHomePreviewActive', 'advanceRandomHomePreview', 'sendBottomPreview',
    'refreshCurrentPreview', 'requestScreensaverGame', 'advanceScreensaverVideo',
    'screensaverPlaybackFinished', 'pollBottomLaunchRequest']) vm.runInContext(extract(name), state);
function reply(request, payload, status=200) {
    request.readyState = 4; request.status = status; request.responseText = payload;
    request.onreadystatechange();
}
// Start a request before gameplay, then enter while a screensaver is already playing.
state.requestScreensaverGame({}, false, 2);
const staleVideo = requests.pop();
state.pollBottomLaunchRequest();
const staleLaunch = requests.pop();
state.gameplayActive = true; state.handleGameplayActiveChanged();
assert.strictEqual(state.screensaverActive, false);
assert.strictEqual(state.screensaverRequestPending, false);
assert.strictEqual(state.screensaverSourceA, ''); assert.strictEqual(state.screensaverSourceB, '');
assert.strictEqual(state.screensaverGeneration, 3); assert.strictEqual(later.length, 0);
reply(staleVideo, '{}'); reply(staleLaunch, '{"seq":3,"completedSeq":3}');
assert.strictEqual(state.screensaverActive, false); assert.strictEqual(state.launchPollPending, false);
// Stop/onStopped/callLater callbacks cannot start deck/network/selection work under the game.
assert.strictEqual(state.randomHomePreviewActive(), false);
state.advanceRandomHomePreview(); state.advanceScreensaverVideo();
state.requestScreensaverGame({}, true, 3); state.sendBottomPreview({}); state.refreshCurrentPreview();
assert.strictEqual(state.screensaverPlaybackFinished(), false);
assert.strictEqual(requests.length, 0); assert.strictEqual(restored, 0);
// New true wins over an older false response; malformed/missing/string values are not state.
state.sendPreviewHeartbeat(); state.sendPreviewHeartbeat();
reply(requests[1], '{"gameplay":true}'); reply(requests[0], '{"gameplay":false}');
assert.strictEqual(state.gameplayActive, true);
for (const payload of ['{', '{}', '{"gameplay":"false"}', '{"gameplay":null}']) {
    state.sendPreviewHeartbeat(); reply(requests[requests.length - 1], payload);
    assert.strictEqual(state.gameplayActive, true);
}
state.sendPreviewHeartbeat(); reply(requests[requests.length - 1], '{"gameplay":false}');
assert.strictEqual(state.gameplayActive, false);
state.handleGameplayActiveChanged(); assert.strictEqual(later.length, 1);
later.pop()(); assert.strictEqual(restored, 1);
state.Qt.application.state = 2;
state.sendPreviewHeartbeat();
assert(requests[requests.length - 1].url.endsWith('/screensaver/status'));
reply(requests[requests.length - 1], '{"gameplay":true}');
assert.strictEqual(state.gameplayActive, true);
state.gameplayActive = false; state.refreshCurrentPreview();
assert.strictEqual(restored, 1); // Inactive status observation cannot resurrect previews.
state.Qt.application.state = 4;
state.sendPreviewHeartbeat();
assert(requests[requests.length - 1].url.endsWith('/heartbeat'));
const count = requests.length;
for (const hiddenState of [0, 1]) {
    state.Qt.application.state = hiddenState; state.sendPreviewHeartbeat();
    assert.strictEqual(requests.length, count); // Suspended/hidden: no network heartbeat.
}
console.log('actual callback race, cancellation, and return-to-library scenarios passed');
'''
        result = subprocess.run([node, "-e", script, str(ROOT / "theme/theme.qml")],
                                capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_all_five_video_sources_are_gated_and_transition_handler_is_connected(self):
        theme = (ROOT / "theme/theme.qml").read_text()
        self.assertIn("onGameplayActiveChanged: handleGameplayActiveChanged()", theme)
        for name, source in (("singleVideoA", "singleSourceA"), ("singleVideoB", "singleSourceB"),
                             ("singleVideoC", "singleSourceC"),
                             ("screensaverVideoA", "screensaverSourceA"),
                             ("screensaverVideoB", "screensaverSourceB")):
            with self.subTest(player=name):
                body = theme.split("id: " + name, 1)[1].split("fillMode:", 1)[0]
                self.assertIn('source: root.gameplayActive ? "" : root.' + source, body)


if __name__ == "__main__":
    unittest.main()
