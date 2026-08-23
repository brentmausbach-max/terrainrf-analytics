import numpy as np

def compute_viewshed_matrix(elevation_grid, window_transform, observer_row, observer_col, observer_height_m=2.0, max_radius_pixels=None):
    """
    Step B3: Executes the ray-casting algorithm across a local elevation grid 
    incorporating Earth curvature, atmospheric refraction, and longitude scaling.
    """
    height, width = elevation_grid.shape
    
    # Ensure observer is within bounds
    if not (0 <= observer_row < height and 0 <= observer_col < width):
        raise ValueError("Observer point is outside the elevation grid window.")
        
    obs_elev = float(elevation_grid[observer_row, observer_col])
    obs_alt = obs_elev + observer_height_m
    
    # Initialize viewshed output mask (0 = not visible, 1 = visible)
    viewshed_mask = np.zeros_like(elevation_grid, dtype=np.uint8)
    viewshed_mask[observer_row, observer_col] = 1
    
    if max_radius_pixels is None:
        max_radius_pixels = int(np.hypot(height, width))
    
    # Scale ray count to perimeter circumference to eliminate long-range striping
    num_rays = max(360, int(2 * np.pi * max_radius_pixels))
    angles = np.linspace(0, 2 * np.pi, num_rays, endpoint=False)
    
    pixel_size_y = abs(window_transform[4])
    pixel_size_x = abs(window_transform[0])
    north_bound = window_transform[5]
    
    # Calculate exact observer latitude for precise longitudinal scaling
    obs_lat = north_bound - (observer_row * pixel_size_y)
    
    m_per_deg_lat = 111132.0
    m_per_deg_lon = 111132.0 * np.cos(np.radians(obs_lat))
    
    # Effective Earth radius with 4/3 atmospheric refraction
    earth_radius_eff = 6371000.0 * (4.0 / 3.0)
    
    for angle in angles:
        cos_a = np.cos(angle)
        sin_a = np.sin(angle)
        max_elevation_angle = -999.0
        
        for r in range(1, max_radius_pixels):
            curr_row = int(round(observer_row - r * sin_a))
            curr_col = int(round(observer_col + r * cos_a))
            
            # Stop ray if it goes outside the grid window
            if not (0 <= curr_row < height and 0 <= curr_col < width):
                break
                
            curr_elev = float(elevation_grid[curr_row, curr_col])
            
            # Calculate true physical distances in meters
            d_row_m = (curr_row - observer_row) * pixel_size_y * m_per_deg_lat
            d_col_m = (curr_col - observer_col) * pixel_size_x * m_per_deg_lon
            distance_m = np.sqrt(d_row_m**2 + d_col_m**2)
            
            if distance_m == 0:
                continue
                
            # Account for Earth curvature and refraction drop
            earth_drop = (distance_m ** 2) / (2.0 * earth_radius_eff)
            effective_curr_elev = curr_elev - earth_drop
            
            # True line-of-sight angle calculation
            curr_angle = (effective_curr_elev - obs_alt) / distance_m
            signal_clear = curr_angle >= max_elevation_angle
            
            if signal_clear:
                max_elevation_angle = curr_angle
                viewshed_mask[curr_row, curr_col] = 1
                
    return viewshed_mask