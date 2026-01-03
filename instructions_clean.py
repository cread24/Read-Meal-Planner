import re
from app import db, create_app
from app.models import Recipe

app = create_app()
with app.app_context():
    recipes = Recipe.query.all()
    for r in recipes:
        if r.instructions:
            # 1. Fix merged words (lowerCaseUpperCase -> lowerCase. UpperCase)
            # This looks for 'eR' and turns it into 'e. R'
            cleaned = re.sub(r'([a-z])([A-Z])', r'\1. \2', r.instructions)
            
            # 2. Fix multiple full stops if they already existed
            cleaned = cleaned.replace('..', '.')
            
            r.instructions = cleaned
    
    db.session.commit()
    print("Database instructions cleaned!")