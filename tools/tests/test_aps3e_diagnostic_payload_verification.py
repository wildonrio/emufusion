"""Run the production ZIP comparison block with disposable small archives."""
import ast
from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
import zipfile
import json

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "engines/diagnostics/package_spurs_trace.py"


class DiagnosticPayloadVerification(unittest.TestCase):
    def compare(self, candidate, replacements):
        tree = ast.parse(SCRIPT.read_text())
        block = next(node for node in ast.walk(tree) if isinstance(node, ast.With)
                     and len(node.items) == 2
                     and isinstance(node.items[0].optional_vars, ast.Name)
                     and node.items[0].optional_vars.id == "old")
        original = {"native": b"old", "source": b"same", "unrelated": b"retain"}
        with tempfile.TemporaryDirectory(prefix="emufusion-payload-check-") as temp:
            base, signed = Path(temp) / "base.zip", Path(temp) / "new.zip"
            for path, values in ((base, original), (signed, candidate)):
                with zipfile.ZipFile(path, "w") as archive:
                    for name, value in values.items():
                        archive.writestr(name, value)
            env = {"zipfile": zipfile, "base": base, "signed": signed,
                   "signature": lambda name: name == "signature", "NOTE": "note",
                   "replacements": replacements, "json": json}
            with redirect_stdout(io.StringIO()):
                exec(compile(ast.Module(body=[block], type_ignores=[]), str(SCRIPT), "exec"), env)

    def test_explicit_unchanged_source_is_valid(self):
        self.compare({"native": b"new", "source": b"same", "unrelated": b"retain", "note": b"local"},
                     {"native": b"new", "source": b"same"})

    def test_changed_source_is_valid(self):
        self.compare({"native": b"new", "source": b"changed", "unrelated": b"retain", "note": b"local"},
                     {"native": b"new", "source": b"changed"})

    def test_wrong_or_unrelated_payload_is_rejected(self):
        correct = {"native": b"new", "source": b"same", "unrelated": b"retain", "note": b"local"}
        for name in ("native", "source", "unrelated"):
            with self.subTest(name=name), self.assertRaises(AssertionError):
                self.compare(dict(correct, **{name: b"wrong"}), {"native": b"new", "source": b"same"})

    def test_unexpected_entry_is_rejected(self):
        with self.assertRaises(AssertionError):
            self.compare({"native": b"new", "source": b"same", "unrelated": b"retain", "note": b"local", "extra": b"oops"},
                         {"native": b"new", "source": b"same"})


if __name__ == "__main__":
    unittest.main()
