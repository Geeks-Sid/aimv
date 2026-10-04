"""
Command line interface for the AIMV tool.

Usage:
    aimv [OPTIONS] FILE_PATH              # Shorthand for 'aimv sort FILE_PATH'
    aimv sort [OPTIONS] FILE_PATH         # Organize a file
    aimv batch [OPTIONS] DIRECTORY        # Organize all files in a directory
    aimv undo [--last | --id ID]          # Reverse a move operation
    aimv log [--last N | --search QUERY]  # View movement history
    aimv index [search QUERY | list]      # Query the file index
    aimv rules [list | show NAME]         # View loaded rules
    aimv template [show | generate]       # Manage organization template
    aimv init                             # Initialize ~/.aimv/ data directory
"""

import os
import sys
import argparse
import traceback

from aimv import __version__
from aimv import config
from aimv.config import check_dependencies, ensure_data_dir, load_user_config


def _init_subsystems():
    """Initialize the shared subsystems (rules, log, index, template)."""
    from aimv.rules.loader import load_all_rules
    from aimv.tracking.move_log import MoveLog
    from aimv.index.file_index import FileIndex
    from aimv.templates.org_template import OrgTemplate
    from aimv.taxonomy.catalog import TaxonomyCatalog

    ensure_data_dir()
    load_user_config()

    rules = load_all_rules(config.AIMV_USER_RULES_DIR) if config.ENABLE_RULES_ENGINE else []
    move_log = MoveLog(config.AIMV_LOG_DIR) if config.ENABLE_MOVE_LOGGING else None
    file_index = FileIndex(config.AIMV_INDEX_PATH) if config.ENABLE_FILE_INDEX else None

    org_template = None
    if config.ENABLE_ORG_TEMPLATE:
        org_template = OrgTemplate(config.AIMV_TEMPLATE_PATH)
        if os.path.exists(config.AIMV_TEMPLATE_PATH):
            org_template.load()

    catalog = TaxonomyCatalog.load_default(config.AIMV_TAXONOMY_ROOT)

    return rules, move_log, file_index, org_template, catalog


# --------------------------------------------------------------------------- #
# Subcommand handlers
# --------------------------------------------------------------------------- #

def cmd_sort(args):
    """Handle the 'sort' subcommand — organize a single file."""
    dependencies = check_dependencies()

    file_path = args.file_path
    if not os.path.exists(file_path):
        print(f"Error: File '{file_path}' does not exist.")
        sys.exit(1)
    if not os.path.isfile(file_path):
        print(f"Error: Path '{file_path}' is not a file.")
        sys.exit(1)

    rules, move_log, file_index, org_template, catalog = _init_subsystems()

    if getattr(args, "no_rules", False):
        rules = []
    elif getattr(args, "rule", None):
        forced = [rule for rule in rules if rule.name == args.rule]
        if not forced:
            print(f"Error: No rule named '{args.rule}'.")
            sys.exit(1)
        rules = forced

    from aimv.core import SmartMover

    try:
        mover = SmartMover(
            file_path,
            rules=rules,
            move_log=move_log,
            file_index=file_index,
            org_template=org_template,
            dry_run=getattr(args, "dry_run", False),
            catalog=catalog,
            dependencies=dependencies,
        )
        outcome = mover.sort_file()
        if outcome.status == "failed":
            sys.exit(1)
    except Exception as e:
        print(f"Critical error: {e}")
        traceback.print_exc()
        sys.exit(1)


def cmd_batch(args):
    """Handle the 'batch' subcommand — organize all files in a directory."""
    dependencies = check_dependencies()

    directory = args.directory
    if not os.path.isdir(directory):
        print(f"Error: '{directory}' is not a directory.")
        sys.exit(1)

    rules, move_log, file_index, org_template, catalog = _init_subsystems()

    from aimv.batch import BatchOrganizer
    from aimv.core import create_file_classifier
    from aimv.organization.committer import OrganizationCommitter

    files = [
        os.path.join(directory, f)
        for f in sorted(os.listdir(directory))
        if os.path.isfile(os.path.join(directory, f))
        and not f.startswith(".")
    ]

    if not files:
        print(f"No files found in '{directory}'.")
        return

    workers = max(1, getattr(args, "workers", config.BATCH_CLASSIFICATION_WORKERS))
    print(
        f"Found {len(files)} files. Classifying with up to {workers} parallel workers.\n"
    )
    dry_run = getattr(args, "dry_run", False)
    classifier = create_file_classifier(
        rules=rules,
        catalog=catalog,
        dependencies=dependencies,
    )
    committer = OrganizationCommitter(
        catalog=catalog,
        move_log=move_log,
        file_index=file_index,
        dry_run=dry_run,
    )

    def report_progress(completed, total, path):
        print(f"[{completed}/{total}] Classified {os.path.basename(path)}")

    summary = BatchOrganizer(
        classifier,
        committer,
        workers=workers,
        on_classified=report_progress,
    ).run(files)

    print("\nResults:")
    for outcome in summary.outcomes:
        destination = f" -> {outcome.destination_path}" if outcome.destination_path else ""
        print(f"  [{outcome.status}] {os.path.basename(outcome.source_path)}{destination}")
        if outcome.status in {"failed", "skipped"}:
            print(f"    {outcome.message}")
    print(
        f"\nBatch complete: {summary.succeeded} succeeded, {summary.skipped} skipped, "
        f"{summary.failed} failed out of {len(files)} files."
    )


