"""
Destructive one-off: wipe both Qdrant and Neo4j for a clean-slate environment.

Usage (from backend/):
    python -m scripts.reset_databases

Requires the user to type exactly: RESET
Nothing happens otherwise.
"""

from __future__ import annotations

import argparse
import sys

from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse
from neo4j import GraphDatabase

from core.config import settings


CONFIRM_PHRASE = "RESET"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Wipe both Qdrant and Neo4j for a clean-slate environment.",
    )
    parser.add_argument(
        "--confirm",
        type=str,
        default=None,
        help=f"Non-interactive confirmation phrase (must be exactly {CONFIRM_PHRASE!r}).",
    )
    return parser.parse_args()


def reset_qdrant() -> None:
    if not settings.qdrant_url:
        print("  [skip] QDRANT_URL not configured")
        return

    client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
    collection = settings.qdrant_collection

    try:
        client.delete_collection(collection_name=collection)
        print(f"  [ok]   deleted Qdrant collection: {collection}")
    except UnexpectedResponse as e:
        if "not found" in str(e).lower() or "404" in str(e):
            print(f"  [skip] Qdrant collection {collection!r} did not exist")
        else:
            raise


def reset_neo4j() -> None:
    if not (settings.neo4j_uri and settings.neo4j_password):
        print("  [skip] Neo4j credentials not configured")
        return

    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_username, settings.neo4j_password),
    )
    try:
        with driver.session() as session:
            # Count first so we can show what we're about to destroy.
            count_result = session.run("MATCH (n) RETURN count(n) AS c").single()
            node_count = count_result["c"] if count_result else 0
            print(f"  [info] Neo4j node count before wipe: {node_count}")

            # Wipe everything: nodes, relationships, indexes, constraints.
            session.run("MATCH (n) DETACH DELETE n")
            print("  [ok]   wiped all Neo4j nodes and relationships")

            # Drop all constraints + indexes so schema is truly blank.
            for row in session.run("SHOW CONSTRAINTS YIELD name").data():
                session.run(f"DROP CONSTRAINT `{row['name']}`")
                print(f"  [ok]   dropped constraint: {row['name']}")
            for row in session.run("SHOW INDEXES YIELD name, type WHERE type <> 'LOOKUP'").data():
                session.run(f"DROP INDEX `{row['name']}`")
                print(f"  [ok]   dropped index: {row['name']}")
    finally:
        driver.close()


def main() -> int:
    args = _parse_args()

    print("=" * 70)
    print(" CORTEX DATABASE RESET")
    print("=" * 70)
    print()
    print(f"  Qdrant collection: {settings.qdrant_collection}")
    print(f"  Qdrant URL:        {settings.qdrant_url}")
    print(f"  Neo4j URI:         {settings.neo4j_uri}")
    print()
    print("  This will IRREVERSIBLY delete:")
    print("    - The entire Qdrant collection and every chunk in it")
    print("    - Every Neo4j node, relationship, constraint, and index")
    print()

    if args.confirm is None:
        print("  Missing required confirmation flag.")
        print(f"  Re-run with: python -m scripts.reset_databases --confirm {CONFIRM_PHRASE}")
        return 1

    typed = args.confirm.strip()
    print(f"  Confirmation via --confirm: {typed!r}")

    if typed != CONFIRM_PHRASE:
        print("\n  Aborted. Nothing was deleted.")
        return 1

    print()
    print("Resetting Qdrant…")
    reset_qdrant()
    print()
    print("Resetting Neo4j…")
    reset_neo4j()
    print()
    print("Done. Both stores are empty.")
    print("Next ingest will recreate the Qdrant collection and Neo4j schema.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
