# set_favs.py
import logging

from app import create_app, db
from app.models import Recipe

app = create_app()
with app.app_context():
    recipes = Recipe.query.limit(10).all()
    for r in recipes:
        r.is_favourite = True

    db.session.commit()
    logging.info("Marked %s recipes as favourites", len(recipes))
