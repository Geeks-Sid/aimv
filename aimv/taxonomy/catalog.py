"""A searchable, materializable taxonomy of managed AIMV folders."""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import yaml


METADATA_FILENAME = ".aimv-folder.yaml"
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "file", "files",
    "for", "from", "in", "into", "is", "of", "on", "or", "the", "to",
    "with",
}


def _tokens(value: str) -> Tuple[str, ...]:
    normalized: List[str] = []
    for token in _TOKEN_RE.findall(value.lower()):
        if token in _STOP_WORDS:
            continue
        normalized.append(token)
        if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
            normalized.append(token[:-1])
    return tuple(dict.fromkeys(normalized))


def _safe_segment(code: str, title: str) -> str:
    clean = re.sub(r"[\\/:*?\"<>|]+", "-", title).strip(" .-")
    return f"{code} {clean}"


def _code_sort_key(code: str) -> Tuple[int, ...]:
    try:
        return tuple(int(part) for part in code.split("."))
    except ValueError:
        return (10_000,)


@dataclass(frozen=True)
class TaxonomyNode:
    """One managed area, category, or leaf bucket."""

    id: str
    code: str
    title: str
    kind: str
    relative_path: str
    parent_id: Optional[str] = None
    purpose: str = ""
    aliases: Tuple[str, ...] = field(default_factory=tuple)
    tags: Tuple[str, ...] = field(default_factory=tuple)
    include: Tuple[str, ...] = field(default_factory=tuple)
    exclude: Tuple[str, ...] = field(default_factory=tuple)
    partition: str = "year"

    def resolve(self, root: str) -> str:
        return os.path.join(os.path.abspath(os.path.expanduser(root)), self.relative_path)

    def to_metadata(self) -> dict:
        data = asdict(self)
        data["schema_version"] = 1
        for key in ("aliases", "tags", "include", "exclude"):
            data[key] = list(data[key])
        return data

    @classmethod
    def from_metadata(cls, data: dict) -> "TaxonomyNode":
        return cls(
            id=str(data["id"]),
            code=str(data.get("code", data["id"])),
            title=str(data["title"]),
            kind=str(data.get("kind", "bucket")),
            relative_path=str(data["relative_path"]),
            parent_id=data.get("parent_id"),
            purpose=str(data.get("purpose", "")),
            aliases=tuple(data.get("aliases") or ()),
            tags=tuple(data.get("tags") or ()),
            include=tuple(data.get("include") or ()),
            exclude=tuple(data.get("exclude") or ()),
            partition=str(data.get("partition") or "year"),
        )


@dataclass(frozen=True)
class BucketMatch:
    """A ranked leaf bucket returned by local semantic retrieval."""

    bucket: TaxonomyNode
    score: float
    matched_terms: Tuple[str, ...] = field(default_factory=tuple)


