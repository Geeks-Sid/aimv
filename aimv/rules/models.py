"""Data models for the rules engine."""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class NamingConvention:
    """Defines how files in a category should be named."""

    template: str = "{description}.{ext}"
    date_format: str = "%Y-%m-%d"
    separator: str = "_"
    case: str = "preserve"  # "lower", "title", "upper", "preserve"

    def apply_case(self, value: str) -> str:
        if self.case == "lower":
            return value.lower()
        elif self.case == "upper":
            return value.upper()
        elif self.case == "title":
            return value.replace(self.separator, " ").title().replace(" ", self.separator)
        return value

    @classmethod
    def from_dict(cls, data: dict) -> "NamingConvention":
        if not data:
            return cls()
        return cls(
            template=data.get("template", cls.template),
            date_format=data.get("date_format", cls.date_format),
            separator=data.get("separator", cls.separator),
            case=data.get("case", cls.case),
        )

    def to_dict(self) -> dict:
        return {
            "template": self.template,
            "date_format": self.date_format,
            "separator": self.separator,
            "case": self.case,
        }


@dataclass
class CategoryRule:
    """Defines organization rules for a category of files."""

    name: str
    description: str = ""
    priority: int = 0
    keywords: List[str] = field(default_factory=list)
    filename_patterns: List[str] = field(default_factory=list)
    target_folder: str = ""
    naming: NamingConvention = field(default_factory=NamingConvention)
    metadata_fields: List[str] = field(default_factory=list)
    create_subfolders: bool = False
    examples: List[dict] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "CategoryRule":
        naming_data = data.get("naming", {})
        naming = NamingConvention.from_dict(naming_data) if naming_data else NamingConvention()

        return cls(
            name=data.get("name", "unknown"),
            description=data.get("description", ""),
            priority=data.get("priority", 0),
            keywords=data.get("keywords", []),
            filename_patterns=data.get("filename_patterns", []),
            target_folder=data.get("target_folder", ""),
            naming=naming,
            metadata_fields=data.get("metadata_fields", []),
            create_subfolders=data.get("create_subfolders", False),
            examples=data.get("examples", []),
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "priority": self.priority,
            "keywords": self.keywords,
            "filename_patterns": self.filename_patterns,
            "target_folder": self.target_folder,
            "naming": self.naming.to_dict(),
            "metadata_fields": self.metadata_fields,
            "create_subfolders": self.create_subfolders,
            "examples": self.examples,
        }
