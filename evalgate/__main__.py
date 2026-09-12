"""Allow `python -m evalgate`."""
import sys

from .cli import main

sys.exit(main())
