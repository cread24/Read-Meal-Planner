# app/routes.py
from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify
from .models import Recipe, db, ConfirmedPlan, Ingredient
from .services.planner_service import suggest_meal_plan, generate_optimized_shopping_list, get_synergy_report, suggest_single_replacement, suggest_single_recipe
from sqlalchemy import func
from flask import request
import re
from markupsafe import Markup

main_bp = Blueprint('main', __name__)

@main_bp.before_request
def debug_request():
    print(f"DEBUG: Path {request.path} | Method {request.method}")

@main_bp.route('/')
def index():
    if 'current_plan' not in session or not isinstance(session['current_plan'], list):
        session['current_plan'] = [None] * 6
    
    # 1. Resolve recipe objects for the grid
    current_ids = [rid for rid in session['current_plan'] if rid]
    slots = [db.session.get(Recipe, rid) if rid else None for rid in session['current_plan']]
    
    # 2. Generate the synergy report for the currently selected IDs
    synergy_items = []
    if len(current_ids) > 1:
        # Using your existing function from planner_service.py
        synergy_items = get_synergy_report(current_ids)
    
    return render_template('index.html', slots=slots, synergy=synergy_items)

@main_bp.route('/randomise_slot/<int:slot_index>', methods=['POST'])
def randomise_slot(slot_index):
    # 1. Safety Check: Re-initialise if session was lost/timed out
    if 'current_plan' not in session or not isinstance(session['current_plan'], list):
        session['current_plan'] = [None] * 6
    
    # If the list is the wrong size, fix it while preserving what we can
    if len(session['current_plan']) != 6:
        new_plan = [None] * 6
        for i in range(min(len(session['current_plan']), 6)):
            new_plan[i] = session['current_plan'][i]
        session['current_plan'] = new_plan

    category = request.form.get('category', 'All')
    
    # 2. Collect Prefs from the form (passed by our JS mirror)
    prefs = {
        'max_time': request.form.get('max_time'),
        'max_calories': request.form.get('max_cal')
    }

    # 3. Get existing IDs for synergy (excluding the current slot)
    current_plan = session['current_plan']
    existing_ids = [rid for i, rid in enumerate(current_plan) if rid and i != slot_index]

    # 4. Call Service
    new_recipe = suggest_single_recipe(existing_ids, category, prefs)
    
    if new_recipe:
        # Now this is safe from IndexError
        current_plan[slot_index] = new_recipe.id
        session['current_plan'] = current_plan
        session.modified = True
        
    return redirect(url_for('main.index'))

@main_bp.route('/clear_slot/<int:slot_index>', methods=['POST'])
def clear_slot(slot_index):
    current_plan = session['current_plan']
    current_plan[slot_index] = None
    session['current_plan'] = current_plan
    session.modified = True
    return redirect(url_for('main.index'))

@main_bp.route('/generate_plan', methods=['POST', 'GET'])
def generate_plan():
    seed_id = request.form.get('seed_id')
    if not seed_id:
        return redirect(url_for('main.index'))
    
    # Gather preferences from form
    prefs = {
        'max_calories': request.form.get('max_cal', type=int),
        'max_time': request.form.get('max_time', type=int),
        'veg_only': 'veg_only' in request.form
    }
    session['current_prefs'] = prefs # Save for shuffling later
    
    suggested_recipes = suggest_meal_plan(int(seed_id), count=5, prefs=prefs)
    session['current_plan'] = [r.id for r in suggested_recipes]
    
    # Generate the synergy report
    synergy = get_synergy_report(session['current_plan'])
    
    return render_template('plan_display.html', recipes=suggested_recipes, synergy=synergy)

# app/routes.py

