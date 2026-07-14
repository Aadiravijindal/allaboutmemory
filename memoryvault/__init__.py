"""MemoryVault — one memory your company owns, that every AI plugs into.

The 8 parts of the product map to modules:

  PART 1  The Vault        -> store.Vault, schema.MemoryUnit, crypto.Cipher
  PART 2  The Plugs        -> connectors.*, mcp_server.MCPServer
  PART 3  The Sync Engine  -> sync.SyncEngine
  PART 4  The Rescue Tool  -> rescue.RescueTool
  PART 5  The Control Room -> dashboard.py (Flask web app)
  PART 6  The Rulebook     -> policy.Policy (+ enforced in store.Vault)
  PART 7  The Cleaner      -> cleaner.Cleaner
  PART 8  Insights         -> insights.Insights
"""
from .schema import MemoryUnit, Provenance, MemoryType, DecayClass, MemoryStatus
from .store import Vault
from .policy import Policy
from .connectors import (Connector, FileConnector, ConnectorRegistry,
                         default_registry)
from .sync import SyncEngine
from .rescue import RescueTool
from .cleaner import Cleaner
from .insights import Insights
from .mcp_server import MCPServer

__version__ = "0.1.0"

__all__ = [
    "MemoryUnit", "Provenance", "MemoryType", "DecayClass", "MemoryStatus",
    "Vault", "Policy", "Connector", "FileConnector", "ConnectorRegistry",
    "default_registry", "SyncEngine", "RescueTool", "Cleaner", "Insights",
    "MCPServer",
]
