"""MCP resource registrations."""

from .bible_resources import register_bible_resources
from .chroma_resources import register_chroma_resources
from .config_resources import register_config_resources
from .context_resources import register_context_resources
from .epub_resources import register_epub_resources
from .manifest_resources import register_manifest_resources
from .prompt_resources import register_prompt_resources
from .rag_resources import register_rag_resources

__all__ = [
    "register_bible_resources",
    "register_chroma_resources",
    "register_config_resources",
    "register_context_resources",
    "register_epub_resources",
    "register_manifest_resources",
    "register_prompt_resources",
    "register_rag_resources",
]

