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
# The spec's list, plus "from": it lowercases four-letter "with", and
# "Remove from Ensemble" pairs with "Add to Ensemble".
SMALL_WORDS = frozenset("a an and as at but by for from in of on or the to with".split())
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
    if isinstance(node, ast.IfExp):
        return _string_parts(node.body) + _string_parts(node.orelse)
    return []


def _name(node: ast.expr) -> str:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


# Keywords and dataclass fields that hold a dialog title or button label.
_PICKER_FIELDS = frozenset({"title", "add_label", "remove_label"})


def _call_strings(node: ast.Call) -> list[tuple[str, bool]]:
    name = _name(node.func)
    receiver = _name(node.func.value) if isinstance(node.func, ast.Attribute) else ""
    parts: list[tuple[str, bool]] = []
    if name == "add_response" and len(node.args) >= 2:
        parts += _string_parts(node.args[1])
    if node.args and (
        name in ("set_heading", "set_button_label")
        or (name == "set_label" and "button" in receiver.lower())
    ):
        parts += _string_parts(node.args[0])
    for keyword in node.keywords:
        if keyword.arg == "heading" and name in ("AlertDialog", "present_error_dialog"):
            parts += _string_parts(keyword.value)
        if keyword.arg in _PICKER_FIELDS and name == "PickerConfig":
            parts += _string_parts(keyword.value)
    return parts


def _python_strings(tree: ast.AST) -> Iterator[tuple[int, str, bool]]:
    picker_fields = {
        id(statement)
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "PickerConfig"
        for statement in node.body
        if isinstance(statement, ast.AnnAssign)
        and isinstance(statement.target, ast.Name)
        and statement.target.id in _PICKER_FIELDS
    }
    for node in ast.walk(tree):
        parts: list[tuple[str, bool]] = []
        if isinstance(node, ast.Call):
            parts += _call_strings(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "heading" for target in node.targets
        ):
            parts += _string_parts(node.value)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            if id(node) in picker_fields or (
                isinstance(node.target, ast.Name) and node.target.id == "heading"
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
        self.assertEqual(title_case_violations("Remove from Ensemble"), [])


class PythonScanTests(unittest.TestCase):
    """The scan reaches every way the UI code spells a dialog string."""

    def found(self, source: str) -> list[str]:
        return [text for _line, text, _start in _python_strings(ast.parse(source))]

    def test_button_labels_set_from_python(self) -> None:
        self.assertEqual(self.found('self.update_button.set_label("check again")'), ["check again"])
        self.assertEqual(self.found('button.set_label("use this model")'), ["use this model"])
        self.assertEqual(self.found('toast.set_button_label("view queue")'), ["view queue"])
        self.assertEqual(self.found('self.status_label.set_label("body text")'), [])

    def test_conditional_and_annotated_headings(self) -> None:
        self.assertEqual(self.found('heading = "a b" if mock else "c d"'), ["a b", "c d"])
        self.assertEqual(self.found('heading: str = "e f"'), ["e f"])
        self.assertEqual(self.found('dialog.set_heading("g h")'), ["g h"])

    def test_picker_config_labels(self) -> None:
        source = (
            "class PickerConfig:\n"
            "    title: str = 'choose model'\n"
            "    add_label: str = 'add it'\n"
            "    search_placeholder: str = 'search here'\n"
            "PickerConfig(title='member models', remove_label='drop it')\n"
        )
        self.assertEqual(
            sorted(self.found(source)),
            ["add it", "choose model", "drop it", "member models"],
        )


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
