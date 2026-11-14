"""Where documents come from: the :class:`DocumentSource` seam and a local-file implementation.

A product's real sources (an object store, a crawler, a database, the backend API through
``trellis_sdk``) are plugins in the ``trellis.rag.sources`` entry point group; this module only
fixes the shape they must have and ships the one source that needs nothing but a filesystem.
"""

from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Final, Protocol, runtime_checkable

from pydantic import Field

from trellis_core.config import ConfigModel
from trellis_core.errors import InputError
from trellis_core.json_types import JsonObject
from trellis_core.logs import get_logger
from trellis_core.plugins import SupportStatus, plugin
from trellis_rag.config import TEXT_FILE_SOURCE
from trellis_rag.model import Document

_log = get_logger(__name__)

#: Suffixes :class:`TextFileSource` reads. Anything else needs a converter, which is a product
#: concern (a PDF extractor pulls in a heavy dependency; see the package README).
TEXT_SUFFIXES: Final = frozenset({".txt", ".md", ".rst"})


@runtime_checkable
class DocumentSource(Protocol):
    """Yields the documents to index.

    Lazy on purpose: a corpus does not fit in memory, and the indexing pipeline embeds and stores
    in batches as documents arrive.
    """

    def documents(self) -> Iterator[Document]: ...


class TextFileSourceOptions(ConfigModel):
    paths: list[Path] = Field(default_factory=list)
    """Files to read, or directories to walk for .txt/.md/.rst."""
    root: Path | None = None
    """Documents are identified by their path relative to this (default: the working directory)."""


@plugin(
    name=TEXT_FILE_SOURCE,
    description="Reads .txt/.md/.rst files from paths on the local filesystem.",
    status=SupportStatus.INCUBATING,
)
class TextFileSource:
    """Plain text files. ``doc_id`` is the path relative to ``root`` so re-indexing replaces a
    file's chunks instead of adding a second copy."""

    def __init__(self, paths: Sequence[Path], root: Path | None = None) -> None:
        self._paths = tuple(paths)
        self._root = (root or Path.cwd()).resolve()

    @classmethod
    def from_config(cls, options: JsonObject) -> "TextFileSource":
        """The construction contract every source provider implements (trellis_rag.registry)."""
        parsed = TextFileSourceOptions.model_validate(options)
        return cls(parsed.paths, parsed.root)

    def documents(self) -> Iterator[Document]:
        for path in self._paths:
            for file in self._files(path):
                text = file.read_text(encoding="utf-8")
                if not text.strip():
                    _log.warning("skipping empty document", path=str(file))
                    continue
                yield Document(
                    doc_id=self._doc_id(file),
                    text=text,
                    metadata={"path": str(file), "bytes": file.stat().st_size},
                )

    def _files(self, path: Path) -> Iterator[Path]:
        resolved = path.resolve()
        if resolved.is_dir():
            yield from sorted(p for p in resolved.rglob("*") if p.suffix in TEXT_SUFFIXES)
        elif resolved.is_file():
            yield resolved
        else:
            raise InputError(f"no such file or directory: {path}")

    def _doc_id(self, file: Path) -> str:
        try:
            return str(file.relative_to(self._root))
        except ValueError:
            return str(file)
