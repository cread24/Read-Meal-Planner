# app/routes.py
import logging
from datetime import datetime

from flask import (
    Blueprint,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from sqlalchemy import func

from .models import ConfirmedPlan, Ingredient, Recipe, db
from .services.planner_service import (
    generate_optimized_shopping_list,
    get_synergy_report,
    suggest_meal_plan,
    suggest_single_recipe,
    suggest_single_replacement,
)

main_bp = Blueprint("main", __name__)


@main_bp.before_request
def debug_request():
    logging.debug("Path %s | Method %s", request.path, request.method)


@main_bp.route("/")
def index():
    if "current_plan" not in session or not isinstance(session["current_plan"], list):
        session["current_plan"] = [None] * 6

    # 1. Resolve recipe objects for the grid
    current_ids = [rid for rid in session["current_plan"] if rid]
    slots = [
        db.session.get(Recipe, rid) if rid else None for rid in session["current_plan"]
    ]

    # 2. Generate the synergy report for the currently selected IDs
    synergy_items = []
    if len(current_ids) > 1:
        # Using your existing function from planner_service.py
        synergy_items = get_synergy_report(current_ids)

    # Check if a plan is already being cooked
    active_plan_exists = (
        ConfirmedPlan.query.filter_by(status="active").first() is not None
    )

    return render_template(
        "index.html",
        slots=slots,
        has_active_plan=active_plan_exists,
        synergy=synergy_items,
    )


@main_bp.route("/randomise_slot/<int:slot_index>", methods=["POST"])
def randomise_slot(slot_index):
    # 1. Safety Check: Re-initialise if session was lost/timed out
    if "current_plan" not in session or not isinstance(session["current_plan"], list):
        session["current_plan"] = [None] * 6

    # If the list is the wrong size, fix it while preserving what we can
    if len(session["current_plan"]) != 6:
        new_plan = [None] * 6
        for i in range(min(len(session["current_plan"]), 6)):
            new_plan[i] = session["current_plan"][i]
        session["current_plan"] = new_plan

    category = request.form.get("category", "All")

    # 2. Collect Prefs from the form (passed by our JS mirror)
    prefs = {
        "max_time": request.form.get("max_time"),
        "max_calories": request.form.get("max_cal"),
    }

    # 3. Get existing IDs for synergy (excluding the current slot)
    current_plan = session["current_plan"]
    existing_ids = [
        rid for i, rid in enumerate(current_plan) if rid and i != slot_index
    ]

    # 4. Call Service
    new_recipe = suggest_single_recipe(existing_ids, category, prefs)

    if new_recipe:
        # Now this is safe from IndexError
        current_plan[slot_index] = new_recipe.id
        session["current_plan"] = current_plan
        session.modified = True

    return redirect(url_for("main.index"))


@main_bp.route("/clear_slot/<int:slot_index>", methods=["POST"])
def clear_slot(slot_index):
    current_plan = session["current_plan"]
    current_plan[slot_index] = None
    session["current_plan"] = current_plan
    session.modified = True
    return redirect(url_for("main.index"))


@main_bp.route("/generate_plan", methods=["POST", "GET"])
def generate_plan():
    seed_id = request.form.get("seed_id")
    if not seed_id:
        return redirect(url_for("main.index"))

    # Gather preferences from form
    prefs = {
        "max_calories": request.form.get("max_cal", type=int),
        "max_time": request.form.get("max_time", type=int),
        "veg_only": "veg_only" in request.form,
    }
    session["current_prefs"] = prefs  # Save for shuffling later

    suggested_recipes = suggest_meal_plan(int(seed_id), count=5, prefs=prefs)
    session["current_plan"] = [r.id for r in suggested_recipes]

    # Generate the synergy report
    synergy = get_synergy_report(session["current_plan"])

    return render_template(
        "plan_display.html", recipes=suggested_recipes, synergy=synergy
    )


# app/routes.py


@main_bp.route("/shuffle/<int:index>", methods=["POST"])
def shuffle(index):
    current_ids = session.get("current_plan", [])
    prefs = session.get("current_prefs", {})

    # Check which button was pressed
    shuffle_mode = request.form.get("mode", "all")

    fixed_ids = [rid for i, rid in enumerate(current_ids) if i != index]

    # Pass the mode into the service
    new_recipe = suggest_single_replacement(
        fixed_ids, current_ids, prefs, mode=shuffle_mode
    )

    current_ids[index] = new_recipe.id
    session["current_plan"] = current_ids

    recipes = [db.session.get(Recipe, rid) for rid in current_ids]
    synergy = get_synergy_report(current_ids)

    return render_template("plan_display.html", recipes=recipes, synergy=synergy)


@main_bp.route("/api/finalise_plan", methods=["POST"])
def finalise_plan():
    try:
        current_ids = session.get("current_plan", [])
        valid_ids = [rid for rid in current_ids if rid is not None]

        if not valid_ids:
            return {"status": "error", "message": "No meals selected"}, 400

        recipe_ids_str = ",".join(map(str, valid_ids))

        # Look for existing active plan
        existing_plan = ConfirmedPlan.query.filter_by(status="active").first()

        if existing_plan:
            existing_plan.recipe_ids = recipe_ids_str
            existing_plan.date_confirmed = datetime.utcnow()
        else:
            new_plan = ConfirmedPlan(recipe_ids=recipe_ids_str, status="active")
            db.session.add(new_plan)

        db.session.commit()
        return {"status": "success"}  # Explicit JSON

    except Exception as e:
        logging.exception("Error in finalise_plan")
        return {"status": "error", "message": str(e)}, 500


@main_bp.route("/current-plan")
def current_plan():
    plan_record = ConfirmedPlan.query.filter_by(status="active").first()

    if not plan_record:
        return render_template("current_plan.html", recipes=[], active_recipe=None)

    # Convert "1,2,3" string back to objects
    id_list = [int(rid) for rid in plan_record.recipe_ids.split(",") if rid]
    recipes = [db.session.get(Recipe, rid) for rid in id_list]

    active_id = request.args.get("active", type=int)
    active_recipe = next(
        (r for r in recipes if r.id == active_id), recipes[0] if recipes else None
    )

    return render_template(
        "current_plan.html", recipes=recipes, active_recipe=active_recipe
    )


@main_bp.route("/toggle_dislike/<int:recipe_id>", methods=["POST"])
def toggle_dislike(recipe_id):
    recipe = db.session.get(Recipe, recipe_id)
    if recipe:
        recipe.is_disliked = not recipe.is_disliked
        db.session.commit()
    return redirect(request.referrer or url_for("main.plan_display"))


@main_bp.route("/api/shopping_list_preview")
def shopping_list_preview():
    # 1. Try to get IDs from session (Planner view)
    current_ids = [rid for rid in session.get("current_plan", []) if rid]

    # 2. If session is empty, look at the Database (Current Plan view)
    if not current_ids:
        planned_items = ConfirmedPlan.query.all()
        current_ids = []
        for item in planned_items:
            if item.recipe_ids:
                # Splits "1,2,5" into [1, 2, 5]
                ids = [
                    int(rid) for rid in str(item.recipe_ids).split(",") if rid.strip()
                ]
                current_ids.extend(ids)

    if not current_ids:
        return jsonify({"grouped_shopping_list": {}, "basics_check_list": []})

    report = generate_optimized_shopping_list(current_ids)
    return jsonify(report)


@main_bp.route("/api/update_ingredient_category", methods=["POST"])
def update_ingredient_category():
    data = request.json
    ing_name = data.get("name")
    new_cat = data.get("category")

    # Use func.lower to match regardless of capitalisation
    ingredient = Ingredient.query.filter(
        func.lower(Ingredient.name) == ing_name.lower()
    ).first()

    if ingredient:
        ingredient.category = new_cat
        db.session.commit()
        return jsonify({"status": "success"})

    return (
        jsonify({"status": "error", "message": f"Ingredient '{ing_name}' not found"}),
        404,
    )


# app/routes.py


@main_bp.route("/select_recipe/<int:slot_index>/<int:recipe_id>", methods=["POST"])
def select_recipe(slot_index, recipe_id):
    if "current_plan" not in session:
        session["current_plan"] = [None] * 6

    # Verify the recipe exists
    recipe = db.session.get(Recipe, recipe_id)
    if recipe:
        current_plan = session["current_plan"]
        current_plan[slot_index] = recipe.id
        session["current_plan"] = current_plan
        session.modified = True

    return redirect(url_for("main.index"))


@main_bp.route("/api/search_recipes")
def search_recipes():
    query = request.args.get("q", "").strip()
    only_favourites = request.args.get("favourites", "false") == "true"

    stmt = Recipe.query.filter(Recipe.is_disliked.is_(False))

    if only_favourites:
        stmt = stmt.filter(Recipe.is_favourite.is_(True))

    if query:
        stmt = stmt.filter(Recipe.name.ilike(f"%{query}%"))

    # Limit results for performance
    recipes = stmt.limit(10).all()

    return jsonify(
        [
            {"id": r.id, "name": r.name, "category": r.category, "time": r.time_minutes}
            for r in recipes
        ]
    )


@main_bp.route("/toggle_status/<int:recipe_id>/<string:status_type>", methods=["POST"])
def toggle_status(recipe_id, status_type):
    recipe = db.session.get(Recipe, recipe_id)
    if not recipe:
        return {"error": "Recipe not found"}, 404

    if status_type == "favourite":
        recipe.is_favourite = not recipe.is_favourite
        # Logic: If favourited, it cannot be disliked
        if recipe.is_favourite:
            recipe.is_disliked = False

    elif status_type == "dislike":
        recipe.is_disliked = not recipe.is_disliked
        # Logic: If disliked, it cannot be a favourite
        if recipe.is_disliked:
            recipe.is_favourite = False

    db.session.commit()
    return redirect(request.referrer or url_for("main.index"))


@main_bp.route("/complete_plan", methods=["POST"])
def complete_plan():
    plan = ConfirmedPlan.query.filter_by(status="active").first()
    if plan:
        plan.status = "completed"  # It's now history!
        plan.date_confirmed = datetime.utcnow()
        db.session.commit()
        session.pop("current_plan", None)  # Clear local draft
        flash("Plan moved to history. Recency bias applied!", "success")
    return redirect(url_for("main.index"))


@main_bp.route("/abandon_plan", methods=["POST"])
def abandon_plan():
    ConfirmedPlan.query.filter_by(status="active").delete()
    db.session.commit()
    session.pop("current_plan", None)
    flash("Plan deleted.", "info")
    return redirect(url_for("main.index"))


@main_bp.route("/reclassify_recipe/<int:recipe_id>", methods=["POST"])
def reclassify_recipe(recipe_id):
    new_category = request.form.get("category")
    recipe = db.session.get(Recipe, recipe_id)

    if recipe and new_category:
        recipe.category = new_category
        db.session.commit()
        flash(f"Updated {recipe.name} to {new_category}.", "success")

    return redirect(request.referrer or url_for("main.index"))
