"""Print the API's OpenAPI spec. The web (and later Android) clients are generated from it.

uv run python -m app.openapi > ../web/openapi.json && npm --prefix ../web run gen:api
"""

import json

from app.main import app

print(json.dumps(app.openapi(), indent=2))
