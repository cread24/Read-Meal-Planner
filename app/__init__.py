# app/__init__.py

import os
import re
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
from markupsafe import Markup

# Initialize the database object
# We do this here so it can be imported by models.py
db = SQLAlchemy()

def create_app():
    # Load environment variables from .env file
    load_dotenv()

    app = Flask(__name__)

    # --- Configuration ---
    # Get SECRET_KEY from .env, with a fallback for local safety
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-fallback-key-12345')
    
    # Database Configuration
    # It will look for DATABASE_URL in .env, otherwise defaults to your app.db
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///app.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Initialize the app with the database
    db.init_app(app)

    # --- Custom Jinja Filters ---
    @app.template_filter('format_substeps')
    def format_substeps(text):
        if not text:
            return ""
        
        # Define the pattern to find the start of a new sub-step
        pattern = r'(?<=[a-z0-9\]\)])\s*(?=[A-Z])'
        
        # Split the text into a list of sub-steps based on the capital letters
        substeps = re.split(pattern, text)
        
        # Wrap each sub-step in a div with a custom class
        # The '•' adds a nice visual bullet point
        html_output = "".join([f'<div class="recipe-substep"> {s.strip()}</div>' for s in substeps if s.strip()])
        
        return Markup(html_output)

    # --- Blueprint Registration ---
    # We import these inside the function to prevent "circular imports"
    from .routes import main_bp
    app.register_blueprint(main_bp)

    # Create database tables if they don't exist
    with app.app_context():
        # This ensures all models (Recipe, Ingredient, etc.) are known to SQLAlchemy
        from . import models 
        db.create_all()

    return app