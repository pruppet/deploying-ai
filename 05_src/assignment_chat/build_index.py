# Convert campaign-note sections into a persistent Chroma collection for retrieval.
import os
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions
from dotenv import load_dotenv

load_dotenv(".env")
load_dotenv(".secrets")

BASE_DIR = Path(__file__).parent
NOTES_DIR = BASE_DIR / "campaign_notes"
CHROMA_DIR = BASE_DIR / "chroma_db"
COLLECTION_NAME = "campaign_lore"
EMBEDDING_MODEL = "text-embedding-3-small"
GATEWAY_BASE_URL = "https://k7uffyg03f.execute-api.us-east-1.amazonaws.com/prod/openai/v1"


def get_embedding_function():
    """The same function must be used here and in the app when querying."""
    gateway_key = os.environ.get("API_GATEWAY_KEY")
    if not gateway_key:
        raise ValueError("Missing API_GATEWAY_KEY environment variable")

    return embedding_functions.OpenAIEmbeddingFunction(
        model_name=EMBEDDING_MODEL,
        api_key="gateway-auth-is-in-x-api-key",
        api_base=GATEWAY_BASE_URL,
        default_headers={"x-api-key": gateway_key},
    )


def parse_note(path: Path):
    """Split a note into (header metadata, list of (heading, body) sections)."""
    text = path.read_text(encoding="utf-8").strip()

    header = {}
    if text.startswith("---"):
        _, header_block, text = text.split("---", 2)
        for line in header_block.strip().splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                header[key.strip()] = value.strip()

    sections = []
    for block in ("\n" + text).split("\n## ")[1:]:
        heading, _, body = block.partition("\n")
        body = body.strip()
        if body:
            sections.append((heading.strip(), body))
    return header, sections


def build_chunks(notes_dir: Path):
    """Return parallel lists of ids, documents and metadatas for Chroma."""
    ids, documents, metadatas = [], [], []

    for path in sorted(notes_dir.rglob("*.md")):
        header, sections = parse_note(path)
        name = header.get("name", path.stem)
        note_type = header.get("type", path.parent.name)
        relative = path.relative_to(notes_dir).as_posix()

        for index, (heading, body) in enumerate(sections):
            # Keep each retrieved section identifiable without relying on adjacent chunks.
            documents.append(f"{name} ({note_type}), {heading}: {body}")
            ids.append(f"{relative}::{index}")

            metadata = {
                "name": name,
                "type": note_type,
                "section": heading,
                "source_file": relative,
                "dm_only": "DM Only" in heading,
            }
            # Chroma metadata must be str, int, float or bool, so header
            # fields (including comma-separated lists) are stored as strings.
            for key in ("aliases", "location", "faction", "related", "status"):
                if header.get(key):
                    metadata[key] = header[key]
            if header.get("session_number", "").isdigit():
                metadata["session_number"] = int(header["session_number"])
            metadatas.append(metadata)

    return ids, documents, metadatas


def build_index():
    ids, documents, metadatas = build_chunks(NOTES_DIR)
    if not ids:
        raise SystemExit(f"No notes found in {NOTES_DIR}")

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))

    # Rebuild from scratch so edited or deleted sections leave no stale chunks.
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass

    collection = client.create_collection(
        name=COLLECTION_NAME,
        embedding_function=get_embedding_function(),
        metadata={"hnsw:space": "cosine"},
    )
    collection.add(ids=ids, documents=documents, metadatas=metadatas)
    print(f"Indexed {len(ids)} chunks from {NOTES_DIR} into {CHROMA_DIR}")


if __name__ == "__main__":
    build_index()