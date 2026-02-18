import io
import requests
import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="MacroViz v0.1", layout="wide")
st.title("MacroViz v0.1")
st.caption("World Bank API → charts + table + CSV export (proof of concept)")

INDICATORS = {
    "GDP (current US$)": "NY.GDP.MKTP.CD",
    "GDP per capita (current US$)": "NY.GDP.PCAP.CD",
    "Population": "SP.POP.TOTL",
    "Inflation, consumer prices (annual %)": "FP.CPI.TOTL.ZG",
    "Unemployment, total (% of labor force)": "SL.UEM.TOTL.ZS",
    "CO₂ emissions (kt)": "EN.ATM.CO2E.KT",
    "Exports of goods & services (% of GDP)": "NE.EXP.GNFS.ZS",
    "Imports of goods & services (% of GDP)": "NE.IMP.GNFS.ZS",
}

@st.cache_data(show_spinner=False)
def fetch_world_bank(country_iso3: str, indicator: str, start_year: int, end_year: int) -> pd.DataFrame:
    url = (
        f"https://api.worldbank.org/v2/country/{country_iso3}/indicator/{indicator}"
        f"?format=json&per_page=2000&date={start_year}:{end_year}"
    )
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    data = r.json()

    if not isinstance(data, list) or len(data) < 2 or data[1] is None:
        return pd.DataFrame(columns=["iso3", "country", "indicator", "year", "value"])

    rows = []
    for item in data[1]:
        year = item.get("date")
        rows.append({
            "iso3": country_iso3.upper(),
            "country": (item.get("country") or {}).get("value", country_iso3.upper()),
            "indicator": (item.get("indicator") or {}).get("id", indicator),
            "year": int(year) if year else None,
            "value": item.get("value"),
        })

    df = pd.DataFrame(rows).dropna(subset=["year"]).sort_values("year").reset_index(drop=True)
    return df

with st.sidebar:
    st.header("Query")
    countries_text = st.text_input(
        "Countries (ISO3, comma-separated)",
        value="DEU,BRA",
        help="Example: DEU,BRA,USA",
    )
    indicator_name = st.selectbox("Indicator", list(INDICATORS.keys()), index=0)
    indicator_code = INDICATORS[indicator_name]
    start_year, end_year = st.slider("Year range", 1960, 2026, (2000, 2024))
    run = st.button("Load data", type="primary")

countries = [c.strip().upper() for c in countries_text.split(",") if c.strip()]

st.markdown(
    f"**Source:** World Bank API · **Indicator code:** `{indicator_code}`"
)

if not run:
    st.info("Configure inputs and click **Load data**.")
    st.stop()

if len(countries) == 0:
    st.error("Please enter at least one ISO3 country code (e.g., DEU).")
    st.stop()

if len(countries) > 15:
    st.error("Too many countries selected for v0.1. Please keep it ≤ 15.")
    st.stop()

with st.spinner("Fetching data from World Bank..."):
    frames = []
    for c in countries:
        try:
            frames.append(fetch_world_bank(c, indicator_code, start_year, end_year))
        except Exception as e:
            st.warning(f"{c}: failed to fetch ({e})")

df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

if df.empty:
    st.warning("No data returned. Try another indicator, country code, or year range.")
    st.stop()

# Trend chart
st.subheader("Trend")
fig = px.line(df, x="year", y="value", color="iso3", markers=True)
st.plotly_chart(fig, use_container_width=True)

# Table
st.subheader("Data")
st.dataframe(df, use_container_width=True)

# CSV export
csv_buf = io.StringIO()
df.to_csv(csv_buf, index=False)
st.download_button(
    "Download CSV",
    data=csv_buf.getvalue(),
    file_name=f"macro_viz_{indicator_code}_{start_year}_{end_year}.csv",
    mime="text/csv",
)
