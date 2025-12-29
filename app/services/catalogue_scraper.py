import requests
import time
import re
import json
from bs4 import BeautifulSoup
from flask import current_app
from app.models import Recipe, Ingredient, RecipeIngredient, Label, db, recipe_label

# --- 1. CONFIGURATION (Your Proven Logic) ---
GET_RECIPES_ENDPOINT = "https://production-api.gousto.co.uk/cmsreadbroker/v1/recipes?category=recipes"
GET_RECIPE_INFO_ENDPOINT = "https://production-api.gousto.co.uk/cmsreadbroker/v1/recipe/"
GET_RECIPES_PAGE_LIMIT = 16 
MAX_RECIPES = 96
POLL_DELAY = 3 

def clean_label(label_text):
    """Standardises labels: 'Vegetarian recipes' -> 'Vegetarian'"""
    if not label_text: return None
    # Use regex to strip 'recipes' or 'recipe' regardless of case
    return re.sub(r'\brecipes?\b', '', label_text, flags=re.IGNORECASE).strip()

def scrape_and_save_recipe(recipe_path, recipe_name, servings):
    """Processes a single recipe's deep details."""
    clean_path = recipe_path.lstrip('/')
    slug = clean_path.split('/')[-1]
    api_url = GET_RECIPE_INFO_ENDPOINT + slug

    try:
        response = requests.get(api_url)
        response.raise_for_status()
        api_data = response.json().get('data', {}).get('entry', {})
        if not api_data: return

        # --- DB UPSERT LOGIC ---
        recipe_id = api_data.get('id')
        recipe = db.session.get(Recipe, recipe_id)

        if recipe:
            # Clear old links for a clean update
            db.session.execute(RecipeIngredient.__table__.delete().where(RecipeIngredient.recipe_id == recipe.id))
            db.session.execute(recipe_label.delete().where(recipe_label.c.recipe_id == recipe.id))
        else:
            recipe = Recipe(id=recipe_id, name=recipe_name)
            db.session.add(recipe)

        # --- DATA EXTRACTION ---
        recipe.servings = servings
        recipe.time_minutes = api_data.get('prep_times', {}).get('for_2') or api_data.get('prep_times', {}).get('for_4')
        
        # New Visuals
        media = api_data.get('media', {})
        images = media.get('images', [])
        if images:
            # We specifically target the 'image' key found in your JSON extract
            # Attempt to get the 400px wide one (usually index 1)
            recipe.image_url = images[1].get('image') if len(images) > 1 else images[0].get('image')
        recipe.source_url = f"https://www.gousto.co.uk/cookbook/recipes/{slug}"

        # Clean Instructions
        raw_instr = api_data.get('cooking_instructions', [])
        recipe.instructions = '\n'.join([BeautifulSoup(s.get('instruction', ''), 'html.parser').get_text(strip=True) for s in raw_instr])
        recipe.nutritional_info = json.dumps(api_data.get('nutritional_information'))

        # --- SANITISED LABELS ---
        for cat in api_data.get('categories', []):
            title = clean_label(cat.get('title'))
            if title and title.lower() != 'all':
                lbl = Label.query.filter_by(title=title).first() or Label(title=title)
                if lbl not in recipe.labels:
                    recipe.labels.append(lbl)

        # --- INGREDIENT PARSING (Regex Logic) ---
        ingredient_map = {}
        for item in api_data.get('ingredients', []):
            name = item.get('name', 'N/A').strip()
            label = item.get('label', '')
            qty, unit = 1.0, 'item'
            
            # Pattern 1: (Quantity Unit) xMultiplier
            m1 = re.search(r'\(([\d\s\/\.]+)\s*([a-zA-Z]{1,4})\)(?:\s*x(\d+))?$', label, re.IGNORECASE)
            if m1:
                raw_qty, unit = m1.group(1).strip(), m1.group(2).strip()
                mult = int(m1.group(3)) if m1.group(3) else 1
                try:
                    base = eval(raw_qty) if '/' in raw_qty else float(raw_qty)
                    qty = base * mult
                except: pass
            else:
                m2 = re.search(r'x(\d+)$', label, re.IGNORECASE)
                if m2: qty = float(m2.group(1))

            if qty > 0:
                key = (name, unit)
                if key in ingredient_map: ingredient_map[key]['quantity'] += qty
                else: ingredient_map[key] = {'name': name, 'quantity': qty, 'unit': unit}

        # --- LINKING ---
        for ing in ingredient_map.values():
            ing_db = Ingredient.query.filter_by(name=ing['name']).first() or Ingredient(name=ing['name'])
            db.session.add(ing_db)
            db.session.flush()
            link = RecipeIngredient(recipe=recipe, ingredient=ing_db, quantity=ing['quantity'], unit=ing['unit'])
            db.session.add(link)

        db.session.commit()

    except Exception as e:
        db.session.rollback()
        print(f"⚠️ Error on {slug}: {e}")

def scrape_all_recipes():
    """Discovery Loop using proven offset pagination."""
    total_scraped = 0
    offset = 0
    print("--- Starting Full Catalogue Scrape ---")

    while True:
        api_url = f"{GET_RECIPES_ENDPOINT}&limit={GET_RECIPES_PAGE_LIMIT}&offset={offset}"
        print(f"📡 Fetching Page {(offset // GET_RECIPES_PAGE_LIMIT) + 1} (Offset: {offset})...")

        try:
            response = requests.get(api_url)
            response.raise_for_status()
            entries = response.json().get('data', {}).get('entries', [])

            if not entries:
                print("🏁 No more entries found.")
                break

            for entry in entries:
                path, name = entry.get('url'), entry.get('title')
                serv = entry.get('prep_times', {}).get('for_2', 2)
                
                if path and name:
                    print(f"  --> Processing: {name}")
                    scrape_and_save_recipe(path, name, serv)
                    total_scraped += 1
                
                if total_scraped >= MAX_RECIPES:
                    print(f"Reached limit of {MAX_RECIPES}.")
                    return

            offset += GET_RECIPES_PAGE_LIMIT
            time.sleep(POLL_DELAY)

        except Exception as e:
            print(f"❌ Catalogue Error: {e}")
            break
            
    print(f"--- Finished! Total recipes: {total_scraped} ---")

if __name__ == "__main__":
    from app import create_app
    app = create_app()
    with app.app_context():
        scrape_all_recipes()