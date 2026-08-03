from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from photon_cruncher import __version__
from photon_cruncher.analysis.runner import AnalysisResult
from photon_cruncher.analysis.trial_classifier import (
    ClassifiedTrialSource,
    classified_trial_sources,
)
from photon_cruncher.export.exporter import export_channel, save_result_figure
from photon_cruncher.io.loader import (
    discover_tdt_block_paths,
    is_tdt_block_path,
    load_session,
)
from photon_cruncher.model import Epoc, PhotometrySession
from photon_cruncher.processing.pipeline import (
    ProcessingSettings,
    available_channels,
    default_settings_for_channel,
    process_channel,
    subset_processed_signal,
)


EXIT_SUCCESS = 0
EXIT_NO_ANALYSES = 1
EXIT_INVALID = 2
EXIT_RUNTIME_ERROR = 3

FIGURE_FORMATS = {"png", "pdf", "tiff"}
EXPORT_MODES = {"csv", "figures", "both", "none"}
EPOC_POLICIES = {"all", "prefer_left", "prefer_right"}


class CliError(Exception):
    exit_code = EXIT_RUNTIME_ERROR


class ConfigError(CliError):
    exit_code = EXIT_INVALID


class InputError(CliError):
    exit_code = EXIT_RUNTIME_ERROR


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            return inspect_command(args)
        if args.command == "validate-config":
            return validate_config_command(args)
        if args.command == "analyze":
            return analyze_command(args)
        parser.print_help(sys.stderr)
        return EXIT_INVALID
    except CliError as exc:
        _write_json({"ok": False, "error": str(exc), "app_version": __version__}, sys.stderr)
        return exc.exit_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="photon-cruncher-cli",
        description="Headless Photon Cruncher access point for automated workflows.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser(
        "inspect", help="Inspect sessions, epocs, channels, and classified sources."
    )
    inspect_parser.add_argument("inputs", nargs="+")
    inspect_parser.add_argument("--summary-json", default=None)
    inspect_parser.add_argument("--json", action="store_true", help=argparse.SUPPRESS)

    validate_parser = subparsers.add_parser(
        "validate-config", help="Validate an analyze JSON config file."
    )
    validate_parser.add_argument("config")
    validate_parser.add_argument("--summary-json", default=None)

    analyze_parser = subparsers.add_parser(
        "analyze", help="Run headless analysis and optional exports."
    )
    analyze_parser.add_argument("inputs", nargs="*")
    analyze_parser.add_argument("--config", default=None)
    analyze_parser.add_argument("--output-dir", default=None)
    analyze_parser.add_argument("--summary-json", default=None)
    epoc_group = analyze_parser.add_mutually_exclusive_group()
    epoc_group.add_argument("--epoc", nargs="+", default=None)
    epoc_group.add_argument(
        "--all-epocs",
        action="store_true",
        default=None,
        help="Analyze every epoc available in each session.",
    )
    analyze_parser.add_argument(
        "--epoc-policy",
        choices=("all", "prefer-left", "prefer-right"),
        default=None,
        help="Analyze all selected epocs or prefer the A/1_ or C/2_ member of each pair.",
    )
    analyze_parser.add_argument("--channel", nargs="+", default=None)
    analyze_parser.add_argument(
        "--channel-smooth",
        nargs="+",
        action="append",
        metavar="CHANNEL=FACTOR",
        default=None,
        help="Override smoothing for individual channels (for example A_465=10 C_465=20).",
    )
    analyze_parser.add_argument("--trial-number", nargs="+", type=int, default=None)
    analyze_parser.add_argument("--trial-type", nargs="+", default=None)
    analyze_parser.add_argument("--trange-start", type=float, default=None)
    analyze_parser.add_argument("--trange-end", type=float, default=None)
    analyze_parser.add_argument("--baseline-start", type=float, default=None)
    analyze_parser.add_argument("--baseline-end", type=float, default=None)
    analyze_parser.add_argument("--baseline-adjust", type=float, default=None)
    analyze_parser.add_argument("--downsample-factor", type=int, default=None)
    smoothing_group = analyze_parser.add_mutually_exclusive_group()
    smoothing_group.add_argument(
        "--smooth-factor",
        type=int,
        default=argparse.SUPPRESS,
        help="Use one smoothing factor for every channel.",
    )
    smoothing_group.add_argument(
        "--default-smoothing",
        dest="smooth_factor",
        action="store_const",
        const=None,
        default=argparse.SUPPRESS,
        help="Restore each channel's built-in smoothing default.",
    )
    artifact_405_group = analyze_parser.add_mutually_exclusive_group()
    artifact_405_group.add_argument(
        "--artifact-405", type=float, default=argparse.SUPPRESS
    )
    artifact_405_group.add_argument(
        "--no-artifact-405",
        dest="artifact_405",
        action="store_const",
        const=None,
        default=argparse.SUPPRESS,
        help="Disable the 405 artifact threshold.",
    )
    artifact_465_group = analyze_parser.add_mutually_exclusive_group()
    artifact_465_group.add_argument(
        "--artifact-465", type=float, default=argparse.SUPPRESS
    )
    artifact_465_group.add_argument(
        "--no-artifact-465",
        dest="artifact_465",
        action="store_const",
        const=None,
        default=argparse.SUPPRESS,
        help="Disable the signal-channel artifact threshold.",
    )
    isosbestic_group = analyze_parser.add_mutually_exclusive_group()
    isosbestic_group.add_argument(
        "--use-isosbestic",
        dest="use_isosbestic",
        action="store_true",
        help="Fit and subtract the paired 405 isosbestic channel (default).",
    )
    isosbestic_group.add_argument(
        "--no-isosbestic",
        dest="use_isosbestic",
        action="store_false",
        help="Skip the 405 fit and process the signal channel directly.",
    )
    analyze_parser.set_defaults(use_isosbestic=None)
    analyze_parser.add_argument(
        "--polynomial-degree",
        type=int,
        default=None,
        help="Polynomial degree for the 405 fit (default: 1).",
    )
    plot_group = analyze_parser.add_mutually_exclusive_group()
    plot_group.add_argument(
        "--plot-smoothed",
        dest="plot_smoothed",
        action="store_true",
        default=None,
    )
    plot_group.add_argument(
        "--plot-raw",
        dest="plot_smoothed",
        action="store_false",
    )
    baseline_group = analyze_parser.add_mutually_exclusive_group()
    baseline_group.add_argument(
        "--baseline-correction",
        dest="baseline_correction",
        action="store_true",
        default=None,
    )
    baseline_group.add_argument(
        "--no-baseline-correction",
        dest="baseline_correction",
        action="store_false",
    )
    analyze_parser.add_argument("--export", choices=sorted(EXPORT_MODES), default=None)
    analyze_parser.add_argument("--figure-format", choices=sorted(FIGURE_FORMATS), default=None)
    analyze_parser.add_argument("--per-session-subdir", action="store_true", default=None)
    analyze_parser.add_argument("--no-per-session-subdir", action="store_true")
    return parser


