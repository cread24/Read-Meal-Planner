# app/routes.py
from flask import Blueprint, render_template, request, redirect, url_for, session
from .models import Recipe, db, ConfirmedPlan
from .services.planner_service import suggest_meal_plan, generate_optimized_shopping_list, get_synergy_report, suggest_single_replacement
from sqlalchemy import select
from flask import request

main_bp = Blueprint('main', __name__)

@main_bp.before_request
def debug_request():
    print(f"DEBUG: Path {request.path} | Method {request.method}")

@main_bp.route('/')
def index():
    all_recipes = Recipe.query.order_by(Recipe.name).all()
    fav_recipes = Recipe.query.filter_by(is_favourite=True).order_by(Recipe.name).all()
    return render_template('smart_index.html', recipes=all_recipes, favourites=fav_recipes)

# app/routes.py

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

@main_bp.route('/finalize')
def finalize():
    current_ids = session.get('current_plan', [])
    shopping_data = generate_optimized_shopping_list(current_ids)
    return render_template('shopping_list.html', shopping_data=shopping_data)

@main_bp.route('/confirm_plan', methods=['POST'])
def confirm_plan():
    current_plan = session.get('current_plan')
    if not current_plan:
        return redirect(url_for('main.index'))
    
    # Convert list of IDs to a comma-separated string
    ids_string = ",".join(map(str, current_plan))
    
    new_confirmation = ConfirmedPlan(recipe_ids=ids_string)
    db.session.add(new_confirmation)
    db.session.commit()
    
    # Clear the session so a new plan can be started
    session.pop('current_plan', None)
    
    return render_template('confirmation_success.html')

@main_bp.route('/toggle_dislike/<int:recipe_id>', methods=['POST']) 
def toggle_dislike(recipe_id):
    recipe = db.session.get(Recipe, recipe_id)
    if recipe:
        recipe.is_disliked = not recipe.is_disliked
        db.session.commit()
    return redirect(request.referrer or url_for('main.plan_display'))