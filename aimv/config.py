"""
Constants and configuration settings for the AIMV tool.
"""

import os
from typing import Any, Dict, List, Set, Tuple


def _load_local_env() -> None:
    """Load key/value pairs from src/aimv/.env into process env."""
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        return
    try:
        with open(env_path, "r", encoding="utf-8") as env_file:
            for raw_line in env_file:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key:
                    os.environ.setdefault(key, value)
    except OSError:
        # Keep defaults if .env is unavailable/unreadable.
        pass


_load_local_env()

# --------------------------------------------------------------------------- #
# AIMV Data Directory (user state: logs, index, custom rules, template)
# --------------------------------------------------------------------------- #
AIMV_DATA_DIR: str = os.path.expanduser("~/.aimv")
AIMV_LOG_DIR: str = os.path.join(AIMV_DATA_DIR, "logs")
AIMV_INDEX_PATH: str = os.path.join(AIMV_DATA_DIR, "index.json")
AIMV_TEMPLATE_PATH: str = os.path.join(AIMV_DATA_DIR, "template.yaml")
AIMV_USER_RULES_DIR: str = os.path.join(AIMV_DATA_DIR, "rules")
AIMV_USER_CONFIG_PATH: str = os.path.join(AIMV_DATA_DIR, "config.yaml")
AIMV_TAXONOMY_ROOT: str = os.path.expanduser(
    os.getenv("AIMV_TAXONOMY_ROOT", "~/AIMV")
)

# Feature toggles
ENABLE_RULES_ENGINE: bool = True
ENABLE_MOVE_LOGGING: bool = True
ENABLE_FILE_INDEX: bool = True
ENABLE_ORG_TEMPLATE: bool = True
ENABLE_MANAGED_TAXONOMY: bool = True

# Organization template settings
TEMPLATE_SCAN_DEPTH: int = 3
TEMPLATE_ROOT_DIRS: List[str] = [
    "~/Documents",
    "~/Downloads",
    "~/Desktop",
    "~/Pictures",
]

# Managed taxonomy and concurrent classification
TAXONOMY_CANDIDATE_LIMIT: int = int(
    os.getenv("AIMV_TAXONOMY_CANDIDATE_LIMIT", "12")
)
BATCH_CLASSIFICATION_WORKERS: int = int(
    os.getenv("AIMV_BATCH_WORKERS", "4")
)

# Decision providers. Jev is hosted by OpenRouter; Laya remains available locally.
DECISION_PROVIDER: str = os.getenv("AIMV_DECISION_PROVIDER", "jev").strip().lower()
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_DECISIONS_URL: str = os.getenv(
    "OPENROUTER_DECISIONS_URL",
    "https://openrouter.ai/api/alpha/decisions",
).strip()
JEV_MODEL: str = os.getenv("JEV_MODEL", "typesafe/jev-1.13").strip()
LAYA_BASE_URL: str = os.getenv("LAYA_BASE_URL", "").strip()
LAYA_API_KEY: str = os.getenv("LAYA_API_KEY", "")
LAYA_MODEL: str = os.getenv("LAYA_MODEL", "").strip()
LAYA_PRELOAD: bool = os.getenv("LAYA_PRELOAD", "1").lower() in {
    "1", "true", "yes", "on"
}

# NVIDIA
NVIDIA_API_KEY: str = os.getenv("NVIDIA_API_KEY", "")
NVIDIA_API_BASE_URL: str = os.getenv("NVIDIA_API_BASE_URL", "https://api.nvidia.com/v1")

# MINIMAX
MINIMAX_API_KEY: str = os.getenv("MINIMAX_API_KEY", "")
MINIMAX_API_BASE_URL: str = os.getenv("MINIMAX_API_BASE_URL", "https://api.minimax.io/v1")

# GOOGLE
MODEL_NAME: str = os.getenv("MODEL_NAME", "gemma-4-31b-it")
OPENAI_API_BASE_URL: str = os.getenv(
    "OPENAI_API_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/"
)
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

# OPENAI
if os.getenv("AIMV_USE_MINIMAX_AS_OPENAI", "").lower() in {"1", "true", "yes"}:
    OPENAI_API_BASE_URL = MINIMAX_API_BASE_URL
    OPENAI_API_KEY = MINIMAX_API_KEY

MAX_LLM_RETRIES_ON_PARSE_ERROR: int = 3

# API usage limits
MAX_API_CALLS_PER_DAY: int = int(os.getenv("AIMV_MAX_API_CALLS_PER_DAY", "1400"))
MAX_API_CALLS_PER_MINUTE: int = int(os.getenv("AIMV_MAX_API_CALLS_PER_MINUTE", "10"))
AIMV_USAGE_PATH: str = os.path.join(AIMV_DATA_DIR, "api_usage.json")
LLM_TEMPERATURE: float = 0.1
MAX_TOKENS_UNIFIED: int = 600  # Single-step JSON response (action + destination + rename + tags)

# Legacy per-step token limits (kept for backward compatibility)
MAX_TOKENS_STEP1: int = 500
MAX_TOKENS_STEP3: int = 500
MAX_TOKENS_STEP5: int = 750
MAX_TOKENS_STEP6: int = 750
MAX_TOKENS_STEP7: int = 750

# File Search and Sorting Settings
MIN_KEYWORD_LENGTH: int = 4
MAX_DEPTH_STEP5: int = 3
HIGH_CONFIDENCE: float = 0.8
MEDIUM_CONFIDENCE: float = 0.5
PATH_PRE_FILTER_THRESHOLD: int = 50
MAX_PATHS_TO_LLM_PREFILTER: int = 150
MAX_PATHS_AFTER_PREFILTER: int = 15
MAX_PATHS_TO_STEP6_LLM: int = 30
MAX_LS_OUTPUT_FILES_TO_SHOW_LLM: int = 10
MAX_LS_OUTPUT_OTHER_FILES: int = 5

