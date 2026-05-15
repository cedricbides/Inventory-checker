"""GUI package column/comparison selector."""
import os

if os.environ.get("GUI", "0") == "1":
    from .app import launch_gui
else:
    from .tui import launch_gui

__all__ = ["launch_gui"]