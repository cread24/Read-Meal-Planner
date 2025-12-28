# set_favs.py
from app import create_app, db
from app.models import Recipe

app = create_app()
with app.app_context():
    # Let's mark the first 10 recipes as favourites for testing
    recipes = Recipe.query.limit(10).all()
    for r in recipes:
        r.is_favourite = True
    
    db.session.commit()
    print(f"✅ Marked {len(recipes)} recipes as favourites!")