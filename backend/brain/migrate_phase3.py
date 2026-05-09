"""
MAIHERA Phase 3 Schema Migration
Adds provenance fields to all existing Neo4j nodes.
Run once: python backend/brain/migrate_phase3.py
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv(Path(__file__).parent.parent / '.env')

from brain.schema import get_driver

def migrate():
    driver = get_driver()
    with driver.session() as session:
        # Add provenance fields to all existing nodes with safe defaults
        result = session.run("""
            MATCH (n:Node)
            WHERE n.evidence IS NULL
            SET n.evidence = [],
                n.source_ref = null,
                n.last_verified = null,
                n.is_stale = false,
                n.node_weight = 1.0
            RETURN count(n) as updated
        """)
        record = result.single()
        print(f"Migrated {record['updated']} existing nodes.")

        # Add new index for stale nodes — used by re-analysis pipeline
        session.run("""
            CREATE INDEX maihera_node_stale IF NOT EXISTS
            FOR (n:Node) ON (n.is_stale)
        """)
        print("Stale index created.")

        # Add index for source_ref — used by deduplication pipeline
        session.run("""
            CREATE INDEX maihera_node_source_ref IF NOT EXISTS
            FOR (n:Node) ON (n.source_ref)
        """)
        print("Source ref index created.")

    driver.close()
    print("Phase 3 migration complete.")

if __name__ == "__main__":
    migrate()