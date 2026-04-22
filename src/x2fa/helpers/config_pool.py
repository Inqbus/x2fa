"""ConfigPool - holds loaded config instances, tracks missing configs."""

from pathlib import Path

from x2fa.helpers.attr_dict import AttrDict


class ConfigPool:
    """Pool of loaded configs with tracking of missing config files."""

    def __init__(self, config_dir: Path):
        self._config_dir = config_dir
        self._loaded = {}
        self._missing = {}

    def add_config(self, namespace: str, config_instance):
        """Add a successfully loaded config instance."""
        self._loaded[namespace] = config_instance

    def add_missing(self, namespace: str, filename: str):
        """Track a missing config namespace."""
        self._missing[namespace] = filename

    def __getattr__(self, name: str):
        if name in self._loaded:
            return self._loaded[name]
        if name in self._missing:
            raise AttributeError(
                f"Config file '{self._missing[name]}' not found in {self._config_dir}. "
                f"Run the installer first to generate configuration files."
            )
        raise AttributeError(f"Config namespace '{name}' not available")

    def __iter__(self):
        """Iterate over loaded config namespaces."""
        return iter(self._loaded)
