"""Completion command operations."""

from __future__ import annotations

import argparse
import shlex

from core.model_identity import (
    iter_model_records,
)

from ..profiles import (
    list_profiles,
)
from .ensemble_rows import ensemble_rows
from .settings_fields import setting_paths


def add_completion_parser(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("completion", help="Generate shell completion")
    parser.add_argument("shell", choices=("bash", "zsh", "fish"))
    parser.set_defaults(func=cmd_completion, report="human", quiet=False, verbose=False)


def cmd_completion(args: argparse.Namespace) -> int:
    from ..main import build_parser

    root = build_parser()
    subcommands = next(
        action for action in root._actions if isinstance(action, argparse._SubParsersAction)
    )
    commands = " ".join(subcommands.choices)
    dynamic: list[str] = ["defaults", "gui", *setting_paths(), *list_profiles()]
    try:
        from core.model_repository import ModelRepository

        dynamic.extend(record.id for record in iter_model_records(ModelRepository()))
        dynamic.extend(str(row["id"]) for row in ensemble_rows())
        from core.gpu import list_gpu_devices

        dynamic.append("cpu")
        dynamic.extend(
            ident if ident in {"mps", "directml"} else f"cuda:{ident}"
            for ident, _label in list_gpu_devices()
        )
    except (ImportError, OSError, ValueError):
        # Completion remains usable from a minimally provisioned install.
        pass
    words = " ".join(shlex.quote(item) for item in [*commands.split(), *sorted(set(dynamic))])
    if args.shell == "bash":
        print(f"complete -W {shlex.quote(words)} uvr")
    elif args.shell == "zsh":
        print(f"#compdef uvr\n_arguments '*:uvr value:({words})'")
    else:
        for command in commands.split():
            print(f"complete -c uvr -n '__fish_use_subcommand' -a {command}")
        for item in sorted(set(dynamic)):
            print(f"complete -c uvr -a {shlex.quote(item)}")
    return 0
