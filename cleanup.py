"""Global cleanup registry for graceful SIGINT/SIGTERM handling."""

_registry: list = []


def register_for_cleanup(obj):
    """Register a process/collector for cleanup on signal interrupt."""
    _registry.append(obj)


def unregister_for_cleanup(obj):
    """Remove a process/collector from cleanup registry."""
    try:
        _registry.remove(obj)
    except ValueError:
        pass


def cleanup_all():
    """Stop/kill all registered objects."""
    for obj in list(_registry):
        try:
            if hasattr(obj, "stop"):
                obj.stop()
            elif hasattr(obj, "kill"):
                obj.kill()
        except Exception:
            pass
    _registry.clear()
