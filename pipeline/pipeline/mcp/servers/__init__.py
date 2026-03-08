"""MCP tool server registrations."""

from .bible_server import register_bible_tools
from .builder_server import register_builder_tools
from .config_server import register_config_tools
from .librarian_server import register_librarian_tools
from .metadata_server import register_metadata_tools
from .postprocessor_server import register_postprocessor_tools
from .qc_server import register_qc_tools
from .translator_server import register_translator_tools

__all__ = [
    "register_bible_tools",
    "register_builder_tools",
    "register_config_tools",
    "register_librarian_tools",
    "register_metadata_tools",
    "register_postprocessor_tools",
    "register_qc_tools",
    "register_translator_tools",
]

