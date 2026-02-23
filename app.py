import io
import re
from typing import Dict, List, Optional, Tuple

import pandas as pd
import plotly.express as px
import requests
import streamlit as st
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

INDICATORS: Dict[str, str] = {
    "GDP (current US$)": "NY.GDP.MKTP.CD",
    "GDP per capita (current US$)": "NY.GDP.PCAP.CD",
    "Population": "SP.POP.TOTL",
    "Inflation (CPI, annual %)": "FP.CPI.TOTL.ZG",
    "Unemployment (%)": "SL.UEM.TOTL.ZS",
    "CO₂ emissions (kt)": "EN.ATM.CO2E.KT",
    "Exports (% of GDP)": "NE.EXP.GNFS.ZS",
    "Imports (% of GDP)": "NE.IMP.GNFS.ZS",
}

DEFAULT_ISO3 = ["USA", "DEU", "BRA"]


def make_session() -> requests.Session:
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def parse_iso3_codes(raw: str) -> Tuple[List[str], Optional[str]]:
    countries = [c.strip().upper() for c in raw.split(",") if c.strip()]
    if not countries:
        return [], "Please enter at least one ISO3 country code."
    if len(countries) > 8:
        return [], "Please provide at most 8 country codes."
    invalid = [c for c in countries if not re.fullmatch(r"[A-Z]{3}", c)]
    if invalid:
        return [], f"Invalid ISO3 code(s): {', '.join(invalid)}. Use exactly 3 letters (A-Z)."
    return countries, None


def get_scale(max_value: float, auto_scale: bool) -> Tuple[float, str]:
    if not auto_scale or pd.isna(max_value):
        return 1.0, "raw"
    if max_value >= 1e12:
        return 1e12, "trillions"
    if max_value >= 1e9:
        return 1e9, "billions"
    if max_value >= 1e6:
        return 1e6, "millions"
    if max_value >= 1e3:
        return 1e3, "thousands"
    return 1.0, "raw"


@st.cache_data(ttl=12 * 60 * 60)
def get_country_catalog() -> pd.DataFrame:
    session = make_session()
    url = "https://api.worldbank.org/v2/country?format=json&per_page=400"
    response = session.get(url, timeout=20)
    response.raise_for_status()
    payload = response.json()

    records = []
    if isinstance(payload, list) and len(payload) > 1 and payload[1]:
        for item in payload[1]:
            iso3 = item.get("id", "")
            region = item.get("region", {}).get("value", "")
            name = item.get("name", "")
            if region != "Aggregates" and re.fullmatch(r"[A-Z]{3}", iso3):
                records.append({"iso3": iso3, "country": name})

    df = pd.DataFrame(records).drop_duplicates(subset=["iso3"]).sort_values("country")
    return df.reset_index(drop=True)


def build_country_indicator_url(iso3: str, indicator_code: str, start_year: int, end_year: int) -> str:
    return (
        f"https://api.worldbank.org/v2/country/{iso3}/indicator/{indicator_code}"
        f"?format=json&per_page=2000&date={start_year}:{end_year}"
    )


def build_global_indicator_url(indicator_code: str, year: int) -> str:
    return (
        f"https://api.worldbank.org/v2/country/all/indicator/{indicator_code}"
        f"?format=json&per_page=20000&date={year}:{year}"
    )


