# app/services/catalogue_scraper.py (REVISED)

import requests
import time
from app.services.scraper_service import scrape_and_save_recipe

# Use the full endpoint you provided initially, but without the category filter
GET_RECIPES_ENDPOINT = (
    "https://production-api.gousto.co.uk/cmsreadbroker/v1/recipes?category=recipes"
)
GET_RECIPES_PAGE_LIMIT = 16  # Max recipes per request
MAX_RECIPES = 1000  # Adjust this based on your desired dataset size
POLL_DELAY = 3  # Delay to be polite and avoid rate limiting

def scrape_all_recipes():
    """
    Iterates through the Gousto API catalogue using the confirmed OFFSET parameter
    for pagination.
    """
    total_recipes_scraped = 0
    offset = 0 # Start with the first recipe (offset 0)
    
    print("--- Starting Full Catalogue Scrape ---")
    
    while True:
        # Construct the URL using the OFFSET
        api_url = f"{GET_RECIPES_ENDPOINT}&limit={GET_RECIPES_PAGE_LIMIT}&offset={offset}"
        
        # Log the current status for debugging
        page_number = (offset // GET_RECIPES_PAGE_LIMIT) + 1
        print(f"Fetching Page {page_number} (Offset: {offset}) from {api_url}...")

        try:
            response = requests.get(api_url)
            response.raise_for_status()
            data = response.json()
            
            recipe_entries = data.get('data', {}).get('entries', [])

            if not recipe_entries:
                print("No more entries found. Stopping scrape.")
                break

            for entry in recipe_entries:
                recipe_path = entry.get('url') 
                recipe_name = entry.get('title')
                servings = entry.get('prep_times', {}).get('for_2', 2) 
                
                if recipe_path and recipe_name:
                    print(f"--> Scraping: {recipe_name}")
                    scrape_and_save_recipe(recipe_path, recipe_name, servings)
                    total_recipes_scraped += 1
                
                if total_recipes_scraped >= MAX_RECIPES:
                    print(f"Reached defined limit of {MAX_RECIPES} recipes.")
                    return

            # CRITICAL STEP: Increment the offset by the limit for the next page
            offset += GET_RECIPES_PAGE_LIMIT
            
            # Wait to respect the API rate limit
            time.sleep(POLL_DELAY) 

        except requests.RequestException as e:
            print(f"Error fetching catalogue (Offset {offset}): {e}. Check API status.")
            break
        except Exception as e:
            print(f"An unexpected error occurred during page processing: {e}")
            break
            
    print(f"--- Catalogue Scrape Finished. Total recipes scraped: {total_recipes_scraped} ---")


if __name__ == "__main__":
    from app import create_app
    app = create_app()
    with app.app_context():
        scrape_all_recipes()