class TaxonomyCatalog:
    """Load, search, validate, and materialize AIMV's managed folder tree."""

    def __init__(self, nodes: Sequence[TaxonomyNode], root: str):
        self.root = os.path.abspath(os.path.expanduser(root))
        self._nodes: Dict[str, TaxonomyNode] = {node.id: node for node in nodes}
        if len(self._nodes) != len(nodes):
            raise ValueError("Taxonomy contains duplicate node IDs")

    @classmethod
    def load_default(cls, root: str) -> "TaxonomyCatalog":
        definition = Path(__file__).with_name("defaults") / "personal.yaml"
        catalog = cls.from_yaml(str(definition), root)
        expanded = os.path.abspath(os.path.expanduser(root))
        if os.path.isdir(expanded):
            installed = cls.discover(expanded)
            merged = dict(catalog._nodes)
            for node in installed.nodes:
                existing = merged.get(node.id)
                if existing and existing.kind == node.kind:
                    merged[node.id] = node
            candidate = cls(list(merged.values()), expanded)
            if not candidate.validate():
                catalog = candidate
        return catalog

    @classmethod
    def from_yaml(cls, path: str, root: str) -> "TaxonomyCatalog":
        with open(path, "r", encoding="utf-8") as stream:
            data = yaml.safe_load(stream) or {}
        if data.get("schema_version") != 1:
            raise ValueError("Unsupported taxonomy schema version")

        nodes: List[TaxonomyNode] = []
        default_partition = str(data.get("default_partition") or "year")
        for area in data.get("areas") or []:
            area_code = str(area["code"])
            area_title = str(area["title"])
            area_id = f"area.{area_code}"
            area_path = _safe_segment(area_code, area_title)
            area_tags = tuple(area.get("tags") or _tokens(area_title))
            area_partition = str(area.get("partition") or default_partition)
            nodes.append(
                TaxonomyNode(
                    id=area_id,
                    code=area_code,
                    title=area_title,
                    kind="area",
                    relative_path=area_path,
                    purpose=str(area.get("purpose") or f"Files related to {area_title}."),
                    aliases=tuple(area.get("aliases") or ()),
                    tags=area_tags,
                    partition=area_partition,
                )
            )

            for category in area.get("categories") or []:
                category_code = str(category["code"])
                category_title = str(category["title"])
                category_id = f"category.{category_code}"
                category_path = os.path.join(
                    area_path, _safe_segment(category_code, category_title)
                )
                category_tags = tuple(
                    category.get("tags")
                    or dict.fromkeys(_tokens(f"{area_title} {category_title}"))
                )
                category_partition = str(
                    category.get("partition") or area_partition
                )
                nodes.append(
                    TaxonomyNode(
                        id=category_id,
                        code=category_code,
                        title=category_title,
                        kind="category",
                        relative_path=category_path,
                        parent_id=area_id,
                        purpose=str(
                            category.get("purpose")
                            or f"{category_title} within {area_title}."
                        ),
                        aliases=tuple(category.get("aliases") or ()),
                        tags=category_tags,
                        partition=category_partition,
                    )
                )

                for position, raw_bucket in enumerate(category.get("buckets") or [], 1):
                    bucket = (
                        {"title": raw_bucket}
                        if isinstance(raw_bucket, str)
                        else dict(raw_bucket)
                    )
                    bucket_code = str(bucket.get("code") or f"{category_code}.{position:02d}")
                    title = str(bucket["title"])
                    bucket_id = str(bucket.get("id") or f"bucket.{bucket_code}")
                    relative_path = os.path.join(
                        category_path, _safe_segment(bucket_code, title)
                    )
                    inherited = f"{area_title} {category_title} {title}"
                    tags = tuple(
                        bucket.get("tags") or dict.fromkeys(_tokens(inherited))
                    )
                    nodes.append(
                        TaxonomyNode(
                            id=bucket_id,
                            code=bucket_code,
                            title=title,
                            kind="bucket",
                            relative_path=relative_path,
                            parent_id=category_id,
                            purpose=str(
                                bucket.get("purpose")
                                or f"{title} within {category_title}."
                            ),
                            aliases=tuple(bucket.get("aliases") or ()),
                            tags=tags,
                            include=tuple(bucket.get("include") or ()),
                            exclude=tuple(bucket.get("exclude") or ()),
                            partition=str(
                                bucket.get("partition") or category_partition
                            ),
                        )
                    )

        catalog = cls(nodes, root)
        errors = catalog.validate()
        if errors:
            raise ValueError("Invalid taxonomy: " + "; ".join(errors))
        return catalog

    @classmethod
    def discover(cls, root: str) -> "TaxonomyCatalog":
        """Rebuild a catalog from hidden metadata files under an installed root."""
        expanded = os.path.abspath(os.path.expanduser(root))
        nodes: List[TaxonomyNode] = []
        for current, dirs, files in os.walk(expanded):
            dirs.sort()
            if METADATA_FILENAME not in files:
                continue
            metadata_path = os.path.join(current, METADATA_FILENAME)
            try:
                with open(metadata_path, "r", encoding="utf-8") as stream:
                    data = yaml.safe_load(stream) or {}
                if data.get("id") == "aimv.root":
                    continue
                nodes.append(TaxonomyNode.from_metadata(data))
            except (OSError, KeyError, TypeError, yaml.YAMLError):
                continue
        return cls(nodes, expanded)

    @property
    def nodes(self) -> Tuple[TaxonomyNode, ...]:
        return tuple(
            sorted(self._nodes.values(), key=lambda node: _code_sort_key(node.code))
        )

    @property
    def buckets(self) -> Tuple[TaxonomyNode, ...]:
        return tuple(node for node in self.nodes if node.kind == "bucket")

    def get(self, node_id: str) -> Optional[TaxonomyNode]:
        return self._nodes.get(node_id)

    def children(
        self, parent_id: Optional[str], kind: Optional[str] = None
    ) -> Tuple[TaxonomyNode, ...]:
        """Return human-ordered children for hierarchical decisions."""
        return tuple(
            node
            for node in self.nodes
            if node.parent_id == parent_id and (kind is None or node.kind == kind)
        )

    def resolve(self, bucket_id: str) -> str:
        node = self._nodes.get(bucket_id)
        if node is None or node.kind != "bucket":
            raise KeyError(f"Unknown bucket ID: {bucket_id}")
        return node.resolve(self.root)

    def validate(self) -> List[str]:
        errors: List[str] = []
        seen_paths: Dict[str, str] = {}
        for node in self._nodes.values():
            if node.kind not in {"area", "category", "bucket"}:
                errors.append(f"{node.id} has invalid kind {node.kind}")
            if node.partition not in {"none", "year", "year_month"}:
                errors.append(f"{node.id} has invalid partition {node.partition}")
            if node.parent_id and node.parent_id not in self._nodes:
                errors.append(f"{node.id} has missing parent {node.parent_id}")
            normalized = os.path.normcase(os.path.normpath(node.relative_path))
            if os.path.isabs(node.relative_path) or normalized.startswith(".."):
                errors.append(f"{node.id} has unsafe relative path")
            if normalized in seen_paths:
                errors.append(
                    f"{node.id} and {seen_paths[normalized]} share relative path"
                )
            seen_paths[normalized] = node.id
        if len(self.buckets) < 200:
            errors.append("Taxonomy must define at least 200 leaf buckets")
        return errors

    def search(self, query: str, limit: int = 12) -> List[BucketMatch]:
        """Rank leaf buckets locally without sending the whole tree to an LLM."""
        query_tokens = set(_tokens(query))
        normalized_query = " ".join(_tokens(query))
        matches: List[BucketMatch] = []

        for bucket in self.buckets:
            title_tokens = set(_tokens(bucket.title))
            alias_tokens = set(_tokens(" ".join(bucket.aliases)))
            tag_tokens = set(_tokens(" ".join(bucket.tags)))
            context_tokens = set(
                _tokens(
                    " ".join(
                        (bucket.purpose, bucket.relative_path, *bucket.include)
                    )
                )
            )
            excluded = set(_tokens(" ".join(bucket.exclude)))

            matched = query_tokens & (title_tokens | alias_tokens | tag_tokens | context_tokens)
            score = 0.0
            score += 8.0 * len(query_tokens & title_tokens)
            score += 7.0 * len(query_tokens & alias_tokens)
            score += 4.0 * len(query_tokens & tag_tokens)
            score += 1.5 * len(query_tokens & context_tokens)
            score -= 8.0 * len(query_tokens & excluded)
            if normalized_query and normalized_query in " ".join(_tokens(bucket.title)):
                score += 12.0
            if score > 0:
                matches.append(
                    BucketMatch(bucket, score, tuple(sorted(matched)))
                )

        matches.sort(key=lambda match: (-match.score, match.bucket.code))
        if matches:
            return matches[: max(1, limit)]

        fallback = [
            bucket for bucket in self.buckets if bucket.code.startswith("00.10")
        ]
        return [BucketMatch(bucket, 0.0, ()) for bucket in fallback[: max(1, limit)]]

    def format_candidates(self, query: str, limit: int = 12) -> str:
        lines: List[str] = []
        for match in self.search(query, limit):
            bucket = match.bucket
            aliases = f"; aliases={', '.join(bucket.aliases)}" if bucket.aliases else ""
            lines.append(
                f"- {bucket.id} | {bucket.title} | {bucket.relative_path} | "
                f"{bucket.purpose}{aliases}"
            )
        return "\n".join(lines)

    def materialize(
        self,
        bucket_ids: Optional[Iterable[str]] = None,
        overwrite_metadata: bool = False,
    ) -> int:
        """Create managed directories and hidden metadata; return files written."""
        selected: Optional[set] = set(bucket_ids) if bucket_ids is not None else None
        nodes: List[TaxonomyNode]
        if selected is None:
            nodes = list(self.nodes)
        else:
            expanded = set(selected)
            for node_id in list(selected):
                node = self._nodes.get(node_id)
                if node is None or node.kind != "bucket":
                    raise KeyError(f"Unknown bucket ID: {node_id}")
                while node.parent_id:
                    expanded.add(node.parent_id)
                    node = self._nodes[node.parent_id]
            nodes = [node for node in self.nodes if node.id in expanded]

        os.makedirs(self.root, exist_ok=True)
        written = self._write_metadata(
            self.root,
            {
                "schema_version": 1,
                "id": "aimv.root",
                "code": "root",
                "title": "AIMV",
                "kind": "root",
                "relative_path": ".",
                "parent_id": None,
                "purpose": "Managed root for the AIMV organization taxonomy.",
                "aliases": [],
                "tags": ["aimv", "organized", "files"],
                "include": [],
                "exclude": [],
                "partition": "none",
            },
            overwrite_metadata,
        )
        for node in nodes:
            directory = node.resolve(self.root)
            os.makedirs(directory, exist_ok=True)
            written += self._write_metadata(
                directory, node.to_metadata(), overwrite_metadata
            )
        return written

    @staticmethod
    def _write_metadata(directory: str, data: dict, overwrite: bool) -> int:
        path = os.path.join(directory, METADATA_FILENAME)
        if os.path.exists(path) and not overwrite:
            return 0
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as stream:
            yaml.safe_dump(data, stream, sort_keys=False, allow_unicode=True)
        os.replace(tmp_path, path)
        return 1
