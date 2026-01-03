# app/services/planner_service.py

from app.models import Recipe, Ingredient, RecipeIngredient, db, Label, ConfirmedPlan
from typing import List, Dict, Tuple
from sqlalchemy import select
from sqlalchemy.orm import selectinload
import random
import numpy as np
from datetime import datetime, timedelta

# --- Unit Standardization Mapping ---
# Maps units to a (base_unit, conversion_factor)
# Example: 1 kg = 1000 g, 1 l = 1000 ml

UNIT_CONVERSIONS = {
    # Mass Conversions (Base: g - Grams)
    'g': ('g', 1.0),
    'gram': ('g', 1.0),
    'grams': ('g', 1.0),
    'kg': ('g', 1000.0),
    'kilogram': ('g', 1000.0),
    
    # Volume Conversions (Base: ml - Milliliters)
    'ml': ('ml', 1.0),
    'millilitre': ('ml', 1.0),
    'l': ('ml', 1000.0),
    'litre': ('ml', 1000.0),
    'litres': ('ml', 1000.0),
    
    # Simple Counts/Units (Base: item - Item)
    'item': ('item', 1.0),
    'items': ('item', 1.0),
    'tsp': ('tsp', 1.0),
    'tbsp': ('tbsp', 1.0),
    'clove': ('clove', 1.0),
    'cloves': ('clove', 1.0),
    
    # Units we cannot convert or are complex (Keep separate)
    'to taste': ('to taste', 1.0),
    'splash': ('splash', 1.0),
    'pinch': ('pinch', 1.0),
    'pack': ('pack', 1.0)
}

# --- Diversity and Constraint Configuration ---
# Define minimum/maximum number of recipes allowed for specific labels.
# This ensures a balanced week of meals.

LABEL_CONSTRAINTS = {
    # Label Title: (Min Recipes, Max Recipes)
    'Spicy': (0, 2),        # Max 2 spicy meals
    'Quick': (1, 7),        # At least 1 quick meal, up to all of them
    'Healthy': (2, 7),      # Aim for at least 2 healthy options
    'Vegetarian': (0, 7)    # No specific constraint, but can be added later
}

# The maximum number of recipes the user requested
MAX_PLAN_SIZE = 5

def standardize_ingredient_unit(quantity: float, unit: str) -> Tuple[float, str]:
    """
    Converts a quantity and unit to a standard base unit using UNIT_CONVERSIONS.
    """
    # Clean the unit to handle minor variations
    clean_unit = unit.lower().strip()
    
    conversion = UNIT_CONVERSIONS.get(clean_unit)
    
    if conversion:
        base_unit, factor = conversion
        standardized_quantity = quantity * factor
        return standardized_quantity, base_unit
    else:
        # If unit is not in the map, return original values for aggregation under 'other'
        return quantity, clean_unit

# We need a small helper function to format the ingredient data consistently
def get_raw_ingredients_for_recipes(recipe_ids: List[int]) -> List[Dict]:
    """
    Queries the database to fetch all RecipeIngredient association objects 
    for the given list of recipe IDs.
    """
    
    # Use SQLAlchemy to select all RecipeIngredient records where the recipe_id is in the list
    # Eagerly load the associated Ingredient object for the name and is_basic flag
    query = (
        select(RecipeIngredient)
        .where(RecipeIngredient.recipe_id.in_(recipe_ids))
        .join(Ingredient) # Join to Ingredient to get its name/flags
    )
    
    raw_links = db.session.scalars(query).all()
    
    raw_ingredients_list = []
    
    for link in raw_links:
        # Extract and consolidate the necessary information
        raw_ingredients_list.append({
            'name': link.ingredient.name,
            'quantity': link.quantity,
            'unit': link.unit,
            'is_basic': link.ingredient.is_basic
        })
        
    return raw_ingredients_list

def generate_optimized_shopping_list(recipe_ids: List[int]) -> Dict:
    """
    1. Fetches full Recipe objects.
    2. Filters recipes using diversity constraints.
    3. Aggregates and standardizes units for the final shopping list.
    """
    if not recipe_ids:
        return {"error": "No recipes selected."}

    # 1. Fetch full Recipe objects (we need the .labels relationship here)