def inspect_command(args: argparse.Namespace) -> int:
    summary: dict[str, Any] = {
        "ok": True,
        "app_version": __version__,
        "inputs": [],
        "sessions": [],
        "warnings": [],
    }
    for raw_input in args.inputs:
        try:
            paths = discover_input_paths([raw_input])
            summary["inputs"].append(
                {
                    "path": str(Path(raw_input).expanduser()),
                    "discovered_paths": [str(path) for path in paths],
                }
            )
            for path in paths:
                session = load_session(path)
                summary["sessions"].append(session_inspection(session))
        except Exception as exc:
            summary["warnings"].append({"input": raw_input, "message": str(exc)})

    exit_code = EXIT_SUCCESS if summary["sessions"] else EXIT_RUNTIME_ERROR
    summary["ok"] = exit_code == EXIT_SUCCESS
    emit_summary(summary, args.summary_json)
    return exit_code


def validate_config_command(args: argparse.Namespace) -> int:
    try:
        raw_config = load_config(Path(args.config))
        config = normalize_analyze_config(argparse.Namespace(config=None), raw_config)
        validate_analyze_config(config)
        summary = {
            "ok": True,
            "valid": True,
            "app_version": __version__,
            "config": config,
            "errors": [],
        }
        exit_code = EXIT_SUCCESS
    except ConfigError as exc:
        summary = {
            "ok": False,
            "valid": False,
            "app_version": __version__,
            "errors": [{"field": "config", "code": "invalid", "message": str(exc)}],
        }
        exit_code = EXIT_INVALID
    emit_summary(summary, args.summary_json)
    return exit_code


