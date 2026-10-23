"""Configuration pytest.

pytest est lancé depuis /base_app (`make test`) alors que les modules du
projet vivent dans `app/` et sont importés sous leur nom « court »
(`libs.*`, `monkey_mcp.*`, `monkey_api.*`) — comme le fait `main.py` au
lancement avec /base_app/app comme cwd. On réplique ce sys.path ici pour que
les tests puissent importer les mêmes modules.
"""
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"

if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
