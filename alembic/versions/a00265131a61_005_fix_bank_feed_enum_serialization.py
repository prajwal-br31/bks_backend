"""005_fix_bank_feed_enum_serialization

Revision ID: a00265131a61
Revises: 5aa22abf9649
Create Date: 2025-12-08 02:55:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = 'a00265131a61'
down_revision: Union[str, None] = '5aa22abf9649'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Convert enum columns to VARCHAR to fix serialization issues.
    
    SQLAlchemy's native enum handling can cause issues where enum names
    are used instead of enum values. Converting to VARCHAR ensures
    SQLAlchemy properly uses the enum's value attribute.
    """
    # Convert bank_files.status from enum to VARCHAR
    op.execute("""
        ALTER TABLE bank_files 
        ALTER COLUMN status TYPE VARCHAR(50) 
        USING status::text
    """)
    
    # Convert bank_transactions.type from enum to VARCHAR
    op.execute("""
        ALTER TABLE bank_transactions 
        ALTER COLUMN type TYPE VARCHAR(50) 
        USING type::text
    """)
    
    # Convert bank_transactions.status from enum to VARCHAR
    op.execute("""
        ALTER TABLE bank_transactions 
        ALTER COLUMN status TYPE VARCHAR(50) 
        USING status::text
    """)
    
    # Convert bank_matches.matched_type from enum to VARCHAR
    op.execute("""
        ALTER TABLE bank_matches 
        ALTER COLUMN matched_type TYPE VARCHAR(50) 
        USING matched_type::text
    """)
    
    # Convert bank_files.classification_status from enum to VARCHAR
    op.execute("""
        ALTER TABLE bank_files 
        ALTER COLUMN classification_status TYPE VARCHAR(50) 
        USING classification_status::text
    """)
    
    # Convert bank_transactions.classification_status from enum to VARCHAR
    op.execute("""
        ALTER TABLE bank_transactions 
        ALTER COLUMN classification_status TYPE VARCHAR(50) 
        USING classification_status::text
    """)


def downgrade() -> None:
    """
    Convert VARCHAR columns back to enums.
    Note: This may fail if data doesn't match enum values.
    """
    # Convert back to enums (this may fail if invalid data exists)
    op.execute("""
        ALTER TABLE bank_files 
        ALTER COLUMN status TYPE filestatus 
        USING status::filestatus
    """)
    
    op.execute("""
        ALTER TABLE bank_transactions 
        ALTER COLUMN type TYPE transactiontype 
        USING type::transactiontype
    """)
    
    op.execute("""
        ALTER TABLE bank_transactions 
        ALTER COLUMN status TYPE transactionstatus 
        USING status::transactionstatus
    """)
    
    op.execute("""
        ALTER TABLE bank_matches 
        ALTER COLUMN matched_type TYPE matchedentitytype 
        USING matched_type::matchedentitytype
    """)
    
    op.execute("""
        ALTER TABLE bank_files 
        ALTER COLUMN classification_status TYPE classificationstatus 
        USING classification_status::classificationstatus
    """)
    
    op.execute("""
        ALTER TABLE bank_transactions 
        ALTER COLUMN classification_status TYPE classificationstatus 
        USING classification_status::classificationstatus
    """)