def analyze_command(args: argparse.Namespace) -> int:
    raw_config: dict[str, Any] = {}
    if args.config:
        raw_config = load_config(Path(args.config))
    config = normalize_analyze_config(args, raw_config)
    validate_analyze_config(config)

    input_paths = discover_input_paths(config["inputs"])
    if not input_paths:
        raise InputError("No .mat files or TDT blocks were discovered.")

    output_dir = Path(config["output_dir"] or ".").expanduser().resolve()
    export_csv = bool(config["exports"]["csv"])
    export_figures = bool(config["exports"]["figures"])
    if export_csv or export_figures:
        output_dir.mkdir(parents=True, exist_ok=True)

    summary: dict[str, Any] = {
        "ok": True,
        "app_version": __version__,
        "output_dir": str(output_dir),
        "results": [],
        "skipped": [],
        "warnings": [],
    }

    for input_path in input_paths:
        try:
            session = load_session(input_path)
        except Exception as exc:
            summary["skipped"].append(
                {"input": str(input_path), "reason": f"load failed: {exc}"}
            )
            continue

        session_output_dir = (
            output_dir / session.source_path.stem
            if config["exports"]["per_session_subdir"]
            else output_dir
        )
        for epoc_name in epoc_names_for_config(session, config):
            try:
                epoc, source = resolve_epoc_or_source(session, epoc_name)
            except ValueError as exc:
                summary["skipped"].append(
                    {
                        "input": str(input_path),
                        "epoc": epoc_name,
                        "reason": str(exc),
                    }
                )
                continue
            if epoc.onset.size == 0:
                summary["skipped"].append(
                    {
                        "input": str(input_path),
                        "epoc": epoc.name,
                        "reason": "epoc has no events",
                    }
                )
                continue
            if source and source.warnings:
                for warning in source.warnings:
                    summary["warnings"].append(
                        {
                            "input": str(input_path),
                            "source": source.label,
                            "message": warning,
                        }
                    )
            result_items = analyze_session_epoc(session, epoc, source, config)
            if not result_items:
                summary["skipped"].append(
                    {
                        "input": str(input_path),
                        "epoc": epoc.name,
                        "reason": "no requested channels could be analyzed",
                    }
                )
                continue
            for result in result_items:
                try:
                    result_summary = export_result(
                        result,
                        session_output_dir,
                        config,
                        export_csv,
                        export_figures,
                    )
                    summary["results"].append(result_summary)
                except Exception as exc:
                    summary["skipped"].append(
                        {
                            "input": str(input_path),
                            "epoc": epoc.name,
                            "channel": result.channel_key,
                            "reason": f"export failed: {exc}",
                        }
                    )

    exit_code = EXIT_SUCCESS if summary["results"] else EXIT_NO_ANALYSES
    summary["ok"] = exit_code == EXIT_SUCCESS
    emit_summary(summary, config.get("summary_json"))
    return exit_code


def discover_input_paths(raw_inputs: Iterable[str | Path]) -> list[Path]:
    discovered: list[Path] = []
    seen: set[Path] = set()
    for raw_input in raw_inputs:
        path = Path(raw_input).expanduser().resolve()
        if not path.exists():
            raise InputError(f"Input path not found: {path}")
        if path.is_file():
            if path.suffix.lower() != ".mat":
                raise InputError(f"Unsupported file input: {path}")
            candidates = [path]
        elif is_tdt_block_path(path):
            candidates = [path]
        elif path.is_dir():
            mats = sorted(candidate.resolve() for candidate in path.rglob("*.mat"))
            blocks = [candidate.resolve() for candidate in discover_tdt_block_paths(path)]
            candidates = [*mats, *blocks]
        else:
            candidates = []
        for candidate in candidates:
            if candidate not in seen:
                seen.add(candidate)
                discovered.append(candidate)
    return discovered


