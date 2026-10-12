import os
import sys

READER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ocr_reader")
if READER_DIR not in sys.path:
    sys.path.insert(0, READER_DIR)