def cmd_undo(args):
    """Handle the 'undo' subcommand — reverse a move operation."""
    ensure_data_dir()

    from aimv.tracking.move_log import MoveLog
    from aimv.index.file_index import FileIndex
    from aimv.tracking.undo import UndoManager

    move_log = MoveLog(config.AIMV_LOG_DIR)
    file_index = FileIndex(config.AIMV_INDEX_PATH)
    undo_mgr = UndoManager(move_log, file_index)

    if args.id:
        success, msg = undo_mgr.undo_by_id(args.id)
    else:
        success, msg = undo_mgr.undo_last()

    print(msg)
    sys.exit(0 if success else 1)


def cmd_log(args):
    """Handle the 'log' subcommand — view movement history."""
    ensure_data_dir()

    from aimv.tracking.move_log import MoveLog

    move_log = MoveLog(config.AIMV_LOG_DIR)

    if args.search:
        records = move_log.search(args.search)
        if not records:
            print(f"No log entries matching '{args.search}'.")
            return
        print(f"Found {len(records)} matching entries:\n")
    else:
        n = args.last if args.last else 10
        records = move_log.get_last(n)
        if not records:
            print("No movement history yet.")
            return
        print(f"Last {len(records)} operations:\n")

    for r in records:
        status = "[UNDONE]" if r.reversed else "[ACTIVE]"
        rule_info = f" (rule: {r.rule_applied})" if r.rule_applied else ""
        print(f"  {status} {r.id}  {r.timestamp[:19]}")
        print(f"    {r.action}{rule_info}")
        print(f"    From: {r.source_path}")
        print(f"    To:   {r.destination_path}")
        if r.summary:
            print(f"    Summary: {r.summary[:80]}")
        print()


def cmd_index(args):
    """Handle the 'index' subcommand — query the file index."""
    ensure_data_dir()

    from aimv.index.file_index import FileIndex

    file_index = FileIndex(config.AIMV_INDEX_PATH)
    file_index.load()

    sub = args.index_action

    if sub == "search" and args.query:
        results = file_index.search(args.query)
        if not results:
            print(f"No index entries matching '{args.query}'.")
            return
        print(f"Found {len(results)} entries:\n")
        for entry in results:
            print(f"  [{entry.category}] {entry.path}")
            print(f"    {entry.description[:80]}")
            print()

    elif sub == "list":
        entries = file_index.list_all()
        if not entries:
            print("File index is empty.")
            return
        print(file_index.to_summary_string())

    else:
        entries = file_index.list_all()
        if not entries:
            print("File index is empty.")
        else:
            print(file_index.to_summary_string())


def cmd_rules(args):
    """Handle the 'rules' subcommand — view loaded rules."""
    from aimv.rules.loader import load_all_rules

    ensure_data_dir()
    rules = load_all_rules(config.AIMV_USER_RULES_DIR)

    if args.show:
        found = [r for r in rules if r.name == args.show]
        if not found:
            print(f"No rule named '{args.show}'. Available: {', '.join(r.name for r in rules)}")
            sys.exit(1)
        rule = found[0]
        print(f"Rule: {rule.name}")
        print(f"  Description: {rule.description}")
        print(f"  Priority: {rule.priority}")
        print(f"  Keywords: {', '.join(rule.keywords)}")
        print(f"  Filename patterns: {', '.join(rule.filename_patterns)}")
        print(f"  Target folder: {rule.target_folder}")
        print(f"  Naming template: {rule.naming.template}")
        print(f"  Naming case: {rule.naming.case}")
        print(f"  Metadata fields: {', '.join(rule.metadata_fields)}")
        print(f"  Create subfolders: {rule.create_subfolders}")
        if rule.examples:
            print(f"  Examples:")
            for ex in rule.examples:
                print(f"    {ex.get('input', '?')} -> {ex.get('output', '?')}")
    else:
        if not rules:
            print("No rules loaded.")
            return
        print(f"Loaded {len(rules)} rules:\n")
        for rule in rules:
            kw_preview = ", ".join(rule.keywords[:4])
            if len(rule.keywords) > 4:
                kw_preview += "..."
            print(f"  {rule.name:20s} (priority: {rule.priority:2d}) — {rule.description[:50]}")
            print(f"    Keywords: {kw_preview}")
            print(f"    Target:   {rule.target_folder}")
            print()


