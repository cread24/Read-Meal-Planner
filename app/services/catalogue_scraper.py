import json
import logging
import re
import time
from fractions import Fraction

import requests
from bs4 import BeautifulSoup

from app.models import Ingredient, Label, Recipe, RecipeIngredient, db, recipe_label

# --- 1. CONFIGURATION (Your Proven Logic) ---
GET_RECIPES_ENDPOINT = (
    "https://production-api.gousto.co.uk/cmsreadbroker/v1/recipes?category=recipes"
)
GET_RECIPE_INFO_ENDPOINT = (
    "https://production-api.gousto.co.uk/cmsreadbroker/v1/recipe/"
)
GET_RECIPES_PAGE_LIMIT = 16
MAX_RECIPES = 96
POLL_DELAY = 3


def clean_label(label_text):
    """Standardises labels: 'Vegetarian recipes' -> 'Vegetarian'"""
    if not label_text:
        return None
    # Use regex to strip 'recipes' or 'recipe' regardless of case
    return re.sub(r"\brecipes?\b", "", label_text, flags=re.IGNORECASE).strip()


def scrape_and_save_recipe(recipe_path, recipe_name, servings):
    clean_path = recipe_path.lstrip("/")
    slug = clean_path.split("/")[-1]
    api_url = GET_RECIPE_INFO_ENDPOINT + slug

    try:
        response = requests.get(api_url)
        response.raise_for_status()
        api_data = response.json().get("data", {}).get("entry", {})
        if not api_data:
            return

        # --- DB UPSERT LOGIC (Sequential ID Version) ---
        # Instead of db.session.get(Recipe, id), we filter by name or slug
        recipe = Recipe.query.filter_by(name=recipe_name).first()

        if recipe:
            # Clear old links for a clean update
            db.session.execute(
                RecipeIngredient.__table__.delete().where(
                    RecipeIngredient.recipe_id == recipe.id
                )
            )
            db.session.execute(
                recipe_label.delete().where(recipe_label.c.recipe_id == recipe.id)
            )
            db.session.flush()
        else:
            # Do not provide an id; the DB assigns a sequential ID automatically.
            recipe = Recipe(name=recipe_name)
            db.session.add(recipe)

        # IMPORTANT: Flush here so the DB generates the new sequential ID
        # for the recipe before we try to link ingredients/labels.
        db.session.flush()

        # --- DATA EXTRACTION ---
        recipe.servings = servings
        recipe.time_minutes = api_data.get("prep_times", {}).get(
            "for_2"
        ) or api_data.get("prep_times", {}).get("for_4")

        # New Visuals
        media = api_data.get("media", {})
        images = media.get("images", [])
        if images:
            # We specifically target the 'image' key found in your JSON extract
            # Attempt to get the 400px wide one (usually index 1)
            recipe.image_url = (
                images[1].get("image") if len(images) > 1 else images[0].get("image")
            )
        recipe.source_url = f"https://www.gousto.co.uk/cookbook/recipes/{slug}"

        # Clean Instructions
        raw_instr = api_data.get("cooking_instructions", [])
        recipe.instructions = "\n".join(
            [
                BeautifulSoup(s.get("instruction", ""), "html.parser").get_text(
                    separator=" ", strip=True
                )
                for s in raw_instr
            ]
        )
        recipe.nutritional_info = json.dumps(api_data.get("nutritional_information"))

        # --- SANITISED LABELS ---
        for cat in api_data.get("categories", []):
            title = clean_label(cat.get("title"))
            if title and title.lower() != "all":
                lbl = Label.query.filter_by(title=title).first() or Label(title=title)
                if lbl not in recipe.labels:
                    recipe.labels.append(lbl)

        # --- INGREDIENT PARSING (Regex Logic) ---
        ingredient_map = {}
        for item in api_data.get("ingredients", []):
            name = item.get("name", "N/A").strip()
            label = item.get("label", "")
            qty, unit = 1.0, "item"

            # Pattern 1: (Quantity Unit) xMultiplier
            m1 = re.search(
                r"\(([\d\s\/\.]+)\s*([a-zA-Z]{1,4})\)(?:\s*x(\d+))?$",
                label,
                re.IGNORECASE,
            )
            if m1:
                raw_qty, unit = m1.group(1).strip(), m1.group(2).strip()
                mult = int(m1.group(3)) if m1.group(3) else 1

                # Safe parsing for fractions and mixed numbers
                def parse_quantity(s: str):
                    s = s.strip()
                    try:
                        if " " in s:
                            whole, frac = s.split(" ", 1)
                            return float(int(whole) + Fraction(frac))
                        if "/" in s:
                            return float(Fraction(s))
                        return float(s)
                    except Exception:
                        logging.debug("Failed to parse quantity '%s'", s)
                        return None

                base = parse_quantity(raw_qty)
                if base is not None:
                    qty = base * mult
            else:
                m2 = re.search(r"x(\d+)$", label, re.IGNORECASE)
                if m2:
                    qty = float(m2.group(1))

            if qty > 0:
                key = (name, unit)
                if key in ingredient_map:
                    ingredient_map[key]["quantity"] += qty
                else:
                    ingredient_map[key] = {"name": name, "quantity": qty, "unit": unit}

        # --- LINKING ---
        # Ensure the recipe object has been flushed so it has an ID
        db.session.flush()

        for ing in ingredient_map.values():
            # 1. Skip if the name is empty or just "N/A"
            if not ing["name"] or ing["name"] == "N/A":
                continue

            # 2. Get or Create Ingredient
            ing_db = Ingredient.query.filter_by(name=ing["name"]).first()
            if not ing_db:
                ing_db = Ingredient(name=ing["name"], category="Other")
                db.session.add(ing_db)

            # 3. Flush to ensure ing_db has an ID before creating the link
            db.session.flush()

            # 4. Final Safety Check: Only link if BOTH IDs are present
            if recipe.id and ing_db.id:
                link = RecipeIngredient(
                    recipe_id=recipe.id,  # Use IDs directly for stability
                    ingredient_id=ing_db.id,
                    quantity=ing["quantity"],
                    unit=ing["unit"],
                )
                db.session.add(link)
            else:
                logging.warning(
                    "Skipping link: Recipe ID %s or Ing ID %s is NULL",
                    recipe.id,
                    getattr(ing_db, "id", None),
                )

        db.session.commit()

    except Exception:
        db.session.rollback()
        logging.exception("Error scraping recipe %s", slug)


