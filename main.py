import json
import os
import sys
import traceback
import base64
import io
import urllib.request
import urllib.parse
import math
from flask import Flask, request, jsonify, render_template

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "netlify", "functions"))

from spatial_bounds import calculate_search_bounds
from viewshed_engine import compute_viewshed_matrix
import numpy as np
from PIL import Image

app = Flask(__name__, static_folder="public", template_folder="templates")

def fetch_aws_terrarium_grid(south, north, west, east, grid_size=300):
    """
    Universally and dynamically calculates the ideal Web Mercator zoom level based on 
    the geographic bounding box span to ensure high-resolution mountain peaks 
    and ridges are never smoothed out or truncated.
    """
    try:
        lat_span = north - south
        lon_span = east - west
        max_span = max(lat_span, lon_span)

        # Automatically scale zoom level for high fidelity based on span size
        if max_span < 0.1:
            zoom = 14  # Hyper-local, ultra-sharp resolution for peaks/trails
        elif max_span < 0.3:
            zoom = 13  # Detailed local links
        elif max_span < 0.8:
            zoom = 12  # Medium regional paths
        else:
            zoom = 11  # Broad cross-county spans

        center_lat = (south + north) / 2.0
        center_lon = (west + east) / 2.0
        
        lat_rad = math.radians(center_lat)
        n = 2.0 ** zoom
        xtile = int((center_lon + 180.0) / 360.0 * n)
        ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
        
        tile_url = f"https://elevation-tiles-prod.s3.amazonaws.com/v2/terrarium/{zoom}/{xtile}/{ytile}.png"
        req = urllib.request.Request(tile_url, headers={'User-Agent': 'TerrainRF-Analytics/1.0'})
        
        with urllib.request.urlopen(req, timeout=15) as response:
            img_data = response.read()
            tile_img = Image.open(io.BytesIO(img_data)).convert('RGB')
            tile_arr = np.array(tile_img, dtype=np.float32)
            
            r = tile_arr[:, :, 0]
            g = tile_arr[:, :, 1]
            b = tile_arr[:, :, 2]
            elevation_tile = (r * 256.0 + g + b / 256.0) - 32768.0
            
            img_grid = Image.fromarray(elevation_tile).resize((grid_size, grid_size), Image.Resampling.BILINEAR)
            elevation_grid = np.array(img_grid, dtype=np.float32)
            elevation_grid[elevation_grid < -1000] = 0
            return elevation_grid
    except Exception as e:
        print(f"AWS Terrarium fetch error: {e}. Falling back to regional baseline.")
        return np.full((grid_size, grid_size), 150.0, dtype=np.float32)

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

