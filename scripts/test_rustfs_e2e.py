"""
End-to-end test: RustFS → RAGRig S3 source ingestion → object storage sink export.

RustFS runs on http://localhost:9100 with credentials rustfsadmin/rustfsadmin.
Buckets:  ragrig-source  (input)   ragrig-sink  (output)
"""

from __future__ import annotations

import os
import sys

project_root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(project_root, "src"))
sys.path.insert(0, project_root)  # for scripts module referenced by web_console

# SQLite compatibility patches (mirrors conftest.py)
import sqlalchemy
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from pgvector.sqlalchemy import Vector


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


@compiles(Vector, "sqlite")
def _compile_vector_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


import boto3
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from ragrig.db.models import Base
from ragrig.repositories import get_or_create_knowledge_base
from ragrig.plugins.sources.s3.connector import ingest_s3_source
from ragrig.plugins.sinks.object_storage.connector import export_to_object_storage

# ── Configuration ─────────────────────────────────────────────────────────────

RUSTFS_ENDPOINT = "http://localhost:9100"
RUSTFS_ACCESS_KEY = "rustfsadmin"
RUSTFS_SECRET_KEY = "rustfsadmin"

SOURCE_BUCKET = "ragrig-source"
SINK_BUCKET = "ragrig-sink"
KB_NAME = "rustfs-test"
DB_PATH = "/tmp/ragrig_rustfs_test.db"

# ── Database setup ─────────────────────────────────────────────────────────────

print("=" * 60)
print("Setting up SQLite database …")
engine = create_engine(
    f"sqlite+pysqlite:///{DB_PATH}",
    future=True,
    poolclass=NullPool,
)
Base.metadata.create_all(engine)


def session_factory() -> Session:
    return Session(engine, expire_on_commit=False)


with session_factory() as session:
    kb = get_or_create_knowledge_base(session, KB_NAME)
    session.commit()
    print(f"Knowledge base '{KB_NAME}' ready (id={kb.id})")

# ── STEP 1: Verify source bucket contents ─────────────────────────────────────

print("\n" + "=" * 60)
print("STEP 1 — Verify objects in source bucket …")

s3 = boto3.client(
    "s3",
    endpoint_url=RUSTFS_ENDPOINT,
    aws_access_key_id=RUSTFS_ACCESS_KEY,
    aws_secret_access_key=RUSTFS_SECRET_KEY,
    region_name="us-east-1",
)

resp = s3.list_objects_v2(Bucket=SOURCE_BUCKET)
objects = resp.get("Contents", [])
print(f"Found {len(objects)} objects:")
for obj in objects:
    print(f"  {obj['Key']}  ({obj['Size']} bytes)")

# ── STEP 2: S3 Source ingestion ────────────────────────────────────────────────

print("\n" + "=" * 60)
print("STEP 2 — Ingesting S3 source into RAGRig …")

s3_source_config = {
    "bucket": SOURCE_BUCKET,
    "endpoint_url": RUSTFS_ENDPOINT,
    "access_key": "env:AWS_ACCESS_KEY_ID",
    "secret_key": "env:AWS_SECRET_ACCESS_KEY",
    "region": "us-east-1",
    "use_path_style": True,
    "verify_tls": False,
    "include_patterns": ["*.txt", "*.md"],
    "page_size": 1000,
}
env = {"AWS_ACCESS_KEY_ID": RUSTFS_ACCESS_KEY, "AWS_SECRET_ACCESS_KEY": RUSTFS_SECRET_KEY}

with session_factory() as session:
    report = ingest_s3_source(
        session=session,
        knowledge_base_name=KB_NAME,
        config=s3_source_config,
        env=env,
    )
    session.commit()

print(f"Ingestion report:")
print(f"  pipeline_run_id  : {report.pipeline_run_id}")
print(f"  created_documents: {report.created_documents}")
print(f"  created_versions : {report.created_versions}")
print(f"  skipped_count    : {report.skipped_count}")
print(f"  failed_count     : {report.failed_count}")

assert report.created_documents > 0, "Expected documents to be created"
assert report.created_versions > 0, "Expected new document versions to be created"

# ── STEP 3: Chunk & Embed (index) ─────────────────────────────────────────────

print("\n" + "=" * 60)
print("STEP 3 — Indexing (chunk + embed) …")

from ragrig.web_console import index_knowledge_base

with session_factory() as session:
    idx_report = index_knowledge_base(session=session, knowledge_base_name=KB_NAME)
    session.commit()

