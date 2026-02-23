# MacroViz Tool v0.3

MacroViz is a Streamlit app for journalist-friendly macroeconomic charts and maps using the **World Bank API**.

## Features
- Country multiselect by **country name** (ISO3 hidden from normal UI)
- Optional Advanced ISO3 override for power users
- Multi-country line chart
- Choropleth map tab with two modes:
  - **Global map** (all countries for indicator/year)
  - **Selected only** fallback
- Robust error handling and API transparency
- Exports: CSV + interactive HTML chart

## Data source
- World Bank API only: `https://api.worldbank.org/`

## Run locally
```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
streamlit run app.py --server.address 0.0.0.0 --server.port 8501 --server.headless true
```

## Run in GitHub Codespaces
1. Open this repo in Codespaces.
2. Run:
   ```bash
   python -m pip install --upgrade pip
   python -m pip install -r requirements.txt
   streamlit run app.py --server.address 0.0.0.0 --server.port 8501 --server.headless true
   ```
3. Open the **Ports** tab.
4. Open forwarded port **8501** in browser.

## Map modes and limitations
- Global map fetches indicator values for all countries for one selected year and is cached (12h TTL).
- If global map fails or returns no data, app auto-falls back to **Selected only** mode.
- Projection is `natural earth` (non-Mercator).
- v0.3 still uses World Bank only.