def session_inspection(session: PhotometrySession) -> dict[str, Any]:
    sources = classified_trial_sources(session)
    return {
        "source_path": str(session.source_path),
        "session_name": session.source_path.stem,
        "info": _json_safe(session.info),
        "streams": {
            name: {
                "fs": stream.fs,
                "samples": int(stream.data.size),
                "t0": stream.t0,
            }
            for name, stream in sorted(session.streams.items())
        },
        "epocs": {
            name: {
                "events": int(epoc.onset.size),
                "first_onset": _optional_float(epoc.onset[0] if epoc.onset.size else None),
                "last_onset": _optional_float(epoc.onset[-1] if epoc.onset.size else None),
            }
            for name, epoc in sorted(session.epocs.items())
        },
        "channels": sorted(available_channels(session).keys()),
        "classified_sources": [
            {
                "key": source.key,
                "label": source.label,
                "events": len(source.trials),
                "type_counts": trial_type_counts(
                    trial.trial_type for trial in source.trials
                ),
                "warnings": source.warnings,
            }
            for source in sources
        ],
    }


def normalize_analyze_config(
    args: argparse.Namespace,
    raw_config: dict[str, Any],
) -> dict[str, Any]:
    processing = _config_object(raw_config, "processing")
    exports = _config_object(raw_config, "exports")
    trial_filter = _config_object(raw_config, "trial_filter")
    raw_channel_settings = raw_config.get("channel_settings", {})
    if not isinstance(raw_channel_settings, dict):
        raise ConfigError("channel_settings must be an object")
    channel_settings: dict[str, dict[str, Any]] = {}
    for channel, settings in raw_channel_settings.items():
        if not isinstance(settings, dict):
            raise ConfigError(f"channel_settings.{channel} must be an object")
        channel_settings[str(channel)] = dict(settings)

    config = {
        "inputs": _config_list(raw_config, "inputs"),
        "output_dir": raw_config.get("output_dir"),
        "summary_json": raw_config.get("summary_json"),
        "channels": _config_list(raw_config, "channels"),
        "epocs": _config_list(raw_config, "epocs"),
        "all_epocs": raw_config.get("all_epocs", False),
        "epoc_policy": str(raw_config.get("epoc_policy", "all")).replace("-", "_"),
        "channel_settings": channel_settings,
        "trial_filter": {
            "trial_numbers": _config_list(trial_filter, "trial_numbers"),
            "trial_types": _config_list(trial_filter, "trial_types"),
        },
        "processing": {
            "trange_start": processing.get("trange_start", -2.0),
            "trange_end": processing.get("trange_end", 5.0),
            "baseline_start": processing.get("baseline_start", -3.0),
            "baseline_end": processing.get("baseline_end", -1.0),
            "baseline_adjust": processing.get("baseline_adjust", -2.0),
            "downsample_factor": processing.get("downsample_factor", 10),
            "smooth_factor": processing.get("smooth_factor"),
            "artifact_405": processing.get("artifact_405"),
            "artifact_465": processing.get("artifact_465"),
            "use_isosbestic": processing.get("use_isosbestic", True),
            "polynomial_degree": processing.get("polynomial_degree", 1),
            "plot_smoothed": processing.get("plot_smoothed", True),
            "baseline_correction": processing.get("baseline_correction", True),
        },
        "exports": {
            "csv": exports.get("csv", True),
            "figures": exports.get("figures", False),
            "figure_format": exports.get("figure_format", "png"),
            "per_session_subdir": exports.get("per_session_subdir", True),
        },
    }

    if getattr(args, "inputs", None):
        config["inputs"] = list(args.inputs)
    if getattr(args, "output_dir", None) is not None:
        config["output_dir"] = args.output_dir
    if getattr(args, "summary_json", None) is not None:
        config["summary_json"] = args.summary_json
    if getattr(args, "epoc", None) is not None:
        config["epocs"] = list(args.epoc)
        config["all_epocs"] = False
    if getattr(args, "all_epocs", None):
        config["epocs"] = []
        config["all_epocs"] = True
    if getattr(args, "epoc_policy", None) is not None:
        config["epoc_policy"] = args.epoc_policy.replace("-", "_")
    if getattr(args, "channel", None) is not None:
        config["channels"] = list(args.channel)
    if getattr(args, "channel_smooth", None):
        for override in _flatten(args.channel_smooth):
            channel, smooth_factor = parse_channel_smooth_override(override)
            config["channel_settings"].setdefault(channel, {})[
                "smooth_factor"
            ] = smooth_factor
    if getattr(args, "trial_number", None) is not None:
        config["trial_filter"]["trial_numbers"] = list(args.trial_number)
    if getattr(args, "trial_type", None) is not None:
        config["trial_filter"]["trial_types"] = list(args.trial_type)

    for option, field in [
        ("trange_start", "trange_start"),
        ("trange_end", "trange_end"),
        ("baseline_start", "baseline_start"),
        ("baseline_end", "baseline_end"),
        ("baseline_adjust", "baseline_adjust"),
        ("downsample_factor", "downsample_factor"),
        ("polynomial_degree", "polynomial_degree"),
    ]:
        value = getattr(args, option, None)
        if value is not None:
            config["processing"][field] = value
    for option in ("smooth_factor", "artifact_405", "artifact_465"):
        if hasattr(args, option):
            config["processing"][option] = getattr(args, option)
    if getattr(args, "use_isosbestic", None) is not None:
        config["processing"]["use_isosbestic"] = bool(args.use_isosbestic)
    if getattr(args, "plot_smoothed", None) is not None:
        config["processing"]["plot_smoothed"] = bool(args.plot_smoothed)
    if getattr(args, "baseline_correction", None) is not None:
        config["processing"]["baseline_correction"] = bool(args.baseline_correction)
    if getattr(args, "figure_format", None) is not None:
        config["exports"]["figure_format"] = args.figure_format
    if getattr(args, "per_session_subdir", None):
        config["exports"]["per_session_subdir"] = True
    if getattr(args, "no_per_session_subdir", False):
        config["exports"]["per_session_subdir"] = False
    export_mode = getattr(args, "export", None)
    if export_mode is not None:
        config["exports"]["csv"] = export_mode in {"csv", "both"}
        config["exports"]["figures"] = export_mode in {"figures", "both"}

    return config


