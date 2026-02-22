import io
import re
import time
import requests
import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="MacroViz", layout="wide")
st.title("MacroViz")
st.caption("Official macro data → clean charts (World Bank API)")

INDICATORS = {
    "GDP (current US$)": "NY.GDP.MKTP.CD",
    "GDP per capita (current US$)": "NY.GDP.PCAP.CD",
    "Population": "SP.POP.TOTL",
    "Inflation (CPI, annual %)": "FP.CPI.TOTL.ZG",
    "Unemployment (% of labor force)": "SL.UEM.TOTL.ZS",
    "CO₂ emissions (kt)": "EN.ATM.CO2E.KT",
    "Exports (% of GDP)": "NE.EXP.GNFS.ZS",
    "Imports (% of GDP)": "NE.IMP.GNFS.ZS",
}

ISO3_RE = re.compile(r"^[A-Z]{3}$")

def build_wb_url(iso3: str, indicator: str, start_year: int, end_year: int) -> str:
    return (
        f"https://api.worldbank.org/v2/country/{iso3}/indicator/{indicator}"
        f"?format=json&per_page=2000&date={start_year}:{end_year}"
    )

@st.cache_data(show_spinner=False, ttl=3600)
def fetch_world_bank(iso3: str, indicator: str, start_year: int, end_year: int) -> pd.DataFrame:
    url = build_wb_url(iso3, indicator, start_year, end_year)

    last_err = None
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            payload = r.json()
            break
        except Exception as e:
            last_err = e
            time.sleep(0.6 * (attempt + 1))
    else:
        raise RuntimeError(f"Request failed after retries: {last_err}")

    if not isinstance(payload, list) or len(payload) < 2 or payload[1] is None:
        return pd.DataFrame(columns=["iso3", "country", "year", "value", "indicator"])

    rows = []
    for item in payload[1]:
        year = item.get("date")
        rows.append({
            "iso3": iso3,
            "country": (item.get("country") or {}).get("value", iso3),
            "year": int(year) if year else None,
            "value": item.get("value"),
            "indicator": (item.get("indicator") or {}).get("id", indicator),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.dropna(subset=["year"]).sort_values("year").reset_index(drop=True)

with st.sidebar:
    st.header("Data settings")
    countries_text = st.text_input(
        "Countries (ISO-3, comma-separated)",
        value="USA,DEU,BRA",
        help="Example: USA,DEU,CHN",
    )
    indicator_name = st.selectbox("Indicator", list(INDICATORS.keys()), index=0)
    auto_scale = st.checkbox("Auto-scale units (K/M/B/T)", value=True)
    start_year, end_year = st.slider("Year range", 1960, 2026, (2000, 2024))
    run = st.button("Load data", type="primary")

countries = [c.strip().upper() for c in countries_text.split(",") if c.strip()]
invalid = [c for c in countries if not ISO3_RE.match(c)]

if invalid:
    st.error(f"Invalid ISO-3 country code(s): {', '.join(invalid)}. Example: USA, DEU, BRA.")
    st.stop()

indicator_code = INDICATORS[indicator_name]

tab_chart, tab_data, tab_about = st.tabs(["Chart", "Data", "About / Source"])

with tab_about:
    st.markdown("**Source:** World Bank API")
    st.markdown("This v0.2 prototype supports a small curated set of indicators and ISO-3 country codes.")
    st.markdown("It is designed to never crash: invalid inputs and empty datasets should show friendly messages.")
    st.code(build_wb_url(countries[0] if countries else "USA", indicator_code, start_year, end_year))

if not run:
    with tab_chart:
        st.info("Choose countries/indicator and click **Load data**.")
    with tab_data:
        st.info("Data table will appear after you load data.")
    st.stop()

if len(countries) == 0:
    st.error("Please enter at least one ISO-3 country code.")
    st.stop()

if len(countries) > 8:
    st.error("Too many countries for v0.2. Please keep it ≤ 8.")
    st.stop()

frames = []
errors = []
with st.spinner("Fetching data..."):
    for c in countries:
        try:
            df_c = fetch_world_bank(c, indicator_code, start_year, end_year)
            if df_c is None or df_c.empty:
                errors.append(f"{c}: no data returned for this period/indicator.")
            else:
                frames.append(df_c)
        except Exception as e:
            errors.append(f"{c}: {e}")

if errors and not frames:
    with tab_chart:
        st.error("No usable data returned. Try another indicator or year range.")
        st.code("\n".join(errors))
        st.markdown("API URL used:")
        st.code(build_wb_url(countries[0], indicator_code, start_year, end_year))
    st.stop()

if errors:
    with tab_chart:
        st.warning("Some countries returned no data or failed. Showing what was retrieved.")
        st.code("\n".join(errors))

df = pd.concat(frames, ignore_index=True)

# Auto-scale units
scale_label = ""
scale_factor = 1.0
if auto_scale and not df["value"].dropna().empty:
    vmax = float(df["value"].dropna().abs().max())
    if vmax >= 1e12:
        scale_factor, scale_label = 1e12, " (trillions)"
    elif vmax >= 1e9:
        scale_factor, scale_label = 1e9, " (billions)"
    elif vmax >= 1e6:
        scale_factor, scale_label = 1e6, " (millions)"
    elif vmax >= 1e3:
        scale_factor, scale_label = 1e3, " (thousands)"
if scale_factor != 1.0:
    df["value"] = df["value"] / scale_factor

title = f"{indicator_name}{scale_label} — {', '.join(countries)}"

fig = px.line(df, x="year", y="value", color="iso3", markers=True, title=title)
fig.update_layout(margin=dict(l=10, r=10, t=60, b=10), legend_title_text="Country")

with tab_chart:
    st.plotly_chart(fig, use_container_width=True)
    st.caption(f"Source: World Bank API · Indicator: {indicator_code} · Years: {start_year}–{end_year}")

with tab_data:
    st.dataframe(df, use_container_width=True)

csv_buf = io.StringIO()
df.to_csv(csv_buf, index=False)
with tab_data:
    st.download_button(
        "Download CSV",
        data=csv_buf.getvalue(),
        file_name=f"macro_viz_{indicator_code}_{start_year}_{end_year}.csv",
        mime="text/csv",
    )