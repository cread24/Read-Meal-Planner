from app import create_app
from app.models import db
from app.services.classifier import classify_all_recipes
from app.services.ingredient_classifier import classify_ingredients
from app.services.catalogue_scraper import run_catalogue_import

app = create_app()

with app.app_context():
    print("🗑️ Clearing old data...")
    db.drop_all()
    db.create_all()
    
    print("🕷️ Running Scraper...")
    run_catalogue_import()  # This now runs all 4 of your scraper functions

    print("🏷️ Classifying...")
    classify_ingredients()
    classify_all_recipes()
    
    print("✅ Done!")