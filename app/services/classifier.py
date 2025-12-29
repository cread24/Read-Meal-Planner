# app/services/classifier.py
import re
from app.models import Recipe, db, RecipeIngredient

# Define our search terms
MEAT_MAP = {
    'Beef': ['beef', 'steak'],
    'Chicken': ['chicken'],
    'Pork': ['pork', 'bacon', 'sausage', 'gammon', 'ham', 'chorizo', 'pancetta', 'pigs in blankets'],
    'Fish' : ['fish', 'salmon', 'tuna', 'cod', 'trout', 'haddock', 'mackerel', 'sardine', 'anchovy', 
              'pollock', 'basa', 'prawn', 'shrimp', 'lobster', 'seafood', 'crab']
}

# Ingredients to ignore when categorising
DECEPTIVE_INGREDIENTS = ['stock', 'cube', 'mix', 'gravy', 'flavouring', 'bouillon']

def classify_all_recipes():
    recipes = Recipe.query.all()
    print(f"--- Classifying {len(recipes)} recipes ---")

    for recipe in recipes:
        assigned_category = "Other"
        
        # 1. Label Check (Vegetarian/Vegan)
        label_titles = [l.title.lower() for l in recipe.labels]
        if any(v in label_titles for v in ['vegetarian', 'vegan', 'meat free']):
            assigned_category = "Vegetarian"

        # 2: If not veggie, check for specific meat labels first
        elif any('chicken' in t for t in label_titles): assigned_category = "Chicken"
        elif any('beef' in t for t in label_titles): assigned_category = "Beef"
        elif any('pork' in t for t in label_titles): assigned_category = "Pork"
        elif any('fish' in t for t in label_titles): assigned_category = "Fish"

        # 3. If still Other, check for meat keywords in ingredients
        if assigned_category == "Other":
            # Explicitly query the link table for this recipe's ingredients
            links = RecipeIngredient.query.filter_by(recipe_id=recipe.id).all()
            
            ingredient_names = []
            for link in links:
                name = link.ingredient.name.lower()
                # Filter out stock, cubes, etc.
                if not any(d in name for d in DECEPTIVE_INGREDIENTS):
                    ingredient_names.append(name)
            
            combined_text = " ".join(ingredient_names)
            
            # Check against your MEAT_MAP
            for category, keywords in MEAT_MAP.items():
                if any(k in combined_text for k in keywords):
                    assigned_category = category
                    break

        recipe.category = assigned_category
        # Print progress to the terminal
        print(f"📌 {recipe.id}: {recipe.name[:25]} -> {assigned_category}")

    db.session.commit()
    print("--- Classification Complete ---")