def validate_analyze_config(config: dict[str, Any]) -> None:
    errors: list[str] = []
    for field in ("output_dir", "summary_json"):
        if config[field] is not None and not isinstance(config[field], str):
            errors.append(f"{field} must be a string or null")
    for field in ("inputs", "channels", "epocs"):
        if not isinstance(config[field], list) or not all(
            isinstance(item, str) and item.strip() for item in config[field]
        ):
            errors.append(f"{field} must be a list of non-empty strings")
    trial_filter = config["trial_filter"]
    if not all(_is_positive_integer(value) for value in trial_filter["trial_numbers"]):
        errors.append("trial_numbers must be a list of integers of at least 1")
    if not all(
        isinstance(value, str) and value.strip()
        for value in trial_filter["trial_types"]
    ):
        errors.append("trial_types must be a list of non-empty strings")
    if not isinstance(config["all_epocs"], bool):
        errors.append("all_epocs must be true or false")
    for field in ("csv", "figures", "per_session_subdir"):
        if not isinstance(config["exports"][field], bool):
            errors.append(f"exports.{field} must be true or false")
    if not config["inputs"]:
        errors.append("inputs must include at least one file or folder")
    if not config["epocs"] and not config["all_epocs"]:
        errors.append("epocs must include at least one epoc or set all_epocs to true")
    if config["epocs"] and config["all_epocs"]:
        errors.append("epocs and all_epocs cannot both be set")
    if config["epoc_policy"] not in EPOC_POLICIES:
        errors.append("epoc_policy must be one of: all, prefer_left, prefer_right")
    if not config["output_dir"] and (
        config["exports"]["csv"] or config["exports"]["figures"]
    ):
        errors.append("output_dir is required when exporting CSV files or figures")
    processing = config["processing"]
    numeric_fields = (
        "trange_start",
        "trange_end",
        "baseline_start",
        "baseline_end",
        "baseline_adjust",
    )
    for field in numeric_fields:
        if not _is_finite_number(processing[field]):
            errors.append(f"{field} must be a finite number")
    if all(
        _is_finite_number(processing[field])
        for field in ("trange_start", "trange_end")
    ) and processing["trange_start"] >= processing["trange_end"]:
        errors.append("trange_start must be less than trange_end")
    if all(
        _is_finite_number(processing[field])
        for field in ("baseline_start", "baseline_end")
    ) and processing["baseline_start"] >= processing["baseline_end"]:
        errors.append("baseline_start must be less than baseline_end")
    if not _is_positive_integer(processing["downsample_factor"]):
        errors.append("downsample_factor must be an integer of at least 1")
    if processing["smooth_factor"] is not None and not _is_positive_integer(
        processing["smooth_factor"]
    ):
        errors.append("smooth_factor must be an integer of at least 1 when provided")
    for field in ("artifact_405", "artifact_465"):
        value = processing[field]
        if value is not None and (not _is_finite_number(value) or float(value) < 0):
            errors.append(f"{field} must be a non-negative finite number or null")
    for channel, overrides in config["channel_settings"].items():
        if not isinstance(overrides, dict):
            errors.append(f"channel_settings.{channel} must be an object")
            continue
        unknown = set(overrides) - {"smooth_factor"}
        if unknown:
            errors.append(
                f"channel_settings.{channel} has unsupported fields: "
                + ", ".join(sorted(unknown))
            )
        smooth_factor = overrides.get("smooth_factor")
        if smooth_factor is None or not _is_positive_integer(smooth_factor):
            errors.append(
                f"channel_settings.{channel}.smooth_factor must be an integer of at least 1"
            )
    for field in ("use_isosbestic", "plot_smoothed", "baseline_correction"):
        if not isinstance(processing[field], bool):
            errors.append(f"{field} must be true or false")
    polynomial_degree = processing["polynomial_degree"]
    try:
        if isinstance(polynomial_degree, bool):
            raise ValueError
        polynomial_degree_int = int(polynomial_degree)
        if float(polynomial_degree) != polynomial_degree_int:
            raise ValueError
    except (TypeError, ValueError):
        errors.append("polynomial_degree must be an integer")
    else:
        if polynomial_degree_int < 1:
            errors.append("polynomial_degree must be at least 1")
    if (
        not isinstance(config["exports"]["figure_format"], str)
        or config["exports"]["figure_format"] not in FIGURE_FORMATS
    ):
        errors.append("figure_format must be one of: pdf, png, tiff")
    if errors:
        raise ConfigError("; ".join(errors))


