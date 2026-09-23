"""Settings command operations."""

from __future__ import annotations

import argparse
import difflib
import os

from core.settings import Settings
from core.settings.access import parse_setting_assignment, validate_setting_path

from ..model_identity import CliModelLookup
from ..profiles import (
    IDENTITY_SETTING_PATHS,
    MODEL_REFERENCE_SETTING_PATHS,
    LoadedProfile,
    list_profiles,
    load_profile,
    profile_path,
    save_profile,
)
from ..reporting import add_reporting_args, fail, report_mode
from .ensemble_rows import ensemble_rows
from .formatting import _human_cell, _jsonable, _print_rows
from .settings_fields import setting_paths


def add_settings_parser(sub: argparse._SubParsersAction) -> None:
    root = sub.add_parser("settings", help="Inspect settings and sparse profiles")
    children = root.add_subparsers(dest="settings_command", required=True)
    show = children.add_parser("show")
    show.add_argument("--profile")
    add_reporting_args(show)
    show.set_defaults(func=cmd_settings_show)
    explain = children.add_parser("explain")
    explain.add_argument("path")
    explain.add_argument("--profile")
    add_reporting_args(explain)
    explain.set_defaults(func=cmd_settings_explain)
    validate = children.add_parser("validate")
    validate.add_argument("--profile")
    validate.add_argument("--set", action="append", default=[])
    add_reporting_args(validate)
    validate.set_defaults(func=cmd_settings_validate)
    profiles = children.add_parser("profile")
    profile_sub = profiles.add_subparsers(dest="profile_command", required=True)
    listing = profile_sub.add_parser("list")
    add_reporting_args(listing)
    listing.set_defaults(func=cmd_profile_list)
    pshow = profile_sub.add_parser("show")
    pshow.add_argument("name")
    add_reporting_args(pshow)
    pshow.set_defaults(func=cmd_profile_show)
    create = profile_sub.add_parser("create")
    create.add_argument("name")
    identity = create.add_mutually_exclusive_group()
    identity.add_argument("--model")
    identity.add_argument("--ensemble")
    create.add_argument("--member", action="append", default=[])
    create.add_argument("--set", action="append", default=[])
    create.add_argument("--replace", action="store_true")
    add_reporting_args(create)
    create.set_defaults(func=cmd_profile_create)
    delete = profile_sub.add_parser("delete")
    delete.add_argument("name")
    add_reporting_args(delete)
    delete.set_defaults(func=cmd_profile_delete)


def cmd_settings_show(args: argparse.Namespace) -> int:
    try:
        settings, profile = load_profile(args.profile)
        from core.settings.job_resolution import SettingsResolver

        profile_source = "gui" if profile.source == "gui" else profile.source
        settings, sources = SettingsResolver().resolve(
            settings,
            base_provenance={path: profile_source for path in profile.settings},
        )
    except (OSError, ValueError) as exc:
        return fail(args, str(exc), exit_code=2, exc=exc)
    payload = {
        "profile": profile.to_dict(),
        "settings": settings.to_json_dict(),
        "sources": sources,
    }
    if report_mode(args) == "human":
        print(f"profile\t{profile.name}\t{profile.source}")
        for path in setting_paths():
            section, name = path.split(".", 1)
            value = getattr(getattr(settings, section), name)
            print(f"{path}\t{_human_cell(value)}\t{sources[path]}")
        return 0
    return _print_rows(args, [payload])


