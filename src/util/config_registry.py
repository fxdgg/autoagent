"""Global configuration registry.

Provides a single source of truth for the merged configuration so that
all modules read from the same dict instead of independently loading
``config.yaml`` from disk.

Typical usage::

    # At startup (orchestrator.py main()):
    from util.config_registry import set_config
    config = _load_config()          # load default config.yaml
    if args.settings:
        settings = yaml.safe_load(open(args.settings))
        config.update(settings)
    set_config(config)

    # In any module:
    from util.config_registry import get_config, is_registered
    if is_registered():
        cfg = get_config()
    else:
        cfg = _fallback_load()       # legacy file-based loading
"""

import logging

logger = logging.getLogger(__name__)

_config: dict | None = None


def set_config(config: dict) -> None:
    """Register the merged configuration dict.

    Should be called exactly once during startup, after all config
    layers (default config.yaml + ``--settings`` overlay) have been
    merged.
    """
    global _config
    _config = config
    logger.debug("Config registry: configuration registered")


def get_config() -> dict:
    """Return the registered configuration.

    Returns an empty dict if :func:`set_config` has not been called.
    """
    if _config is None:
        return {}
    return _config


def is_registered() -> bool:
    """Return True if a configuration has been registered."""
    return _config is not None
