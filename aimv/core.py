import json
import os
import re
import argparse
from typing import Any, Dict, List, Optional

from aimv import config
from aimv.analyzers.image_analyzer import ImageAnalyzer
from aimv.analyzers.text_analyzer import TextAnalyzer
from aimv.utils import file_utils, llm_utils
from aimv.utils.api_usage import get_tracker
from aimv.rules.models import CategoryRule
from aimv.rules.matcher import match_file, build_rule_context_for_prompt
from aimv.tracking.move_log import MoveLog, MoveRecord
from aimv.index.file_index import FileIndex, IndexEntry
from aimv.templates.org_template import OrgTemplate


class SmartMover:
    """
    AI-driven file organizer.  Gathers file metadata and folder context
    locally, makes a **single** LLM call that returns a compact JSON
    decision, then executes the move/rename/trash action.
    """

    def __init__(
        self,
        file_path_to_sort: str,
        rules: Optional[List[CategoryRule]] = None,
        move_log: Optional[MoveLog] = None,
        file_index: Optional[FileIndex] = None,
        org_template: Optional[OrgTemplate] = None,
        dry_run: bool = False,
    ):
        self.file_path = os.path.abspath(file_path_to_sort)
        if not os.path.exists(self.file_path):
            raise FileNotFoundError(f"File not found: {self.file_path}")
        if not os.path.isfile(self.file_path):
            raise ValueError(f"Path is not a file: {self.file_path}")

        usage_tracker = get_tracker(
            config.AIMV_USAGE_PATH,
            config.MAX_API_CALLS_PER_DAY,
            config.MAX_API_CALLS_PER_MINUTE,
        )
        self.llm_helper = llm_utils.LLMHelper(
            api_key=config.OPENAI_API_KEY,
            base_url=config.OPENAI_API_BASE_URL,
            model_name=config.MODEL_NAME,
            max_retries=config.MAX_LLM_RETRIES_ON_PARSE_ERROR,
            usage_tracker=usage_tracker,
        )
        self.file_summary = "Not yet summarized."
        self.home_dir = os.path.expanduser("~")
        self.trash_dir = os.path.join(self.home_dir, ".Trash")
        self.dry_run = dry_run
        self._decision_tags: List[str] = []

        self.rules = rules or []
        self.move_log = move_log
        self.file_index = file_index
        self.org_template = org_template
        self.matched_rule: Optional[CategoryRule] = None

        if self.rules and config.ENABLE_RULES_ENGINE:
            self.matched_rule = match_file(self.file_path, "", self.rules)

        self.pypdf_installed, self.pillow_installed, self.pdf2image_installed = (
            config.check_dependencies()
        )

    # ------------------------------------------------------------------
    # Context gathering (replaces multi-step LLM calls)
    # ------------------------------------------------------------------

    def _gather_context(self) -> Dict[str, Any]:
        """Collect all file metadata, content, and folder context locally."""
        _, ext = os.path.splitext(self.file_path)
        ext = ext.lower()
        file_age = file_utils.get_file_age_description(self.file_path)
        try:
            file_size = os.path.getsize(self.file_path)
        except OSError:
            file_size = 0
        file_type = TextAnalyzer.get_file_type_description(self.file_path)

        content_text = ""
        image_b64 = None

        if config.ALLOW_LLM_FILE_PROCESSING:
            try:
                if ext == ".pdf" and self.pypdf_installed:
                    ok, text = TextAnalyzer.extract_from_pdf(
                        self.file_path, config.MAX_EXTRACTED_TEXT_SIZE_KB
                    )
                    if ok and len(text.strip()) >= config.MIN_MEANINGFUL_TEXT_LENGTH:
                        content_text = text[:3000]
                    elif (
                        config.ALLOW_LLM_IMAGE_PROCESSING
                        and self.pdf2image_installed
                        and self.pillow_installed
                    ):
                        image_b64 = ImageAnalyzer.pdf_to_image(
                            self.file_path,
                            config.MAX_IMAGE_RESOLUTION_FOR_LLM,
                            config.IMAGE_QUALITY_FOR_LLM,
                        )
                elif TextAnalyzer.is_text_file(self.file_path):
                    ok, text = TextAnalyzer.extract_from_text_file(
                        self.file_path, config.MAX_EXTRACTED_TEXT_SIZE_KB
                    )
                    if ok and len(text.strip()) >= config.MIN_MEANINGFUL_TEXT_LENGTH:
                        content_text = text[:3000]
                elif (
                    ImageAnalyzer.is_image_file(self.file_path)
                    and config.ALLOW_LLM_IMAGE_PROCESSING
                    and self.pillow_installed
                ):
                    image_b64 = ImageAnalyzer.process_image(
                        self.file_path,
                        config.MAX_IMAGE_RESOLUTION_FOR_LLM,
                        config.IMAGE_QUALITY_FOR_LLM,
                    )
            except Exception as e:
                print(f"Content extraction error: {e}")

        archive_info = ""
        extracted = file_utils.check_if_archive_extracted(
            self.file_path, config.ARCHIVE_EXTENSIONS
        )
        if extracted:
            archive_info = f"Already extracted to '{os.path.basename(extracted)}'"

        deletable = ext in config.DELETABLE_CANDIDATE_EXTENSIONS

        # Folder structure from org template or fallback to home listing
        folders_ctx = ""
        if self.org_template and config.ENABLE_ORG_TEMPLATE:
            folders_ctx = self.org_template.build_prompt_context()
        if not folders_ctx:
            try:
                dirs = sorted(
                    d
                    for d in os.listdir(self.home_dir)
                    if os.path.isdir(os.path.join(self.home_dir, d))
                    and not d.startswith(".")
                )
                folders_ctx = "Home folders:\n" + "\n".join(
                    f"  ~/{d}/" for d in dirs[:25]
                )
            except OSError:
                folders_ctx = ""

        rule_ctx = ""
        if self.matched_rule:
            rule_ctx = build_rule_context_for_prompt(self.matched_rule)

        custom_instructions = ""
        if config.CUSTOM_AI_INSTRUCTIONS and config.CUSTOM_AI_INSTRUCTIONS.strip():
            custom_instructions = config.CUSTOM_AI_INSTRUCTIONS.strip()

        return {
            "name": os.path.basename(self.file_path),
            "path": self.file_path,
            "ext": ext,
            "type": file_type,
            "age": file_age,
            "size": file_size,
            "content_text": content_text,
            "image_b64": image_b64,
            "archive_info": archive_info,
            "deletable": deletable,
            "folders_ctx": folders_ctx,
            "rule_ctx": rule_ctx,
            "custom_instructions": custom_instructions,
        }

    # ------------------------------------------------------------------
    # Single unified prompt
    # ------------------------------------------------------------------

    def _build_unified_prompt(self, ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Build one compact prompt that decides action + destination + rename + tags."""
        system = (
            "You are a file organizer. You MUST respond with a single JSON object and NOTHING else. "
            "No explanation, no markdown, no bullet points — just the raw JSON.\n\n"
            "Example input:\n"
            "FILE: receipt_nike_2024.pdf | ~/Downloads/receipt_nike_2024.pdf | PDF document | 30 days old | 95KB\n"
            "FOLDERS:\n  ~/Documents/\n    Financial/\n      Receipts/\n\n"
            "Example response:\n"
            '{"action":"move","dst":"/Users/user/Documents/Financial/Receipts",'
            '"name":"2024_Nike_Receipt.pdf","sub":null,'
            '"tags":["receipt","nike","purchase"],"conf":0.92}\n\n'
            "Field reference:\n"
            "action: move | trash | stay\n"
            "dst: full destination folder path picked from FOLDERS (expand ~ to absolute)\n"
            "name: improved filename with key details (date/vendor/topic), keep extension, or null to keep original\n"
            "sub: null (STRONGLY prefer null — only use if absolutely no existing folder fits)\n"
            "tags: 3-5 descriptive keywords\n"
            "conf: confidence 0.0-1.0\n\n"
            "STRICT RULES (follow these exactly):\n"
            "1. ALWAYS pick an EXISTING folder from FOLDERS. Do NOT invent new paths.\n"
            "2. sub MUST be null unless no existing folder remotely fits. Almost never create subfolders.\n"
            "3. MAXIMUM folder depth is 2 levels under ~/Documents/ (e.g. ~/Documents/Financial/Receipts/ is OK, "
            "~/Documents/Financial/Receipts/2024/January/ is TOO DEEP).\n"
            "4. NEVER create duplicate categories. If 'Research' already exists, do NOT put research files "
            "in School/Research/ or Work/Research/ — use the existing Research/ folder.\n"
            "5. Research papers, academic papers, and publications ALL go to ONE folder — do not scatter them "
            "across Research/, Research_Papers/, School/Research/, Academic/, etc.\n"
            "6. Prefer FLAT organization: many files in one folder is fine. Avoid creating subcategories.\n"
            "7. Encode distinguishing info (date, vendor, topic, course) in the FILENAME, not in folder nesting.\n"
            "8. Old files in Downloads → move or trash. Match naming patterns of existing files in target folder."
        )

        size = ctx["size"]
        size_str = (
            f"{size / 1024:.0f}KB" if size < 1_048_576 else f"{size / 1_048_576:.1f}MB"
        )
        parts = [
            f"FILE: {ctx['name']} | {ctx['path']} | {ctx['type']} | {ctx['age']} | {size_str}"
        ]

        if ctx["archive_info"]:
            parts.append(f"NOTE: {ctx['archive_info']} — original archive is trash candidate")
        if ctx["deletable"]:
            parts.append("NOTE: Temp/installer type, trash candidate if old")
        if ctx["content_text"]:
            parts.append(f"CONTENT:\n{ctx['content_text'][:2000]}")
        if ctx["folders_ctx"]:
            parts.append(f"FOLDERS:\n{ctx['folders_ctx']}")
        if ctx["rule_ctx"]:
            parts.append(f"RULE:\n{ctx['rule_ctx']}")
        if ctx["custom_instructions"]:
            parts.append(f"GUIDELINES:\n{ctx['custom_instructions']}")

        parts.append("\nRespond with the JSON object only:")

        user_text = "\n".join(parts)

        messages: List[Dict[str, Any]] = [{"role": "system", "content": system}]

        if ctx["image_b64"]:
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{ctx['image_b64']}"
                            },
                        },
                    ],
                }
            )
        else:
            messages.append({"role": "user", "content": user_text})

        return messages

    # ------------------------------------------------------------------
    # Decision execution
    # ------------------------------------------------------------------

    def _execute_decision(self, decision: dict) -> None:
        """Validate the JSON decision and execute the file operation."""
        action = (decision.get("action") or "").lower().strip()
        confidence = float(decision.get("conf", decision.get("confidence", 0.0)))
        dst = (decision.get("dst") or "").strip()
        new_name = decision.get("name")
        subfolder = decision.get("sub")

        _null_values = {"null", "none", "no", ""}
        if new_name and str(new_name).lower() in _null_values:
            new_name = None
        if subfolder and str(subfolder).lower() in _null_values:
            subfolder = None

        display_name = new_name or os.path.basename(self.file_path)
        print(
            f"  action={action}  dst={dst or 'N/A'}  name={new_name or 'keep'}  "
            f"sub={subfolder or 'none'}  conf={confidence:.2f}"
        )

        if action == "stay":
            if confidence >= config.HIGH_CONFIDENCE or input(
                f"AI suggests STAY (conf: {confidence:.2f}). Confirm? (Y/n): "
            ).lower() != "n":
                print("File stays in place.")
            return

        if action == "trash":
            if input(
                f"Move '{os.path.basename(self.file_path)}' to Trash? (y/N): "
            ).lower() == "y":
                self._do_move(
                    {
                        "action": "move_to_trash",
                        "target_folder": config.TRASH_DESTINATION_IDENTIFIER,
                        "create_new_folder": None,
                        "new_file_name": None,
                        "confidence": confidence,
                    }
                )
            return

        if action != "move":
            print(f"Unknown action '{action}'. Aborting.")
            return

        if not dst:
            print("No destination provided. Aborting.")
            return

        if dst.startswith("~"):
            dst = os.path.expanduser(dst)

        if not os.path.isdir(dst):
            if input(f"'{dst}' doesn't exist. Create? (y/N): ").lower() == "y":
                try:
                    os.makedirs(dst, exist_ok=True)
                except OSError as e:
                    print(f"Cannot create directory: {e}")
                    return
            else:
                return

        move_details = {
            "action": "move",
            "target_folder": dst,
            "create_new_folder": subfolder,
            "new_file_name": new_name,
            "confidence": confidence,
        }

        display_dst = os.path.join(dst, subfolder) if subfolder else dst

        if confidence >= config.HIGH_CONFIDENCE:
            print(f"  → {display_name} → {display_dst}")
            self._do_move(move_details)
        elif confidence >= config.MEDIUM_CONFIDENCE:
            if input(
                f"Move '{display_name}' → '{display_dst}'? (y/N): "
            ).lower() == "y":
                self._do_move(move_details)
            else:
                print("Declined.")
        else:
            print(f"Confidence too low ({confidence:.2f}). Aborting.")

    # ------------------------------------------------------------------
    # sort_file — single-step entry point
    # ------------------------------------------------------------------

    def sort_file(self):
        """Organize a file in a single LLM call: gather context → JSON decision → execute."""
        print(f"\n--- Smart Mover: {os.path.basename(self.file_path)} ---")

        ctx = self._gather_context()

        # Refine rule match now that we have file content
        if ctx["content_text"] and self.rules and config.ENABLE_RULES_ENGINE:
            refined = match_file(self.file_path, ctx["content_text"][:500], self.rules)
            if refined and (
                not self.matched_rule or refined.name != self.matched_rule.name
            ):
                self.matched_rule = refined
                ctx["rule_ctx"] = build_rule_context_for_prompt(refined)
                print(f"Rule matched: '{refined.name}'")

        messages = self._build_unified_prompt(ctx)

        print("Calling AI...")
        decision = self.llm_helper.call_llm_json(
            messages,
            temperature=config.LLM_TEMPERATURE,
            max_tokens=config.MAX_TOKENS_UNIFIED,
        )

        if not decision:
            print("AI decision failed. Aborting.")
            return

        print(f"AI response: {json.dumps(decision)}")

        # Store metadata for logging / indexing
        self.file_summary = (
            ctx["content_text"][:200] if ctx["content_text"] else ctx["type"]
        )
        self._decision_tags = decision.get("tags", [])

        self._execute_decision(decision)
        print(f"--- Done: {os.path.basename(self.file_path)} ---")

    # ------------------------------------------------------------------
    # File move execution (kept from original)
    # ------------------------------------------------------------------

    def _do_move(self, decision_details: dict) -> None:
        """Execute the physical file move / rename / trash operation."""
        self.step8_execute_move(decision_details)

    def step8_execute_move(self, decision_details):
        print(f"\n--- Step 8: Executing File Move ---")
        target_path_from_decision = decision_details["target_folder"]
        action = decision_details["action"]
        final_destination_path, is_trash_move_intent = (
            None,
            (
                action == "move_to_trash"
                or target_path_from_decision == config.TRASH_DESTINATION_IDENTIFIER
            ),
        )
        created_dirs: list = []

        if is_trash_move_intent:
            if not os.path.exists(self.trash_dir):
                try:
                    os.makedirs(self.trash_dir)
                except OSError as e:
                    print(f"Error creating Trash {self.trash_dir}: {e}.")
                    return
            base_name = os.path.basename(self.file_path)
            final_destination_path = os.path.join(self.trash_dir, base_name)
            counter = 1
            temp_base, temp_ext = os.path.splitext(final_destination_path)
            while os.path.exists(final_destination_path):
                final_destination_path = f"{temp_base}_{counter}{temp_ext}"
                counter += 1
            print(
                f"Preparing to move '{self.file_path}' to Trash at '{final_destination_path}'"
            )
        else:
            target_folder_base = target_path_from_decision
            new_subfolder, new_filename = (
                decision_details.get("create_new_folder"),
                decision_details.get("new_file_name"),
            )
            if not target_folder_base:
                print("Error: Target folder undefined.")
                return
            final_target_folder = os.path.normpath(target_folder_base)
            if new_subfolder:
                final_target_folder = os.path.join(final_target_folder, new_subfolder)
                if not os.path.exists(final_target_folder):
                    try:
                        os.makedirs(final_target_folder)
                        created_dirs.append(final_target_folder)
                        print(f"Created subfolder: {final_target_folder}")
                    except OSError as e:
                        print(
                            f"Error creating subfolder {final_target_folder}: {e}. Using base."
                        )
                        final_target_folder = os.path.normpath(target_folder_base)
                elif not os.path.isdir(final_target_folder):
                    print(f"Error: {final_target_folder} not a dir. Using base.")
                    final_target_folder = os.path.normpath(target_folder_base)
            final_basename = (
                new_filename if new_filename else os.path.basename(self.file_path)
            )
            final_destination_path = os.path.normpath(
                os.path.join(final_target_folder, final_basename)
            )

        if os.path.abspath(self.file_path) == os.path.abspath(final_destination_path):
            print(f"File '{self.file_path}' already at target.")
            return

        # Compute file hash before the move for logging
        pre_move_hash = ""
        pre_move_size = 0
        if config.ENABLE_MOVE_LOGGING:
            pre_move_hash = file_utils.compute_file_hash(self.file_path) or ""
            try:
                pre_move_size = os.path.getsize(self.file_path)
            except OSError:
                pass

        source_path_before_move = self.file_path

        if self.dry_run:
            print(f"[DRY RUN] Would move: {self.file_path}")
            print(f"[DRY RUN]        To: {final_destination_path}")
            self._record_move(
                source_path_before_move, final_destination_path,
                "dry_run", pre_move_hash, pre_move_size, created_dirs,
            )
            return

        success, message = file_utils.execute_move(
            self.file_path, final_destination_path, self.trash_dir
        )
        print(message)
        if success and "Successfully moved file to" in message:
            self.file_path = final_destination_path
            self._record_move(
                source_path_before_move, final_destination_path,
                action, pre_move_hash, pre_move_size, created_dirs,
            )

    def _record_move(
        self,
        source_path: str,
        destination_path: str,
        action: str,
        file_hash: str,
        file_size: int,
        created_dirs: list,
    ) -> None:
        """Log the move and update the file index after a successful operation."""
        rule_name = self.matched_rule.name if self.matched_rule else None
        record_id = ""

        if self.move_log and config.ENABLE_MOVE_LOGGING:
            record = MoveRecord.create(
                source_path=source_path,
                destination_path=destination_path,
                action=action,
                file_hash=file_hash,
                file_size=file_size,
                summary=self.file_summary[:200] if self.file_summary else "",
                rule_applied=rule_name,
                created_dirs=created_dirs,
                new_filename=os.path.basename(destination_path),
            )
            record_id = self.move_log.record(record)
            print(f"Move logged (ID: {record_id})")

        if self.file_index and config.ENABLE_FILE_INDEX and action != "dry_run":
            tags = list(self._decision_tags) if self._decision_tags else []
            if not tags and self.file_summary and self.file_summary != "Not yet summarized.":
                words = re.findall(r"\b[a-zA-Z]{3,}\b", self.file_summary.lower())
                tags = list(set(words))[:15]

            entry = IndexEntry.create(
                path=destination_path,
                description=self.file_summary[:200] if self.file_summary else "",
                category=rule_name or "uncategorized",
                original_name=os.path.basename(source_path),
                original_location=os.path.dirname(source_path),
                move_id=record_id,
                tags=tags,
            )
            self.file_index.add_entry(entry)
            print(f"File indexed: {os.path.basename(destination_path)}")


if __name__ == "__main__":
    config.PYPDF_INSTALLED, config.PILLOW_INSTALLED, config.PDF2IMAGE_INSTALLED = (
        config.check_dependencies()
    )
    parser = argparse.ArgumentParser(description="AI File Sorter - SmartMover")
    parser.add_argument("file_path", help="Path to the file to sort.")
    args = parser.parse_args()
    file_to_sort_arg = args.file_path
    print(f"SmartMover AI starting for: {file_to_sort_arg}")
    try:
        if not os.path.exists(file_to_sort_arg):
            print(f"Error: File '{file_to_sort_arg}' does not exist.")
        elif not os.path.isfile(file_to_sort_arg):
            print(f"Error: Path '{file_to_sort_arg}' is not a file.")
        else:
            SmartMover(file_to_sort_arg).sort_file()
    except Exception as e:
        print(f"Critical error in main execution: {e}")
        import traceback

        traceback.print_exc()
    finally:
        print("\n--- End of Script ---")
