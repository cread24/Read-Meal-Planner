import os
import sys
import importlib

# Ensure project root is on sys.path so `app` package can be imported
ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Import after modifying sys.path to avoid ModuleNotFoundError
app_mod = importlib.import_module("app")
app = app_mod.create_app()

with app.test_client() as c:
    r = c.get("/")
    print("GET / ->", r.status_code)

    r2 = c.get("/current-plan")
    print("GET /current-plan ->", r2.status_code)

    r3 = c.get("/api/shopping_list_preview")
    print("GET /api/shopping_list_preview ->", r3.status_code)
