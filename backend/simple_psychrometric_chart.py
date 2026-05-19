"""
Simple Psychrometric Chart using psychrolib
Clean and straightforward implementation
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch
import psychrolib as psy
from typing import Dict, List, Tuple, Optional

# Set psychrolib to use IP units
psy.SetUnitSystem(psy.IP)

def normalize_weather_columns(df):
    """Normalize column names to standard format"""
    column_map = {
        'Tdb': 'Tdb_F',
        'Tdp': 'Tdp_F',
        'Twb': 'Twb_F',
        'RH': 'RH_percent',
    }
    return df.rename(columns=column_map)

def calculate_point_data(tdb, twb, pressure_psia):
    """Calculate humidity ratio"""
    w = psy.GetHumRatioFromTWetBulb(tdb, twb, pressure_psia)
    tdp = psy.GetTDewPointFromHumRatio(tdb, w, pressure_psia)
    return (tdb, twb, w, tdp)


def find_saturation_segment(tdb_start, tdb_end, tdb_sat, w_sat):
    """Find points on saturation line between tdb_start and tdb_end"""
    sat_segment_tdb = []
    sat_segment_w = []
    for i, (t_sat, w_sat_val) in enumerate(zip(tdb_sat, w_sat)):
        if not np.isnan(w_sat_val):
            if tdb_start < tdb_end:
                if tdb_start <= t_sat <= tdb_end:
                    sat_segment_tdb.append(t_sat)
                    sat_segment_w.append(w_sat_val)
            else:
                if tdb_end <= t_sat <= tdb_start:
                    sat_segment_tdb.append(t_sat)
                    sat_segment_w.append(w_sat_val)
    return sat_segment_tdb, sat_segment_w

def draw_arrow_segments(ax, points_tdb, points_w, color, linewidth=10, linestyle='--', alpha=0.8):
    """Draw arrow segment connecting points"""
    if len(points_tdb) < 2:
        return
    
    for i in range(len(points_tdb) - 1):
        ax.annotate('', xy=(points_tdb[i+1], points_w[i+1]),
                   xytext=(points_tdb[i], points_w[i]),
                   arrowprops=dict(arrowstyle='->', color=color, lw=linewidth, linestyle=linestyle, alpha=alpha))

def create_simple_psychrometric_chart(
    weather_data,
    elevation_ft: float = 0,
    location_name: str = "Location",
    output_file: str = None,
    unit_system: str = "IP",
    tdb_min: float = None,  # None → 0°C / 10°F standard frame
    tdb_max: float = None,  # None → 50°C / 120°F standard frame
    w_min: float = None,    # None → auto from data
    w_max: float = None,    # None → auto from data
    show_dew_point: bool = False,
    T1_SEA_Tdb: float = None,
    T1_SEA_Twb: float = None,
    T1_SEA_description: str = None,
    T1_Customer_Tdb: float = None,
    T1_Customer_Twb: float = None,
    T1_Customer_description: str = None,
    T2_SEA_Tdb: float = None,
    T2_Customer_Tdb: float = None,
    show_SEA_Cooling_path: bool = False,
    show_Customer_Cooling_path: bool = False,
    bin_size_db: float = 0.9,  # Default: 3.6°F (IP) or 2.0°C (SI)
    bin_size_wb: float = 0.9,  # Default: 3.6°F (IP) or 2.0°C (SI)
    # show_wet_bulb: bool = False,
    # show_enthalpy: bool = False,
    # show_rh: bool = False,
) -> str:
    """
    Create a simple psychrometric chart with weather data
    
    Args:
        weather_data: DataFrame or file path string with weather data
        elevation_ft: Elevation in feet (IP) or meters (SI)
        location_name: Name for the chart title
        output_file: Output file path (optional)
        unit_system: "IP" for Imperial units or "SI" for metric units
    
    Returns:
        Path to saved chart
    """
    
    # Set psychrolib unit system and create helper variables
    is_si = unit_system.upper() == "SI"
    temp_unit = '°C' if is_si else '°F'
    
    if is_si:
        psy.SetUnitSystem(psy.SI)
        elevation_m = elevation_ft  # elevation_ft is actually meters in SI mode
        elevation_ft = elevation_m * 3.28084  # Convert to feet for display
    else:
        psy.SetUnitSystem(psy.IP)
        elevation_m = elevation_ft * 0.3048  # Convert feet to meters
    
    # Handle file path input or Streamlit uploaded file
    if isinstance(weather_data, str):
        weather_data = load_weather_file(weather_data)
    elif hasattr(weather_data, 'read'):  # Streamlit uploaded file
        import io
        weather_data = pd.read_csv(io.StringIO(weather_data.read().decode('utf-8')))
        weather_data = normalize_weather_columns(weather_data)
    
    # Calculate pressure from elevation
    if is_si:
        # SI units: pressure in Pa, elevation in meters
        pressure_Pa = 101325 * (1 - 0.0000065 * elevation_m) ** 5.2559
        pressure_psia_display = pressure_Pa * 0.000145038  # for display only
        pressure_inHg = pressure_psia_display / 0.491154
    else:
        # IP units: pressure in inHg, elevation in feet
        pressure_inHg = 29.92 * (1 - 0.0000068753 * elevation_ft) ** 5.2559
        pressure_Pa = pressure_inHg * 0.491154 / 0.000145038
        pressure_psia_display = pressure_inHg * 0.491154

    # psychrolib expects Pa in SI mode, psia in IP mode
    pressure_psia = pressure_Pa if is_si else pressure_psia_display
    
    # Create figure with ASHRAE-style appearance
    fig, ax = plt.subplots(figsize=(21, 14))
    fig.patch.set_facecolor('white')
    
    # Fixed standard frame — consistent across sessions and sites
    if tdb_min is None:
        tdb_min = 0 if is_si else 10
    if tdb_max is None:
        tdb_max = 50 if is_si else 120
    
    # Calculate humidity ratio from weather data and store in DataFrame
    w_data = []
    for _, row in weather_data.iterrows():
        try:
            if is_si:
                # Convert temperatures to SI if needed
                if 'Tdb_F' in weather_data.columns:
                    tdb = (row['Tdb_F'] - 32) * 5/9
                    twb = (row['Twb_F'] - 32) * 5/9
                else:
                    tdb = row['Tdb_C']
                    twb = row['Twb_C']
                
                if 'Twb_F' in weather_data.columns or 'Twb_C' in weather_data.columns:
                    w = psy.GetHumRatioFromTWetBulb(tdb, twb, pressure_psia)
                elif 'RH_percent' in weather_data.columns:
                    w = psy.GetHumRatioFromRelHum(tdb, row['RH_percent']/100, pressure_psia)
                else:
                    w_data.append(np.nan)
                    continue
            else:
                # IP units
                if 'Twb_F' in weather_data.columns:
                    w = psy.GetHumRatioFromTWetBulb(row['Tdb_F'], row['Twb_F'], pressure_psia)
                elif 'RH_percent' in weather_data.columns:
                    w = psy.GetHumRatioFromRelHum(row['Tdb_F'], row['RH_percent']/100, pressure_psia)
                else:
                    w_data.append(np.nan)
                    continue
            w_data.append(w)
        except:
            w_data.append(np.nan)
    
    # Store humidity ratio in DataFrame
    weather_data = weather_data.copy()
    weather_data['humidity_ratio'] = w_data

    # Tdb/Twb in the correct axis unit (°C in SI, °F in IP)
    if is_si and 'Tdb_F' in weather_data.columns:
        weather_data['Tdb_plot'] = (weather_data['Tdb_F'] - 32) * 5 / 9
        weather_data['Twb_plot'] = (weather_data['Twb_F'] - 32) * 5 / 9
    elif is_si and 'Tdb_C' in weather_data.columns:
        weather_data['Tdb_plot'] = weather_data['Tdb_C']
        weather_data['Twb_plot'] = weather_data['Twb_C']
    else:
        weather_data['Tdb_plot'] = weather_data['Tdb_F']
        weather_data['Twb_plot'] = weather_data['Twb_F']
    
    # Humidity ratio range — always auto from data, rounded to clean 0.005 steps
    if w_min is None or w_max is None:
        valid_w_data = [w for w in w_data if not np.isnan(w)]
        if valid_w_data:
            import math as _math
            if w_min is None:
                w_min = 0.0
            if w_max is None:
                _raw_max = max(valid_w_data) + 0.002
                w_max = _math.ceil(_raw_max / 0.005) * 0.005
                w_max = max(w_max, 0.010)  # minimum sensible range
        else:
            if w_min is None:
                w_min = 0.0
            if w_max is None:
                w_max = 0.07  # Fallback range
    
    # Create saturation line (100% RH)
    tdb_sat = np.linspace(tdb_min, tdb_max, 200)
    w_sat = []
    for t in tdb_sat:
        try:
            w = psy.GetHumRatioFromTWetBulb(t, t, pressure_psia)
            w_sat.append(w)
        except:
            w_sat.append(np.nan)
    
    ax.plot(tdb_sat, w_sat, 'k-', linewidth=3, label='Saturation Line (100% RH)')
    
    # Add constant RH lines
    for rh in range(10, 91, 5):
        w_rh = []
        tdb_rh = []
        for t in np.linspace(tdb_min, tdb_max, 100):
            try:
                w = psy.GetHumRatioFromRelHum(t, rh/100, pressure_psia)
                if 0 <= w <= w_max:
                    w_rh.append(w)
                    tdb_rh.append(t)
            except:
                continue
        if w_rh:
            ax.plot(tdb_rh, w_rh, 'b-', alpha=0.7, linewidth=1.0, 
                   label='Relative Humidity Lines (%)' if rh == 10 else None)
    
    # Add RH% labels at intersection of dry bulb line and RH curves - easily configurable
    rh_label_dry_bulb = 105 if not is_si else 40.6  # X-axis: dry bulb temperature (°F or °C)
    rh_label_rh_percents = [10, 20, 30, 40, 50, 60, 70]  # List of RH% values to label (e.g., [40, 45, 50])
    
    for rh_percent in rh_label_rh_percents:
        if tdb_min <= rh_label_dry_bulb <= tdb_max:
            try:
                # Calculate Y-coordinate (humidity ratio) at intersection of DB line and RH curve
                w = psy.GetHumRatioFromRelHum(rh_label_dry_bulb, rh_percent/100, pressure_psia)
                if w_min <= w <= w_max:
                    ax.text(rh_label_dry_bulb, w, f'{rh_percent}%',# RH', 
                           fontsize=12, fontweight='bold', rotation=45, ha='center', va='center',
                           color='blue')
            except:
                pass
    
    # Add constant wet bulb lines
    if is_si:
        twb_range = range(5, 33, 5)  # 5 to 32°C in steps of 5
    else:
        twb_range = range(10, 90, 5)  # 10 to 90°F in steps of 5
    for twb in twb_range:
        w_twb = []
        tdb_twb = []
        for t in np.linspace(tdb_min, tdb_max, 100):
            try:
                w = psy.GetHumRatioFromTWetBulb(t, twb, pressure_psia)
                if 0 <= w <= w_max:
                    w_twb.append(w)
                    tdb_twb.append(t)
            except:
                continue
        if w_twb:
            ax.plot(tdb_twb, w_twb, 'g-', alpha=0.7, linewidth=1.0,
                   label=f'Wet Bulb Temperature Lines ({temp_unit})' if twb == 10 else None)
            if tdb_twb:
                # Position label at 3% of original coordinates (slightly left and up)
                ax.text(tdb_twb[0] * 0.97, w_twb[0] * 1.03, f'{twb}{temp_unit}', 
                       fontsize=12, fontweight='bold', color='green',
                       rotation=-45, ha='right')
    
    # Constant enthalpy lines — scan full tdb range, no heuristic start
    if is_si:
        h_range = range(10, 135, 5)   # 10–130 kJ/kg
        h_unit  = 'kJ/kg'
    else:
        h_range = range(5, 60, 5)     # 5–55 BTU/lb
        h_unit  = 'BTU/lb'

    for h in h_range:
        _h_psy = h * 1000 if is_si else h  # psychrolib SI needs J/kg
        w_h, tdb_h = [], []
        for t in np.linspace(tdb_min, tdb_max, 300):
            try:
                w = psy.GetHumRatioFromEnthalpyAndTDryBulb(_h_psy, t)
                if w_min <= w <= w_max:
                    w_h.append(w)
                    tdb_h.append(t)
            except:
                continue
        if len(w_h) >= 2:
            ax.plot(tdb_h, w_h, color='#C0392B', alpha=0.55, linewidth=0.8,
                   label=f'Enthalpy ({h_unit})' if h == list(h_range)[0] else None)
            # Label at the left-most visible point
            ax.text(tdb_h[0], w_h[0], f'{h}', fontsize=9, fontweight='bold',
                   color='#C0392B', va='bottom')
    
    # Add dew point lines with secondary y-axis on right - terminate at saturation line from right
    if show_dew_point:
        # Create secondary y-axis for dew point temperature
        ax2 = ax.twinx()
        ax2.set_ylim(w_min, w_max)
        # Move dew point axis to right side, offset outward to avoid overlap
        ax2.yaxis.tick_right()
        ax2.yaxis.set_label_position('right')
        # Hide top, bottom, and left spines, but show right spine for dew point axis
        ax2.spines['top'].set_visible(False)
        ax2.spines['bottom'].set_visible(False)
        ax2.spines['left'].set_visible(False)
        # Show right spine and color it magenta to match dew point lines
        # Offset the spine outward to create a separate visible axis line
        ax2.spines['right'].set_visible(True)
        ax2.spines['right'].set_color('magenta')
        ax2.spines['right'].set_linewidth(2)
        ax2.spines['right'].set_position(('outward', 100))  # Offset 100 points outward to avoid overlap
        # Position ticks to align with the offset spine
        # Color ticks and labels magenta to match dew point lines
        # Set tick direction to 'out' so they extend from the spine
        ax2.tick_params(axis='y', which='major', pad=10, colors='magenta', direction='out', length=4)
        
        # Calculate dew point temperature range from humidity ratio range
        dew_point_labels = []
        dew_point_positions = []
        
        # Add constant dew point lines (horizontal lines terminating at saturation line from right)
        if is_si:
            tdp_range = range(0, 56, 5)  # 0 to 55°C in steps of 5
        else:
            tdp_range = range(10, 91, 5)  # 10 to 90°F in steps of 5
        
        for tdp in tdp_range:
            try:
                # Calculate humidity ratio at saturation (dew point = dry bulb at saturation)
                w_dp = psy.GetHumRatioFromTWetBulb(tdp, tdp, pressure_psia)
                if w_min <= w_dp <= w_max:
                    # Find where this horizontal line intersects saturation curve
                    # For horizontal line at w_dp, find tdb where saturation line has w_dp
                    tdb_intersect = None
                    for i, (t_sat, w_sat_val) in enumerate(zip(tdb_sat, w_sat)):
                        if not np.isnan(w_sat_val) and abs(w_sat_val - w_dp) < 0.0001:
                            tdb_intersect = t_sat
                            break
                        # Interpolate if needed
                        if i > 0 and not np.isnan(w_sat_val) and not np.isnan(w_sat[i-1]):
                            if (w_sat[i-1] <= w_dp <= w_sat_val) or (w_sat_val <= w_dp <= w_sat[i-1]):
                                # Linear interpolation
                                tdb_intersect = tdb_sat[i-1] + (tdb_sat[i] - tdb_sat[i-1]) * \
                                              (w_dp - w_sat[i-1]) / (w_sat_val - w_sat[i-1])
                                break
                    
                    # Draw horizontal line from right edge to saturation intersection
                    if tdb_intersect is not None and tdb_intersect <= tdb_max:
                        ax.plot([tdb_intersect, tdb_max], [w_dp, w_dp], 'm-', alpha=0.5, linewidth=0.8,
                               label=f'Dew Point Lines ({temp_unit})' if tdp == tdp_range[0] else None)
                    else:
                        # If no intersection found, draw full width
                        ax.plot([tdb_min, tdb_max], [w_dp, w_dp], 'm-', alpha=0.5, linewidth=0.8,
                               label=f'Dew Point Lines ({temp_unit})' if tdp == tdp_range[0] else None)
                    
                    # Store for secondary axis labels (without unit suffix)
                    dew_point_labels.append(f'{tdp}')
                    dew_point_positions.append(w_dp)
            except:
                continue
        
        # Set secondary y-axis labels for dew point temperature
        if dew_point_positions:
            # Create tick positions and labels - color label magenta to match dew point lines
            ax2.set_ylabel('DEW POINT TEMPERATURE - ' + temp_unit, fontsize=12, fontweight='bold', color='magenta')
            ax2.set_yticks(dew_point_positions)
            ax2.set_yticklabels(dew_point_labels, fontsize=9)
    
    # Plot weather data colored by hours per 2D bin (DB and WB)
    valid_data = weather_data.dropna(subset=['Tdb_plot', 'Twb_plot', 'humidity_ratio']).copy()
    if not valid_data.empty:
        # Bin by both dry bulb and wet bulb temperature
        if bin_size_db is None:
            bin_size_db = 2.0 if is_si else 3.6
        if bin_size_wb is None:
            bin_size_wb = 2.0 if is_si else 3.6
        tdb_bins = pd.cut(valid_data['Tdb_plot'],
                         bins=np.arange(tdb_min, tdb_max + bin_size_db, bin_size_db),
                         include_lowest=True)
        twb_bins = pd.cut(valid_data['Twb_plot'],
                         bins=np.arange(tdb_min, tdb_max + bin_size_wb, bin_size_wb),
                         include_lowest=True)

        # Count hours per 2D bin (DB x WB combination)
        valid_data['db_bin'] = tdb_bins
        valid_data['wb_bin'] = twb_bins
        bin_counts = valid_data.groupby(['db_bin', 'wb_bin'], observed=True).size()

        # Create mapping dictionary from (db_bin, wb_bin) tuple to count
        bin_to_count = {}
        for idx, count in bin_counts.items():
            bin_to_count[idx] = int(count)

        # Map each point to its 2D bin's hour count
        hours_in_bin = np.array([bin_to_count.get((db_bin, wb_bin), 0)
                                 for db_bin, wb_bin in zip(tdb_bins, twb_bins)])

        # Normalize hours for color intensity (darker = more hours)
        max_hours = float(bin_counts.max()) if len(bin_counts) > 0 else 1
        if max_hours > 0:
            from matplotlib.colors import LinearSegmentedColormap
            # Green (rare) → yellow → red (frequent) — traffic signal density
            density_cmap = LinearSegmentedColormap.from_list(
                'density_traffic', ['#00AA44', '#FFDD00', '#CC2200'], N=256)
            # Small, semi-transparent dots: each hourly point is visible individually;
            # dense areas appear darker by natural alpha stacking, not by collapsing to a patch
            scatter = ax.scatter(valid_data['Tdb_plot'], valid_data['humidity_ratio'],
                               c=hours_in_bin, cmap=density_cmap, vmin=1, vmax=max_hours,
                               s=4, alpha=0.4, edgecolors='none', zorder=1)

            # Colorbar on the left side, half height
            cbar = plt.colorbar(scatter, ax=ax, pad=0.15, location='left', shrink=0.5)
            cbar.set_label('Hours per Bin', fontsize=10, fontweight='bold')
            cbar.ax.tick_params(labelsize=9)
    
    # Add T1 and T2 points with callouts
    def plot_point_with_callout(tdb, twb, w, description=None, color='red', show_tdb_only=False):
        """Plot a point and add callout label with description"""
        if tdb is None or w is None:
            return
        
        try:
            # Plot point
            ax.scatter(tdb, w, s=150, color=color, edgecolors='black', linewidth=2.5, zorder=10)
            # Create description text - only show user description
            if show_tdb_only:
                # For T2: only show dry bulb temperature
                label_text = f'{tdb:.1f}{temp_unit}'
                if description:
                    label_text = f'{description}\n{label_text}'
            else:
                # For T1: only show user description (no labels)
                # Skip callout if no description provided
                if not description:
                    return
                label_text = description
            
            # Add callout with arrow only if we have text to show
            if label_text:
                offset_x = (tdb_max - tdb_min) * 0.05
                offset_y = (w_max - w_min) * 0.05
                ax.annotate(label_text, xy=(tdb, w), xytext=(tdb + offset_x, w + offset_y),
                           fontsize=12, fontweight='bold', color=color,
                           bbox=dict(boxstyle='round,pad=0.5', facecolor='white', edgecolor=color, linewidth=2.5),
                           arrowprops=dict(arrowstyle='->', color=color, lw=2.5))
        except:
            pass
    
    # Helper function to plot cooling path
    def plot_cooling_path(T1_tdb, T1_twb, T2_tdb, color, path_name, T1_description=None):
        """Plot cooling path: T1 → Dew Point → T2"""
        try:
            T1_data = calculate_point_data(T1_tdb, T1_twb, pressure_psia)
            if not T1_data:
                return
            
            T1_tdb_val, T1_twb_val, T1_w, T1_dp = T1_data
            
            # Check bounds
            if not (w_min <= T1_w <= w_max and tdb_min <= T1_tdb_val <= tdb_max):
                return
            
            # Calculate dew point position
            T1_dp_w = psy.GetHumRatioFromTWetBulb(T1_dp, T1_dp, pressure_psia)
            T1_dp_tdb = T1_dp
            if not (w_min <= T1_dp_w <= w_max and tdb_min <= T1_dp_tdb <= tdb_max):
                return
            
            # Calculate T2 position
            T2_tdb_val = T2_tdb
            if T2_tdb < T1_dp:
                # T2 < dew point: T2 is on saturation line
                try:
                    T2_w = psy.GetHumRatioFromTWetBulb(T2_tdb, T2_tdb, pressure_psia)
                except:
                    print(f"Error calculating T2_w for T2={T2_tdb}, T1_dp={T1_dp}")
                    return
            else:
                # T2 > dew point: T2 is on horizontal line (constant humidity ratio = T1 humidity ratio)
                T2_w = T1_w
            
            # Check if T2 is within reasonable bounds for plotting
            T2_in_bounds = (tdb_min <= T2_tdb_val <= tdb_max and w_min <= T2_w <= w_max)
            if not T2_in_bounds:
                print(f"Warning ({path_name}): T2 ({T2_tdb_val:.1f}{temp_unit}, w={T2_w:.4f}) is outside chart bounds (tdb: {tdb_min}-{tdb_max}{temp_unit}, w: {w_min:.4f}-{w_max:.4f})")
                # If T2 is way outside bounds, clip it to chart edge for visualization
                if T2_tdb_val < tdb_min:
                    print(f"  Clipping T2 from {T2_tdb_val} to {tdb_min} for visualization")
                    T2_tdb_val = tdb_min
                    # Recalculate T2_w at clipped position
                    if T2_tdb < T1_dp:
                        T2_w = psy.GetHumRatioFromTWetBulb(T2_tdb_val, T2_tdb_val, pressure_psia)
                    else:
                        T2_w = T1_w
                elif T2_tdb_val > tdb_max:
                    print(f"  Clipping T2 from {T2_tdb_val} to {tdb_max} for visualization")
                    T2_tdb_val = tdb_max
                    if T2_tdb < T1_dp:
                        T2_w = psy.GetHumRatioFromTWetBulb(T2_tdb_val, T2_tdb_val, pressure_psia)
                    else:
                        T2_w = T1_w
            
            # Plot points (only if within bounds)
            ax.scatter(T1_tdb_val, T1_w, s=150, color=color, edgecolors='black', linewidth=2.5, zorder=10)
            ax.scatter(T1_dp_tdb, T1_dp_w, s=150, color=color, edgecolors='black', linewidth=2.5, zorder=10, marker='s')
            # Only plot T2 point if it's within chart bounds
            if tdb_min <= T2_tdb_val <= tdb_max and w_min <= T2_w <= w_max:
                ax.scatter(T2_tdb_val, T2_w, s=150, color=color, edgecolors='black', linewidth=2.5, zorder=10, marker='^')
            else:
                print(f"  T2 point ({T2_tdb_val:.1f}{temp_unit}, w={T2_w:.4f}) outside bounds - arrows will be drawn but point not plotted")
            
            # Add callout at T1 showing description, db and wb
            offset_x, offset_y = (tdb_max - tdb_min) * 0.05, (w_max - w_min) * 0.05
            T1_label_parts = []
            if T1_description:
                T1_label_parts.append(T1_description)
            T1_label_parts.append(f'Tdb={T1_tdb_val:.1f}{temp_unit}\nTwb={T1_twb_val:.1f}{temp_unit}')
            T1_label = '\n'.join(T1_label_parts)
            T1_callout_props = dict(fontsize=11, fontweight='bold', color=color,
                                   bbox=dict(boxstyle='round,pad=0.5', facecolor='white', edgecolor=color, linewidth=2),
                                   arrowprops=dict(arrowstyle='->', color=color, lw=3))
            # For SEA (violet), place callout upward; for Customer (orange), place upward
            T1_offset_y = offset_y if color == 'violet' else offset_y
            ax.annotate(T1_label, xy=(T1_tdb_val, T1_w),
                       xytext=(T1_tdb_val + offset_x, T1_w + T1_offset_y), **T1_callout_props)
            
            # Draw arrows using FancyArrowPatch for better visibility
            def draw_arrow(x1, y1, x2, y2, color, linewidth=4, linestyle='--'):
                """Helper to draw arrow between two points"""
                # Draw line with linestyle first
                ax.plot([x1, x2], [y1, y2], color=color, linewidth=linewidth, 
                       linestyle=linestyle, alpha=1.0, zorder=14)
                # Then add arrowhead
                arrow = FancyArrowPatch((x1, y1), (x2, y2),
                                       arrowstyle='->', color=color, 
                                       linewidth=0,  # No line, just arrowhead
                                       alpha=1.0, zorder=15)
                ax.add_patch(arrow)
            
            # Both paths use dashed linestyle
            linestyle = '--'
            
            if T2_tdb < T1_dp:
                # T2 < dew point: T1 → Dew Point → T2 (along saturation line)
                # Arrow 1: T1 → Dew Point (horizontal line)
                draw_arrow(T1_tdb_val, T1_w, T1_dp_tdb, T1_dp_w, color, linestyle=linestyle)
                # Arrow 2: Dew Point → T2 (along saturation line downward)
                # Use max(tdb_min, T2_tdb_val) to ensure we stay within chart bounds
                T2_clipped = max(tdb_min, T2_tdb_val)
                sat_segment_tdb, sat_segment_w = find_saturation_segment(T1_dp_tdb, T2_clipped, tdb_sat, w_sat)
                if len(sat_segment_tdb) > 1:
                    # Draw entire saturation segment as one continuous dashed line
                    ax.plot(sat_segment_tdb, sat_segment_w, color=color, linewidth=4, 
                           linestyle=linestyle, alpha=1.0, zorder=14)
                    # Draw to actual T2 position (may be outside bounds, but arrow will be clipped)
                    last_sat_tdb, last_sat_w = sat_segment_tdb[0], sat_segment_w[0]
                    # Draw connecting line to T2
                    ax.plot([last_sat_tdb, T2_tdb_val], [last_sat_w, T2_w], color=color, 
                           linewidth=4, linestyle=linestyle, alpha=1.0, zorder=14)
                    # Add arrowhead at T2
                    draw_arrow(last_sat_tdb, last_sat_w, T2_tdb_val, T2_w, color, linestyle=linestyle)
                else:
                    # Direct arrow if no saturation segment found
                    draw_arrow(T1_dp_tdb, T1_dp_w, T2_tdb_val, T2_w, color, linestyle=linestyle)
            else:
                # T2 > dew point: T1 → T2 directly (horizontal line, constant humidity ratio)
                draw_arrow(T1_tdb_val, T1_w, T2_tdb_val, T2_w, color, linestyle=linestyle)
            
            # Add callouts at dew point and T2 (thicker arrows)
            callout_props = dict(fontsize=11, fontweight='bold', color=color,
                                bbox=dict(boxstyle='round,pad=0.5', facecolor='white', edgecolor=color, linewidth=2),
                                arrowprops=dict(arrowstyle='->', color=color, lw=3))
            
            # For SEA (violet), place all callouts upward; for Customer (orange), place upward
            callout_offset_y = offset_y if color == 'violet' else offset_y
            
            # Dew point callout: tilt to the left (negative x offset)
            ax.annotate(f'{T1_dp:.1f}{temp_unit}', xy=(T1_dp_tdb, T1_dp_w),
                       xytext=(T1_dp_tdb - offset_x, T1_dp_w + callout_offset_y), **callout_props)
            if tdb_min <= T2_tdb_val <= tdb_max and w_min <= T2_w <= w_max:
                # T2 callout: same direction as dew point (tilt to the left, negative x offset)
                ax.annotate(f'{T2_tdb:.1f}{temp_unit}', xy=(T2_tdb_val, T2_w),
                       xytext=(T2_tdb_val - offset_x, T2_w + callout_offset_y), **callout_props)
        except Exception as e:
            # Debug: print error to see what's wrong
            print(f"Error in plot_cooling_path ({path_name}): {e}")
            import traceback
            traceback.print_exc()
    
    # Plot SEA cooling path if enabled (cyan color)
    if show_SEA_Cooling_path and T1_SEA_Tdb is not None and T1_SEA_Twb is not None and T2_SEA_Tdb is not None:
        print(f"Plotting SEA path: T1=({T1_SEA_Tdb}, {T1_SEA_Twb}), T2={T2_SEA_Tdb}, bounds: tdb={tdb_min}-{tdb_max}, w={w_min:.4f}-{w_max:.4f}")  # Debug
        plot_cooling_path(T1_SEA_Tdb, T1_SEA_Twb, T2_SEA_Tdb, 'blue', 'SEA', T1_SEA_description)
    
    # Plot Customer cooling path if enabled (orange color for good visibility with green)
    if show_Customer_Cooling_path and T1_Customer_Tdb is not None and T1_Customer_Twb is not None and T2_Customer_Tdb is not None:
        print(f"Plotting Customer path: T1=({T1_Customer_Tdb}, {T1_Customer_Twb}), T2={T2_Customer_Tdb}, bounds: tdb={tdb_min}-{tdb_max}, w={w_min:.4f}-{w_max:.4f}")  # Debug
        plot_cooling_path(T1_Customer_Tdb, T1_Customer_Twb, T2_Customer_Tdb, 'orange', 'Customer', T1_Customer_description)
    
    # ASHRAE-style formatting
    ax.set_xlim(tdb_min, tdb_max)
    ax.set_ylim(w_min, w_max)
    
    # Axis labels — secondary unit shown via top tick axis added below
    if is_si:
        ax.set_xlabel('DRY BULB TEMPERATURE  °C', fontsize=13, fontweight='bold')
        ax.set_ylabel('HUMIDITY RATIO  kg/kg dry air', fontsize=13, fontweight='bold')
        unit_text = "SI UNITS"
        pressure_text = f"Pressure: {pressure_Pa/1000:.1f} kPa  ({pressure_inHg:.2f} inHg)"
    else:
        ax.set_xlabel('DRY BULB TEMPERATURE  °F', fontsize=13, fontweight='bold')
        ax.set_ylabel('HUMIDITY RATIO  lb/lb dry air', fontsize=13, fontweight='bold')
        unit_text = "I-P UNITS"
        pressure_text = f"Pressure: {pressure_inHg:.3f} inHg  ({pressure_Pa/1000:.1f} kPa)"
    
    # Move humidity ratio y-axis to the right side
    ax.yaxis.tick_right()
    ax.yaxis.set_label_position('right')
    
    # ASHRAE-style title
    title = f'PSYCHROMETRIC CHART - NORMAL TEMPERATURE {unit_text}\n'
    _elev_str = f'{elevation_m:.0f} m' if is_si else f'{elevation_ft:.0f} ft'
    title += f'Elevation: {_elev_str}  {pressure_text}\n'
    title += f'{location_name}'
    ax.set_title(title, fontsize=16, fontweight='bold', pad=20)
    
    # Add legend on top of curves - bigger size with units
    ax.legend(loc='upper left', frameon=True, fancybox=True, shadow=True, fontsize=14)

    # Secondary top x-axis — IP (°F) primary on bottom, SI (°C) on top; flipped in SI mode
    ax_top = ax.twiny()
    ax_top.set_xlim(tdb_min, tdb_max)
    for _sp in ['bottom', 'left', 'right']:
        ax_top.spines[_sp].set_visible(False)
    ax_top.spines['top'].set_linewidth(1.5)
    ax_top.spines['top'].set_color('black')
    if is_si:
        # Primary bottom = °C → top shows °F
        _f_candidates = np.arange(-20, 140, 10)
        _c_positions = (_f_candidates - 32) * 5 / 9
        _mask = (_c_positions >= tdb_min) & (_c_positions <= tdb_max)
        ax_top.set_xticks(_c_positions[_mask])
        ax_top.set_xticklabels([f'{int(v)}' for v in _f_candidates[_mask]], fontsize=9)
        ax_top.set_xlabel('°F', fontsize=11, fontweight='bold', labelpad=6)
    else:
        # Primary bottom = °F → top shows °C
        _c_candidates = np.arange(-20, 60, 5)
        _f_positions = _c_candidates * 9 / 5 + 32
        _mask = (_f_positions >= tdb_min) & (_f_positions <= tdb_max)
        ax_top.set_xticks(_f_positions[_mask])
        ax_top.set_xticklabels([f'{int(v)}' for v in _c_candidates[_mask]], fontsize=9)
        ax_top.set_xlabel('°C', fontsize=11, fontweight='bold', labelpad=6)

    # Professional grid - both dry bulb and humidity ratio lines truncated at saturation
    ax.set_xticks(np.arange(tdb_min, tdb_max + 1, 5))  # Every 5°F
    ax.set_yticks(np.arange(w_min, w_max + 0.001, 0.01))  # Every 0.01 humidity ratio
    # Disable automatic grid - we'll draw manually
    ax.grid(False)
    
    # Manually draw dry bulb grid lines truncated at saturation line
    for t_grid in np.arange(tdb_min, tdb_max + 1, 5):  # Every 5°F
        try:
            # Find humidity ratio at saturation for this temperature
            w_at_sat = psy.GetHumRatioFromTWetBulb(t_grid, t_grid, pressure_psia)
            if w_min <= w_at_sat <= w_max:
                # Draw vertical line from bottom to saturation line
                ax.plot([t_grid, t_grid], [w_min, w_at_sat], 
                       'gray', alpha=0.6, linewidth=0.8, linestyle='-')
        except:
            continue
    
    # Manually draw humidity ratio grid lines truncated at saturation line
    for w_grid in np.arange(w_min, w_max + 0.001, 0.01):  # Every 0.01 humidity ratio
        # Find where this horizontal line intersects saturation curve
        tdb_intersect = None
        for i, (t_sat, w_sat_val) in enumerate(zip(tdb_sat, w_sat)):
            if not np.isnan(w_sat_val) and abs(w_sat_val - w_grid) < 0.0001:
                tdb_intersect = t_sat
                break
            # Interpolate if needed
            if i > 0 and not np.isnan(w_sat_val) and not np.isnan(w_sat[i-1]):
                if (w_sat[i-1] <= w_grid <= w_sat_val) or (w_sat_val <= w_grid <= w_sat[i-1]):
                    # Linear interpolation
                    tdb_intersect = tdb_sat[i-1] + (tdb_sat[i] - tdb_sat[i-1]) * \
                                  (w_grid - w_sat[i-1]) / (w_sat_val - w_sat[i-1])
                    break
        
        # Draw horizontal line from right edge to saturation intersection
        if tdb_intersect is not None and tdb_intersect <= tdb_max:
            ax.plot([tdb_intersect, tdb_max], [w_grid, w_grid], 
                   'gray', alpha=0.6, linewidth=0.8, linestyle='-')
        else:
            # If no intersection found (above saturation), draw full width
            ax.plot([tdb_min, tdb_max], [w_grid, w_grid], 
                   'gray', alpha=0.6, linewidth=0.8, linestyle='-')
    ax.set_facecolor('white')
    
    # Add border - hide left spine where saturation line forms boundary, clip top spine
    # Find where saturation line reaches top (w_max)
    sat_top_tdb = tdb_max  # Default to right edge
    for i, (t, w) in enumerate(zip(tdb_sat, w_sat)):
        if not np.isnan(w) and w >= w_max * 0.99:  # Close to top
            sat_top_tdb = t
            break
    
    # Hide left spine and full top spine
    ax.spines['left'].set_visible(False)
    ax.spines['top'].set_visible(False)
    # Draw top spine segment only from saturation line to right edge
    ax.plot([sat_top_tdb, tdb_max], [w_max, w_max], 'k-', linewidth=2, clip_on=False)
    ax.spines['right'].set_linewidth(2)
    ax.spines['right'].set_color('black')
    ax.spines['bottom'].set_linewidth(2)
    ax.spines['bottom'].set_color('black')
    
    # Save chart
    if output_file is None:
        import time
        output_file = f"psychrometric_chart_{int(time.time())}.png"
    
    from io import BytesIO
    plt.tight_layout()
    buf = BytesIO()
    plt.savefig(buf, format="png", dpi=150, bbox_inches='tight')
    buf.seek(0)
    plot_bytes = buf.read()
    plt.close()
    return {"plot_bytes": plot_bytes}

def load_weather_file(file_path: str) -> pd.DataFrame:
    """Load weather data from CSV file"""
    df = pd.read_csv(file_path)
    return normalize_weather_columns(df)

