import array
import unittest
import wave
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "android-companion" / "res" / "raw"
GENERATOR = ROOT / "tools" / "generate_menu_sfx.py"
PLAYER = ROOT / "android-companion" / "src" / "com" / "thorium" / "preview" \
    / "MenuSoundPlayer.java"
SERVICE = ROOT / "android-companion" / "src" / "com" / "thorium" / "preview" \
    / "PreviewService.java"
HOST = ROOT / "unified-android" / "src" / "com" / "thorium" / "preview" \
    / "game" / "InWindowGameHost.java"
BUILD = ROOT / "unified-android" / "build.sh"
THEME = ROOT / "theme" / "theme.qml"

CUES = ("move", "confirm", "back", "error")
# A launcher plays these hundreds of times a session, so both bounds are about
# fatigue rather than fidelity: long or loud blips become unbearable fast.
MAX_DURATION_SECONDS = 0.120
MAX_PEAK = 0.30
MIN_PEAK = 0.05


def read_samples(path: Path):
    with wave.open(str(path), "rb") as source:
        channels = source.getnchannels()
        width = source.getsampwidth()
        rate = source.getframerate()
        frames = source.readframes(source.getnframes())
    samples = array.array("h")
    samples.frombytes(frames)
    return channels, width, rate, samples


class MenuSoundEffectsTest(unittest.TestCase):
    def test_every_cue_is_packaged_as_a_raw_asset(self):
        self.assertTrue(GENERATOR.is_file(), "the sfx generator is missing")
        for cue in CUES:
            path = RAW / f"emufusion_sfx_{cue}.wav"
            self.assertTrue(path.is_file(), f"{path.name} was never generated")

    def test_every_cue_is_short_and_quiet(self):
        for cue in CUES:
            path = RAW / f"emufusion_sfx_{cue}.wav"
            channels, width, rate, samples = read_samples(path)
            self.assertEqual(channels, 1, f"{path.name} is not mono")
            self.assertEqual(width, 2, f"{path.name} is not 16-bit PCM")
            duration = len(samples) / channels / rate
            self.assertGreater(duration, 0.0, f"{path.name} is empty")
            self.assertLessEqual(
                duration, MAX_DURATION_SECONDS,
                f"{path.name} runs {duration * 1000:.0f} ms, past the UI budget")
            peak = max(abs(value) for value in samples) / 32_767.0
            self.assertLessEqual(
                peak, MAX_PEAK,
                f"{path.name} peaks at {peak:.2f}, louder than a menu blip")
            self.assertGreaterEqual(
                peak, MIN_PEAK,
                f"{path.name} peaks at {peak:.2f} and would be inaudible")

    def test_no_cue_clicks_at_its_edges(self):
        # A blip that starts or ends away from zero pops, which is exactly the
        # harshness the design is meant to avoid.
        for cue in CUES:
            path = RAW / f"emufusion_sfx_{cue}.wav"
            _, _, _, samples = read_samples(path)
            self.assertLess(abs(samples[0]) / 32_767.0, 0.01,
                            f"{path.name} starts with a click")
            self.assertLess(abs(samples[-1]) / 32_767.0, 0.01,
                            f"{path.name} ends with a click")

    def test_the_cues_are_distinguished_by_pitch(self):
        # Move is the shortest and highest; back is the longest-tailed low
        # pair. If two cues ever collapse onto the same length and level the
        # user cannot tell an accepted action from a rejected one.
        lengths = {}
        for cue in CUES:
            _, _, rate, samples = read_samples(RAW / f"emufusion_sfx_{cue}.wav")
            lengths[cue] = len(samples) / rate
        self.assertLess(lengths["move"], lengths["confirm"])
        self.assertLess(lengths["move"], lengths["back"])

    def test_the_build_packages_the_assets(self):
        build = BUILD.read_text(encoding="utf-8")
        self.assertIn('cp "$ROOT_DIR/android-companion/res/raw/"*', build)

    def test_the_player_stays_on_the_shared_music_stream(self):
        source = PLAYER.read_text(encoding="utf-8")
        self.assertIn("SoundPool.Builder()", source)
        # USAGE_MEDIA is what puts SoundPool on STREAM_MUSIC, the same stream
        # the hardware volume keys are bound to.
        self.assertIn("AudioAttributes.USAGE_MEDIA", source)
        for cue in CUES:
            self.assertIn(cue.upper(), source)

    def test_sound_effects_default_to_on(self):
        source = PLAYER.read_text(encoding="utf-8")
        self.assertIn("DEFAULT_ENABLED = true", source)
        self.assertIn("getBoolean(PREF_ENABLED, DEFAULT_ENABLED)", source)
        service = SERVICE.read_text(encoding="utf-8")
        # An absent parameter must mean on, matching the shipped default.
        settings = service.split('"/settings/sfx".equals(path)', 1)[1]
        self.assertIn('values.getOrDefault("enabled", "1")', settings)
        theme = THEME.read_text(encoding="utf-8")
        self.assertIn("property bool soundEffectsEnabled: true", theme)
        self.assertIn('api.memory.has("emufusionSoundEffects") ?', theme)

    def test_the_cues_never_play_over_a_running_game(self):
        source = HOST.read_text(encoding="utf-8")
        dispatch = source.split(
            "public static synchronized boolean dispatchKeyEvent", 1)[1]
        dispatch = dispatch.split("\n    }", 1)[0]
        # The sound hook sits strictly after the "a session exists" return, so
        # gameplay input can never reach it.
        gameplay = dispatch.index("if (active != null)")
        handled = dispatch.index("active.handleKeyEvent(event)")
        sfx = dispatch.index("MenuSoundPlayer.playForKey")
        self.assertGreater(sfx, gameplay)
        self.assertGreater(sfx, handled)
        self.assertIn("return false;", dispatch)

    def test_the_theme_can_toggle_and_trigger_the_cues(self):
        service = SERVICE.read_text(encoding="utf-8")
        self.assertIn('"/settings/sfx"', service)
        self.assertIn('"/sfx"', service)
        self.assertIn("MenuSoundPlayer.cueByName", service)
        # Both are called by the theme without a control token, like the
        # neighbouring /settings/sound row.
        theme_called = service.split("THEME_CALLED_ENDPOINTS", 1)[1].split(
            "));", 1)[0]
        self.assertIn('"/settings/sfx"', theme_called)
        self.assertIn('"/sfx"', theme_called)
        theme = THEME.read_text(encoding="utf-8")
        self.assertIn('requestPreviewEndpoint("settings/sfx?enabled="', theme)
        self.assertIn('"SOUND EFFECTS"', theme)


if __name__ == "__main__":
    unittest.main()
