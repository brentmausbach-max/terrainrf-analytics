import numpy as np

def compute_viewshed_matrix(elevation_grid, window_transform, observer_row, observer_col, observer_height_m=2.0, max_radius_pixels=150):
    """
    Step B3: Executes the ray-casting algorithm across a local elevation grid 
    to determine line-of-sight visibility for every pixel.
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
    
    # Cast rays in a circle around the observer
    num_rays = 360
    angles = np.linspace(0, 2 * np.pi, num_rays, endpoint=False)
    
    pixel_size_y = abs(window_transform[4])
    pixel_size_x = abs(window_transform[0])
    
    for angle in angles:
        cos_a = np.cos(angle)
        sin_a = np.sin(angle)
        max_elevation_angle = -999.0
        
        for r in range(1, max_radius_pixels):
            curr_row = int(round(observer_row + r * sin_a))
            curr_col = int(round(observer_col + r * cos_a))
            
            # Stop ray if it goes outside the grid window
            if not (0 <= curr_row < height and 0 <= curr_col < width):
                break
                
            curr_elev = float(elevation_grid[curr_row, curr_col])
            
            # Calculate physical distance from observer
            d_row_m = (curr_row - observer_row) * pixel_size_y * 111132.0
            d_col_m = (curr_col - observer_col) * pixel_size_x * 111132.0
            distance_m = np.sqrt(d_row_m**2 + d_col_m**2)
            
            if distance_m == 0:
                continue
                
            # Line-of-sight angle calculation
            curr_angle = (curr_elev - obs_alt) / distance_m
            
            if curr_angle >= max_elevation_angle:
                max_elevation_angle = curr_angle
                viewshed_mask[curr_row, curr_col] = 1
                
    return viewshed_mask