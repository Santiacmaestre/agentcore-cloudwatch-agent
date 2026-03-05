"""cw_sre_agent – Conversational SRE incident-troubleshooting agent.

Entry point when called as ``python -m cw_sre_agent``.
"""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("cw-sre-agent")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"

__all__ = ["__version__"]
