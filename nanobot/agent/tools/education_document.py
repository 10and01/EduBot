"""Education document tools: import, list, search, and delete local materials."""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool


def _safe_rel_path(path: Path, workspace: Path) -> str:
    try:
        return str(path.resolve().relative_to(workspace.resolve()))
    except ValueError:
        return str(path.resolve())


class _EducationDocMixin:
    """Shared helpers for document ingestion and vector retrieval."""

    _SUPPORTED_SUFFIXES = {".txt", ".md", ".pdf", ".docx", ".doc"}

    def __init__(
        self,
        workspace: Path,
        vectordb_path: str = "documents/chroma",
        collection_name: str = "lesson_materials",
    ) -> None:
        self._workspace = workspace
        self._vectordb_path = (workspace / vectordb_path).resolve()
        self._collection_name = collection_name

    def _resolve(self, path: str) -> Path:
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = (self._workspace / p).resolve()
        return p

    def _get_collection(self):
        try:
            import chromadb
        except Exception as exc:  # pragma: no cover - runtime dependency guard
            raise RuntimeError(
                "chromadb is not installed. Run: pip install chromadb"
            ) from exc

        self._vectordb_path.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=str(self._vectordb_path))
        return client.get_or_create_collection(name=self._collection_name)

    @staticmethod
    def _chunk_text(text: str, chunk_size: int = 900, overlap: int = 120) -> list[str]:
        normalized = " ".join(text.split())
        if not normalized:
            return []
        chunks: list[str] = []
        start = 0
        while start < len(normalized):
            end = min(len(normalized), start + chunk_size)
            chunks.append(normalized[start:end])
            if end >= len(normalized):
                break
            start = max(0, end - overlap)
        return chunks

    def _extract_text(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix not in self._SUPPORTED_SUFFIXES:
            raise ValueError(f"unsupported file type: {suffix}")

        if suffix in {".txt", ".md"}:
            return path.read_text(encoding="utf-8", errors="ignore")

        if suffix == ".pdf":
            try:
                from pypdf import PdfReader
            except Exception as exc:  # pragma: no cover
                raise RuntimeError("pypdf is required for PDF import") from exc
            reader = PdfReader(str(path))
            return "\n".join((page.extract_text() or "") for page in reader.pages)

        if suffix == ".docx":
            try:
                from docx import Document
            except Exception as exc:  # pragma: no cover
                raise RuntimeError("python-docx is required for DOCX import") from exc
            doc = Document(str(path))
            return "\n".join(p.text for p in doc.paragraphs if p.text)

        # .doc fallback: use antiword if available
        import shutil
        import subprocess

        antiword = shutil.which("antiword")
        if not antiword:
            raise RuntimeError(
                "legacy .doc import requires antiword in PATH; or convert .doc to .docx first"
            )

        proc = subprocess.run(
            [antiword, str(path)],
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="ignore",
        )
        if proc.returncode != 0:
            raise RuntimeError(f"antiword failed: {proc.stderr.strip() or 'unknown error'}")
        return proc.stdout


class DocumentImportTool(_EducationDocMixin, Tool):
    """Import local files into a Chroma collection for retrieval."""

    @property
    def name(self) -> str:
        return "document_import"

    @property
    def description(self) -> str:
        return "Import txt/pdf/md/doc/docx into local vector DB for lesson-plan retrieval."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace-relative or absolute file path"},
                "subject": {"type": "string", "description": "Optional subject tag (e.g. mathematics)"},
                "grade": {"type": "string", "description": "Optional grade tag (e.g. grade-7)"},
            },
            "required": ["path"],
        }

    async def execute(self, path: str, subject: str = "", grade: str = "", **kwargs: Any) -> str:
        try:
            fp = self._resolve(path)
            if not fp.exists() or not fp.is_file():
                return f"Error: file not found: {path}"

            text = self._extract_text(fp)
            chunks = self._chunk_text(text)
            if not chunks:
                return f"Error: file has no extractable text: {path}"

            source_hash = hashlib.sha1(str(fp.resolve()).encode("utf-8")).hexdigest()[:16]
            doc_id = f"doc_{source_hash}"
            collection = self._get_collection()

            # Replace previous chunks from the same file.
            try:
                collection.delete(where={"source_hash": source_hash})
            except Exception:
                pass

            ids = [f"{doc_id}_{idx}_{uuid.uuid4().hex[:6]}" for idx in range(len(chunks))]
            metadatas = [
                {
                    "doc_id": doc_id,
                    "chunk_index": idx,
                    "source_hash": source_hash,
                    "source_path": _safe_rel_path(fp, self._workspace),
                    "subject": subject,
                    "grade": grade,
                }
                for idx in range(len(chunks))
            ]
            collection.add(ids=ids, documents=chunks, metadatas=metadatas)

            return json.dumps(
                {
                    "status": "ok",
                    "doc_id": doc_id,
                    "path": _safe_rel_path(fp, self._workspace),
                    "chunks": len(chunks),
                    "subject": subject,
                    "grade": grade,
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            return f"Error: failed to import document: {exc}"

    def _import_file(self, fp: Path, subject: str, grade: str) -> dict[str, Any]:
        text = self._extract_text(fp)
        chunks = self._chunk_text(text)
        if not chunks:
            raise ValueError("file has no extractable text")

        source_hash = hashlib.sha1(str(fp.resolve()).encode("utf-8")).hexdigest()[:16]
        doc_id = f"doc_{source_hash}"
        collection = self._get_collection()

        try:
            collection.delete(where={"source_hash": source_hash})
        except Exception:
            pass

        ids = [f"{doc_id}_{idx}_{uuid.uuid4().hex[:6]}" for idx in range(len(chunks))]
        metadatas = [
            {
                "doc_id": doc_id,
                "chunk_index": idx,
                "source_hash": source_hash,
                "source_path": _safe_rel_path(fp, self._workspace),
                "subject": subject,
                "grade": grade,
            }
            for idx in range(len(chunks))
        ]
        collection.add(ids=ids, documents=chunks, metadatas=metadatas)
        return {
            "doc_id": doc_id,
            "path": _safe_rel_path(fp, self._workspace),
            "chunks": len(chunks),
            "subject": subject,
            "grade": grade,
        }


class DocumentImportDirTool(_EducationDocMixin, Tool):
    @property
    def name(self) -> str:
        return "document_import_dir"

    @property
    def description(self) -> str:
        return "Import all supported documents under a directory into local vector DB for lesson-plan retrieval."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace-relative or absolute directory path"},
                "recursive": {"type": "boolean", "default": True},
                "max_files": {"type": "integer", "minimum": 1, "maximum": 500, "default": 200},
                "subject": {"type": "string", "description": "Optional subject tag (e.g. mathematics)"},
                "grade": {"type": "string", "description": "Optional grade tag (e.g. grade-7)"},
            },
            "required": ["path"],
        }

    async def execute(
        self,
        path: str,
        recursive: bool = True,
        max_files: int = 200,
        subject: str = "",
        grade: str = "",
        **kwargs: Any,
    ) -> str:
        try:
            root = self._resolve(path)
            if not root.exists() or not root.is_dir():
                return f"Error: directory not found: {path}"

            max_files = max(1, min(500, int(max_files)))
            iterator = root.rglob("*") if recursive else root.glob("*")
            candidates = [
                p for p in iterator
                if p.is_file() and p.suffix.lower() in self._SUPPORTED_SUFFIXES
            ][:max_files]

            index_path = self._vectordb_path / "import_index.json"
            try:
                index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
            except Exception:
                index = {}
            if not isinstance(index, dict):
                index = {}

            imported: list[dict[str, Any]] = []
            errors: list[dict[str, Any]] = []
            for fp in candidates:
                try:
                    stat = fp.stat()
                    key = str(fp.resolve())
                    prev = index.get(key, {})
                    if (
                        isinstance(prev, dict)
                        and prev.get("mtime_ns") == stat.st_mtime_ns
                        and prev.get("size") == stat.st_size
                    ):
                        continue

                    text = self._extract_text(fp)
                    chunks = self._chunk_text(text)
                    if not chunks:
                        raise ValueError("file has no extractable text")

                    source_hash = hashlib.sha1(str(fp.resolve()).encode("utf-8")).hexdigest()[:16]
                    doc_id = f"doc_{source_hash}"
                    collection = self._get_collection()
                    try:
                        collection.delete(where={"source_hash": source_hash})
                    except Exception:
                        pass

                    ids = [f"{doc_id}_{idx}_{uuid.uuid4().hex[:6]}" for idx in range(len(chunks))]
                    metadatas = [
                        {
                            "doc_id": doc_id,
                            "chunk_index": idx,
                            "source_hash": source_hash,
                            "source_path": _safe_rel_path(fp, self._workspace),
                            "subject": subject,
                            "grade": grade,
                        }
                        for idx in range(len(chunks))
                    ]
                    collection.add(ids=ids, documents=chunks, metadatas=metadatas)
                    imported.append({
                        "doc_id": doc_id,
                        "path": _safe_rel_path(fp, self._workspace),
                        "chunks": len(chunks),
                        "subject": subject,
                        "grade": grade,
                    })
                    index[key] = {"mtime_ns": stat.st_mtime_ns, "size": stat.st_size}
                except Exception as exc:
                    errors.append({"path": _safe_rel_path(fp, self._workspace), "error": str(exc)[:400]})

            try:
                index_path.parent.mkdir(parents=True, exist_ok=True)
                index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass

            return json.dumps(
                {
                    "status": "ok",
                    "root": _safe_rel_path(root, self._workspace),
                    "recursive": bool(recursive),
                    "max_files": max_files,
                    "imported_count": len(imported),
                    "error_count": len(errors),
                    "imported": imported[:50],
                    "errors": errors[:20],
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            return f"Error: failed to import directory: {exc}"


class DocumentSearchTool(_EducationDocMixin, Tool):
    """Semantic document search against the local vector DB."""

    def __init__(
        self,
        workspace: Path,
        vectordb_path: str = "documents/chroma",
        collection_name: str = "lesson_materials",
        top_k: int = 5,
    ) -> None:
        super().__init__(workspace, vectordb_path, collection_name)
        self._top_k = top_k

    @property
    def name(self) -> str:
        return "document_search"

    @property
    def description(self) -> str:
        return "Search imported local documents to support lesson-plan generation."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 20},
                "subject": {"type": "string", "description": "Optional subject filter"},
                "grade": {"type": "string", "description": "Optional grade filter"},
            },
            "required": ["query"],
        }

    async def execute(
        self,
        query: str,
        top_k: int | None = None,
        subject: str = "",
        grade: str = "",
        **kwargs: Any,
    ) -> str:
        try:
            collection = self._get_collection()
            where: dict[str, Any] = {}
            if subject:
                where["subject"] = subject
            if grade:
                where["grade"] = grade

            limit = top_k or self._top_k
            result = collection.query(
                query_texts=[query],
                n_results=limit,
                where=where or None,
                include=["documents", "metadatas", "distances"],
            )

            hits = []
            docs = result.get("documents", [[]])[0]
            metas = result.get("metadatas", [[]])[0]
            dists = result.get("distances", [[]])[0]
            for doc, meta, dist in zip(docs, metas, dists, strict=False):
                hits.append(
                    {
                        "text": doc,
                        "score": round(1.0 - float(dist), 4) if dist is not None else None,
                        "doc_id": (meta or {}).get("doc_id", ""),
                        "source_path": (meta or {}).get("source_path", ""),
                        "subject": (meta or {}).get("subject", ""),
                        "grade": (meta or {}).get("grade", ""),
                    }
                )

            return json.dumps({"status": "ok", "query": query, "hits": hits}, ensure_ascii=False)
        except Exception as exc:
            return f"Error: document search failed: {exc}"


