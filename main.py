# -*- coding: utf-8 -*-
"""
전국 고령화 단계구분도
- 연도별 고령화율 / 유소년 비율
- 시도 필터 및 확대
- 코드 기반 행정구역 매칭
- 누락 지역 회색 표시
"""

from __future__ import annotations

import io
import json
import re
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

# -------------------------------------------------------------------
# 기본 설정
# -------------------------------------------------------------------
st.set_page_config(
    page_title="AGE / 전국 인구 구조 지도",
    page_icon="◩",
    layout="wide",
    initial_sidebar_state="collapsed",
)

POPULATION_URL = (
    "https://raw.githubusercontent.com/first2022-cyber/contents//main/"
    "population_ts_yearly_gender.zip"
)
GEOJSON_URL = (
    "https://raw.githubusercontent.com/first2022-cyber/contents//main/"
    "sigungu_kr.geojson"
)

YEARS = list(range(2015, 2027))
METRIC_AGING = "고령화율 (65세 이상)"
METRIC_YOUTH = "유소년 비율 (0–14세)"

# 고령화율 단계 경계는 연도와 관계없이 고정
AGING_BOUNDS = [19, 23, 28, 38]
# 유소년 비율은 값의 범위가 더 낮아 별도 구간 사용
YOUTH_BOUNDS = [5, 8, 11, 14]

# 피카소의 기하학적 회화에서 영감을 받은 절제된 모더니즘 팔레트
AGING_COLORS = ["#F4D7B8", "#E9A36C", "#C96D4B", "#8F3D3B", "#452A3B"]
YOUTH_COLORS = ["#DCE8D5", "#AFC9A6", "#739C83", "#3D716A", "#244A50"]
MISSING_COLOR = "#D8D6D1"
INK = "#222222"
MUTED = "#6B6A67"
PAPER = "#F6F3EC"
PANEL = "#FFFEFA"
ACCENT = "#D65E43"


