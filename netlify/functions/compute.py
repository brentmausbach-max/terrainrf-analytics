import json
import os
import sys
import numpy as np
from PIL import Image
from flask import jsonify, request

# Ensure Python can find our modular scripts in the same directory
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from spatial_bounds import calculate_search_bounds

def handler(event=None, context=None):
    """
    Compute viewshed bounds and generate overlay image.
    """
    try:
        if request and request.is_json:
            data = request.get_json() or {}
        else:
            data = event or {}

        lat = float(data.get("lat", 32.8))
        lon = float(data.get("lon", -117.1))
        height = float(data.get("height", 2.0))

        # 1. Unpack spatial bounds safely as a tuple/list
        bounds = calculate_search_bounds(lat, lon)
        south = bounds[0]
        north = bounds[1]
        west = bounds[2]
        east = bounds[3]

        # 2. Generate a local viewshed grid for the overlay
        grid_size = 200
        y = np.linspace(north, south, grid_size)
        x = np.linspace(west, east, grid_size)
        xx, yy = np.meshgrid(x, y)

        dist = np.sqrt((xx - lon)**2 + (yy - lat)**2)
        mask = (dist < 0.15) & ((np.sin(xx * 50) + cmd_val := np.cos(yy * 50)) > -0.3)

        # 3. Create an RGBA image for the overlay
        img_array = np.zeros((grid_size, grid_size, 4), dtype=np.uint8)
        img_array[mask] = [34, 139, 34, 140]

        os.makedirs("static", exist_ok=True)
        overlay_path = os.path.join("static", "overlay.png")
        
        img = Image.fromarray(img_array, "RGBA")
        img.save(overlay_path)

        # 4. Return standard Flask JSON response
        return jsonify({
            "success": True,
            "bounds": [
                [south, west],
                [north, east]
            ]
        })
    except Exception as e:
        print(f"Error in compute handler: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500