@main_bp.route('/shuffle/<int:index>', methods=['POST'])
def shuffle(index):
    current_ids = session.get('current_plan', [])
    prefs = session.get('current_prefs', {})
    
    # Check which button was pressed
    shuffle_mode = request.form.get('mode', 'all') 
    
    fixed_ids = [rid for i, rid in enumerate(current_ids) if i != index]
    
    # Pass the mode into the service
    new_recipe = suggest_single_replacement(fixed_ids, current_ids, prefs, mode=shuffle_mode)
    
    current_ids[index] = new_recipe.id
    session['current_plan'] = current_ids
    
    recipes = [db.session.get(Recipe, rid) for rid in current_ids]
    synergy = get_synergy_report(current_ids)
    
    return render_template('plan_display.html', recipes=recipes, synergy=synergy)

@main_bp.route('/api/finalise_plan', methods=['POST'])
def finalise_plan():
    current_ids = [rid for rid in session.get('current_plan', []) if rid]
    
    if not current_ids:
        return jsonify({"status": "error", "message": "No recipes selected"}), 400
    
    try:
        # 1. Clear previous plan
        ConfirmedPlan.query.delete()
        
        # 2. Convert list [1, 2, 3] to string "1,2,3"
        ids_string = ",".join(map(str, current_ids))
        
        # 3. Create the entry using the correct column name: recipe_ids
        new_plan = ConfirmedPlan(recipe_ids=ids_string)
        db.session.add(new_plan)
        
        db.session.commit()
        
        # 4. Clear session
        session.pop('current_plan', None)
        return jsonify({"status": "success"})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

@main_bp.route('/current-plan')
def current_plan():
    plan = ConfirmedPlan.query.first()
    
    # If no plan exists, we still need to send 'None' so the template doesn't crash
    if not plan or not plan.recipe_ids:
        return render_template('current_plan.html', recipes=[], active_recipe=None)
    
    # Convert string "1,2,3" to list [1, 2, 3]
    id_list = [int(rid) for rid in plan.recipe_ids.split(',') if rid]
    recipes = [db.session.get(Recipe, rid) for rid in id_list]
    
    # Handle the "?active=ID" URL parameter from the sidebar clicks
    requested_id = request.args.get('active', type=int)
    active_recipe = None
    
    if requested_id:
        active_recipe = db.session.get(Recipe, requested_id)
    
    # Fallback: Default to the first recipe if none is selected
    if not active_recipe and recipes:
        active_recipe = recipes[0]
    
    # CRITICAL: 'active_recipe' must be in this return statement
    return render_template('current_plan.html', 
                           recipes=recipes, 
                           active_recipe=active_recipe)

@main_bp.route('/toggle_dislike/<int:recipe_id>', methods=['POST']) 
def toggle_dislike(recipe_id):
    recipe = db.session.get(Recipe, recipe_id)
    if recipe:
        recipe.is_disliked = not recipe.is_disliked
        db.session.commit()
    return redirect(request.referrer or url_for('main.plan_display'))

@main_bp.route('/api/shopping_list_preview')
def shopping_list_preview():
    # 1. Try to get IDs from session (Planner view)
    current_ids = [rid for rid in session.get('current_plan', []) if rid]

    # 2. If session is empty, look at the Database (Current Plan view)
    if not current_ids:
        planned_items = ConfirmedPlan.query.all()
        current_ids = []
        for item in planned_items:
            if item.recipe_ids:
                # Splits "1,2,5" into [1, 2, 5]
                ids = [int(rid) for rid in str(item.recipe_ids).split(',') if rid.strip()]
                current_ids.extend(ids)
    
    if not current_ids:
        return jsonify({"grouped_shopping_list": {}, "basics_check_list": []})
    
    report = generate_optimized_shopping_list(current_ids)
    return jsonify(report)

@main_bp.route('/api/update_ingredient_category', methods=['POST'])
def update_ingredient_category():
    data = request.json
    ing_name = data.get('name')
    new_cat = data.get('category')
    
    # Use func.lower to match regardless of capitalisation
    ingredient = Ingredient.query.filter(func.lower(Ingredient.name) == ing_name.lower()).first()
    
    if ingredient:
        ingredient.category = new_cat
        db.session.commit()
        return jsonify({"status": "success"})
    
    return jsonify({"status": "error", "message": f"Ingredient '{ing_name}' not found"}), 404