# File Processing Settings
ALLOW_LLM_FILE_PROCESSING: bool = True
MAX_FILE_SIZE_FOR_FULL_PROCESSING_MB: int = 10
MAX_EXTRACTED_TEXT_SIZE_KB: int = 100
MIN_MEANINGFUL_TEXT_LENGTH: int = 50

# Image Processing Settings
ALLOW_LLM_IMAGE_PROCESSING: bool = True
MAX_IMAGE_RESOLUTION_FOR_LLM: Tuple[int, int] = (1024, 1024)
IMAGE_QUALITY_FOR_LLM: int = 75

MAX_HINT_RETRIES: int = 2

# File System Settings
IGNORE_HIDDEN_FOLDERS: bool = True

EXCLUDED_DIRS_FIND_PATTERNS: List[str] = [
    ".*",
    "venv",
    ".venv",
    "env",
    "__pycache__",
    "node_modules",
    ".git",
    ".idea",
    ".DS_Store",
    "CVS",
    "$RECYCLE.BIN",
    "System Volume Information",
    ".Spotlight-V100",
    ".fseventsd",
]
# Note: .Trash is not in EXCLUDED_DIRS_FIND_PATTERNS because we might want to search *in* it if specified,
# or it might be a target. The find command itself won't list .Trash unless it's part of search_paths.

FILES_TO_IGNORE_IN_LS: Set[str] = {".DS_Store", "Thumbs.db", ".localized"}

COMMON_FILE_EXTENSIONS_TO_FILTER: Set[str] = {
    "pdf",
    "doc",
    "docx",
    "xls",
    "xlsx",
    "ppt",
    "pptx",
    "txt",
    "rtf",
    "odt",
    "ods",
    "odp",
    "jpg",
    "jpeg",
    "png",
    "gif",
    "bmp",
    "tiff",
    "webp",
    "svg",
    "mp3",
    "wav",
    "aac",
    "flac",
    "ogg",
    "m4a",
    "mp4",
    "mov",
    "avi",
    "mkv",
    "wmv",
    "flv",
    "webm",
    "zip",
    "rar",
    "7z",
    "tar",
    "gz",
    "bz2",
    "tgz",
    "exe",
    "dmg",
    "pkg",
    "deb",
    "rpm",
    "html",
    "htm",
    "css",
    "js",
    "json",
    "xml",
    "yaml",
    "yml",
    "py",
    "java",
    "c",
    "cpp",
    "cs",
    "go",
    "rb",
    "php",
    "swift",
    "kt",
    "srt",
    "vtt",
    "sub",
    "log",
    "ini",
    "cfg",
    "conf",
    "iso",
    "img",
    "md",
}

DELETABLE_CANDIDATE_EXTENSIONS: Set[str] = {
    ".pkg",
    ".dmg",
    ".exe",
    ".msi",
    ".crdownload",
    ".part",
    ".download",
    ".tmp",
    ".temp",
}

# AI Instruction Settings
CUSTOM_AI_INSTRUCTIONS: str = ""

# Special Destination Identifiers
TRASH_DESTINATION_IDENTIFIER: str = "USER_TRASH_BIN"
ARCHIVE_EXTENSIONS: List[str] = [".zip", ".tar", ".gz", ".tgz", ".rar", ".7z", ".bz2"]


# Function to update config at runtime
def update_config(updates: Dict[str, Any]) -> None:
    """
    Update configuration settings at runtime.

    Args:
        updates (dict): Dictionary of configuration settings to update.
    """
    globals().update(updates)


PYPDF_INSTALLED: bool = False
PILLOW_INSTALLED: bool = False
PDF2IMAGE_INSTALLED: bool = False


def ensure_data_dir() -> None:
    """Create the ~/.aimv/ directory tree if it doesn't exist."""
    for d in (AIMV_DATA_DIR, AIMV_LOG_DIR, AIMV_USER_RULES_DIR):
        os.makedirs(d, exist_ok=True)


def load_user_config() -> None:
    """Load ~/.aimv/config.yaml and merge overrides into this module's globals."""
    if not os.path.exists(AIMV_USER_CONFIG_PATH):
        return
    try:
        import yaml  # noqa: E402

        with open(AIMV_USER_CONFIG_PATH, "r", encoding="utf-8") as f:
            user_cfg = yaml.safe_load(f)
        if isinstance(user_cfg, dict):
            update_config(user_cfg)
    except Exception as e:
        print(f"Warning: Could not load user config {AIMV_USER_CONFIG_PATH}: {e}")


# Function to check optional dependencies
def check_dependencies() -> Tuple[bool, bool, bool]:
    """
    Check for optional dependencies and return status.

    Returns:
        tuple: (pypdf_installed, pillow_installed, pdf2image_installed)
    """
    # Check for pypdf
    try:
        from pypdf import PdfReader

        pypdf_installed: bool = True
    except ImportError:
        pypdf_installed = False
        print(
            "WARNING: pypdf not installed. PDF text extraction will be disabled. To enable: `pip install pypdf`"
        )

    # Check for Pillow
    try:
        from PIL import Image

        pillow_installed: bool = True
    except ImportError:
        pillow_installed = False
        print(
            "WARNING: Pillow (PIL) not installed. Image processing will be disabled. To enable: `pip install Pillow`"
        )

    # Check for pdf2image
    try:
        from pdf2image import convert_from_path

        pdf2image_installed = True
    except ImportError:
        pdf2image_installed = False
        print(
            "WARNING: pdf2image not installed (or poppler dependency missing). PDF to image conversion will be disabled."
        )

    return pypdf_installed, pillow_installed, pdf2image_installed
