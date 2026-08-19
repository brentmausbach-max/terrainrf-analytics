import json
import os
import sys
import numpy as np
from PIL import Image

# Ensure Python can find our modular scripts in the same directory
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from spatial_bounds import calculate_search_bounds

def handler(event, context):
    """
    Netlify Serverless Function handler for TerrainRF Analytics viewshed computation.
    """
    if event.get("httpMethod") != "POST":
        return {
            "statusCode": 405,
            "body": json.dumps({"success": False, "error": "Method Not Allowed"})
        }

    try:
        # Parse incoming JSON payload from frontend map click
        body = json.loads(event.get("body", "{}"))
        lat = float(body.get("lat"))
        lon = float(body.get("lon"))
        height = float(body.get("height", 2.0))

        # 1. Calculate spatial bounds based on click
        bounds = calculate_search_bounds(lat, lon)
        south, north, west, east = bounds[0], bounds[1], bounds[2], bounds[3]

        # 2. Generate a local viewshed grid (simulated raster matrix for rapid prototyping)
        grid_size = 200
        y = np.linspace(north, south, grid_size)
        x = np.linspace(west, east, grid_size)
        xx, yy = np.meshgrid(x, y)

        # Create a realistic radial/line-of-sight pattern from the center observer point
        dist = np.sqrt((xx - lon)**2 + (yy - lat)**2)
        # Simulate some terrain/obstacle blocking based on distance and angle
        mask = (dist < 0.15) & ((np.sin(xx * 50) + np.cos(yy * 50)) > -0.3)

        # 3. Create an RGBA image for the overlay
        img_array = np.zeros((grid_size, grid_size, 4), dtype=np.uint8)
        # Color visible areas green with transparency (R, G, B, Alpha)
        img_array[mask] = [34, 139, 34, 140]

        # Ensure static directory exists
        os.makedirs("static", exist_ok=True)
        overlay_path = os.path.join("static", "overlay.png")
        
        # Save image using PIL
        img = Image.fromarray(img_array, "RGBA")
        img.save(overlay_path)

        # 4. Return success with computed bounds and image reference
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "success": True,
                "bounds": [
                    [south, west],
                    [north, east]
                ]
            })
        }
    except Exception as e:
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"success": False, "error": str(e)})
        }