print(f"Indexing report:")
print(f"  pipeline_run_id  : {idx_report.pipeline_run_id}")
print(f"  indexed_count    : {idx_report.indexed_count}")
print(f"  chunk_count      : {idx_report.chunk_count}")
print(f"  embedding_count  : {idx_report.embedding_count}")
print(f"  skipped_count    : {idx_report.skipped_count}")
print(f"  failed_count     : {idx_report.failed_count}")

assert idx_report.indexed_count > 0, "Expected versions to be indexed"
assert idx_report.chunk_count > 0, "Expected chunks to be created"

# ── STEP 4: Retrieval smoke test ───────────────────────────────────────────────

print("\n" + "=" * 60)
print("STEP 4 — Retrieval smoke test …")

with engine.connect() as conn:
    chunk_count = conn.execute(text("SELECT COUNT(*) FROM chunks")).scalar()
    doc_count = conn.execute(text("SELECT COUNT(*) FROM documents")).scalar()

print(f"  Documents in DB: {doc_count}")
print(f"  Chunks in DB   : {chunk_count}")

assert chunk_count > 0, "Expected chunks in the database"

# Show a sample chunk
with engine.connect() as conn:
    sample = conn.execute(text("SELECT text FROM chunks ORDER BY id LIMIT 1")).fetchone()
    print(f"  Sample chunk preview: {sample[0][:100]!r} …")

# ── STEP 5: Object storage sink export ────────────────────────────────────────

print("\n" + "=" * 60)
print("STEP 5 — Exporting to RustFS sink bucket …")

sink_config = {
    "bucket": SINK_BUCKET,
    "endpoint_url": RUSTFS_ENDPOINT,
    "access_key": "env:AWS_ACCESS_KEY_ID",
    "secret_key": "env:AWS_SECRET_ACCESS_KEY",
    "region": "us-east-1",
    "use_path_style": True,
    "verify_tls": False,
    "path_template": "{knowledge_base}/{run_id}/{artifact}.{format}",
    "overwrite": True,
    "dry_run": False,
    "include_retrieval_artifact": True,
    "include_markdown_summary": True,
    "parquet_export": True,  # test parquet too since pyarrow is installed
}

with session_factory() as session:
    export_report = export_to_object_storage(
        session=session,
        knowledge_base_name=KB_NAME,
        config=sink_config,
        env=env,
    )
    session.commit()

print(f"Export report:")
print(f"  pipeline_run_id  : {export_report.pipeline_run_id}")
print(f"  planned_count    : {export_report.planned_count}")
print(f"  uploaded_count   : {export_report.uploaded_count}")
print(f"  skipped_count    : {export_report.skipped_count}")
print(f"  failed_count     : {export_report.failed_count}")
print(f"  dry_run          : {export_report.dry_run}")
print(f"  artifact_keys    : {export_report.artifact_keys}")

assert not export_report.dry_run
assert export_report.failed_count == 0, (
    f"Expected 0 failed exports, got {export_report.failed_count}"
)

# ── STEP 6: Verify sink objects in RustFS ─────────────────────────────────────

print("\n" + "=" * 60)
print("STEP 6 — Verify exported objects in sink bucket …")

resp = s3.list_objects_v2(Bucket=SINK_BUCKET)
sink_objects = resp.get("Contents", [])
print(f"Found {len(sink_objects)} objects in '{SINK_BUCKET}':")
for obj in sink_objects:
    size_kb = obj["Size"] / 1024
    print(f"  {obj['Key']}  ({size_kb:.1f} KB)")

assert len(sink_objects) > 0, "Expected exported objects in sink bucket"

# Download and peek at the JSON artifact
json_keys = [o["Key"] for o in sink_objects if o["Key"].endswith(".json")]
if json_keys:
    import json

    obj_body = s3.get_object(Bucket=SINK_BUCKET, Key=json_keys[0])["Body"].read()
    data = json.loads(obj_body)
    if isinstance(data, list):
        print(
            f"\n  JSON artifact has {len(data)} records. First record keys: {list(data[0].keys()) if data else '(empty)'}"
        )
    else:
        print(f"\n  JSON artifact keys: {list(data.keys())}")

# ── Summary ────────────────────────────────────────────────────────────────────

print("\n" + "=" * 60)
print("✓ ALL STEPS PASSED")
print()
print("Flow summary:")
print(f"  Source      : RustFS s3://{SOURCE_BUCKET}/ ({len(objects)} objects)")
print(f"  Ingested    : {report.created_versions} documents → {idx_report.chunk_count} chunks")
print(f"  Sink        : RustFS s3://{SINK_BUCKET}/ ({len(sink_objects)} artifacts uploaded)")
print("=" * 60)
