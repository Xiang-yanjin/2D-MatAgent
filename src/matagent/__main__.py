"""Allow python -m matagent to use the terminal interface."""

from .cli import main


if __name__ == "__main__":
    raise SystemExit(main())
