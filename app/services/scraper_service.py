# app/services/scraper_service.py

import requests
from bs4 import BeautifulSoup 
import re
import json 
from flask import current_app
# Ensure all models and the association table are imported
from app.models import Recipe, Ingredient, RecipeIngredient, Label, db, recipe_label 

# Global variables/API Endpoints
GET_RECIPE_INFO_ENDPOINT = "https://production-api.gousto.co.uk/cmsreadbroker/v1/recipe/"

def scrape_and_save_recipe(recipe_path: str, recipe_name: str, servings: int) -> int:
    """
    Fetches recipe details from the Gousto API, parses the JSON, and saves/updates 
    the data to the database (Upsert). Includes:
    - Ingredient parsing (multiplier, zero-quantity skip, deduplication).
    - Linking of main and basic ingredients (with quantity/unit).
    - Linking of recipe labels (categories).
    - Robust method for clearing old links (necessary for UPSERT).
    """
    
    clean_path = recipe_path.lstrip('/')
    slug = clean_path.split('/')[-1]
    
    api_url = GET_RECIPE_INFO_ENDPOINT + slug
    
    # --- Initialize variables ---
    time_minutes = None
    nutritional_info = None
    instructions_text = ""
    basic_items = [] 
    label_titles = []
    ingredient_map = {} 

    try:
        # 1. Fetch JSON content from the API
        response = requests.get(api_url)
        response.raise_for_status() 
        api_data = response.json()
        
        # --- 2. Extract Fields ---
        recipe_details = api_data.get('data', {}).get('entry', {})
        
        if not recipe_details:
             raise ValueError("API returned no recipe entry data.")

        # TIME
        prep_times = recipe_details.get('prep_times', {})
        time_minutes = prep_times.get('for_2')
        if time_minutes is None:
            time_minutes = prep_times.get('for_4') 
        
        # INSTRUCTIONS (Cleaning HTML tags)
        raw_instructions = recipe_details.get('cooking_instructions', [])
        all_steps_text = []
        for step in raw_instructions:
            step_html = step.get('instruction')
            if step_html:
                clean_step = BeautifulSoup(step_html, 'html.parser').get_text(strip=True)
                all_steps_text.append(clean_step)
        instructions_text = '\n'.join(all_steps_text)
        
        # NUTRITION (Store as JSON string)
        nutritional_data_object = recipe_details.get('nutritional_information')
        if nutritional_data_object:
            nutritional_info = json.dumps(nutritional_data_object)
            
        # LABELS (Categories)
        raw_categories = recipe_details.get('categories', [])
        label_titles = [cat.get('title') for cat in raw_categories if cat.get('title')]

        # BASIC INGREDIENTS
        raw_basics_list = recipe_details.get('basics', [])
        for item in raw_basics_list:
            basic_items.append(item.get('title').lower().strip()) 

        # MAIN INGREDIENTS: Parsing, Deduplication, Multiplier Logic
        raw_ingredients_list = recipe_details.get('ingredients', [])
        
        for item in raw_ingredients_list:
            ingredient_name = item.get('name', 'N/A').strip()
            ingredient_label = item.get('label', '') 

            # --- Pattern Check Initialization ---
            quantity = 1.0 
            unit = 'item' 
            multiplier = 1 
            
            # --- Pattern 1: (Quantity Unit) xMultiplier ---
            match_pattern_1 = re.search(r'\(([\d\s\/\.]+)\s*([a-zA-Z]{1,4})\)(?:\s*x(\d+))?$', ingredient_label, re.IGNORECASE)
            
            if match_pattern_1:
                raw_quantity = match_pattern_1.group(1).strip() 
                unit = match_pattern_1.group(2).strip()
                raw_multiplier = match_pattern_1.group(3)
                
                if raw_multiplier is not None:
                    try:
                        multiplier = int(raw_multiplier)
                    except ValueError:
                        pass
                        
                try:
                    # Safely evaluate fractions (e.g., 1/2) and convert to float
                    base_quantity = eval(raw_quantity) if '/' in raw_quantity else float(raw_quantity)
                    quantity = base_quantity * multiplier
                except Exception:
                    pass
            
            else:
                # --- Pattern 2: Name xMultiplier (No Quantity/Unit in brackets, e.g., "White potato x3") ---
                multiplier_match = re.search(r'x(\d+)$', ingredient_label, re.IGNORECASE)
                
                if multiplier_match:
                    raw_multiplier = multiplier_match.group(1)
                    try:
                        quantity = float(raw_multiplier) 
                        unit = 'item'
                    except ValueError:
                        pass
                
            # --- SKIP IF QUANTITY IS ZERO ---
            if quantity == 0:
                continue
            
            # --- DEDUPLICATION LOGIC (Sums quantities of identical items/units) ---
            key = (ingredient_name, unit)
            if key in ingredient_map:
                ingredient_map[key]['quantity'] += quantity
            else:
                ingredient_map[key] = {
                    'name': ingredient_name,
                    'quantity': quantity,
                    'unit': unit
                }

        parsed_ingredients = list(ingredient_map.values())


        # --- 3. Database Interaction (UPSERT Logic) ---
        with current_app.app_context():
            
            # Find existing or create new Recipe (UPSERT)
            existing_recipe = db.session.scalar(db.select(Recipe).filter_by(name=recipe_name).limit(1))

            if existing_recipe:
                recipe = existing_recipe
                
                # --- CORRECTED CLEARING METHOD (Avoids AppenderQuery error) ---
                
                # 1. Clear all RecipeIngredient links (Association Object)
                db.session.execute(
                    RecipeIngredient.__table__.delete().where(
                        RecipeIngredient.recipe_id == recipe.id
                    )
                )
                
                # 2. Clear all RecipeLabel links (Association Table)
                db.session.execute(
                    recipe_label.delete().where(
                        recipe_label.c.recipe_id == recipe.id
                    )
                )
            else:
                recipe = Recipe(name=recipe_name, category="Gousto")
                db.session.add(recipe)

            # Update Recipe Fields
            recipe.servings = servings
            recipe.instructions = instructions_text
            recipe.time_minutes = time_minutes
            recipe.nutritional_info = nutritional_info
            
            db.session.flush()

            # 3f. Process and Link Labels
            for title in label_titles:
                label_db = db.session.scalar(db.select(Label).filter_by(title=title).limit(1))
                if not label_db:
                    label_db = Label(title=title)
                    db.session.add(label_db)
                
                db.session.flush() 
                
                # Link the Label to the Recipe using the relationship
                if label_db not in recipe.labels:
                    recipe.labels.append(label_db)
            
            # 3a. Process and LINK Basic Ingredients (uses default quantity/unit)
            for basic_name in basic_items:
                ingredient_db = db.session.scalar(db.select(Ingredient).filter_by(name=basic_name).limit(1))
                
                if not ingredient_db:
                    ingredient_db = Ingredient(name=basic_name, is_basic=True)
                    db.session.add(ingredient_db)
                elif not ingredient_db.is_basic:
                    ingredient_db.is_basic = True
                
                db.session.flush() 
                
                recipe_link = RecipeIngredient(
                    recipe=recipe,
                    ingredient=ingredient_db,
                    quantity=1.0,         
                    unit='to taste'       
                )
                db.session.add(recipe_link)
                
            # 3d. Process and link Main Ingredients
            for item in parsed_ingredients:
                ingredient_db = db.session.scalar(db.select(Ingredient).filter_by(name=item['name']))
                
                if not ingredient_db:
                    ingredient_db = Ingredient(name=item['name'])
                    db.session.add(ingredient_db)
                    db.session.flush()
                    
                recipe_link = RecipeIngredient(
                    recipe=recipe,
                    ingredient=ingredient_db,
                    quantity=item['quantity'],
                    unit=item['unit']
                )
                db.session.add(recipe_link)
                
            # 3e. Final Save
            db.session.commit()
            
            return recipe.id

    except requests.RequestException as e:
        raise ValueError(f"Failed to fetch Gousto API for slug '{slug}'. Error: {e}")
    except Exception as e:
        # Log the full error internally, but raise a descriptive message externally
        print(f"FATAL ERROR during scraping/database commit for slug '{slug}': {e}")
        raise ValueError(f"Failed to process API data or commit to database: {e}")