# 1. Fetch full Recipe objects (we need the .labels relationship here)
    all_recipes = db.session.scalars(
        select(Recipe)
        .where(Recipe.id.in_(recipe_ids))
        .options(selectinload(Recipe.labels)) # Use selectinload for the secondary=db.Table relationship
    ).all()
    
    # 2. Filter the recipe set based on constraints
    # NOTE: Since the recipes variable holds full Recipe objects, we need to pass those.
    optimized_ids = find_optimized_recipe_set(all_recipes)
    
    # Identify which recipes were selected in the optimization step (for clean output)
    final_recipe_set = [r for r in all_recipes if r.id in optimized_ids]
    
    # 3. Get raw ingredients for the OPTIMIZED list
    raw_ingredients = get_raw_ingredients_for_recipes(optimized_ids)
    
    # 4. Proceed with unit standardization and aggregation (as before)
    # ... (Aggregation logic is the same) ...

    # Dictionary to hold the aggregated items
    aggregated_items = {}
    basics_check = [] 
    
    for item in raw_ingredients:
        name = item['name'].title()
        unit = item['unit']
        quantity = item['quantity']
        is_basic = item['is_basic']
        
        if is_basic:
            if name not in basics_check:
                basics_check.append(name)
            continue

        standardized_quantity, standardized_unit = standardize_ingredient_unit(quantity, unit)
        key = (name, standardized_unit)
        aggregated_items[key] = aggregated_items.get(key, 0) + standardized_quantity
    
    grouped_list = {
        'Meat': [], 'Fish': [], 'Veg': [], 'Dairy': [], 
        'Pantry': [], 'Bread': [], 'Other': []
    }

    # Instead of a flat list, we sort them as we loop through aggregated_items
    for (name, unit), quantity in aggregated_items.items():
        # Fetch the ingredient to get its category
        ing = Ingredient.query.filter_by(name=name.lower()).first()
        cat = ing.category if (ing and ing.category) else 'Other'
        
        item_data = {"name": name, "quantity": quantity, "unit": unit}
        
        if cat in grouped_list:
            grouped_list[cat].append(item_data)
        else:
            grouped_list['Other'].append(item_data)
            
    return {
        "grouped_shopping_list": grouped_list,
        "basics_check_list": basics_check,
        "total_recipes": len(recipe_ids)
    }

def check_constraints(recipes: List[Recipe], constraints: Dict[str, Tuple[int, int]]) -> bool:
    """
    Checks if the given list of Recipe objects meets all defined label constraints.
    """
    # 1. Count how many recipes belong to each constrained label
    label_counts = {label: 0 for label in constraints.keys()}
    
    for recipe in recipes:
        # Get the titles of all labels for the current recipe
        recipe_label_titles = [label.title for label in recipe.labels]
        
        # Increment the count for any label that is in our constraints
        for title in recipe_label_titles:
            if title in constraints:
                label_counts[title] += 1

    # 2. Check all min/max requirements
    for label, (min_count, max_count) in constraints.items():
        current_count = label_counts.get(label, 0)
        
        # Check if the count is outside the allowed range
        if current_count < min_count or current_count > max_count:
            return False # Fails a constraint

    return True # Passes all constraints

def find_optimized_recipe_set(all_recipes: List[Recipe]) -> List[int]:
    """
    Searches for a subset of recipes that meets the diversity constraints.
    This uses a basic greedy approach (or exhaustive if MAX_PLAN_SIZE is small).
    Since we don't have user preferences yet, we'll start with the first valid set.
    """
    
    # Simple approach: Check all combinations (if MAX_PLAN_SIZE is small, e.g., <= 8)
    # For a small set of recipes selected by the user, this is fine.
    
    # NOTE: Since the current routes.py just sends all selected recipes, we will modify
    # this function to check the ENTIRE list the user selected. If the list is too 
    # large, we will attempt to find a valid subset of size MAX_PLAN_SIZE.
    
    if len(all_recipes) <= MAX_PLAN_SIZE:
        # If the user selected few enough recipes, just check if they are valid.
        if check_constraints(all_recipes, LABEL_CONSTRAINTS):
            return [r.id for r in all_recipes]
        else:
            # If the user's small selection fails, we must return a message.
            print("User's selection failed constraints. Returning first valid set...")
            # For simplicity, we skip complex subset searching and return the original set 
            # to let the aggregation run, but you would normally return an error message.
            return [r.id for r in all_recipes]
            
    else:
        # If the user selected too many recipes, try to find a valid subset of size MAX_PLAN_SIZE
        # In a real app, this would use an algorithm (like simulated annealing or simple
        # random selection/backtracking) to find the 'best' plan.
        
        # For our current scope, we will just take the first MAX_PLAN_SIZE recipes
        # and see if they pass. If not, we return the first MAX_PLAN_SIZE regardless.
        
        candidate_recipes = all_recipes[:MAX_PLAN_SIZE]
        if check_constraints(candidate_recipes, LABEL_CONSTRAINTS):
            return [r.id for r in candidate_recipes]
        else:
             print("Too many recipes selected. Returning unoptimized set of max size.")
             return [r.id for r in all_recipes[:MAX_PLAN_SIZE]]