def resolve_epoc_or_source(
    session: PhotometrySession,
    requested_name: str,
) -> tuple[Epoc, ClassifiedTrialSource | None]:
    if requested_name in session.epocs:
        return session.epocs[requested_name], None
    sources = classified_trial_sources(session)
    for source in sources:
        if requested_name in {source.key, source.label}:
            return source.epoc, source
    available = sorted(session.epocs) + [source.label for source in sources]
    raise ValueError(
        f"epoc or classified source '{requested_name}' not found; "
        f"available: {', '.join(available)}"
    )


def epoc_names_for_config(
    session: PhotometrySession,
    config: dict[str, Any],
) -> list[str]:
    requested = sorted(session.epocs) if config["all_epocs"] else list(config["epocs"])
    policy = config["epoc_policy"]
    if policy == "all":
        return requested

    from photon_cruncher.analysis.runner import epoc_names_for_selection

    groups: dict[tuple[str, str], list[str]] = {}
    unpaired: list[str] = []
    for epoc_name in requested:
        if epoc_name.endswith(("1_", "2_")):
            key = (epoc_name[:-2], "number_underscore")
        elif epoc_name.endswith(("A", "C")):
            key = (epoc_name[:-1], "letter")
        else:
            unpaired.append(epoc_name)
            continue
        groups.setdefault(key, []).append(epoc_name)

    selected = list(unpaired)
    for (base, _family), members in groups.items():
        selected.extend(
            epoc_names_for_selection(
                session,
                (base, tuple(sorted(members)), policy),
            )
        )
    return selected


