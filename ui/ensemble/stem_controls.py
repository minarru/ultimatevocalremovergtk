"""GTK-free selection owner for final four/multi-stem ensemble outputs."""

from collections.abc import Sequence

from core.settings import Settings
from core.stems import StemRoute
from ui.stem_controls import OutputChoice, StemControlsSnapshot
from ui.stem_output_labels import selection_tooltips, stem_label


class EnsembleStemControls:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.routes: tuple[StemRoute, ...] = ()
        self.selected: set[str] = set()
        self.revision = 0
        self.ready = False

    def configure(self, routes: Sequence[StemRoute], *, ready: bool = True) -> None:
        self.routes = tuple(routes)
        self.ready = ready
        self.revision += 1
        self.selected = set(self.settings.ensemble.stems_selected) or {
            str(route.role) for route in self.routes
        }

    def snapshot(self) -> StemControlsSnapshot:
        available = {str(route.role) for route in self.routes}
        review = bool(self.selected - available)
        choices = tuple(
            OutputChoice(
                str(route.role),
                route,
                str(route.role) in self.selected,
                True,
                "Final combined output",
                len(self.selected) > 1 or str(route.role) not in self.selected,
            )
            for route in self.routes
        )
        summary = ", ".join(
            stem_label(route) for route in self.routes if str(route.role) in self.selected
        )
        if review:
            summary = "Review unavailable stem selection"
        elif not self.ready:
            summary = "Choose member models to configure outputs"
        return StemControlsSnapshot(
            mode="native_subset" if self.ready and self.routes else "unavailable",
            choices=choices,
            presets=(("all", "All"),)
            + tuple(
                (str(route.role), stem_label(route))
                for route in self.routes
                if str(route.role) in ("vocal.vocals", "mix.instrumental")
            ),
            modes=(),
            focus_choices=(),
            selected_ids=frozenset(self.selected),
            summary=summary,
            main_count=sum(choice.selected for choice in choices),
            additional_output_note="Individual model outputs will also be saved."
            if self.settings.ensemble.save_all_outputs
            else "",
            review_required=review,
            revision=self.revision,
            model_id="ensemble",
            active_mode_id="",
            active_focus_id="",
            tooltips=selection_tooltips((str(r.role), r) for r in self.routes),
        )

    def toggle_output(self, output_id: str, checked: bool, *, revision: int) -> bool:
        available = {str(route.role) for route in self.routes}
        if revision != self.revision or output_id not in available:
            return False
        selected = self.selected & available
        if checked:
            selected.add(output_id)
        else:
            selected.discard(output_id)
        if not selected or selected == self.selected:
            return False
        self.selected = selected
        return True

    def select_all(self) -> bool:
        if not self.routes:
            return False
        self.selected = {str(route.role) for route in self.routes}
        return True

    def persist_to_settings(self) -> None:
        available = {str(route.role) for route in self.routes}
        if not self.ready or not self.selected or self.selected - available:
            return
        self.settings.ensemble.stems_selected = (
            []
            if self.selected == available
            else [str(route.role) for route in self.routes if str(route.role) in self.selected]
        )
        self.settings.process.stem_focus = ""

    def refresh_options(self, _settings: Settings) -> None:
        # Snapshot reads the current retention option, without resolving models.
        pass

    def choose_preset(self, preset: str, *, revision: int) -> bool:
        if not self.ready or revision != self.revision:
            return False
        if preset not in dict(self.snapshot().presets):
            return False
        if preset == "all":
            return self.select_all()
        self.selected = {preset}
        return True

    def choose_mode(self, _mode: str) -> bool:
        return False

    def choose_focus(self, _focus: str) -> bool:
        return False
