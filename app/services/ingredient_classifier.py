import logging

from app.models import Ingredient, db

# Expanded Gousto-specific mapping
SMART_MAP = {
    "Meat": [
        "chicken",
        "beef",
        "pork",
        "lamb",
        "steak",
        "bacon",
        "sausage",
        "mince",
        "chorizo",
        "duck",
        "turkey",
        "gammon",
        "venison",
        "meatball",
        "salami",
        "prosciutto",
        "pancetta",
        "ham",
        "porker",
    ],
    "Fish": [
        "salmon",
        "cod",
        "prawn",
        "shrimp",
        "haddock",
        "tuna",
        "trout",
        "bass",
        "mackerel",
        "hake",
        "fish",
        "smoked fish",
    ],
    "Veg": [
        "potato",
        "onion",
        "garlic",
        "carrot",
        "pepper",
        "chilli",
        "tomato",
        "spinach",
        "aubergine",
        "mushroom",
        "parsnip",
        "shallot",
        "leek",
        "cabbage",
        "herb",
        "broccoli",
        "ginger",
        "coriander",
        "bean",
        "pea",
        "kale",
        "squash",
        "courgette",
        "cucumber",
        "lettuce",
        "rocket",
        "sweetcorn",
        "beetroot",
        "radish",
        "celery",
    ],
    "Dairy": [
        "milk",
        "cheese",
        "butter",
        "cream",
        "yogurt",
        "egg",
        "parmesan",
        "cheddar",
        "mozzarella",
        "paneer",
        "feta",
        "haloumi",
        "crème fraîche",
        "mascarpone",
    ],
    "Pantry": [
        "rice",
        "pasta",
        "flour",
        "sugar",
        "oil",
        "vinegar",
        "stock",
        "spice",
        "powder",
        "paste",
        "sauce",
        "honey",
        "syrup",
        "lentil",
        "seed",
        "chutney",
        "pastry",
        "nut",
        "olive",
        "tamarind",
        "curry",
        "ketchup",
        "mayo",
        "mustard",
        "soy",
        "oat",
        "quinoa",
        "couscous",
        "noodles",
        "broth",
    ],
    "Bread": [
        "bread",
        "roll",
        "wrap",
        "tortilla",
        "naan",
        "pitta",
        "baguette",
        "bun",
        "ciabatta",
    ],
}


def classify_ingredients():
    """
    Categorises ingredients based on keywords.
    It checks for existing manual categories first to avoid overwriting user edits.
    """
    ingredients = Ingredient.query.all()
    updated_count = 0

    for ing in ingredients:
        name_low = ing.name.lower()
        new_category = "Other"

        # 1. Primary Keyword Search
        found = False
        for category, keywords in SMART_MAP.items():
            if any(k in name_low for k in keywords):
                new_category = category
                found = True
                break

        # 2. Heuristic Fallbacks (The "Smart" part)
        if not found:
            if any(x in name_low for x in ["mix", "blend", "dried", "jar"]):
                new_category = "Pantry"
            elif any(x in name_low for x in ["clove", "root", "leaf", "stalk"]):
                new_category = "Veg"
            elif "stock" in name_low:
                new_category = "Pantry"

        # 3. Apply only if the category has changed or was 'Other'
        if ing.category != new_category:
            ing.category = new_category
            updated_count += 1

    db.session.commit()
    logging.info("%s ingredients re-classified", updated_count)
