"""Dialog titles, button labels and alert headings use GNOME header capitalization.

Every word is capitalized except short articles, conjunctions and prepositions
that are not first. Body text, descriptions and row titles keep sentence case
and are not checked here.
"""

from __future__ import annotations

import ast
import re
import unittest
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SMALL_WORDS = frozenset("a an and as at but by for in of on or the to with".split())
_WORD = re.compile(r"[A-Za-z][A-Za-z'’]*")
_DIALOG_OBJECT = re.compile(r"\bAdw\.(?:Dialog|AlertDialog|Window|PreferencesDialog)\b")


def title_case_violations(text: str, *, first_is_start: bool = True) -> list[str]:
    """Words in ``text`` that break header capitalization."""
    words = _WORD.findall(text.replace("_", ""))
    wrong = []
    for index, word in enumerate(words):
        first = index == 0 and first_is_start
        if not first and word.lower() in SMALL_WORDS:
            if word != word.lower():
                wrong.append(word)
        elif word[0].islower():
            wrong.append(word)
    return wrong


def _blueprint_strings(source: str) -> Iterator[str]:
    """Titles and headings of dialog objects, window titles and button labels."""
    for match in re.finditer(
        r"(?:Adw\.(?:Dialog|AlertDialog|Window|PreferencesDialog)|:\s*Adw\.Dialog)\b[^{]*\{"
        r"\s*(?:[\w-]+:[^;{]*;\s*)*?(?:title|heading):\s*\"([^\"]*)\"",
        source,
    ):
        yield match.group(1)
    for match in re.finditer(r"Adw\.WindowTitle\b[^{]*\{[^}]*?\btitle:\s*\"([^\"]*)\"", source):
        yield match.group(1)
    for match in re.finditer(r"Gtk\.(?:Button|MenuButton)\b[^{]*\{([^{}]*)", source):
        label = re.search(r"(?:^|[\s;])label:\s*_?\(?\"([^\"]*)\"", match.group(1))
        if label:
            yield label.group(1)


def _string_parts(node: ast.expr) -> list[tuple[str, bool]]:
    """Constant text in ``node`` with whether each part starts the string."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [(node.value, True)]
    if isinstance(node, ast.JoinedStr):
        parts = []
        for index, value in enumerate(node.values):
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append((value.value, index == 0))
        return parts
    return []


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _python_strings(tree: ast.AST) -> Iterator[tuple[int, str, bool]]:
    for node in ast.walk(tree):
        parts: list[tuple[str, bool]] = []
        if isinstance(node, ast.Call):
            name = _call_name(node)
            if name == "add_response" and len(node.args) >= 2:
                parts += _string_parts(node.args[1])
            for keyword in node.keywords:
                if keyword.arg == "heading" and name in ("AlertDialog", "present_error_dialog"):
                    parts += _string_parts(keyword.value)
                if keyword.arg == "title" and name == "PickerConfig":
                    parts += _string_parts(keyword.value)
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "heading" for target in node.targets
        ):
            parts += _string_parts(node.value)
        line = getattr(node, "lineno", 0)
        for text, start in parts:
            yield line, text, start


class TitleCaseRuleTests(unittest.TestCase):
    def test_rule(self) -> None:
        self.assertEqual(title_case_violations("Retry with Smaller Segment"), [])
        self.assertEqual(title_case_violations("GPU Out of Memory (Debug Mock)"), [])
        self.assertEqual(title_case_violations("_Add Files…"), [])
        self.assertEqual(title_case_violations("Input pairs"), ["pairs"])
        self.assertEqual(title_case_violations("Stop And Quit"), ["And"])
        self.assertEqual(title_case_violations("With Care"), [])
        self.assertEqual(title_case_violations(" Failed", first_is_start=False), [])
        self.assertEqual(title_case_violations(" with", first_is_start=False), [])


class DialogWordingTests(unittest.TestCase):
    maxDiff = None

    def test_dialog_blueprint_strings_are_title_case(self) -> None:
        found = []
        for path in sorted((ROOT / "resources" / "ui").glob("*.blp")):
            source = path.read_text(encoding="utf-8")
            if not _DIALOG_OBJECT.search(source):
                continue
            for text in _blueprint_strings(source):
                wrong = title_case_violations(text)
                if wrong:
                    found.append(f"{path.name}: {text!r} -> {wrong}")
        self.assertEqual(found, [])

    def test_python_dialog_strings_are_title_case(self) -> None:
        found = []
        for path in sorted((ROOT / "ui").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for line, text, start in _python_strings(tree):
                wrong = title_case_violations(text, first_is_start=start)
                if wrong:
                    found.append(f"{path.relative_to(ROOT)}:{line}: {text!r} -> {wrong}")
        self.assertEqual(found, [])

    def test_shared_dialog_constants_are_title_case(self) -> None:
        from bundled.constants import (
            APOLLO_MODEL_PARAMETERS_TEXT,
            CHANGE_MODEL_DEFAULTS_TEXT,
            QUIT_WHILE_PROCESSING_CONFIRM,
            STOP_PROCESS_CONFIRM,
        )

        for text in (
            STOP_PROCESS_CONFIRM[0],
            QUIT_WHILE_PROCESSING_CONFIRM[0],
            APOLLO_MODEL_PARAMETERS_TEXT,
            CHANGE_MODEL_DEFAULTS_TEXT,
        ):
            with self.subTest(text=text):
                self.assertEqual(title_case_violations(text), [])

    def test_stop_confirmation_names_its_action(self) -> None:
        from bundled.constants import STOP_PROCESS_CONFIRM

        self.assertEqual(STOP_PROCESS_CONFIRM[0], "Stop Processing?")


if __name__ == "__main__":
    unittest.main()