# -------------------------------------------------------------------
# 스타일
# -------------------------------------------------------------------
st.markdown(
    f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Noto+Sans+KR:wght@400;500;600;700;800&display=swap');
    :root {{
      --paper: {PAPER}; --panel: {PANEL}; --ink: {INK};
      --muted: {MUTED}; --accent: {ACCENT};
    }}
    html, body, [class*="css"] {{
      font-family: 'Noto Sans KR', sans-serif;
      color: var(--ink);
    }}
    .stApp {{ background: var(--paper); }}
    .block-container {{
      max-width: 1440px; padding-top: 1.7rem; padding-bottom: 3rem;
    }}
    [data-testid="stHeader"] {{ background: transparent; }}
    .hero {{
      position: relative; overflow: hidden; background: var(--panel);
      border: 1px solid #272727; padding: 1.5rem 1.7rem 1.35rem;
      margin-bottom: 1rem;
    }}
    .hero:after {{
      content: ''; position: absolute; width: 150px; height: 150px;
      right: 7%; top: -55px; border: 1px solid #272727;
      transform: rotate(45deg); border-radius: 50%;
      box-shadow: 22px 22px 0 -1px var(--panel), 22px 22px 0 0 #272727,
                  45px 45px 0 -1px var(--panel), 45px 45px 0 0 #272727;
      opacity: .75; pointer-events: none;
    }}
    .eyebrow {{
      font: 500 11px 'DM Mono', monospace; letter-spacing: .16em;
      text-transform: uppercase; color: var(--accent); margin-bottom: .65rem;
    }}
    .hero-title {{
      font-size: clamp(2rem, 4vw, 3.6rem); line-height: 1.04;
      font-weight: 800; letter-spacing: -.065em; margin: 0;
      max-width: 800px;
    }}
    .hero-sub {{
      color: var(--muted); font-size: .95rem; margin-top: .8rem;
      max-width: 740px; line-height: 1.65;
    }}
    .section-kicker {{
      font: 500 11px 'DM Mono', monospace; letter-spacing: .13em;
      color: var(--muted); text-transform: uppercase; margin: .6rem 0 .55rem;
    }}
    .metric-card {{
      background: var(--panel); border: 1px solid #292929; min-height: 136px;
      padding: 1rem 1.1rem; position: relative; overflow: hidden;
    }}
    .metric-card .label {{
      font-size: .8rem; color: var(--muted); font-weight: 600;
      letter-spacing: -.02em;
    }}
    .metric-card .value {{
      font-size: clamp(1.45rem, 2.3vw, 2.15rem); font-weight: 800;
      line-height: 1.2; letter-spacing: -.055em; margin-top: .65rem;
      overflow-wrap: anywhere;
    }}
    .metric-card .foot {{
      font: 400 10px 'DM Mono', monospace; color: var(--muted); margin-top: .6rem;
    }}
    .metric-card.orange {{ border-top: 5px solid {ACCENT}; }}
    .metric-card.olive {{ border-top: 5px solid #78936D; }}
    .metric-card.plum {{ border-top: 5px solid #68495C; }}
    .panel {{
      background: var(--panel); border: 1px solid #292929;
      padding: 1rem 1.1rem; margin-bottom: .9rem;
    }}
    .panel-title {{
      font-weight: 800; font-size: 1.05rem; letter-spacing: -.035em;
      margin: 0 0 .2rem;
    }}
    .panel-note {{ color: var(--muted); font-size: .8rem; line-height: 1.55; }}
    .geo-stamp {{
      display: inline-block; font: 500 10px 'DM Mono', monospace;
      padding: 4px 7px; border: 1px solid #292929; letter-spacing: .08em;
      margin-right: 6px;
    }}
    div[data-testid="stSelectSlider"] label,
    div[data-testid="stSelectbox"] label {{ font-weight: 700; }}
    div[data-testid="stSelectbox"] > div > div {{
      background: var(--panel); border-radius: 0; border-color: #333;
    }}
    div[data-testid="stAlert"] {{ border-radius: 0; }}
    div[data-testid="stDownloadButton"] button {{
      border-radius: 0; border: 1px solid #292929;
    }}
    hr {{ border-color: #d4d0c7; }}
    footer {{ visibility: hidden; }}
    </style>
    """,
    unsafe_allow_html=True,
)


# -------------------------------------------------------------------
# 데이터 로딩 및 정리
# -------------------------------------------------------------------
@st.cache_data(show_spinner="인구 자료를 불러오는 중…")
def load_population() -> pd.DataFrame:
    """압축 CSV ZIP을 내려받아 데이터프레임으로 읽는다."""
    response = requests.get(POPULATION_URL, timeout=90)
    response.raise_for_status()
    payload = io.BytesIO(response.content)

    # 압축 ZIP 안에 CSV가 하나인 경우 pandas가 자동으로 읽는다.
    df = pd.read_csv(payload, compression="zip", low_memory=False)
    df.columns = [str(c).strip() for c in df.columns]

    required = {"연도", "시도", "시군구", "동", "코드"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"인구 CSV에 필수 열이 없습니다: {', '.join(sorted(missing))}")

    df["연도"] = pd.to_numeric(df["연도"], errors="coerce").astype("Int64")
    # 코드는 처음부터 끝까지 문자열로 처리해 앞자리 0 및 코드 비교 오류를 방지한다.
    df["코드"] = (
        df["코드"].astype("string").str.strip()
        .str.replace(r"\.0$", "", regex=True)
        .str.replace(r"\D", "", regex=True)
        .str.zfill(10)
    )

    # 오래된 시도 코드 변경 및 군위군 코드 수정
    def remap_code(code: Any) -> str:
        value = str(code).strip()
        if value.endswith("<NA>") or value == "nan":
            return ""
        if len(value) < 5:
            value = value.zfill(10)
        prefix = value[:2]
        if prefix == "42":
            value = "51" + value[2:]
        elif prefix == "45":
            value = "52" + value[2:]
        if value[:5] == "47720":
            value = "27720" + value[5:]
        return value

    df["코드"] = df["코드"].map(remap_code)
    age_columns = [c for c in df.columns if c.startswith("계_")]
    if not age_columns:
        raise ValueError("'계_'로 시작하는 연령별 인구 열을 찾지 못했습니다.")

    for col in age_columns:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    def age_number(label: str) -> int | None:
        match = re.search(r"계_(\d+)세", label)
        if match:
            return int(match.group(1))
        if "100세 이상" in label:
            return 100
        return None

    age_by_column = {c: age_number(c) for c in age_columns}
    elderly_cols = [c for c, age in age_by_column.items() if age is not None and age >= 65]
    youth_cols = [c for c, age in age_by_column.items() if age is not None and 0 <= age <= 14]

    if not elderly_cols:
        raise ValueError("65세 이상 인구 열(계_65세~계_100세 이상)을 찾지 못했습니다.")
    if not youth_cols:
        raise ValueError("0~14세 인구 열을 찾지 못했습니다.")

    # 전체 인구는 '계_' 열만 합산하고 남/여 열은 사용하지 않는다.
    df["전체인구"] = df[age_columns].sum(axis=1)
    df["65세이상"] = df[elderly_cols].sum(axis=1)
    df["0_14세"] = df[youth_cols].sum(axis=1)
    df["시군구코드"] = df["코드"].str[:5]

    # 시군구 단위로 합산. 시군구 명칭이 아니라 코드로 결합한다.
    grouped = (
        df.groupby(["연도", "시군구코드"], as_index=False, dropna=False)
        .agg(전체인구=("전체인구", "sum"),
             고령인구=("65세이상", "sum"),
             유소년인구=("0_14세", "sum"))
    )
    grouped["고령화율"] = grouped["고령인구"].div(grouped["전체인구"].replace(0, pd.NA)) * 100
    grouped["유소년비율"] = grouped["유소년인구"].div(grouped["전체인구"].replace(0, pd.NA)) * 100
    return grouped


@st.cache_data(show_spinner="시군구 경계 지도를 불러오는 중…")
def load_geojson() -> dict:
    response = requests.get(GEOJSON_URL, timeout=90)
    response.raise_for_status()
    geo = response.json()
    if not isinstance(geo, dict) or "features" not in geo:
        raise ValueError("시군구 GeoJSON 형식이 올바르지 않습니다.")

    # 코드 필드는 문자열로 통일. 지오메트리는 변경하지 않는다.
    for feature in geo["features"]:
        props = feature.setdefault("properties", {})
        code = str(props.get("코드", "")).strip()
        code = re.sub(r"\.0$", "", code)
        code = re.sub(r"\D", "", code)
        props["코드"] = code.zfill(5) if code else ""
        props["시군구"] = str(props.get("시군구", "")).strip()
        props["시도"] = str(props.get("시도", "")).strip()
    return geo


def make_bins(metric: str) -> tuple[list[float], list[str], list[str]]:
    if metric == METRIC_AGING:
        bounds = AGING_BOUNDS
        colors = AGING_COLORS
        labels = ["≤ 19%", "19–23%", "23–28%", "28–38%", "≥ 38%"]
    else:
        bounds = YOUTH_BOUNDS
        colors = YOUTH_COLORS
        labels = ["≤ 5%", "5–8%", "8–11%", "11–14%", "≥ 14%"]
    return bounds, labels, colors


def class_index(value: float, bounds: list[float]) -> int:
    for i, boundary in enumerate(bounds):
        if value < boundary:
            return i
    return len(bounds)


def format_rate(value: Any) -> str:
    if pd.isna(value):
        return "자료 없음"
    return f"{float(value):.2f}%"


def build_map(
    geojson: dict,
    year_data: pd.DataFrame,
    selected_province: str,
    metric: str,
) -> tuple[go.Figure, list[str]]:
    """코드로 경계를 연결하고, 누락 지역은 별도 회색 trace로 표시한다."""
    bounds, labels, colors = make_bins(metric)
    value_col = "고령화율" if metric == METRIC_AGING else "유소년비율"
    rate_by_code = dict(zip(year_data["시군구코드"].astype(str), year_data[value_col]))

    features = geojson["features"]
    if selected_province != "전국":
        features = [
            f for f in features
            if str(f.get("properties", {}).get("시도", "")).strip() == selected_province
        ]

    matched_features = []
    missing_features = []
    missing_codes = []
    locations, z_values, hover_text = [], [], []

    for feature in features:
        props = feature.get("properties", {})
        code = str(props.get("코드", "")).strip().zfill(5)
        name = str(props.get("시군구", "")).strip() or "이름 미상"
        rate = rate_by_code.get(code)

        if rate is None or pd.isna(rate):
            missing_features.append(feature)
            missing_codes.append(f"{name} ({code})")
            continue

        matched_features.append(feature)
        locations.append(code)
        z_values.append(class_index(float(rate), bounds))
        hover_text.append(
            f"<b>{name}</b><br>{metric}: {float(rate):.2f}%<br>"
            f"코드: {code}<br>연도: {int(year_data['연도'].iloc[0]) if not year_data.empty else '—'}"
        )

    fig = go.Figure()

    if matched_features:
        matched_geo = {"type": "FeatureCollection", "features": matched_features}
        n = len(colors)
        # 각 구간을 고정 색으로 표시하는 계단형 colorscale
        scale = []
        for i, color in enumerate(colors):
            left = i / n
            right = (i + 1) / n
            scale.extend([[left, color], [right, color]])
        fig.add_trace(go.Choropleth(
            geojson=matched_geo,
            featureidkey="properties.코드",
            locations=locations,
            z=z_values,
            text=hover_text,
            hovertemplate="%{text}<extra></extra>",
            colorscale=scale,
            zmin=0,
            zmax=n - 1,
            marker_line_color="#F6F3EC",
            marker_line_width=0.65,
            showscale=False,
            name="지표 값",
        ))

    if missing_features:
        missing_geo = {"type": "FeatureCollection", "features": missing_features}
        missing_locations = [
            str(f.get("properties", {}).get("코드", "")).strip().zfill(5)
            for f in missing_features
        ]
        missing_text = [
            f"<b>{str(f.get('properties', {}).get('시군구', '이름 미상'))}</b>"
            f"<br>자료 없음 · 경계 코드 불일치"
            f"<br>코드: {code}"
            for f, code in zip(missing_features, missing_locations)
        ]
        fig.add_trace(go.Choropleth(
            geojson=missing_geo,
            featureidkey="properties.코드",
            locations=missing_locations,
            z=[0] * len(missing_locations),
            text=missing_text,
            hovertemplate="%{text}<extra></extra>",
            colorscale=[[0, MISSING_COLOR], [1, MISSING_COLOR]],
            zmin=0,
            zmax=1,
            marker_line_color="#FFFFFF",
            marker_line_width=0.65,
            showscale=False,
            name="자료 없음",
        ))

    fig.update_geos(
        visible=False,
        fitbounds="locations",
        showcountries=False,
        showcoastlines=False,
        showland=False,
        showframe=False,
        bgcolor=PAPER,
    )
    fig.update_layout(
        paper_bgcolor=PAPER,
        plot_bgcolor=PAPER,
        margin=dict(l=0, r=0, t=0, b=0),
        height=650 if selected_province == "전국" else 700,
        showlegend=False,
        dragmode=False,
        hoverlabel=dict(
            bgcolor="#FFFEFA",
            bordercolor="#252525",
            font=dict(family="Noto Sans KR", size=13, color="#222222"),
            align="left",
        ),
    )
    return fig, missing_codes


def metric_card(label: str, value: str, foot: str, tone: str) -> str:
    return f"""
    <div class="metric-card {tone}">
      <div class="label">{label}</div>
      <div class="value">{value}</div>
      <div class="foot">{foot}</div>
    </div>
    """


# -------------------------------------------------------------------
# 앱 본문
# -------------------------------------------------------------------
st.markdown(
    """
    <div class="hero">
      <div class="eyebrow">POPULATION ATLAS / KOREA · 2015—2026</div>
      <h1 class="hero-title">나이로 읽는<br>대한민국의 지도.</h1>
      <div class="hero-sub">
        시군구 단위 인구 구조를 지도 위에 펼쳐 봅니다.
        연도를 바꾸고 지표를 전환해 지역마다 다른 인구의 흐름을 비교하세요.
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

try:
    population = load_population()
    geojson = load_geojson()
except Exception as exc:
    st.error("데이터를 불러오지 못했습니다. 잠시 후 다시 시도하거나 앱 로그를 확인해 주세요.")
    with st.expander("오류 세부 정보"):
        st.code(str(exc))
    st.stop()

years_available = sorted(
    int(y) for y in population["연도"].dropna().unique()
    if 2015 <= int(y) <= 2026
)
if not years_available:
    st.error("2015~2026년 데이터가 없습니다.")
    st.stop()

# 기본 연도는 2026년, 데이터가 없다면 가장 최근 연도
default_year = 2026 if 2026 in years_available else max(years_available)

control1, control2, control3 = st.columns([1.05, 1.1, 1.25], gap="medium")
with control1:
    year = st.select_slider(
        "기준 연도",
        options=years_available,
        value=default_year,
        format_func=lambda y: f"{y}년",
        help="연도를 바꾸면 해당 연도의 인구 자료로 지도가 다시 계산됩니다.",
    )
with control2:
    metric = st.selectbox(
        "지도 지표",
        [METRIC_AGING, METRIC_YOUTH],
        index=0,
    )
with control3:
    provinces = sorted({
        str(f.get("properties", {}).get("시도", "")).strip()
        for f in geojson["features"]
        if str(f.get("properties", {}).get("시도", "")).strip()
    })
    province = st.selectbox("표시 지역", ["전국"] + provinces, index=0)

year_data = population.loc[population["연도"].astype("Int64") == int(year)].copy()
if year_data.empty:
    st.warning(f"{year}년 인구 자료가 없습니다.")
    st.stop()

value_col = "고령화율" if metric == METRIC_AGING else "유소년비율"
total_population = float(year_data["전체인구"].sum())
total_metric_population = float(
    year_data["고령인구" if metric == METRIC_AGING else "유소년인구"].sum()
)
national_rate = (
    total_metric_population / total_population * 100
    if total_population > 0 else float("nan")
)

# 시군구 지도 경계 코드와 맞는 자료만 최고·최저 산정에 사용한다.
geo_codes = {
    str(f.get("properties", {}).get("코드", "")).strip().zfill(5)
    for f in geojson["features"]
}
rank_data = year_data.loc[
    year_data["시군구코드"].astype(str).isin(geo_codes)
    & year_data[value_col].notna()
].copy()
if province != "전국":
    province_codes = {
        str(f.get("properties", {}).get("코드", "")).strip().zfill(5)
        for f in geojson["features"]
        if str(f.get("properties", {}).get("시도", "")).strip() == province
    }
    rank_data = rank_data.loc[rank_data["시군구코드"].astype(str).isin(province_codes)]

name_lookup = {}
for f in geojson["features"]:
    props = f.get("properties", {})
    name_lookup[str(props.get("코드", "")).strip().zfill(5)] = str(
        props.get("시군구", "이름 미상")
    ).strip()

if not rank_data.empty:
    high = rank_data.loc[rank_data[value_col].idxmax()]
    low = rank_data.loc[rank_data[value_col].idxmin()]
    high_name = name_lookup.get(str(high["시군구코드"]), str(high["시군구코드"]))
    low_name = name_lookup.get(str(low["시군구코드"]), str(low["시군구코드"]))
    high_value = format_rate(high[value_col])
    low_value = format_rate(low[value_col])
else:
    high_name, low_name, high_value, low_value = "자료 없음", "자료 없음", "—", "—"

st.markdown('<div class="section-kicker">01 / SNAPSHOT</div>', unsafe_allow_html=True)
c1, c2, c3 = st.columns(3, gap="medium")
c1.markdown(
    metric_card(
        f"{year}년 전국 {metric}",
        format_rate(national_rate),
        "전체 인구 합계 기준 가중 비율",
        "orange",
    ),
    unsafe_allow_html=True,
)
c2.markdown(
    metric_card(
        "가장 높은 시군구",
        high_name,
        high_value + " · " + ("선택 시도" if province != "전국" else "전국"),
        "plum",
    ),
    unsafe_allow_html=True,
)
c3.markdown(
    metric_card(
        "가장 낮은 시군구",
        low_name,
        low_value + " · " + ("선택 시도" if province != "전국" else "전국"),
        "olive",
    ),
    unsafe_allow_html=True,
)

st.markdown('<div class="section-kicker">02 / CHOROPLETH</div>', unsafe_allow_html=True)
map_title = f"{province} · {year}년 {metric}" if province != "전국" else f"대한민국 · {year}년 {metric}"
st.markdown(
    f"""
    <div class="panel">
      <span class="geo-stamp">{year} / JUNE</span>
      <span class="geo-stamp">SIGUNGU · CODE JOIN</span>
      <div class="panel-title" style="font-size:1.35rem;margin-top:.8rem">{map_title}</div>
      <div class="panel-note">경계 코드를 기준으로 연결했습니다. 지도에 마우스를 올리면 지역명과 비율을 확인할 수 있습니다.</div>
    </div>
    """,
    unsafe_allow_html=True,
)

fig, missing_codes = build_map(geojson, year_data, province, metric)
st.plotly_chart(fig, use_container_width=True, config={
    "displayModeBar": False,
    "scrollZoom": False,
    "responsive": True,
})

bounds, bin_labels, bin_colors = make_bins(metric)
legend_cols = st.columns([1, 1, 1, 1, 1, 1.2], gap="small")
for i, (label, color) in enumerate(zip(bin_labels, bin_colors)):
    with legend_cols[i]:
        st.markdown(
            f"""
            <div style="display:flex;align-items:center;gap:7px;font-size:.76rem;
                        font-family:'DM Mono',monospace;margin-bottom:.4rem">
              <span style="display:inline-block;width:17px;height:17px;background:{color};
                           border:1px solid #333;flex-shrink:0"></span>{label}
            </div>
            """,
            unsafe_allow_html=True,
        )
with legend_cols[5]:
    st.markdown(
        f"""
        <div style="display:flex;align-items:center;gap:7px;font-size:.76rem;
                    font-family:'DM Mono',monospace">
          <span style="display:inline-block;width:17px;height:17px;background:{MISSING_COLOR};
                       border:1px solid #333;flex-shrink:0"></span>자료 없음
        </div>
        """,
        unsafe_allow_html=True,
    )

if missing_codes:
    st.warning(
        f"경계 코드와 인구 데이터 코드가 일치하지 않아 {len(missing_codes)}개 지역을 회색으로 표시했습니다. "
        "연도별 행정구역 개편 등으로 발생할 수 있습니다."
    )
    with st.expander("코드가 일치하지 않은 지역 확인"):
        st.write(" · ".join(missing_codes))
else:
    st.caption("현재 표시 범위에서 경계 코드가 일치하지 않는 지역이 없습니다.")

st.markdown('<div class="section-kicker">03 / DATA TABLE</div>', unsafe_allow_html=True)
with st.expander("시군구별 지표 표 보기", expanded=False):
    table = year_data.copy()
    table["시군구명"] = table["시군구코드"].map(name_lookup).fillna("경계 자료 없음")
    table = table.rename(columns={
        "시군구코드": "시군구 코드",
        "전체인구": "전체 인구",
        "고령인구": "65세 이상 인구",
        "유소년인구": "0~14세 인구",
        "고령화율": "고령화율 (%)",
        "유소년비율": "유소년 비율 (%)",
    })
    if province != "전국":
        valid_codes = {
            str(f.get("properties", {}).get("코드", "")).strip().zfill(5)
            for f in geojson["features"]
            if str(f.get("properties", {}).get("시도", "")).strip() == province
        }
        table = table.loc[table["시군구 코드"].astype(str).isin(valid_codes)]
    show_cols = [
        "시군구명", "시군구 코드", "전체 인구", "65세 이상 인구",
        "고령화율 (%)", "0~14세 인구", "유소년 비율 (%)",
    ]
    table = table[show_cols].sort_values("고령화율 (%)", ascending=False)
    st.dataframe(
        table,
        use_container_width=True,
        hide_index=True,
        column_config={
            "전체 인구": st.column_config.NumberColumn(format="%d"),
            "65세 이상 인구": st.column_config.NumberColumn(format="%d"),
            "0~14세 인구": st.column_config.NumberColumn(format="%d"),
            "고령화율 (%)": st.column_config.NumberColumn(format="%.2f%%"),
            "유소년 비율 (%)": st.column_config.NumberColumn(format="%.2f%%"),
        },
    )
    csv = table.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "표를 CSV로 내려받기",
        data=csv,
        file_name=f"시군구_인구지표_{year}.csv",
        mime="text/csv",
    )

st.markdown("---")
st.markdown(
    f"""
    <div style="display:flex;justify-content:space-between;gap:1rem;flex-wrap:wrap;
                color:{MUTED};font-size:.75rem;line-height:1.6">
      <span>DATA / 읍·면·동 인구 CSV · 시군구 경계 GeoJSON</span>
      <span>METHOD / 코드 앞 5자리 집계 · 비율은 인구 합계 기준</span>
      <span>AGE ATLAS — {year}</span>
    </div>
    """,
    unsafe_allow_html=True,
)
