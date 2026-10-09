import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
GAME = ROOT / "unified-android" / "src" / "com" / "thorium" / "preview" / "game"


def method_body(source: str, signature: str) -> str:
    start = source.index(signature)
    brace = source.index("{", start)
    depth = 0
    for index in range(brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[brace + 1:index]
    raise AssertionError(f"unterminated method: {signature}")


class GameplayInputRepeatFilterTest(unittest.TestCase):
    def test_phone_buttons_do_not_swallow_game_stylus_gestures(self):
        source = (GAME / "TouchControlsView.java").read_text()
        body = method_body(source, "@Override public boolean onTouchEvent(MotionEvent event)")
        self.assertIn("event.getActionMasked() == MotionEvent.ACTION_DOWN", body)
        guard = body.index("controlAt(event.getX(0), event.getY(0)) == null) return false")
        self.assertLess(guard, body.index("EnumSet<CanonicalControl> next"))
        self.assertIn("listener.onControl(control, is)", body)
        self.assertIn("return true;", body)

    def test_in_window_gameplay_consumes_repeat_before_engine_dispatch(self):
        source = (GAME / "InWindowGameHost.java").read_text()
        body = method_body(source, "private boolean handleKeyEvent(KeyEvent event)")
        guard = body.index("event.getRepeatCount() != 0) return true")
        dispatch = body.index("session.dispatchKeyEvent(event)")
        self.assertLess(guard, dispatch)

    def test_every_engine_session_filters_repeat_before_input_work(self):
        cases = {
            "LibretroEngineSession.java": "joypad.apply(",
            "PpssppGlesEngineSession.java": "joypad.apply(",
            "NativeAdapterEngineSession.java": "setLocalControl(active,",
        }
        for filename, work in cases.items():
            with self.subTest(filename=filename):
                source = (GAME / filename).read_text()
                body = method_body(
                    source,
                    "@Override public boolean dispatchKeyEvent(KeyEvent event)",
                )
                guard = body.index("event.getRepeatCount() != 0) return true")
                self.assertLess(guard, body.index(work))


if __name__ == "__main__":
    unittest.main()
