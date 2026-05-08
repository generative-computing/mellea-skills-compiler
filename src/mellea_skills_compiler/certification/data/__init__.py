import json
import os
from pathlib import Path


PACKAGEDIR = Path(__file__).parent.absolute()


def get_data_path():
    return os.path.join(PACKAGEDIR, "")