def scrape_all_recipes():
    """Discovery Loop using proven offset pagination."""
    total_scraped = 0
    offset = 0
    logging.info("--- Starting Full Catalogue Scrape ---")

    while True:
        api_url = (
            f"{GET_RECIPES_ENDPOINT}&limit={GET_RECIPES_PAGE_LIMIT}&offset={offset}"
        )
        logging.info(
            "Fetching page %s (offset=%s)",
            (offset // GET_RECIPES_PAGE_LIMIT) + 1,
            offset,
        )

        try:
            response = requests.get(api_url)
            response.raise_for_status()
            entries = response.json().get("data", {}).get("entries", [])

            if not entries:
                logging.info("No more entries found.")
                break

            for entry in entries:
                path, name = entry.get("url"), entry.get("title")
                serv = entry.get("prep_times", {}).get("for_2", 2)

                if path and name:
                    logging.info("Processing: %s", name)
                    scrape_and_save_recipe(path, name, serv)
                    total_scraped += 1

                if total_scraped >= MAX_RECIPES:
                    logging.info("Reached limit of %s.", MAX_RECIPES)
                    return

            offset += GET_RECIPES_PAGE_LIMIT
            time.sleep(POLL_DELAY)

        except Exception:
            logging.exception(
                "Catalogue error while fetching page at offset %s", offset
            )
            break

    logging.info("--- Finished! Total recipes: %s ---", total_scraped)


def run_catalogue_import():
    # from app import create_app
    # app = create_app()
    # with app.app_context():
    scrape_all_recipes()


"""
if __name__ == "__main__":
    from app import create_app
    app = create_app()
    with app.app_context():
        scrape_all_recipes()
"""
