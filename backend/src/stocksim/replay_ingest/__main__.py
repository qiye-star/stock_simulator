"""``python -m stocksim.replay_ingest`` 入口。"""

import sys

from .cli import run

if __name__ == "__main__":
    sys.exit(run())
