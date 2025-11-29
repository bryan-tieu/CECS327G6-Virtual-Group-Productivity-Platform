# tests/conftest.py
import os
import sys
import pytest

# Path to the folder that contains server.py
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from server import PlatformServer 
@pytest.fixture
def server():
    """
    Returns a fresh PlatformServer instance for each test.
    We don't call start_server(), we just use the object directly.
    """
    s = PlatformServer()
    # Optional: make timeouts shorter for tests
    s.tx_timeout_seconds = 0.2
    return s