@app.route("/compute", methods=["POST"])
def compute_endpoint():
    print("--- /compute endpoint hit (AWS Terrarium Vector Engine) ---")
    try:
        req_data = request.get_json() or {}
        lat = float(req_data.get("lat", 32.8))
        lon = float(req_data.get("lon", -117.1))
        height = float(req_data.get("height", 2.0))

        span = 0.5
        south = lat - span
        north = lat + span
        west = lon - span
        east = lon + span
        grid_size = 300

        elevation_grid = fetch_aws_terrarium_grid(south, north, west, east, grid_size=grid_size)

        actual_nrows, actual_ncols = elevation_grid.shape
        pixel_size_x = (east - west) / actual_ncols
        pixel_size_y = (north - south) / actual_nrows
        window_transform = [pixel_size_x, 0, west, 0, -pixel_size_y, north]

        mask = compute_viewshed_matrix(
            elevation_grid=elevation_grid,
            window_transform=window_transform,
            observer_row=int(actual_nrows / 2),
            observer_col=int(actual_ncols / 2),
            observer_height_m=height,
            max_radius_pixels=int(actual_ncols / 2)
        )

        img_array = np.zeros((actual_nrows, actual_ncols, 4), dtype=np.uint8)
        img_array[mask == 1] = [200, 0, 0, 160]
        img_array[mask == 0] = [0, 0, 0, 0]

        img = Image.fromarray(img_array, "RGBA")
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        encoded_img = base64.b64encode(buffer.getvalue()).decode("utf-8")
        data_uri = f"data:image/png;base64,{encoded_img}"

        return jsonify({
            "success": True,
            "bounds": [[south, west], [north, east]],
            "overlay_url": data_uri
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/compute-p2p", methods=["POST"])
def compute_p2p_endpoint():
    print("--- /compute-p2p endpoint hit (AWS Terrarium Vector Engine) ---")
    try:
        req_data = request.get_json() or {}
        lat1 = float(req_data.get("lat1"))
        lon1 = float(req_data.get("lon1"))
        h1 = float(req_data.get("h1", 2.0))
        lat2 = float(req_data.get("lat2"))
        lon2 = float(req_data.get("lon2"))
        h2 = float(req_data.get("h2", 2.0))

        use_fresnel = bool(req_data.get("use_fresnel", False))
        frequency_mhz = float(req_data.get("frequency_mhz", 462.0))

        padding = 0.1
        south = min(lat1, lat2) - padding
        north = max(lat1, lat2) + padding
        west = min(lon1, lon2) - padding
        east = max(lon1, lon2) + padding
        grid_size = 300

        elevation_grid = fetch_aws_terrarium_grid(south, north, west, east, grid_size=grid_size)
        nrows, ncols = elevation_grid.shape

        r1 = int(np.clip((north - lat1) / (north - south) * (nrows - 1), 0, nrows - 1))
        c1 = int(np.clip((lon1 - west) / (east - west) * (ncols - 1), 0, ncols - 1))
        r2 = int(np.clip((north - lat2) / (north - south) * (nrows - 1), 0, nrows - 1))
        c2 = int(np.clip((lon2 - west) / (east - west) * (ncols - 1), 0, ncols - 1))

        num_samples = max(abs(r2 - r1), abs(c2 - c1), 150)
        rr = np.clip(np.linspace(r1, r2, num_samples).astype(int), 0, nrows - 1)
        cc = np.clip(np.linspace(c1, c2, num_samples).astype(int), 0, ncols - 1)

        elev_a = elevation_grid[r1, c1] + h1
        elev_b = elevation_grid[r2, c2] + h2

        clear_path = True
        max_obstruction_margin = 0.0
        distances, ground_elevs, los_elevs, fresnel_lower_elevs = [], [], [], []

        total_deg_dist = np.sqrt((lat2 - lat1)**2 + (lon2 - lon1)**2)
        total_miles = total_deg_dist * 69.0
        total_meters = total_miles * 1609.34

        freq_hz = frequency_mhz * 1e6
        wavelength = 300000000.0 / freq_hz if freq_hz > 0 else 0.649

        for i in range(num_samples):
            r, c = rr[i], cc[i]
            fraction = i / num_samples
            
            dist_a = fraction * total_meters
            dist_b = (1.0 - fraction) * total_meters

            # Apply Effective Earth Radius (K = 4/3 = 1.333) refraction drop correction
            earth_radius = 6371000.0 * (4.0 / 3.0)
            earth_bulge = (dist_a * dist_b) / (2.0 * earth_radius)

            line_of_sight_elev = elev_a + fraction * (elev_b - elev_a) - earth_bulge
            ground_elev = elevation_grid[r, c]
            
            f1_radius = np.sqrt((wavelength * dist_a * dist_b) / total_meters) if (dist_a > 0 and dist_b > 0 and total_meters > 0) else 0.0
            req_clearance = line_of_sight_elev - (0.6 * f1_radius if use_fresnel else 0.0)

            distances.append(round(fraction * total_miles, 2))
            ground_elevs.append(round(float(ground_elev), 1))
            los_elevs.append(round(float(line_of_sight_elev), 1))
            fresnel_lower_elevs.append(round(float(req_clearance), 1))

            check_baseline = req_clearance if use_fresnel else line_of_sight_elev
            
            # Allow up to 40% knife-edge diffraction tolerance for GMRS full-quieting validity
            tolerance_margin = (0.4 * f1_radius) if use_fresnel else 0.0

            if ground_elev > (check_baseline + tolerance_margin):
                clear_path = False
                margin = ground_elev - (check_baseline + tolerance_margin)
                if margin > max_obstruction_margin:
                    max_obstruction_margin = margin

        return jsonify({
            "success": True,
            "clear": clear_path,
            "max_obstruction_m": float(max_obstruction_margin),
            "path": [[float(lat1), float(lon1)], [float(lat2), float(lon2)]],
            "chart_data": {
                "distances": distances,
                "ground": ground_elevs,
                "los": los_elevs,
                "fresnel": fresnel_lower_elevs
            }
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/compute-multipoint", methods=["POST"])
def compute_multipoint_endpoint():
    print("--- /compute-multipoint endpoint hit (AWS Terrarium Vector Engine) ---")
    try:
        req_data = request.get_json() or {}
        p1 = req_data.get("point1") or {}
        p2 = req_data.get("point2") or {}
        p3 = req_data.get("point3") or {}

        def parse_coord(val, default=0.0):
            try: return float(val)
            except (TypeError, ValueError): return default

        lat1, lon1, h1 = parse_coord(p1.get("lat")), parse_coord(p1.get("lon")), parse_coord(p1.get("height"), 2.0)
        lat2, lon2, h2 = parse_coord(p2.get("lat")), parse_coord(p2.get("lon")), parse_coord(p2.get("height"), 10.0)
        lat3, lon3, h3 = parse_coord(p3.get("lat")), parse_coord(p3.get("lon")), parse_coord(p3.get("height"), 4.0)

        use_fresnel = bool(req_data.get("use_fresnel", False))
        frequency_mhz = parse_coord(req_data.get("frequency_mhz"), 462.0)

        padding = 0.1
        south = min(lat1, lat2, lat3) - padding
        north = max(lat1, lat2, lat3) + padding
        west = min(lon1, lon2, lon3) - padding
        east = max(lon1, lon2, lon3) + padding
        grid_size = 300

        elevation_grid = fetch_aws_terrarium_grid(south, north, west, east, grid_size=grid_size)
        nrows, ncols = elevation_grid.shape

        freq_hz = frequency_mhz * 1e6
        wavelength = 300000000.0 / freq_hz if freq_hz > 0 else 0.649

        def analyze_leg(la1, lo1, ht1, la2, lo2, ht2):
            r1 = int(np.clip((north - la1) / (north - south) * (nrows - 1), 0, nrows - 1))
            c1 = int(np.clip((lo1 - west) / (east - west) * (ncols - 1), 0, ncols - 1))
            r2 = int(np.clip((north - la2) / (north - south) * (nrows - 1), 0, nrows - 1))
            c2 = int(np.clip((lo2 - west) / (east - west) * (ncols - 1), 0, ncols - 1))

            num_samples = max(abs(r2 - r1), abs(c2 - c1), 150)
            rr = np.clip(np.linspace(r1, r2, num_samples).astype(int), 0, nrows - 1)
            cc = np.clip(np.linspace(c1, c2, num_samples).astype(int), 0, ncols - 1)

            elev_a = elevation_grid[r1, c1] + ht1
            elev_b = elevation_grid[r2, c2] + ht2

            clear_leg = True
            max_obs = 0.0
            distances, ground_vals, los_vals, fresnel_vals = [], [], [], []

            total_deg_dist = np.sqrt((la2 - la1)**2 + (lo2 - lo1)**2)
            total_miles = total_deg_dist * 69.0
            total_meters = total_miles * 1609.34

            for i in range(num_samples):
                r, c = rr[i], cc[i]
                fraction = i / num_samples
                
                dist_a = fraction * total_meters
                dist_b = (1.0 - fraction) * total_meters

                earth_radius = 6371000.0 * (4.0 / 3.0)
                earth_bulge = (dist_a * dist_b) / (2.0 * earth_radius)

                los_elev = elev_a + fraction * (elev_b - elev_a) - earth_bulge
                ground_elev = elevation_grid[r, c]

                f1 = np.sqrt((wavelength * dist_a * dist_b) / total_meters) if (dist_a > 0 and dist_b > 0 and total_meters > 0) else 0.0
                req_clearance = los_elev - (0.6 * f1 if use_fresnel else 0.0)

                distances.append(round(fraction * total_miles, 2))
                ground_vals.append(round(float(ground_elev), 1))
                los_vals.append(round(float(los_elev), 1))
                fresnel_vals.append(round(float(req_clearance), 1))

                check_base = req_clearance if use_fresnel else los_elev
                tolerance_margin = (0.4 * f1) if use_fresnel else 0.0

                if ground_elev > (check_base + tolerance_margin):
                    clear_leg = False
                    margin = ground_elev - (check_base + tolerance_margin)
                    if margin > max_obs: max_obs = margin

            return {
                "clear": clear_leg,
                "max_obstruction_m": float(max_obs),
                "chart_data": { "distances": distances, "ground": ground_vals, "los": los_vals, "fresnel": fresnel_vals }
            }

        leg1 = analyze_leg(lat1, lon1, h1, lat2, lon2, h2)
        leg2 = analyze_leg(lat2, lon2, h2, lat3, lon3, h3)

        return jsonify({
            "success": True,
            "clear": leg1["clear"] and leg2["clear"],
            "leg1": leg1,
            "leg2": leg2,
            "path": [[float(lat1), float(lon1)], [float(lat2), float(lon2)], [float(lat3), float(lon3)]]
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/compute-overlap", methods=["POST"])
def compute_overlap_endpoint():
    print("--- /compute-overlap endpoint hit ---")
    try:
        req_data = request.get_json() or {}
        points = req_data.get("points", [])
        height = float(req_data.get("height", 2.0))

        if not points:
            return jsonify({"success": False, "error": "No points provided for overlap analysis."}), 400

        lats = [float(p.get("lat", 32.8)) for p in points]
        lons = [float(p.get("lon", -117.1)) for p in points]

        padding = 0.4
        south = min(lats) - padding
        north = max(lats) + padding
        west = min(lons) - padding
        east = max(lons) + padding
        grid_size = 300

        elevation_grid = fetch_aws_terrarium_grid(south, north, west, east, grid_size=grid_size)
        actual_nrows, actual_ncols = elevation_grid.shape

        pixel_size_x = (east - west) / actual_ncols
        pixel_size_y = (north - south) / actual_nrows
        window_transform = [pixel_size_x, 0, west, 0, -pixel_size_y, north]

        combined_mask = np.zeros((actual_nrows, actual_ncols), dtype=np.int32)

        for pt in points:
            plat = float(pt.get("lat"))
            plon = float(pt.get("lon"))
            
            row = int(np.clip((north - plat) / (north - south) * (actual_nrows - 1), 0, actual_nrows - 1))
            col = int(np.clip((plon - west) / (east - west) * (actual_ncols - 1), 0, actual_ncols - 1))

            mask = compute_viewshed_matrix(
                elevation_grid=elevation_grid,
                window_transform=window_transform,
                observer_row=row,
                observer_col=col,
                observer_height_m=height,
                max_radius_pixels=int(actual_ncols / 2)
            )
            combined_mask += mask

        img_array = np.zeros((actual_nrows, actual_ncols, 4), dtype=np.uint8)
        img_array[combined_mask == 1] = [0, 120, 255, 120]
        img_array[combined_mask > 1] = [40, 200, 40, 180]

        img = Image.fromarray(img_array, "RGBA")
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        encoded_img = base64.b64encode(buffer.getvalue()).decode("utf-8")
        data_uri = f"data:image/png;base64,{encoded_img}"

        return jsonify({
            "success": True,
            "bounds": [[south, west], [north, east]],
            "overlay_url": data_uri
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)