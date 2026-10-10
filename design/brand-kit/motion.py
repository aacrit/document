"""void document motion system, re-exported from the studio engine.

The implementation lives in ``studio/engine/motion.py``; the renderer imports
it from there. This file keeps the brand kit's CLI and imports working:

    python design/brand-kit/motion.py            # 6 s demo strip -> demo/
    python design/brand-kit/motion.py --table    # preset table (settle times)
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from studio.engine.motion import *  # noqa: E402,F401,F403
from studio.engine import motion as _engine_motion  # noqa: E402

if __name__ == "__main__":
    _engine_motion.main(Path(__file__).resolve().parent)