def fetch_country_data(
    session: requests.Session, iso3: str, indicator_name: str, indicator_code: str, start_year: int, end_year: int
) -> Tuple[pd.DataFrame, str, Optional[str]]:
    api_url = build_country_indicator_url(iso3, indicator_code, start_year, end_year)
    try:
        response = session.get(api_url, timeout=20)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        return pd.DataFrame(), api_url, f"request failed ({exc})"
    except ValueError:
        return pd.DataFrame(), api_url, "received non-JSON response"

    if not isinstance(payload, list) or len(payload) < 2 or payload[1] is None:
        return pd.DataFrame(), api_url, "no data returned"

    rows = []
    for item in payload[1]:
        try:
            year = int(item.get("date")) if item.get("date") is not None else None
        except (TypeError, ValueError):
            year = None

        rows.append(
            {
                "iso3": iso3,
                "country": item.get("country", {}).get("value", iso3),
                "year": year,
                "value": item.get("value"),
                "indicator": indicator_name,
                "api_url": api_url,
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(), api_url, "no rows parsed"

    df = df.dropna(subset=["year", "value"]).copy()
    if df.empty:
        return pd.DataFrame(), api_url, "all values missing for selected range"

    return df.sort_values("year").reset_index(drop=True), api_url, None


@st.cache_data(ttl=12 * 60 * 60)
def fetch_global_year_data(indicator_name: str, indicator_code: str, year: int) -> Tuple[pd.DataFrame, str, Optional[str]]:
    session = make_session()
    api_url = build_global_indicator_url(indicator_code, year)
    try:
        response = session.get(api_url, timeout=30)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        return pd.DataFrame(), api_url, f"request failed ({exc})"
    except ValueError:
        return pd.DataFrame(), api_url, "received non-JSON response"

    if not isinstance(payload, list) or len(payload) < 2 or payload[1] is None:
        return pd.DataFrame(), api_url, "no data returned"

    rows = []
    for item in payload[1]:
        iso3 = item.get("countryiso3code")
        value = item.get("value")
        if not re.fullmatch(r"[A-Z]{3}", str(iso3 or "")):
            continue
        if value is None:
            continue
        rows.append(
            {
                "iso3": iso3,
                "country": item.get("country", {}).get("value", iso3),
                "year": year,
                "value": value,
                "indicator": indicator_name,
                "api_url": api_url,
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(), api_url, "no usable values"
    return df, api_url, None


def render_app() -> None:
    st.set_page_config(page_title="MacroViz Tool v0.3", layout="wide")
    st.title("MacroViz Tool v0.3")
    st.caption("World Bank API · Charts + Map")

    try:
        country_catalog = get_country_catalog()
    except Exception as exc:
        st.error(f"Could not load country list from World Bank API: {exc}")
        st.stop()

    name_to_iso = {row["country"]: row["iso3"] for _, row in country_catalog.iterrows()}
    iso_to_name = {row["iso3"]: row["country"] for _, row in country_catalog.iterrows()}

    default_names = [iso_to_name[i] for i in DEFAULT_ISO3 if i in iso_to_name]

    with st.sidebar:
        st.header("Inputs")
        selected_country_names = st.multiselect(
            "Countries",
            options=country_catalog["country"].tolist(),
            default=default_names,
            max_selections=8,
            help="Choose up to 8 countries by name.",
        )
        indicator_name = st.selectbox("Indicator", list(INDICATORS.keys()), index=0)
        start_year, end_year = st.slider("Year range", 1960, 2026, (1995, 2023))
        auto_scale = st.toggle("Auto-scale units (K/M/B/T)", value=True)

        with st.expander("Advanced"):
            manual_iso_input = st.text_input(
                "Manual ISO3 override (comma-separated)",
                value="",
                help="If provided, this overrides the country dropdown.",
            )

        run_query = st.button("Generate", type="primary")

    chart_tab, map_tab, data_tab, about_tab = st.tabs(["Chart", "Map", "Data", "About / Source"])

    if not run_query:
        with chart_tab:
            st.info("Select countries and click **Generate**.")
        return

    selected_iso = [name_to_iso[name] for name in selected_country_names if name in name_to_iso]

    if manual_iso_input.strip():
        selected_iso, err = parse_iso3_codes(manual_iso_input)
        if err:
            with chart_tab:
                st.warning(err)
            with map_tab:
                st.warning(err)
            return

    if not selected_iso:
        with chart_tab:
            st.warning("Please select at least one country.")
        return

    indicator_code = INDICATORS[indicator_name]
    session = make_session()

    all_frames: List[pd.DataFrame] = []
    failed: List[str] = []
    urls_used: List[str] = []

    for iso3 in selected_iso:
        df, url, err = fetch_country_data(session, iso3, indicator_name, indicator_code, start_year, end_year)
        urls_used.append(url)
        if err or df.empty:
            failed.append(f"{iso3} ({err or 'no data'})")
        else:
            all_frames.append(df)

    if failed:
        with chart_tab:
            st.warning("Some countries failed or returned no data: " + "; ".join(failed))

    if not all_frames:
        with chart_tab:
            st.error("No usable data returned for your request.")
            st.code("\n".join(urls_used), language="text")
        with map_tab:
            st.error("Map unavailable because no chart data could be loaded.")
        with about_tab:
            st.markdown("**Source URLs used**")
            st.code("\n".join(urls_used), language="text")
        return

    data = pd.concat(all_frames, ignore_index=True)
    max_value = data["value"].abs().max()
    scale, scale_label = get_scale(max_value, auto_scale)
    data["value_display"] = data["value"] / scale
    data["unit_scale"] = scale_label

    title_countries = ", ".join(sorted(data["country"].unique()))
    y_axis_title = indicator_name if scale_label == "raw" else f"{indicator_name} ({scale_label})"

    fig = px.line(
        data,
        x="year",
        y="value_display",
        color="country",
        title=f"{indicator_name} — {title_countries}",
    )
    fig.update_layout(template="simple_white", legend_title_text="Country", hovermode="x unified")
    fig.update_yaxes(title=y_axis_title, tickformat=",.2f")
    fig.update_xaxes(title="Year", tickformat="d")

    csv_cols = ["iso3", "country", "year", "value", "indicator", "unit_scale"]
    csv_data = data[csv_cols].sort_values(["country", "year"]) if set(csv_cols).issubset(data.columns) else data

    with chart_tab:
        st.plotly_chart(fig, use_container_width=True)
        st.caption(f"Source: World Bank API | Indicator code: {indicator_code}")

        csv_buffer = io.StringIO()
        csv_data.to_csv(csv_buffer, index=False)
        st.download_button(
            "Download CSV",
            data=csv_buffer.getvalue(),
            file_name=f"macroviz_{indicator_code}_{start_year}_{end_year}.csv",
            mime="text/csv",
        )

        html_str = fig.to_html(full_html=False, include_plotlyjs="cdn")
        st.download_button(
            "Download Chart (HTML interactive)",
            data=html_str,
            file_name=f"macroviz_{indicator_code}_{start_year}_{end_year}.html",
            mime="text/html",
        )

    with map_tab:
        available_years = sorted(data["year"].dropna().astype(int).unique().tolist())
        default_map_year = end_year if end_year in available_years else available_years[-1]
        map_year = st.selectbox("Map year", options=available_years, index=available_years.index(default_map_year))
        map_mode = st.radio("Map mode", ["Global map", "Selected only"], horizontal=True)

        map_df = pd.DataFrame()
        map_urls = []

        if map_mode == "Global map":
            with st.spinner("Loading global map values from World Bank API..."):
                global_df, global_url, global_err = fetch_global_year_data(indicator_name, indicator_code, int(map_year))
            map_urls.append(global_url)
            if global_err or global_df.empty:
                st.warning("Global map fetch failed or returned no data. Falling back to selected countries only.")
                map_mode = "Selected only"
            else:
                map_df = global_df.copy()

        if map_mode == "Selected only":
            map_df = data.loc[data["year"] == int(map_year), ["iso3", "country", "year", "value", "indicator"]].copy()
            map_urls.extend(urls_used)

        if map_df.empty:
            st.warning("No map data available for the selected year.")
            st.code("\n".join(map_urls), language="text")
        else:
            m_scale, _ = get_scale(map_df["value"].abs().max(), auto_scale)
            map_df["value_display"] = map_df["value"] / m_scale
            map_fig = px.choropleth(
                map_df,
                locations="iso3",
                locationmode="ISO-3",
                color="value_display",
                hover_name="country",
                hover_data={"iso3": True, "value": ":,.2f", "value_display": False},
                projection="natural earth",
                title=f"{indicator_name} map ({map_year})",
                color_continuous_scale="Blues",
            )
            map_fig.update_layout(template="simple_white", margin=dict(l=10, r=10, t=60, b=10))
            st.plotly_chart(map_fig, use_container_width=True)

    with data_tab:
        st.dataframe(csv_data, use_container_width=True)

    with about_tab:
        st.markdown("**Source**: World Bank Open Data API")
        st.write("Sample API URLs used:")
        st.code("\n".join(urls_used[:2]), language="text")
        st.write("Map mode: Global map tries all countries in one API call; on failure it auto-falls back to Selected only.")
        st.write("Limitations: World Bank source only in v0.3.")


if __name__ == "__main__":
    try:
        render_app()
    except Exception as exc:
        st.error(f"Unexpected application error: {exc}")
        st.info("Please revise inputs and try again.")
