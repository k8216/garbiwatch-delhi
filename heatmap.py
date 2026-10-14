import json

import branca.colormap as bcm
import folium
import numpy as np
from folium.raster_layers import ImageOverlay
from matplotlib.colors import LinearSegmentedColormap

ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services"
STYLES = {
    "street": {
        "tiles": f"{ESRI}/World_Street_Map/MapServer/tile/{{z}}/{{y}}/{{x}}",
        "labels": None,
        "text": "#111111",
        "halo": "#ffffff",
    },
    "dark": {
        "tiles": f"{ESRI}/Canvas/World_Dark_Gray_Base/MapServer/tile/{{z}}/{{y}}/{{x}}",
        "labels": f"{ESRI}/Canvas/World_Dark_Gray_Reference/MapServer/tile/{{z}}/{{y}}/{{x}}",
        "text": "#f5f5f5",
        "halo": "#000000",
    },
}
COLORS = ["#2ecc71", "#f1c40f", "#e67e22", "#e74c3c", "#8e44ad"]
PAD = 0.08   # how far (in degrees) the colour spreads beyond the outer points
FADE = 0.07  # distance (in degrees) at which the colour fades to nothing


def status(score):
    if score < 20:
        return "Clean"
    if score < 40:
        return "Low"
    if score < 60:
        return "Moderate"
    if score < 80:
        return "High"
    return "Severe"


def idw(points, lat_grid, lon_grid, power=2):
    # Weighted average of the readings; closer readings count more.
    num = np.zeros_like(lat_grid)
    den = np.zeros_like(lat_grid)
    nearest = np.full_like(lat_grid, np.inf)
    for lat, lon, value in points:
        dist = np.sqrt((lat_grid - lat) ** 2 + (lon_grid - lon) ** 2) + 1e-9
        weight = 1.0 / dist**power
        num += weight * value
        den += weight
        nearest = np.minimum(nearest, dist)
    return num / den, nearest


def build_map(path="locations.json", style="street", status_colors=None):
    look = STYLES.get(style, STYLES["street"])

    with open(path) as f:
        locations = json.load(f)["locations"]

    # (lat, lon, score 0-100) using each location's latest reading
    points = [
        (loc["lat"], loc["lon"], loc["history"][-1]["coverage"] * 100)
        for loc in locations
    ]

    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    south, north = min(lats) - PAD, max(lats) + PAD
    west, east = min(lons) - PAD, max(lons) + PAD

    # A grid of points covering the area, then a score for every grid point
    lat_axis = np.linspace(south, north, 250)
    lon_axis = np.linspace(west, east, 250)
    lon_grid, lat_grid = np.meshgrid(lon_axis, lat_axis)
    values, nearest = idw(points, lat_grid, lon_grid)

    # Turn scores into colours, and fade the colour out far from any reading
    cmap = LinearSegmentedColormap.from_list("garbage", COLORS)
    rgba = cmap(np.clip(values / 100, 0, 1))
    rgba[..., 3] = np.clip(1 - nearest / FADE, 0, 1) * 0.8

    m = folium.Map(
        location=[(south + north) / 2, (west + east) / 2],
        zoom_start=12,
        tiles=look["tiles"],
        attr="Tiles © Esri",
    )
    if look["labels"]:
        folium.TileLayer(
            tiles=look["labels"], attr="Tiles © Esri", name="labels", overlay=True
        ).add_to(m)

    ImageOverlay(
        image=rgba,
        bounds=[[south, west], [north, east]],
        origin="lower",
        pixelated=False,
    ).add_to(m)

    for loc in locations:
        first = loc["history"][0]["coverage"] * 100
        latest = loc["history"][-1]
        score = round(latest["coverage"] * 100)
        pin_color = (status_colors or {}).get(loc["name"], "white")

        popup_html = f"""
        <div style="font-family:Arial;width:220px">
          <b>{loc['name']}</b><br>
          <span style="font-size:22px;font-weight:bold">{score}</span>
          &nbsp;{status(score)}<br>
          Garbage regions: {latest['count']}<br>
          First reading to latest: {round(first)} to {score}
        </div>
        """
        folium.CircleMarker(
            location=[loc["lat"], loc["lon"]],
            radius=8,
            color=look["text"],
            weight=2,
            fill=True,
            fill_color=pin_color,
            fill_opacity=1,
            popup=folium.Popup(popup_html, max_width=260),
        ).add_to(m)

        label_html = (
            f'<div style="text-align:center;font:bold 11px Arial;color:{look["text"]};'
            f'text-shadow:0 0 3px {look["halo"]},0 0 3px {look["halo"]},0 0 3px {look["halo"]}">'
            f"{loc['name']}<br>{score}</div>"
        )
        folium.Marker(
            location=[loc["lat"], loc["lon"]],
            icon=folium.DivIcon(icon_size=(130, 34), icon_anchor=(65, -8), html=label_html),
        ).add_to(m)

    bcm.LinearColormap(
        COLORS,
        vmin=0,
        vmax=100,
        caption="Garbage score (0 = clean, 100 = heavily covered)",
    ).add_to(m)

    m.fit_bounds([[south, west], [north, east]])
    return m


if __name__ == "__main__":
    build_map().save("garbage_map.html")
    print("Map saved to garbage_map.html")