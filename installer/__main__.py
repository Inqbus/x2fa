import argparse
import sys
from pathlib import Path

# Ensure the project root is on sys.path so that `installer` is importable
# regardless of how this script is invoked (uv run installer, python -m installer,
# or python installer/__main__.py directly).
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

try:
    from installer.app import InstallerApp
except ModuleNotFoundError as _e:
    if "textual" in str(_e):
        print(
            "Error: the 'installer' extra is not installed.\n"
            "\n"
            "Install it with:\n"
            "  uv tool install 'x2fa[installer]'\n"
            "  uv tool install 'x2fa[installer] @ x2fa-2.0.0-py3-none-any.whl'\n"
            "  pip install 'x2fa[installer] @ x2fa-2.0.0-py3-none-any.whl'\n",
            file=sys.stderr,
        )
        sys.exit(1)
    raise


def main() -> None:
    parser = argparse.ArgumentParser(
        description="X2FA interactive installer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "By default, config files are written to ~/.config/x2fa/ and\n"
            "data files (CA key, DB) to ~/.local/share/x2fa/.\n"
            "Use --config-root to relocate everything under a different base."
        ),
    )
    parser.add_argument(
        "--config-root",
        type=Path,
        default=None,
        metavar="DIR",
        help="Override the root directory for config and data files (default: ~)",
    )
    args = parser.parse_args()
    InstallerApp(x2fa_home=args.config_root).run()


if __name__ == "__main__":
    main()
