@app.route("/compute-p2p", methods=["POST"])
def compute_p2p_endpoint():
    print("--- /compute-p2p endpoint hit! ---")
    try:
        req_data = request.get_json() or {}
        lat1 = float(req_data.get("lat1"))
        lon1 = float(req_data.get("lon1"))
        h1 = float(req_data.get("h1", 2.0))
        
        lat2 = float(req_data.get("lat2"))
        lon2 = float(req_data.get("lon2"))
        h2 = float(req_data.get("h2", 2.0))

        padding = 0.1
        south = min(lat1, lat2) - padding
        north = max(lat1, lat2) + padding
        west = min(lon1, lon2) - padding
        east = max(lon1, lon2) + padding

        grid_size = 300
        api_key = "d58e9f652fa6e05bef48afa87c718844"
        api_url = (
            f"https://portal.opentopography.org/API/globaldem?"
            f"demtype=SRTMGL1&south={south}&north={north}&west={west}&east={east}"
            f"&outputFormat=AAIGrid&API_Key={api_key}"
        )

        req = urllib.request.Request(api_url, headers={'User-Agent': 'TerrainRF-Analytics/1.0'})
        with urllib.request.urlopen(req, timeout=25) as response:
            content = response.read().decode('utf-8')
            lines = content.splitlines()
            data_rows = []
            header_parsed = False
            ncols, nrows = grid_size, grid_size
            
            for line in lines:
                parts = line.strip().split()
                if not parts:
                    continue
                if not header_parsed:
                    if parts[0].lower() == 'ncols': ncols = int(parts[1])
                    elif parts[0].lower() == 'nrows': nrows = int(parts[1])
                    elif parts[0].lower() in ['xllcorner', 'yllcorner', 'xllcenter', 'yllcenter', 'cellsize', 'nodata_value']: pass
                    else:
                        header_parsed = True
                        data_rows.append([float(p) for p in parts])
                else:
                    data_rows.append([float(p) for p in parts])

            flat_data = [val for row in data_rows for val in row]
            elevation_grid = np.array(flat_data[:ncols * nrows], dtype=np.float32).reshape((nrows, ncols))
            elevation_grid[elevation_grid < -1000] = 0

        r1 = int((north - lat1) / (north - south) * nrows)
        c1 = int((lon1 - west) / (east - west) * ncols)
        r2 = int((north - lat2) / (north - south) * nrows)
        c2 = int((lon2 - west) / (east - west) * ncols)

        num_samples = max(abs(r2 - r1), abs(c2 - c1), 100)
        rr = np.linspace(r1, r2, num_samples).astype(int)
        cc = np.linspace(c1, c2, num_samples).astype(int)

        elev_a = elevation_grid[r1, c1] + h1
        elev_b = elevation_grid[r2, c2] + h2

        clear_path = True
        max_obstruction_margin = 0.0

        distances = []
        ground_elevs = []
        los_elevs = []

        # Approximate total distance in miles using simple haversine or coordinate step approximation
        # Each sample step fractional distance calculation
        total_deg_dist = np.sqrt((lat2 - lat1)**2 + (lon2 - lon1)**2)
        total_miles = total_deg_dist * 69.0 # rough conversion factor

        for i in range(num_samples):
            r, c = rr[i], cc[i]
            fraction = i / num_samples
            line_of_sight_elev = elev_a + fraction * (elev_b - elev_a)
            ground_elev = elevation_grid[r, c]
            
            distances.append(round(fraction * total_miles, 2))
            ground_elevs.append(round(float(ground_elev), 1))
            los_elevs.append(round(float(line_of_sight_elev), 1))

            if ground_elev > line_of_sight_elev:
                clear_path = False
                margin = ground_elev - line_of_sight_elev
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
                "los": los_elevs
            }
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500