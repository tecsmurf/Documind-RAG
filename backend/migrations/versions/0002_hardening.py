"""Hardening: account state, processing metadata, message status, cascading FKs.

Additive and data-preserving:
- users.is_active (default true), users.token_version (default 0)
- documents.processing_stage, page_count, content_hash, updated_at (backfilled
  from created_at so stale-processing detection works for old rows)
- messages.status (default 'complete' for existing rows)
- foreign keys re-created with ON DELETE CASCADE (same columns, same data)
- documents (user_id, content_hash) index for duplicate detection
- legacy documents stuck in 'processing' are marked 'error' (they can never finish)
- legacy raw exception text in error_message is replaced with a safe message

Revision ID: 0002_hardening
Revises: 0001_baseline
Create Date: 2026-10-01
"""
from alembic import op

revision = "0002_hardening"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None

_FKS = [
    # (table, constraint, column, referenced table)
    ("documents", "documents_user_id_fkey", "user_id", "users"),
    ("chunks", "chunks_document_id_fkey", "document_id", "documents"),
    ("conversations", "conversations_user_id_fkey", "user_id", "users"),
    ("messages", "messages_conversation_id_fkey", "conversation_id", "conversations"),
]


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 0")

    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS processing_stage VARCHAR(30)")
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS page_count INTEGER")
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)")
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ")
    op.execute("UPDATE documents SET updated_at = created_at WHERE updated_at IS NULL")
    op.execute("ALTER TABLE documents ALTER COLUMN total_chunks SET DEFAULT 0")
    op.execute(
        "UPDATE documents SET status = 'error', "
        "error_message = 'Processing was interrupted. Try uploading the document again.' "
        "WHERE status = 'processing'"
    )
    # Old rows stored raw provider/parser exception text; replace it with a safe message.
    op.execute(
        "UPDATE documents SET error_message = 'Document processing failed. Try uploading the document again.' "
        "WHERE status = 'error' AND error_message IS DISTINCT FROM "
        "'Processing was interrupted. Try uploading the document again.'"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_documents_user_hash ON documents (user_id, content_hash)")

    op.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'complete'")

    for table, name, column, ref in _FKS:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {name} FOREIGN KEY ({column}) "
            f"REFERENCES {ref}(id) ON DELETE CASCADE"
        )


def downgrade() -> None:
    for table, name, column, ref in _FKS:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} FOREIGN KEY ({column}) REFERENCES {ref}(id)")
    op.execute("DROP INDEX IF EXISTS ix_documents_user_hash")
    # Added columns are left in place on downgrade: dropping them would lose data.
