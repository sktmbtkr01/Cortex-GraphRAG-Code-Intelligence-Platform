"""
Cortex Graph Builder - Neo4j Connection Manager.
Handles AuraDB connectivity, constraints, and standard Cypher execution.
"""

from typing import Any

from neo4j import GraphDatabase
from neo4j.exceptions import SessionExpired, ServiceUnavailable, TransientError

from core.config import settings
from core.logger import get_logger
from core.tenant import tenant_scoped_id

logger = get_logger(__name__)


class Neo4jManager:
    """Manages the Neo4j AuraDB graph database connection and schema."""

    def __init__(self):
        if not settings.neo4j_uri or not settings.neo4j_password:
            raise ValueError("Neo4j credentials missing from environment.")

        self.driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_username, settings.neo4j_password),
            max_connection_lifetime=300,
            connection_timeout=15,
            keep_alive=True,
        )
        self.verify_connectivity()

    def verify_connectivity(self) -> None:
        """Ping the Neo4j instance to ensure it's reachable."""
        try:
            self.driver.verify_connectivity()
            logger.info("Connected to Neo4j AuraDB.")
        except ServiceUnavailable as e:
            logger.error(f"Cannot connect to Neo4j: {e}")
            raise

    def close(self) -> None:
        if self.driver:
            self.driver.close()

    def setup_constraints(self) -> None:
        """Create uniqueness constraints for fast node lookups/merges."""
        constraints = [
            "CREATE CONSTRAINT IF NOT EXISTS FOR (r:Repository) REQUIRE r.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (f:File) REQUIRE f.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (fn:Function) REQUIRE fn.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (c:Class) REQUIRE c.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (i:Issue) REQUIRE i.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (p:PullRequest) REQUIRE p.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (co:Commit) REQUIRE co.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (ct:Contributor) REQUIRE ct.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (d:Dependency) REQUIRE d.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (m:Module) REQUIRE m.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (l:Label) REQUIRE l.id IS UNIQUE",
        ]

        with self.driver.session() as session:
            for query in constraints:
                session.run(query)
        logger.info("Verified Neo4j schema constraints.")

    def run_query(self, query: str, parameters: dict[str, Any] | None = None) -> list[dict]:
        """Execute a raw Cypher query and return the list of records."""
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                with self.driver.session() as session:
                    result = session.run(query, parameters or {})
                    return [dict(record) for record in result]
            except (ServiceUnavailable, SessionExpired, TransientError, OSError) as e:
                last_error = e
                logger.warning(
                    "Neo4j query failed on attempt %s/2, retrying with a fresh session: %s",
                    attempt + 1,
                    e,
                )
                self.verify_connectivity()
        raise last_error or RuntimeError("Neo4j query failed")

    def clear_database(self) -> None:
        """Wipes the entire database. DANGER!"""
        logger.warning("Wiping entire Neo4j database...")
        self.run_query("MATCH (n) DETACH DELETE n")

    def merge_node(self, label: str, unique_id: str, properties: dict[str, Any]) -> None:
        """
        Merge a node based on its unique ID.
        Uses parameterization for safe Cypher execution.
        """
        props_str = ", ".join([f"n.{k} = ${k}" for k in properties.keys() if k != "id"])

        query = f"""
        MERGE (n:{label} {{id: $id}})
        """
        if props_str:
            query += f"ON CREATE SET {props_str} ON MATCH SET {props_str}"

        params = {"id": unique_id, **properties}
        self.run_query(query, params)

    def merge_relationship(
        self,
        from_label: str,
        from_id: str,
        to_label: str,
        to_id: str,
        rel_type: str,
        properties: dict[str, Any] | None = None,
    ) -> None:
        """Merge a directed relationship between two nodes based on unique IDs."""
        props_str = ""
        if properties:
            assignments = ", ".join([f"r.{k} = ${k}" for k in properties.keys()])
            props_str = f"ON CREATE SET {assignments} ON MATCH SET {assignments}"

        query = f"""
        MATCH (a:{from_label} {{id: $from_id}})
        MATCH (b:{to_label} {{id: $to_id}})
        MERGE (a)-[r:{rel_type}]->(b)
        {props_str}
        """
        params = {"from_id": from_id, "to_id": to_id, **(properties or {})}
        self.run_query(query, params)

    def scoped_id(self, raw_id: str, user_id: str | None, is_public: bool = False) -> str:
        return tenant_scoped_id(raw_id, user_id, is_public)

    def merge_tenant_node(
        self,
        label: str,
        raw_id: str,
        properties: dict[str, Any],
        user_id: str | None,
        is_public: bool = False,
    ) -> str:
        scoped_id = self.scoped_id(raw_id, user_id, is_public)
        tenant_props = {
            **properties,
            "raw_id": raw_id,
            "user_id": user_id,
            "is_public": is_public,
        }
        self.merge_node(label, scoped_id, tenant_props)
        return scoped_id

    def merge_tenant_relationship(
        self,
        from_label: str,
        from_raw_id: str,
        to_label: str,
        to_raw_id: str,
        rel_type: str,
        user_id: str | None,
        is_public: bool = False,
        properties: dict[str, Any] | None = None,
    ) -> None:
        self.merge_relationship(
            from_label,
            self.scoped_id(from_raw_id, user_id, is_public),
            to_label,
            self.scoped_id(to_raw_id, user_id, is_public),
            rel_type,
            properties,
        )
