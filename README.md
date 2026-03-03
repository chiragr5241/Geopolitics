# Global Operations Map 2023–2026

Interactive OSINT map of global military operations, compiled from open-source and unclassified sources.

## Overview

This project visualizes military operations across multiple theaters (Middle East, South China Sea, Venezuela, Ukraine, Gaza) on an interactive Leaflet map. Data is sourced from publicly available OSINT, press, and think tank reports.

## Data

- **operationsdata.csv** — Incident data with coordinates, summaries, sources, and metadata
- All imagery links point to Wikimedia Commons (public domain)
- Marked as **OPEN SOURCE / UNCLASSIFIED**

## Tech Stack

- Vanilla JavaScript (no build step)
- [Leaflet](https://leafletjs.com/) for mapping
- CartoDB dark basemap
- CSV loaded at runtime

## Local Development

1. Serve the directory with any static file server (e.g. `python3 -m http.server 8000`)
2. Open `http://localhost:8000`

## License

Data and code are provided for research and educational purposes. Verify sources independently.
