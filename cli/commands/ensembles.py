"""Ensembles command operations."""

from __future__ import annotations

import argparse

from ..model_identity import CliModelLookup
from ..reporting import add_reporting_args, fail
from .ensemble_rows import ensemble_rows
from .formatting import _print_detail, _print_rows


def add_ensembles_parser(sub: argparse._SubParsersAction) -> None:
    root = sub.add_parser("ensembles", help="Inspect ensemble presets")
    children = root.add_subparsers(dest="ensembles_command", required=True)
    listing = children.add_parser("list")
    add_reporting_args(listing)
    listing.set_defaults(func=cmd_ensembles_list)
    show = children.add_parser("show")
    show.add_argument("name")
    add_reporting_args(show)
    show.set_defaults(func=cmd_ensembles_show)
    create = children.add_parser("create", help="Create a saved ensemble")
    create.add_argument("name")
    create.add_argument("--member", action="append", required=True)
    create.add_argument("--main-stem", required=True)
    create.add_argument("--algorithm", required=True)
    create.add_argument("--wav-ensemble", action=argparse.BooleanOptionalAction, default=False)
    create.add_argument("--save-all-outputs", action=argparse.BooleanOptionalAction, default=True)
    create.add_argument("--replace", action="store_true")
    add_reporting_args(create)
    create.set_defaults(func=cmd_ensembles_create)
    delete = children.add_parser("delete", help="Delete a saved user ensemble")
    delete.add_argument("name")
    add_reporting_args(delete)
    delete.set_defaults(func=cmd_ensembles_delete)


def cmd_ensembles_list(args: argparse.Namespace) -> int:
    rows = [{key: value for key, value in row.items() if key != "data"} for row in ensemble_rows()]
    return _print_rows(args, rows)


def cmd_ensembles_show(args: argparse.Namespace) -> int:
    needle = args.name.lower()
    matches = [
        row
        for row in ensemble_rows()
        if row["id"].lower() == needle or row["display"].lower() == needle
    ]
    if len(matches) != 1:
        return fail(args, f"unknown or ambiguous ensemble {args.name!r}", exit_code=2)
    row = matches[0]
    data = dict(row.get("data") or {})
    try:
        from core.model_repository import ModelRepository

        repo = ModelRepository()
        lookup = CliModelLookup(repo)
        members = [lookup.lookup(tag).id for tag in data.get("selected_models") or []]
    except (OSError, ValueError):
        members = list(data.get("selected_models") or [])
    detail = {
        "id": row["id"],
        "display": row["display"],
        "kind": row["kind"],
        "description": data.get("description"),
        "members": members,
        "stem_pair": data.get("ensemble_main_stem"),
        "algorithm": data.get("ensemble_type"),
        "wav_ensemble": bool(data.get("is_wav_ensemble", False)),
        "retain_member_outputs": bool(data.get("save_all_outputs", False)),
    }
    return _print_detail(args, detail)


def cmd_ensembles_create(args: argparse.Namespace) -> int:
    from core.ensemble_service import EnsembleService
    from core.model_repository import ModelRepository

    try:
        preset = EnsembleService(ModelRepository()).create(
            args.name,
            members=args.member,
            main_stem=args.main_stem,
            algorithm=args.algorithm,
            wav_ensemble=args.wav_ensemble,
            save_all_outputs=args.save_all_outputs,
            replace=args.replace,
        )
    except (OSError, TypeError, ValueError) as exc:
        return fail(args, str(exc), exit_code=2, exc=exc)
    return _print_rows(
        args,
        [
            {
                "created": True,
                "id": preset.id,
                "display": preset.display,
                "members": list(preset.members),
                "stem_pair": preset.main_stem,
                "algorithm": preset.algorithm,
            }
        ],
    )


def cmd_ensembles_delete(args: argparse.Namespace) -> int:
    from core.ensemble_service import EnsembleService

    try:
        if not EnsembleService.delete(args.name):
            raise ValueError(f"saved ensemble not found: {args.name!r}")
    except (OSError, ValueError) as exc:
        return fail(args, str(exc), exit_code=2, exc=exc)
    return _print_rows(args, [{"deleted": True, "id": args.name}])