def get_recent_recipe_ids(days=14):
    """Retrieves a set of all recipe IDs eaten in the last fortnight."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    recent_plans = ConfirmedPlan.query.filter(ConfirmedPlan.date_confirmed >= cutoff).all()
    
    recent_ids = set()
    for plan in recent_plans:
        # Turn "1,2,3" back into {1, 2, 3}
        ids = {int(rid) for rid in plan.recipe_ids.split(',') if rid}
        recent_ids.update(ids)
    return recent_ids

# List of labels that don't describe a flavor profile/cuisine
NOISY_LABELS = {'All Gousto Recipes', 'Gluten Free Recipes', 'Dairy Free', 'New'}

def calculate_affinity_score(recipe_a, recipe_b, prefs=None, recent_ids=None):
    score = 0.0
    recent_ids = recent_ids or set()
    prefs = prefs or {}
    
    # 1. Ingredient Synergy (+5 for fresh shared items)
    ing_a = {link.ingredient.name for link in recipe_a.ingredients if not link.ingredient.is_basic}
    ing_b = {link.ingredient.name for link in recipe_b.ingredients if not link.ingredient.is_basic}
    score += len(ing_a.intersection(ing_b)) * 5.0
    
    # 2. Cuisine Variance (-2 for shared REAL cuisines)
    labels_a = {l.title for l in recipe_a.labels if l.title not in NOISY_LABELS}
    labels_b = {l.title for l in recipe_b.labels if l.title not in NOISY_LABELS}
    score -= len(labels_a.intersection(labels_b)) * 2.0 

    # 3. Preference Weighting (New!)
    max_cal = prefs.get('max_calories')
    if max_cal:
        actual_cal = recipe_a.calories
        if actual_cal and actual_cal <= max_cal:
            # Base boost for being under the limit
            score += 15.0
            # Extra bonus if it's "Light" (e.g., 100+ calories under the limit)
            if (max_cal - actual_cal) >= 100:
                score += 5.0

    # 4. Smart Time Weighting
    max_time = prefs.get('max_time')
    if max_time:
        actual_time = recipe_a.time_minutes
        if actual_time and actual_time <= max_time:
            score += 15.0
            # Extra bonus for "Express" meals (under 20 mins)
            if actual_time <= 20:
                score += 5.0

    # 5. Recency Penalty (The "Boredom" Filter)
    if recipe_a.id in recent_ids:
        score -= 50.0 # A heavy penalty to push it to the bottom of the pile

    return score

# app/services/planner_service.py

def suggest_meal_plan(seed_recipe_id: int, count: int = 5, prefs: dict = None) -> List[Recipe]:
    prefs = prefs or {}
    seed_recipe = db.session.get(Recipe, seed_recipe_id)
    plan = [seed_recipe]
    recent_ids = get_recent_recipe_ids(days=14)
    
    # 1. Base Candidates Query
    query = select(Recipe).where(Recipe.id != seed_recipe_id)
    
    # 2. Apply Hard Limits (e.g., Vegetarian)
    if prefs.get('veg_only'):
        # Assuming recipes have a 'Vegetarian' label
        query = query.join(Recipe.labels).where(Label.title == 'Vegetarian')
    
    candidates = db.session.scalars(
        query.options(selectinload(Recipe.labels), selectinload(Recipe.ingredients))
    ).all()
    
    while len(plan) < count and candidates:
        scores = []
        for candidate in candidates:
            # Pass preferences into our affinity logic
            total_affinity = sum(calculate_affinity_score(candidate, r, prefs, recent_ids) for r in plan)
            scores.append(total_affinity)
        
        # Softmax-style weight conversion
        min_score = min(scores)
        weights = [(s - min_score) + 1 for s in scores]
        
        next_recipe = random.choices(candidates, weights=weights, k=1)[0]
        plan.append(next_recipe)
        candidates.remove(next_recipe)
            
    return plan

def get_synergy_report(recipe_ids: List[int]) -> List[str]:
    """Identifies fresh ingredients appearing in 2+ recipes."""
    recipes = db.session.scalars(
        select(Recipe).where(Recipe.id.in_(recipe_ids)).options(selectinload(Recipe.ingredients))
    ).all()
    
    counts = {}
    for r in recipes:
        fresh = {link.ingredient.name.title() for link in r.ingredients if not link.ingredient.is_basic}
        for ing in fresh:
            counts[ing] = counts.get(ing, 0) + 1
            
    return [ing for ing, count in counts.items() if count > 1]

def suggest_single_replacement(current_plan_ids, exclude_ids, prefs=None, mode='all'):
    prefs = prefs or {}
    plan_objects = [db.session.get(Recipe, rid) for rid in current_plan_ids]
    
    query = select(Recipe).where(Recipe.id.notin_(exclude_ids))
    
    # Apply Hard Limit for Favourites
    if mode == 'favs':
        query = query.where(Recipe.is_favourite == True)
    
    # Apply other Hard Limits
    if prefs.get('veg_only'):
        query = query.join(Recipe.labels).where(Label.title.ilike('%Vegetarian%'))

    candidates = db.session.scalars(query).all()

    # Fallback: If no favourites match your filters, broaden to all recipes
    if not candidates:
        return suggest_single_replacement(current_plan_ids, exclude_ids, prefs, mode='all')

    scores = []
    for c in candidates:
        total_affinity = sum(calculate_affinity_score(c, r, prefs) for r in plan_objects)
        scores.append(total_affinity)
    
    min_score = min(scores)
    weights = [(s - min_score) + 1 for s in scores]
    return random.choices(candidates, weights=weights, k=1)[0]

def suggest_single_recipe(existing_ids: List[int], category: str = 'All', prefs: dict = None) -> Recipe:
    prefs = prefs or {}
    recent_ids = get_recent_recipe_ids(days=14)
    
    # 1. Fetch current locked-in recipes
    locked_recipes = []
    if existing_ids:
        locked_recipes = db.session.scalars(
            select(Recipe).where(Recipe.id.in_(existing_ids))
            .options(selectinload(Recipe.labels), selectinload(Recipe.ingredients))
        ).all()

    # 2. Broad Candidate Query (No hard limits on time/calories here)
    query = select(Recipe).where(Recipe.is_disliked == False)
    
    if category != 'All':
        query = query.where(Recipe.category == category)
    
    if existing_ids:
        query = query.where(Recipe.id.notin_(existing_ids))

    candidates = db.session.scalars(
        query.options(selectinload(Recipe.labels), selectinload(Recipe.ingredients))
    ).all()

    if not candidates:
        return None

    # 3. Scoring Logic (This is where weighting happens)
    scores = []
    for c in candidates:
        # Start with a base affinity based on synergy with other meals
        if not locked_recipes:
            total_score = 0.0
        else:
            total_score = sum(calculate_affinity_score(c, r, prefs, recent_ids) for r in locked_recipes)
        
        # ADDED: Self-weighting for the candidate's own stats
        # Even if there are no locked recipes, we still want to weight by prefs
        total_score += calculate_individual_weight(c, prefs)
        
        scores.append(total_score)

    # 4. Pick the winner using the weighted probabilities
    min_score = min(scores)
    weights = [(s - min_score) + 1 for s in scores]
    
    return random.choices(candidates, weights=weights, k=1)[0]

def calculate_individual_weight(recipe, prefs):
    """Gives a bonus/penalty to a recipe based on its own stats vs prefs."""
    bonus = 0.0
    
    # Weight by Calories
    max_cal = prefs.get('max_calories')
    if max_cal and recipe.calories:
        if recipe.calories <= int(max_cal):
            bonus += 20.0  # Significant boost for being under the limit
        else:
            bonus -= 20.0  # Penalty for being over, but NOT a hard exclusion
            
    # Weight by Time
    max_time = prefs.get('max_time')
    if max_time and recipe.time_minutes:
        if recipe.time_minutes <= int(max_time):
            bonus += 20.0
        else:
            bonus -= 20.0
            
    return bonus