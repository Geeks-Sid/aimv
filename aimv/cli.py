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

    return rules, move_log, file_index, org_template


# --------------------------------------------------------------------------- #
# Subcommand handlers
# --------------------------------------------------------------------------- #

def cmd_sort(args):
    """Handle the 'sort' subcommand — organize a single file."""
    check_dependencies()

    file_path = args.file_path
    if not os.path.exists(file_path):
        print(f"Error: File '{file_path}' does not exist.")
        sys.exit(1)
    if not os.path.isfile(file_path):
        print(f"Error: Path '{file_path}' is not a file.")
        sys.exit(1)

    rules, move_log, file_index, org_template = _init_subsystems()

    from aimv.core import SmartMover

    try:
        mover = SmartMover(
            file_path,
            rules=rules,
            move_log=move_log,
            file_index=file_index,
            org_template=org_template,
            dry_run=getattr(args, "dry_run", False),
        )
        mover.sort_file()
    except Exception as e:
        print(f"Critical error: {e}")
        traceback.print_exc()
        sys.exit(1)


def cmd_batch(args):
    """Handle the 'batch' subcommand — organize all files in a directory."""
    check_dependencies()

    directory = args.directory
    if not os.path.isdir(directory):
        print(f"Error: '{directory}' is not a directory.")
        sys.exit(1)

    rules, move_log, file_index, org_template = _init_subsystems()

    from aimv.core import SmartMover

    files = [
        os.path.join(directory, f)
        for f in sorted(os.listdir(directory))
        if os.path.isfile(os.path.join(directory, f))
        and not f.startswith(".")
    ]

    if not files:
        print(f"No files found in '{directory}'.")
        return

    print(f"Found {len(files)} files to process in '{directory}'.\n")
    dry_run = getattr(args, "dry_run", False)
    successes, failures = 0, 0

    for i, file_path in enumerate(files, 1):
        print(f"\n{'='*60}")
        print(f"[{i}/{len(files)}] Processing: {os.path.basename(file_path)}")
        print(f"{'='*60}")
        try:
            mover = SmartMover(
                file_path,
                rules=rules,
                move_log=move_log,
                file_index=file_index,
                org_template=org_template,
                dry_run=dry_run,
            )
            mover.sort_file()
            successes += 1
        except Exception as e:
            print(f"Error processing {file_path}: {e}")
            failures += 1

    print(f"\n{'='*60}")
    print(f"Batch complete: {successes} succeeded, {failures} failed out of {len(files)} files.")


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


def cmd_init(args):
    """Handle the 'init' subcommand — initialize ~/.aimv/ data directory."""
    ensure_data_dir()
    print(f"Initialized AIMV data directory: {config.AIMV_DATA_DIR}")
    print(f"  Logs:     {config.AIMV_LOG_DIR}/")
    print(f"  Rules:    {config.AIMV_USER_RULES_DIR}/")
    print(f"  Index:    {config.AIMV_INDEX_PATH}")
    print(f"  Template: {config.AIMV_TEMPLATE_PATH}")

    from aimv.templates.org_template import OrgTemplate

    if not os.path.exists(config.AIMV_TEMPLATE_PATH):
        print("\nGenerating initial organization template...")
        org_template = OrgTemplate(config.AIMV_TEMPLATE_PATH)
        org_template.generate(config.TEMPLATE_ROOT_DIRS, config.TEMPLATE_SCAN_DEPTH)
        org_template.save()
        print(f"Template saved.")

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