def analyze_session_epoc(
    session: PhotometrySession,
    epoc: Epoc,
    source: ClassifiedTrialSource | None,
    config: dict[str, Any],
) -> list[AnalysisResult]:
    from photon_cruncher import service

    channel_map = available_channels(session)
    channel_keys = config["channels"] or sorted(channel_map)

    def settings_factory(channel_key: str) -> ProcessingSettings:
        return build_settings(config, channel_key)

    try:
        results = service.analyze(
            session,
            epoc,
            channel_keys=channel_keys,
            settings_factory=settings_factory,
            source=source,
        )
    except ValueError:
        return []

    filtered: list[AnalysisResult] = []
    for result in results:
        try:
            result.processed = filter_processed_trials(result.processed, config)
        except ValueError:
            continue
        filtered.append(result)
    return filtered


def build_settings(config: dict[str, Any], channel_key: str) -> ProcessingSettings:
    processing = config["processing"]
    settings = default_settings_for_channel(channel_key)
    settings.trange = (
        float(processing["trange_start"]),
        float(processing["trange_end"]),
    )
    settings.baseline_per = (
        float(processing["baseline_start"]),
        float(processing["baseline_end"]),
    )
    settings.base_adjust = float(processing["baseline_adjust"])
    settings.downsample_factor = int(processing["downsample_factor"])
    settings.plot_smooth = bool(processing["plot_smoothed"])
    settings.set_baseline = bool(processing["baseline_correction"])
    if processing["smooth_factor"] is not None:
        settings.smooth_factor = int(processing["smooth_factor"])
    channel_smooth = config["channel_settings"].get(channel_key, {}).get(
        "smooth_factor"
    )
    if channel_smooth is not None:
        settings.smooth_factor = int(channel_smooth)
    settings.artifact_405 = _threshold_value(processing["artifact_405"])
    settings.artifact_465 = _threshold_value(processing["artifact_465"])
    settings.use_isosbestic = bool(processing["use_isosbestic"])
    settings.polynomial_degree = int(processing["polynomial_degree"])
    return settings


def annotate_processed_trials(
    processed: Any,
    epoc: Epoc,
    source: ClassifiedTrialSource | None,
) -> None:
    if source is not None:
        trials_by_number = {trial.trial_number: trial for trial in source.trials}
        processed.trial_labels = [
            trials_by_number[number].trial_type if number in trials_by_number else ""
            for number in processed.trial_numbers
        ]
        processed.trial_times = [
            trials_by_number[number].onset
            if number in trials_by_number
            else float("nan")
            for number in processed.trial_numbers
        ]
        return

    processed.trial_labels = []
    processed.trial_times = [
        float(epoc.onset[number - 1]) if 0 < number <= epoc.onset.size else float("nan")
        for number in processed.trial_numbers
    ]


def filter_processed_trials(processed: Any, config: dict[str, Any]) -> Any:
    trial_numbers = [int(number) for number in config["trial_filter"]["trial_numbers"]]
    trial_types = set(config["trial_filter"]["trial_types"])
    if not trial_numbers and not trial_types:
        return processed

    available_numbers = (
        processed.trial_numbers
        if processed.trial_numbers
        else list(range(1, processed.zall.shape[0] + 1))
    )
    available_labels = (
        processed.trial_labels
        if len(processed.trial_labels) == len(available_numbers)
        else [""] * len(available_numbers)
    )
    selected_numbers = set(trial_numbers) if trial_numbers else set(available_numbers)
    if trial_types:
        selected_numbers = {
            number
            for number, label in zip(available_numbers, available_labels)
            if number in selected_numbers and label in trial_types
        }
    return subset_processed_signal(processed, sorted(selected_numbers))


