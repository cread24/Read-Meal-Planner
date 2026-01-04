import logging
import re

from app import create_app, db
from app.models import Recipe

app = create_app()
with app.app_context():
    recipes = Recipe.query.all()
    for r in recipes:
        if r.instructions:
            cleaned = re.sub(r"([a-z])([A-Z])", r"\1. \2", r.instructions)
            cleaned = cleaned.replace("..", ".")
            r.instructions = cleaned

    db.session.commit()
    logging.info("Database instructions cleaned")