def cmd_settings_explain(args: argparse.Namespace) -> int:
    paths = setting_paths()
    if args.path not in paths:
        matches = difflib.get_close_matches(args.path, paths, n=5)
        return fail(
            args,
            f"unknown setting {args.path!r}; close matches: {', '.join(matches) or 'none'}",
            exit_code=2,
        )
    settings, profile = load_profile(args.profile)
    from core.settings.job_resolution import SettingsResolver

    settings, sources = SettingsResolver().resolve(
        settings,
        base_provenance={
            path: ("gui" if profile.source == "gui" else profile.source)
            for path in profile.settings
        },
    )
    from core.settings.descriptors import describe_setting

    descriptor = describe_setting(args.path)
    section, field_name = args.path.split(".", 1)
    current = getattr(getattr(settings, section), field_name)
    provenance = sources[args.path]
    row = {
        "path": args.path,
        "type": descriptor.type_name,
        "default": descriptor.default,
        "value": _jsonable(current),
        "supports_auto": descriptor.supports_auto,
        "allowed_values": descriptor.allowed_values,
        "model_specific_behavior": descriptor.model_behavior,
        "provenance": provenance,
    }
    return _print_rows(args, [row])


def cmd_settings_validate(args: argparse.Namespace) -> int:
    try:
        settings, profile = load_profile(args.profile)
        from core.settings.access import apply_settings_overrides

        apply_settings_overrides(settings, [parse_setting_assignment(item) for item in args.set])
    except (OSError, ValueError) as exc:
        return fail(args, str(exc), exit_code=2, exc=exc)
    return _print_rows(args, [{"valid": True, "profile": profile.name}])


def cmd_profile_list(args: argparse.Namespace) -> int:
    rows = [{"name": "defaults", "source": "built-in"}, {"name": "gui", "source": "gui"}]
    rows.extend({"name": name, "source": "profile"} for name in list_profiles())
    return _print_rows(args, rows)


def cmd_profile_show(args: argparse.Namespace) -> int:
    try:
        _settings, profile = load_profile(args.name)
    except (OSError, ValueError) as exc:
        return fail(args, str(exc), exit_code=2, exc=exc)
    return _print_rows(args, [profile.to_dict()])


def cmd_profile_create(args: argparse.Namespace) -> int:
    try:
        values = dict(parse_setting_assignment(item) for item in args.set)
        settings = Settings.defaults()
        for path in values:
            if path in IDENTITY_SETTING_PATHS:
                raise ValueError(f"{path} is identity/state; use --model, --ensemble, or --member")
            validate_setting_path(settings, path)
        if args.model and (args.ensemble or args.member):
            raise ValueError("a profile cannot combine a primary model with ensemble identity")
        if args.ensemble and args.member:
            raise ValueError("choose an ensemble preset or --member values, not both")
        model = args.model
        members = list(args.member)
        reference_paths = MODEL_REFERENCE_SETTING_PATHS.intersection(values)
        if model or members or reference_paths:
            from core.model_repository import ModelRepository

            repo = ModelRepository()
            lookup = CliModelLookup(repo)
            model = lookup.lookup(model).id if model else None
            members = [lookup.lookup(item).id for item in members]
            for setting_path in reference_paths:
                values[setting_path] = lookup.lookup(str(values[setting_path])).id
        if args.ensemble:
            needle = args.ensemble.casefold()
            matches = [
                row
                for row in ensemble_rows()
                if str(row["id"]).casefold() == needle or str(row["display"]).casefold() == needle
            ]
            if len(matches) != 1:
                raise ValueError(f"unknown or ambiguous ensemble {args.ensemble!r}")
            ensemble = str(matches[0]["id"])
        else:
            ensemble = None
        profile = LoadedProfile(
            name=args.name,
            source="profile",
            model=model,
            ensemble=ensemble,
            members=members,
            settings=values,
        )
        path = save_profile(profile, replace=args.replace)
    except (OSError, ValueError) as exc:
        return fail(args, str(exc), exit_code=2, exc=exc)
    return _print_rows(args, [{"created": True, "name": args.name, "path": path}])


def cmd_profile_delete(args: argparse.Namespace) -> int:
    try:
        path = profile_path(args.name)
        if not os.path.isfile(path):
            raise ValueError(f"profile not found: {args.name!r}")
        os.remove(path)
    except (OSError, ValueError) as exc:
        return fail(args, str(exc), exit_code=2, exc=exc)
    return _print_rows(args, [{"deleted": True, "name": args.name}])