def cmd_template(args):
    """Handle the 'template' subcommand — view or regenerate the org template."""
    ensure_data_dir()

    from aimv.templates.org_template import OrgTemplate

    org_template = OrgTemplate(config.AIMV_TEMPLATE_PATH)

    if args.template_action == "generate":
        print("Scanning filesystem to generate organization template...")
        org_template.generate(config.TEMPLATE_ROOT_DIRS, config.TEMPLATE_SCAN_DEPTH)
        org_template.save()
        print(f"Template saved to {config.AIMV_TEMPLATE_PATH}")
        print()
        print(org_template.build_prompt_context())
    else:
        if os.path.exists(config.AIMV_TEMPLATE_PATH):
            org_template.load()
            ctx = org_template.build_prompt_context()
            if ctx:
                print(ctx)
            else:
                print("Template is empty. Run 'aimv template generate' to create one.")
        else:
            print("No template found. Run 'aimv template generate' to create one.")


def cmd_usage(args):
    """Handle the 'usage' subcommand — view or reset API usage stats."""
    ensure_data_dir()

    from aimv.utils.api_usage import get_tracker

    tracker = get_tracker(
        config.AIMV_USAGE_PATH,
        config.MAX_API_CALLS_PER_DAY,
        config.MAX_API_CALLS_PER_MINUTE,
    )

    if getattr(args, "reset", False):
        tracker.reset_today()
        print("Today's API usage counter has been reset.")
        return

    print(tracker.get_summary())


def cmd_taxonomy(args):
    """Install, inspect, search, or validate the managed folder taxonomy."""
    from aimv.taxonomy.catalog import TaxonomyCatalog

    catalog = TaxonomyCatalog.load_default(
        getattr(args, "root", None) or config.AIMV_TAXONOMY_ROOT
    )
    action = args.taxonomy_action

    if action == "install":
        written = catalog.materialize(
            overwrite_metadata=getattr(args, "force", False)
        )
        print(f"Installed {len(catalog.buckets)} buckets under {catalog.root}")
        print(f"Wrote {written} hidden metadata files.")
    elif action == "search":
        matches = catalog.search(args.query, args.limit)
        for match in matches:
            print(
                f"{match.bucket.id:22s} score={match.score:5.1f}  "
                f"{match.bucket.relative_path}"
            )
            print(f"  {match.bucket.purpose}")
    elif action == "validate":
        errors = catalog.validate()
        if errors:
            for error in errors:
                print(f"ERROR: {error}")
            sys.exit(1)
        print(
            f"Taxonomy valid: {len(catalog.nodes)} managed folders, "
            f"{len(catalog.buckets)} leaf buckets."
        )
    else:
        print(
            f"AIMV taxonomy: {len(catalog.buckets)} leaf buckets under {catalog.root}\n"
        )
        for node in catalog.nodes:
            if node.kind == "area":
                area_prefix = node.code + "."
                count = sum(
                    bucket.code.startswith(area_prefix) for bucket in catalog.buckets
                )
                print(f"  {node.code:>3s}  {node.title} ({count} buckets)")


def cmd_init(args):
    """Handle the 'init' subcommand — initialize ~/.aimv/ data directory."""
    ensure_data_dir()
    print(f"Initialized AIMV data directory: {config.AIMV_DATA_DIR}")
    print(f"  Logs:     {config.AIMV_LOG_DIR}/")
    print(f"  Rules:    {config.AIMV_USER_RULES_DIR}/")
    print(f"  Index:    {config.AIMV_INDEX_PATH}")
    print(f"  Template: {config.AIMV_TEMPLATE_PATH}")
    print(f"  Taxonomy: {config.AIMV_TAXONOMY_ROOT}")

    from aimv.templates.org_template import OrgTemplate

    if not os.path.exists(config.AIMV_TEMPLATE_PATH):
        print("\nGenerating initial organization template...")
        org_template = OrgTemplate(config.AIMV_TEMPLATE_PATH)
        org_template.generate(config.TEMPLATE_ROOT_DIRS, config.TEMPLATE_SCAN_DEPTH)
        org_template.save()
        print(f"Template saved.")

    from aimv.taxonomy.catalog import TaxonomyCatalog

    catalog = TaxonomyCatalog.load_default(config.AIMV_TAXONOMY_ROOT)
    written = catalog.materialize()
    print(
        f"Installed {len(catalog.buckets)} managed buckets "
        f"({written} metadata files written)."
    )

    print("\nAIMV is ready. Use 'aimv sort <file>' to organize a file.")


