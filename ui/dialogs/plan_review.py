"""Compact review of a resolved plan; run acceptance remains in RunController."""

import os
from collections.abc import Callable

from gi.repository import Adw, Gtk

from core.job_plan_types import ResolvedJob
from ui.markup import set_row_subtitle, set_row_title
from ui.plan_review import review_presentation
from ui.resources import RESOURCE_PREFIX, require_resource_bundle
from ui.widgets.lazy_populate import LazyPopulator

_RESOURCE = f"{RESOURCE_PREFIX}/ui/plan-review.ui"
require_resource_bundle(_RESOURCE)


@Gtk.Template(resource_path=_RESOURCE)
class ReviewPlanDialog(Adw.Dialog):
    __gtype_name__ = "ReviewPlanDialog"

    summary: Gtk.Label = Gtk.Template.Child()
    result: Gtk.Label = Gtk.Template.Child()
    model_row: Adw.ActionRow = Gtk.Template.Child("model")
    members: Adw.ExpanderRow = Gtk.Template.Child()
    combination: Adw.ActionRow = Gtk.Template.Child()
    inputs: Adw.ExpanderRow = Gtk.Template.Child()
    stems: Adw.ExpanderRow = Gtk.Template.Child()
    additional: Adw.ActionRow = Gtk.Template.Child()
    destination: Adw.ActionRow = Gtk.Template.Child()
    processing: Adw.ExpanderRow = Gtk.Template.Child()
    device: Adw.ActionRow = Gtk.Template.Child()
    sample: Adw.ActionRow = Gtk.Template.Child()
    retention: Adw.ActionRow = Gtk.Template.Child()
    vocal_split: Adw.ActionRow = Gtk.Template.Child()
    warnings: Adw.PreferencesGroup = Gtk.Template.Child()
    technical: Adw.ExpanderRow = Gtk.Template.Child()
    plan_text: Gtk.Label = Gtk.Template.Child()
    copy_button: Gtk.Button = Gtk.Template.Child("copy")
    cancel_button: Gtk.Button = Gtk.Template.Child("cancel")
    start_button: Gtk.Button = Gtk.Template.Child("start")

    def __init__(self, plan: ResolvedJob):
        Adw.init()
        super().__init__()
        self.accepted = False
        self._lazy: list[LazyPopulator] = []
        view = review_presentation(plan)
        self.summary.set_label(view.heading)
        self.result.set_label(view.file_summary)
        ensemble = plan.command == "ensemble"
        self.model_row.set_visible(not ensemble)
        set_row_subtitle(self.model_row, plan.models[0].display if plan.models else "No model")
        self.members.set_visible(ensemble)
        set_row_title(self.members, f"{len(plan.models)} member models")
        self._populate_lazily(
            self.members,
            lambda: self._rows(self.members, tuple((m.display, "") for m in plan.models)),
        )
        self.combination.set_visible(ensemble)
        algorithm = plan.settings.ensemble.type
        if plan.settings.ensemble.derive_complement_from_mix:
            algorithm += " · Derive complement from mix"
        set_row_title(self.combination, f"Combination · {algorithm}")
        set_row_title(
            self.inputs, f"{len(plan.inputs)} input {'file' if len(plan.inputs) == 1 else 'files'}"
        )
        self._populate_lazily(
            self.inputs,
            lambda: self._rows(
                self.inputs, tuple((os.path.basename(i.path), i.path) for i in plan.inputs)
            ),
        )
        labels = view.stems
        set_row_title(
            self.stems,
            " · ".join(labels) if 0 < len(labels) <= 4 else f"{len(labels)} planned stems",
        )
        set_row_subtitle(self.stems, view.format)
        self._populate_lazily(
            self.stems,
            lambda: self._rows(
                self.stems,
                tuple((s, "Planned output") for s in view.stems)
                + tuple((s, "Conditional · saved when produced") for s in view.conditional_stems),
            ),
        )
        self.additional.set_visible(bool(view.additional))
        set_row_subtitle(self.additional, view.additional)
        set_row_subtitle(self.destination, view.destination)
        self.destination.set_tooltip_text(view.destination)
        set_row_subtitle(self.processing, view.processing)
        set_row_subtitle(self.device, view.device)
        set_row_subtitle(self.sample, view.sample)
        self.retention.set_visible(ensemble)
        set_row_subtitle(
            self.retention, "Also saved" if plan.settings.ensemble.save_all_outputs else "Not saved"
        )
        self.vocal_split.set_visible(plan.settings.process.vocal_splitter_enabled)
        splitter = plan.model_dependencies.get("process.vocal_splitter")
        set_row_subtitle(self.vocal_split, splitter.display if splitter else "Enabled")
        self.warnings.set_visible(bool(view.warnings))
        for message in view.warnings:
            row = Adw.ActionRow(title_lines=0)
            set_row_title(row, message)
            row.add_prefix(Gtk.Image(icon_name="dialog-warning-symbolic", css_classes=["warning"]))
            self.warnings.add(row)
        self._populate_lazily(self.technical, lambda: self.plan_text.set_label(view.technical))
        self._plan_text = view.technical
        self.copy_button.connect("clicked", self._copy)
        self.cancel_button.connect("clicked", lambda *_: self.close())
        self.start_button.connect("clicked", self._start)
        self.set_focus(self.cancel_button)

    def _populate_lazily(self, row: Adw.ExpanderRow, populate: Callable[[], None]) -> None:
        lazy = LazyPopulator(is_expanded=row.get_expanded, populate=populate)
        self._lazy.append(lazy)
        row.connect("notify::expanded", lambda *_: lazy.ensure())

    @staticmethod
    def _rows(group: Adw.ExpanderRow, entries: tuple[tuple[str, str], ...]) -> None:
        for title, subtitle in entries:
            row = Adw.ActionRow(title_lines=2, subtitle_lines=2)
            set_row_title(row, title)
            set_row_subtitle(row, subtitle)
            row.set_tooltip_text(subtitle)
            group.add_row(row)

    def _copy(self, button: Gtk.Button) -> None:
        self.get_display().get_clipboard().set(self._plan_text)
        button.set_label("Copied")

    def _start(self, _button: Gtk.Button) -> None:
        self.accepted = True
        self.close()
