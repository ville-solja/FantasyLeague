import sys
import os

# Allow test files to import backend modules directly (e.g. `from scoring import ...`)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