# --------------------------------------------------------------------------- #
# Argument parser
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Smart Move (aimv) — AI-powered file organization tool",
        epilog="Run 'aimv <command> --help' for details on each command.",
    )
    parser.add_argument(
        "-v", "--version", action="version", version=f"AIMV v{__version__}"
    )

    subparsers = parser.add_subparsers(dest="command")

    # --- sort ---
    p_sort = subparsers.add_parser("sort", help="Organize a single file")
    p_sort.add_argument("file_path", help="Path to the file to organize")
    p_sort.add_argument("--dry-run", action="store_true", help="Preview without moving")
    p_sort.add_argument("--rule", type=str, default=None, help="Force a specific rule by name")
    p_sort.add_argument("--no-rules", action="store_true", help="Skip the rules engine")
    p_sort.set_defaults(func=cmd_sort)

    # --- batch ---
    p_batch = subparsers.add_parser("batch", help="Organize all files in a directory")
    p_batch.add_argument("directory", help="Directory containing files to organize")
    p_batch.add_argument("--dry-run", action="store_true", help="Preview without moving")
    p_batch.add_argument(
        "--workers",
        type=int,
        default=config.BATCH_CLASSIFICATION_WORKERS,
        help="Maximum concurrent classification requests",
    )
    p_batch.set_defaults(func=cmd_batch)

    # --- undo ---
    p_undo = subparsers.add_parser("undo", help="Reverse a move operation")
    p_undo.add_argument("--id", type=str, default=None, help="Specific move ID to undo")
    p_undo.add_argument("--last", action="store_true", default=True, help="Undo last move (default)")
    p_undo.set_defaults(func=cmd_undo)

    # --- log ---
    p_log = subparsers.add_parser("log", help="View movement history")
    p_log.add_argument("--last", type=int, default=None, help="Show last N entries")
    p_log.add_argument("--search", type=str, default=None, help="Search log entries")
    p_log.set_defaults(func=cmd_log)

    # --- index ---
    p_index = subparsers.add_parser("index", help="Query the file index")
    p_index.add_argument("index_action", nargs="?", default="list",
                         choices=["list", "search"], help="Action (default: list)")
    p_index.add_argument("query", nargs="?", default=None, help="Search query")
    p_index.set_defaults(func=cmd_index)

    # --- rules ---
    p_rules = subparsers.add_parser("rules", help="View loaded organization rules")
    p_rules.add_argument("--show", type=str, default=None, help="Show details of a specific rule")
    p_rules.set_defaults(func=cmd_rules)

    # --- template ---
    p_template = subparsers.add_parser("template", help="Manage organization template")
    p_template.add_argument("template_action", nargs="?", default="show",
                            choices=["show", "generate"], help="Action (default: show)")
    p_template.set_defaults(func=cmd_template)

    # --- usage ---
    p_usage = subparsers.add_parser("usage", help="View or reset daily API usage")
    p_usage.add_argument("--reset", action="store_true", help="Reset today's usage counter")
    p_usage.set_defaults(func=cmd_usage)

    # --- taxonomy ---
    p_taxonomy = subparsers.add_parser(
        "taxonomy", help="Manage the searchable 200+ bucket folder taxonomy"
    )
    p_taxonomy.add_argument(
        "taxonomy_action",
        nargs="?",
        default="list",
        choices=["list", "search", "install", "validate"],
    )
    p_taxonomy.add_argument("query", nargs="?", default="")
    p_taxonomy.add_argument("--limit", type=int, default=12)
    p_taxonomy.add_argument("--root", default=None, help="Override the managed root")
    p_taxonomy.add_argument(
        "--force", action="store_true", help="Refresh existing folder metadata"
    )
    p_taxonomy.set_defaults(func=cmd_taxonomy)

    # --- init ---
    p_init = subparsers.add_parser("init", help="Initialize ~/.aimv/ data directory")
    p_init.set_defaults(func=cmd_init)

    return parser


def main():
    """Main entry point for the AIMV command line tool."""
    parser = build_parser()

    # Backward compatibility: bare 'aimv <file>' without subcommand defaults to sort
    args = parser.parse_args()

    if args.command is None:
        # Check if there's a positional argument that looks like a file path
        remaining = sys.argv[1:]
        if remaining and not remaining[0].startswith("-"):
            potential_path = remaining[0]
            if os.path.exists(potential_path) or not potential_path.startswith("-"):
                # Re-parse as 'sort <file>'
                args = parser.parse_args(["sort"] + remaining)
            else:
                parser.print_help()
                sys.exit(0)
        else:
            parser.print_help()
            sys.exit(0)

    print(f"Smart Move v{__version__}")

    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()

    print("\n--- End of Script ---")


if __name__ == "__main__":
    main()
