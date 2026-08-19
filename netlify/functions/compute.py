import json
import os
import sys

# Ensure Python can find our modular scripts in the same directory
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from spatial_bounds import calculate_search_bounds
# Note: Ensure your main processing pipeline function from your pipeline/math modules is imported here
# from viewshed_engine import run_viewshed

def handler(event, context):
    """
    Netlify Serverless Function handler for TerrainRF Analytics viewshed computation.
    """
    # Only allow POST requests from the frontend map
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

        # 2. Run viewshed processing (stub or integrate your pipeline execution here)
        # bounds_dict = {"south": bounds[0], "north": bounds[1], "west": bounds[2], "east": bounds[3]}

        # For now, return success with computed bounds so the frontend overlay positions correctly
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "success": True,
                "bounds": [
                    [bounds['south'], bounds['west']],
                    [bounds['north'], bounds['east']]
                ]
            })
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"success": False, "error": str(e)})
        }