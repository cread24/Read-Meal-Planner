# app/models.py (THE CLEAN MODEL STRUCTURE)

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy import Column, Integer, String, Boolean, Float, Text, ForeignKey, Table
from . import db
import json
from datetime import datetime

# --- Association Table for LABELS ONLY ---
# This is a simple many-to-many, so we keep the db.Table definition.
# We keep extend_existing=True for robustness.
recipe_label = db.Table(
    'recipe_label', 
    db.metadata, 
    db.Column('recipe_id', db.Integer, db.ForeignKey('recipe.id'), primary_key=True),
    db.Column('label_id', db.Integer, db.ForeignKey('label.id'), primary_key=True),
    extend_existing=True 
)

# NOTE: The definition for recipe_ingredient = db.Table(...) has been REMOVED!


class Recipe(db.Model):
    __tablename__ = 'recipe'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), unique=True, nullable=False)
    category = db.Column(db.String(100)) 
    servings = db.Column(db.Integer)
    time_minutes = db.Column(db.Integer)
    instructions = db.Column(db.Text)
    nutritional_info = db.Column(db.Text)
    is_favourite = db.Column(db.Boolean, default=False)
    is_disliked = db.Column(db.Boolean, default=False)
    image_url = db.Column(db.String(500))
    source_url = db.Column(db.String(500))

    # 1. UPDATED: Relationship to RecipeIngredient Model (Association Object)
    # primaryjoin ensures we correctly map the RecipeIngredient model
    ingredients = relationship(
        'RecipeIngredient', 
        back_populates='recipe',
        #lazy='dynamic',
        cascade="all, delete-orphan" # Allows cascade deletion when clearing old links
    )
    
    # 2. Relationship to Label (via Association Table)
    labels = relationship(
        'Label', 
        secondary=recipe_label, 
        backref='recipes'
        #lazy='dynamic'
    )
    
    def __repr__(self):
        return f'<Recipe {self.name}>'

    @property
    def calories(self):
        """Extracts kcal from nutritional_info, handling strings or dicts."""
        if not self.nutritional_info:
            return None
            
        try:
            # Step 1: Handle if it's a string (JSON) or already a dictionary
            if isinstance(self.nutritional_info, str):
                data = json.loads(self.nutritional_info)
            else:
                data = self.nutritional_info
            
            # Step 2: Navigate the Gousto structure
            # Check per_portion -> energy_kcal
            portion = data.get('per_portion', {})
            kcal = portion.get('energy_kcal')
            
            # Step 3: Fallback check just in case keys vary
            if kcal is None:
                kcal = data.get('kcal') or portion.get('kcal')

            return int(kcal) if kcal is not None else None
            
        except Exception as e:
            # Print to console so you can see if there's a specific error
            print(f"Error parsing calories for recipe {self.id}: {e}")
            return None
        
class Ingredient(db.Model):
    __tablename__ = 'ingredient'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    is_basic = db.Column(db.Boolean, default=False) 

    # 3. UPDATED: Relationship to RecipeIngredient Model (Association Object)
    recipes = relationship(
        'RecipeIngredient', 
        back_populates='ingredient',
        lazy='dynamic',
        cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f'<Ingredient {self.name}>'


class Label(db.Model):
    __tablename__ = 'label'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), unique=True, nullable=False)
    
    def __repr__(self):
        return f'<Label {self.title}>'


class RecipeIngredient(db.Model):
    # 4. FINAL MODEL: This creates the 'recipe_ingredient' table
    __tablename__ = 'recipe_ingredient'
    
    recipe_id = db.Column(db.Integer, db.ForeignKey('recipe.id'), primary_key=True)
    ingredient_id = db.Column(db.Integer, db.ForeignKey('ingredient.id'), primary_key=True)
    quantity = db.Column(db.Float, nullable=False)
    unit = db.Column(db.String(50), nullable=False)

    # Relationships for back-populating
    recipe = relationship("Recipe", back_populates="ingredients")
    ingredient = relationship("Ingredient", back_populates="recipes")
    
    def __repr__(self):
        return f'<RecipeIngredient Recipe:{self.recipe_id} Ingredient:{self.ingredient_id}>'
    

class ConfirmedPlan(db.Model):
    __tablename__ = 'confirmed_plan'
    id = db.Column(db.Integer, primary_key=True)
    # Using datetime.utcnow for a consistent timestamp
    date_confirmed = db.Column(db.DateTime, default=datetime.utcnow)
    # We will store IDs like "12,45,67,89,102"
    recipe_ids = db.Column(db.String(500), nullable=False)