class DocumentListTool(_EducationDocMixin, Tool):
    """List imported source documents currently indexed in ChromaDB."""

    @property
    def name(self) -> str:
        return "document_list"

    @property
    def description(self) -> str:
        return "List source documents that were imported into the local lesson knowledge base."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
            "required": [],
        }

    async def execute(self, **kwargs: Any) -> str:
        try:
            collection = self._get_collection()
            data = collection.get(include=["metadatas"])
            docs_by_id: dict[str, dict[str, Any]] = {}
            for meta in data.get("metadatas", []):
                m = meta or {}
                doc_id = str(m.get("doc_id", ""))
                if not doc_id:
                    continue
                if doc_id not in docs_by_id:
                    docs_by_id[doc_id] = {
                        "doc_id": doc_id,
                        "source_path": m.get("source_path", ""),
                        "subject": m.get("subject", ""),
                        "grade": m.get("grade", ""),
                        "chunks": 0,
                    }
                docs_by_id[doc_id]["chunks"] += 1

            return json.dumps({"status": "ok", "documents": list(docs_by_id.values())}, ensure_ascii=False)
        except Exception as exc:
            return f"Error: failed to list documents: {exc}"


class DocumentDeleteTool(_EducationDocMixin, Tool):
    """Delete imported documents from ChromaDB by doc_id."""

    @property
    def name(self) -> str:
        return "document_delete"

    @property
    def description(self) -> str:
        return "Delete an imported document from local vector database by doc_id."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "doc_id": {"type": "string", "description": "Document ID from document_list/document_import"},
            },
            "required": ["doc_id"],
        }

    async def execute(self, doc_id: str, **kwargs: Any) -> str:
        try:
            collection = self._get_collection()
            collection.delete(where={"doc_id": doc_id})
            return json.dumps({"status": "ok", "deleted_doc_id": doc_id}, ensure_ascii=False)
        except Exception as exc:
            return f"Error: failed to delete document: {exc}"
