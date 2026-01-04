import logging

from app import create_app
from app.models import db
from app.services.catalogue_scraper import run_catalogue_import
from app.services.classifier import classify_all_recipes
from app.services.ingredient_classifier import classify_ingredients

app = create_app()

with app.app_context():
    logging.info("Clearing old data...")
    db.drop_all()
    db.create_all()

    logging.info("Running scraper...")
    run_catalogue_import()  # This now runs all 4 of your scraper functions

    logging.info("Classifying...")
    classify_ingredients()
    classify_all_recipes()

    logging.info("Done")
