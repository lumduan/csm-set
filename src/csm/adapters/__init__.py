"""Database adapters for quant-infra-db integration.

PostgresAdapter (db_csm_set), MongoAdapter (csm_logs), and GatewayAdapter
(db_gateway) are coordinated by AdapterManager from FastAPI lifespan.
"""

from __future__ import annotations

__all__: list[str] = []