def export_result(
    result: AnalysisResult,
    output_dir: Path,
    config: dict[str, Any],
    export_csv: bool,
    export_figures: bool,
) -> dict[str, Any]:
    csv_path = None
    figure_path = None
    if export_csv:
        csv_path = export_channel(
            output_dir=output_dir,
            session_name=result.session.source_path.stem,
            epoc_name=result.epoc.name,
            channel_key=result.channel_key,
            processed=result.processed,
            settings=result.settings,
            dropped_trials=result.processed.dropped_edge_trials,
            stream_store=result.stream_store,
            metadata={"source_path": str(result.session.source_path), **result.session.info},
            export_smoothed=result.settings.plot_smooth,
        )
    if export_figures:
        figure_path = save_result_figure(
            output_dir,
            result,
            figure_format=config["exports"]["figure_format"],
        )

    processed = result.processed
    return {
        "source_path": str(result.session.source_path),
        "session_name": result.session.source_path.stem,
        "epoc": result.epoc.name,
        "channel": result.channel_key,
        "num_trials": int(processed.zall.shape[0]),
        "num_artifacts": int(processed.num_artifacts),
        "num_edge_trials": int(processed.num_edge_trials),
        "dropped_edge_trials": list(processed.dropped_edge_trials),
        "trial_numbers": list(processed.trial_numbers),
        "trial_labels": list(processed.trial_labels),
        "trial_times": [float(time) for time in processed.trial_times],
        "iso_stream": result.stream_store[0],
        "signal_stream": result.stream_store[1],
        "settings": settings_summary(result.settings),
        "exported_csv": str(csv_path) if csv_path else "",
        "exported_figure": str(figure_path) if figure_path else "",
    }


def settings_summary(settings: ProcessingSettings) -> dict[str, Any]:
    return {
        "trange": list(settings.trange),
        "baseline_per": list(settings.baseline_per),
        "baseline_adjust": settings.base_adjust,
        "downsample_factor": settings.downsample_factor,
        "smooth_factor": settings.smooth_factor,
        "artifact_405": _json_threshold(settings.artifact_405),
        "artifact_465": _json_threshold(settings.artifact_465),
        "use_isosbestic": settings.use_isosbestic,
        "polynomial_degree": settings.polynomial_degree,
        "plot_smoothed": settings.plot_smooth,
        "baseline_correction": settings.set_baseline,
    }


def load_config(path: Path) -> dict[str, Any]:
    try:
        with path.expanduser().open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except OSError as exc:
        raise ConfigError(f"could not read config file: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid JSON config: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError("config file must contain a JSON object")
    return data


def emit_summary(summary: dict[str, Any], summary_json: str | None) -> None:
    if summary_json:
        path = Path(summary_json).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_json_safe(summary), indent=2) + "\n", encoding="utf-8")
    _write_json(summary, sys.stdout)


def _write_json(data: dict[str, Any], stream: Any) -> None:
    stream.write(json.dumps(_json_safe(data), indent=2) + "\n")


def _threshold_value(value: Any) -> float:
    if value is None:
        return float("inf")
    return float(value)


def _json_threshold(value: float) -> float | None:
    if np.isinf(value):
        return None
    return float(value)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def parse_channel_smooth_override(value: str) -> tuple[str, int]:
    channel, separator, raw_factor = value.partition("=")
    channel = channel.strip()
    if not separator or not channel or not _is_positive_integer(raw_factor):
        raise ConfigError(
            f"invalid --channel-smooth value '{value}'; expected CHANNEL=FACTOR "
            "with an integer factor of at least 1"
        )
    return channel, int(raw_factor)


def _is_positive_integer(value: Any) -> bool:
    try:
        if isinstance(value, bool):
            return False
        integer = int(value)
        return float(value) == integer and integer >= 1
    except (TypeError, ValueError):
        return False


def _is_finite_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, int | float)
        and np.isfinite(value)
    )


def _config_object(raw_config: dict[str, Any], name: str) -> dict[str, Any]:
    value = raw_config.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"{name} must be a JSON object")
    return dict(value)


def _config_list(raw_config: dict[str, Any], name: str) -> list[Any]:
    value = raw_config.get(name, [])
    if not isinstance(value, list):
        raise ConfigError(f"{name} must be a JSON array")
    return list(value)


def _flatten(values: Iterable[Iterable[str]]) -> Iterable[str]:
    for group in values:
        yield from group


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.ndarray):
        return _json_safe(value.tolist())
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def trial_type_counts(labels: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for label in labels:
        if not label:
            continue
        counts[label] = counts.get(label, 0) + 1
    return counts


if __name__ == "__main__":
    raise SystemExit(main())
