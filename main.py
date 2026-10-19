# main.py — 전국 고령화 단계구분도
# Streamlit Cloud 배포용. Streamlit / pandas / numpy는 기본 설치 환경으로 간주한다.

import re
from collections import defaultdict

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

# -----------------------------------------------------------------------------
# 페이지와 모던 기하학 UI
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="KOREA / 인구 구조 아틀라스",
    page_icon="◩",
    layout="wide",
    initial_sidebar_state="collapsed",
)

BG = "#F4F0E7"
PAPER = "#FFFCF5"
INK = "#202321"
MUTED = "#6F716D"
LINE = "#D8D2C6"
RED = "#D94A35"
BLUE = "#3159A5"
YELLOW = "#E7B83F"

st.markdown(
f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Noto+Sans+KR:wght@400;500;600;700;800&display=swap');
:root {{ --bg:{BG}; --paper:{PAPER}; --ink:{INK}; --muted:{MUTED}; --line:{LINE}; }}
.stApp {{ background:var(--bg); color:var(--ink); font-family:'Noto Sans KR',sans-serif; }}
.block-container {{ max-width:1500px; padding-top:1.5rem; padding-bottom:3rem; }}
header[data-testid="stHeader"] {{ background:transparent; }}
#MainMenu, footer {{ visibility:hidden; }}
.hero {{ position:relative; overflow:hidden; background:var(--paper); border:1px solid var(--line); padding:28px 30px 24px; margin-bottom:18px; }}
.eyebrow {{ font:500 11px 'DM Mono',monospace; letter-spacing:.18em; color:var(--muted); text-transform:uppercase; }}
.hero-title {{ font-size:clamp(2rem,4vw,3.7rem); line-height:1.03; font-weight:800; letter-spacing:-.065em; margin:13px 0 10px; max-width:850px; }}
.hero-sub {{ font-size:14px; color:var(--muted); line-height:1.7; max-width:700px; }}
.hero-shapes {{ position:absolute; right:4%; top:12%; width:205px; height:145px; pointer-events:none; }}
.shape-circle {{ position:absolute; width:86px; height:86px; border-radius:50%; background:{RED}; right:3px; top:4px; }}
.shape-square {{ position:absolute; width:77px; height:77px; background:{YELLOW}; transform:rotate(19deg); left:10px; bottom:2px; }}
.shape-triangle {{ position:absolute; width:0;height:0;border-left:38px solid transparent;border-right:38px solid transparent;border-bottom:72px solid {BLUE}; left:76px; top:20px; transform:rotate(-16deg); }}
.section-kicker {{ font:500 11px 'DM Mono',monospace; letter-spacing:.16em; color:var(--muted); margin:20px 0 8px; }}
.metric-card {{ height:100%; min-height:125px; padding:17px 18px 15px; background:var(--paper); border:1px solid var(--line); position:relative; }}
.metric-card:before {{ content:''; position:absolute; left:0; top:0; width:5px; height:100%; background:{RED}; }}
.metric-card.blue:before {{ background:{BLUE}; }} .metric-card.yellow:before {{ background:{YELLOW}; }}
.metric-label {{ font-size:12px; color:var(--muted); margin-bottom:14px; }}
.metric-value {{ font-size:clamp(1.5rem,2.7vw,2.35rem); font-weight:800; letter-spacing:-.06em; line-height:1.1; }}
.metric-foot {{ font:11px 'DM Mono',monospace; color:var(--muted); margin-top:9px; }}
.panel {{ background:var(--paper); border:1px solid var(--line); padding:18px 20px; }}
.note {{ font-size:12px; color:var(--muted); line-height:1.7; }}
.legend-wrap {{ display:flex; flex-wrap:wrap; gap:8px 15px; align-items:center; margin:5px 0 13px; }}
.legend-item {{ display:flex; align-items:center; gap:6px; font-size:12px; color:var(--ink); }}
.swatch {{ width:19px; height:12px; border:1px solid rgba(0,0,0,.12); display:inline-block; }}
.stSelectbox label, .stSlider label {{ font-weight:700 !important; color:var(--ink) !important; }}
div[data-baseweb="select"] > div {{ background:var(--paper); border-color:var(--line); border-radius:2px; }}
.stSlider [data-baseweb="slider"] {{ padding-top:7px; }}
.stButton button {{ border-radius:2px; border:1px solid var(--ink); background:var(--ink); color:white; }}
hr {{ border-color:var(--line); }}
@media(max-width:800px) {{ .hero-shapes {{ opacity:.24; right:-25px; }} .hero {{ padding:22px 18px; }} }}
</style>
<div class="hero">
  <div class="eyebrow">POPULATION ATLAS / REPUBLIC OF KOREA</div>
  <div class="hero-title">인구 구조를 읽는<br>전국 단계구분도<span style="color:{RED}">.</span></div>
  <div class="hero-sub">행정구역별 연령 구조를 같은 기준으로 비교합니다. 연도와 지표를 바꾸며 지역 간 인구 변화를 살펴보세요.</div>
  <div class="hero-shapes"><div class="shape-square"></div><div class="shape-triangle"></div><div class="shape-circle"></div></div>
</div>
""", unsafe_allow_html=True)

DATA_URL = "https://raw.githubusercontent.com/first2022-cyber/contents//main/population_ts_yearly_gender.zip"
GEOJSON_URL = "https://raw.githubusercontent.com/first2022-cyber/contents//main/sigungu_kr.geojson"

# 고령화율은 요청된 구간을 연도마다 고정한다.
METRICS = {
    "고령화율 (65세 이상)": {
        "column": "elderly_pct",
        "numerator": "elderly",
        "thresholds": [19, 23, 28, 38],
        "labels": ["19% 미만", "19–23%", "23–28%", "28–38%", "38% 이상"],
        "colors": ["#F7DCCB", "#EFA98C", "#E8795F", "#C94835", "#792C2A"],
        "short": "고령화율",
    },
    "유소년 비율 (0–14세)": {
        "column": "youth_pct",
        "numerator": "youth",
        "thresholds": [5, 8, 11, 14],
        "labels": ["5% 미만", "5–8%", "8–11%", "11–14%", "14% 이상"],
        "colors": ["#DCE7F8", "#AFC7EE", "#789DD9", "#426DB7", "#233F7C"],
        "short": "유소년 비율",
    },
}


def normalize_code(value):
    """코드를 숫자로 변환하지 않고 문자열로 정규화해 앞자리 0을 보존한다."""
    if value is None or pd.isna(value):
        return ""
    s = str(value).strip()
    if s.endswith(".0"):
        s = s[:-2]
    digits = re.sub(r"\D", "", s)
    if not digits:
        return ""
    return digits.zfill(5)[:5]


def normalize_population_code(value):
    """인구 CSV의 옛 행정구역 코드를 현재 시군구 코드에 맞춘다."""
    code = normalize_code(value)
    if len(code) != 5:
        return ""
    if code == "47720":  # 군위군: 경북에서 대구로 편입
        return "27720"
    if code.startswith("42"):  # 옛 강원도 코드 -> 강원특별자치도
        return "51" + code[2:]
    if code.startswith("45"):  # 옛 전라북도 코드 -> 전북특별자치도
        return "52" + code[2:]
    return code


@st.cache_data(ttl=3600, show_spinner="인구 자료를 불러오는 중…")
def load_population():
    """압축 CSV를 읽고 모든 연도의 시군구별 지표를 미리 계산한다."""
    last_error = None
    df = None
    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            df = pd.read_csv(
                DATA_URL,
                compression="zip",
                encoding=encoding,
                dtype={"코드": "string"},
                low_memory=False,
            )
            break
        except Exception as exc:
            last_error = exc
    if df is None:
        raise RuntimeError(f"인구 ZIP CSV를 읽지 못했습니다: {last_error}")

    df.columns = [str(c).strip() for c in df.columns]
    required = ["연도", "시도", "시군구", "동", "코드"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"인구 자료에 필수 열이 없습니다: {', '.join(missing)}")

    df["연도"] = pd.to_numeric(df["연도"], errors="coerce")
    df = df.dropna(subset=["연도"]).copy()
    df["연도"] = df["연도"].astype(int)
    df["구코드"] = df["코드"].map(normalize_population_code)

    age_cols = [c for c in df.columns if c.startswith("계_")]
    if not age_cols:
        raise ValueError("'계_0세', '계_1세' 형식의 연령별 인구 열을 찾지 못했습니다.")

    def age_from_column(column):
        match = re.search(r"계_(\d+)세", column)
        return int(match.group(1)) if match else None

    ages = {c: age_from_column(c) for c in age_cols}
    elderly_cols = [c for c, age in ages.items() if age is not None and age >= 65]
    youth_cols = [c for c, age in ages.items() if age is not None and 0 <= age <= 14]
    if not elderly_cols or not youth_cols:
        raise ValueError("고령·유소년 인구 열을 찾지 못했습니다. 연령 열 이름을 확인해 주세요.")

    # 남_·여_ 열은 합산하지 않고 '계_' 연령 열만 숫자로 변환한다.
    for col in age_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    df["total"] = df[age_cols].sum(axis=1)
    df["elderly"] = df[elderly_cols].sum(axis=1)
    df["youth"] = df[youth_cols].sum(axis=1)

    # 읍·면·동 코드 앞 5자리로 묶어 연도·시군구별 인구를 합산한다.
    grouped = (
        df[df["구코드"] != ""]
        .groupby(["연도", "구코드"], as_index=False, sort=False)
        .agg(total=("total", "sum"), elderly=("elderly", "sum"), youth=("youth", "sum"))
    )
    grouped["elderly_pct"] = (grouped["elderly"] / grouped["total"].where(grouped["total"] != 0)) * 100
    grouped["youth_pct"] = (grouped["youth"] / grouped["total"].where(grouped["total"] != 0)) * 100
    return grouped


@st.cache_data(ttl=86400, show_spinner="시군구 경계 지도를 불러오는 중…")
def load_geojson():
    response = requests.get(GEOJSON_URL, timeout=30)
    response.raise_for_status()
    geo = response.json()
    if not isinstance(geo, dict) or geo.get("type") != "FeatureCollection":
        raise ValueError("경계 GeoJSON 형식이 FeatureCollection이 아닙니다.")

    features = []
    for feature in geo.get("features", []):
        props = feature.get("properties") or {}
        code = normalize_code(props.get("코드"))
        name = str(props.get("시군구", "")).strip()
        province = str(props.get("시도", "")).strip()
        if not code or not feature.get("geometry"):
            continue
        # 속성의 코드는 문자열로 저장하고 매칭에 사용한다.
        copied = dict(feature)
        copied["properties"] = dict(props)
        copied["properties"]["코드"] = code
        copied["properties"]["시군구"] = name
        copied["properties"]["시도"] = province
        features.append(copied)
    if not features:
        raise ValueError("GeoJSON에서 '코드', '시군구', '시도' 속성을 가진 경계를 찾지 못했습니다.")
    return {"type": "FeatureCollection", "features": features}


def feature_collection(features):
    return {"type": "FeatureCollection", "features": features}


def make_step_colorscale(thresholds, colors, upper=100):
    """Plotly 연속형 색상표를 경계값 기준의 계단형 색상표로 만든다."""
    scale = [[0.0, colors[0]]]
    for index, threshold in enumerate(thresholds):
        position = max(0.0, min(1.0, float(threshold) / float(upper)))
        # 같은 위치에 이전 색과 다음 색을 두어 경계에서 즉시 색을 전환한다.
        scale.append([position, colors[index]])
        scale.append([position, colors[index + 1]])
    scale.append([1.0, colors[-1]])
    return scale


def classify(value, thresholds):
    if pd.isna(value):
        return None
    for i, threshold in enumerate(thresholds):
        if value < threshold:
            return i
    return len(thresholds)


def build_map(geo, metrics_df, metric_cfg, province_choice):
    all_features = geo["features"]
    if province_choice != "전국":
        all_features = [f for f in all_features if f["properties"].get("시도") == province_choice]

    by_code = metrics_df.set_index("구코드").to_dict(orient="index")
    matched_features, matched_codes, matched_values, matched_names = [], [], [], []
    missing_features, missing_codes, missing_names = [], [], []

    for feature in all_features:
        props = feature["properties"]
        code = str(props.get("코드", ""))
        record = by_code.get(code)
        if record and pd.notna(record.get(metric_cfg["column"])):
            matched_features.append(feature)
            matched_codes.append(code)
            matched_values.append(float(record[metric_cfg["column"]]))
            matched_names.append(props.get("시군구", code))
        else:
            missing_features.append(feature)
            missing_codes.append(code)
            missing_names.append(props.get("시군구", code))

    fig = go.Figure()
    if missing_features:
        fig.add_trace(go.Choropleth(
            geojson=feature_collection(missing_features),
            locations=missing_codes,
            z=[0] * len(missing_codes),
            featureidkey="properties.코드",
            zmin=0, zmax=1,
            colorscale=[[0, "#D7D5CF"], [1, "#D7D5CF"]],
            showscale=False,
            marker_line_color="#FFFCF5",
            marker_line_width=0.65,
            customdata=[[name, "자료 없음"] for name in missing_names],
            hovertemplate="<b>%{customdata[0]}</b><br>지표: %{customdata[1]}<extra></extra>",
            name="자료 미매칭",
            showlegend=False,
        ))

    if matched_features:
        thresholds = metric_cfg["thresholds"]
        colors = metric_cfg["colors"]
        # 다섯 단계의 색을 동일한 경계값으로 유지한다.
        z_values = matched_values
        fig.add_trace(go.Choropleth(
            geojson=feature_collection(matched_features),
            locations=matched_codes,
            z=z_values,
            featureidkey="properties.코드",
            zmin=0,
            zmax=50 if metric_cfg["column"] == "elderly_pct" else 20,
            colorscale=make_step_colorscale(thresholds, colors, upper=50 if metric_cfg["column"] == "elderly_pct" else 20),
            showscale=False,
            marker_line_color="#FFFCF5",
            marker_line_width=0.65,
            customdata=[[name, val] for name, val in zip(matched_names, matched_values)],
            hovertemplate="<b>%{customdata[0]}</b><br>" + metric_cfg["short"] + ": %{customdata[1]:.2f}%<extra></extra>",
            name=metric_cfg["short"],
            showlegend=False,
        ))

    fig.update_geos(
        fitbounds="locations",
        visible=False,
        showcountries=False,
        showcoastlines=False,
        showland=False,
        bgcolor=BG,
        projection_type="mercator",
    )
    fig.update_layout(
        height=690 if province_choice == "전국" else 600,
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor=PAPER,
        plot_bgcolor=PAPER,
        geo=dict(bgcolor=PAPER),
        font=dict(family="Noto Sans KR, sans-serif", color=INK),
        hoverlabel=dict(bgcolor=INK, bordercolor=INK, font=dict(color="#FFFFFF", size=13)),
        dragmode=False,
    )
    return fig, len(matched_features), len(missing_features), [f["properties"].get("시군구", "") for f in missing_features]


def metric_card(label, value, foot, color_class=""):
    st.markdown(
        f'<div class="metric-card {color_class}"><div class="metric-label">{label}</div>'
        f'<div class="metric-value">{value}</div><div class="metric-foot">{foot}</div></div>',
        unsafe_allow_html=True,
    )


# -----------------------------------------------------------------------------
# 데이터 로드와 기본 검증
# -----------------------------------------------------------------------------
try:
    with st.spinner("데이터를 준비하고 있습니다…"):
        population = load_population()
        geo = load_geojson()
except Exception as exc:
    st.error("데이터를 불러오는 중 문제가 발생했습니다.")
    st.exception(exc)
    st.stop()

available_years = sorted(int(y) for y in population["연도"].dropna().unique())
if not available_years:
    st.error("인구 데이터에서 유효한 연도를 찾지 못했습니다.")
    st.stop()

# GeoJSON을 기준으로 지역 목록과 코드-시도 관계를 만든다.
features = geo["features"]
provinces = sorted({f["properties"].get("시도", "") for f in features if f["properties"].get("시도")})

# -----------------------------------------------------------------------------
# 필터 UI
# -----------------------------------------------------------------------------
st.markdown('<div class="section-kicker">01 / EXPLORE THE DATA</div>', unsafe_allow_html=True)
filter_cols = st.columns([1.15, 1.15, 2.3], gap="medium")
with filter_cols[0]:
    year_index = available_years.index(2026) if 2026 in available_years else len(available_years) - 1
    year = st.slider("기준 연도", min_value=min(available_years), max_value=max(available_years), value=available_years[year_index], step=1)
with filter_cols[1]:
    metric_name = st.selectbox("분석 지표", list(METRICS.keys()), index=0)
with filter_cols[2]:
    province_choice = st.selectbox("지도 범위 · 시도", ["전국"] + provinces, index=0)

metric_cfg = METRICS[metric_name]
year_df = population[population["연도"] == year].copy()
if year_df.empty:
    st.warning(f"{year}년 데이터가 없습니다. 슬라이더에서 제공되는 연도를 선택해 주세요.")
    st.stop()

# 전국 카드 통계는 항상 전국 기준이며, 지도는 선택한 시도만 확대한다.
national_total = float(year_df["total"].sum())
national_numerator = float(year_df[metric_cfg["numerator"]].sum())
national_rate = (national_numerator / national_total * 100) if national_total else float("nan")
year_df[metric_cfg["column"]] = (year_df[metric_cfg["numerator"]] / year_df["total"].where(year_df["total"] != 0)) * 100

# GeoJSON 이름과 코드로 전국 최고·최저 지역 이름을 찾는다.
name_by_code = {str(f["properties"]["코드"]): str(f["properties"].get("시군구", "")) for f in features}
province_by_code = {str(f["properties"]["코드"]): str(f["properties"].get("시도", "")) for f in features}
year_df["지역명"] = year_df["구코드"].map(name_by_code)
valid_stats = year_df.dropna(subset=[metric_cfg["column"]]).copy()
valid_stats = valid_stats[valid_stats["지역명"].notna() & (valid_stats["지역명"] != "")]
if not valid_stats.empty:
    highest = valid_stats.loc[valid_stats[metric_cfg["column"]].idxmax()]
    lowest = valid_stats.loc[valid_stats[metric_cfg["column"]].idxmin()]
    highest_text = f"{highest['지역명']} · {highest[metric_cfg['column']]:.1f}%"
    lowest_text = f"{lowest['지역명']} · {lowest[metric_cfg['column']]:.1f}%"
else:
    highest_text = lowest_text = "자료 없음"

st.markdown('<div class="section-kicker">02 / NATIONAL SNAPSHOT</div>', unsafe_allow_html=True)
card_cols = st.columns(3, gap="medium")
with card_cols[0]:
    metric_card(f"전국 {metric_cfg['short']}", f"{national_rate:.2f}%" if pd.notna(national_rate) else "—", f"{year}년 · 전체 인구 가중 비율", "")
with card_cols[1]:
    metric_card(f"가장 높은 시군구 · {metric_cfg['short']}", highest_text, f"{year}년 · 코드 매칭 지역 중", "blue")
with card_cols[2]:
    metric_card(f"가장 낮은 시군구 · {metric_cfg['short']}", lowest_text, f"{year}년 · 코드 매칭 지역 중", "yellow")

# -----------------------------------------------------------------------------
# 지도와 고정 범례
# -----------------------------------------------------------------------------
st.markdown('<div class="section-kicker">03 / CHOROPLETH MAP</div>', unsafe_allow_html=True)
thresholds = metric_cfg["thresholds"]
colors = metric_cfg["colors"]
legend_html = '<div class="legend-wrap">'
for label, color in zip(metric_cfg["labels"], colors):
    legend_html += f'<div class="legend-item"><span class="swatch" style="background:{color}"></span>{label}</div>'
legend_html += '<div class="legend-item"><span class="swatch" style="background:#D7D5CF"></span>자료 미매칭</div></div>'
st.markdown(legend_html, unsafe_allow_html=True)

metrics_for_map = year_df[["구코드", metric_cfg["column"]]].copy()
fig, matched_count, missing_count, missing_names = build_map(geo, metrics_for_map, metric_cfg, province_choice)
st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False, "scrollZoom": False, "responsive": True})

# 연도별 색상 경계와 자료 미매칭을 분명히 설명한다.
if metric_cfg["column"] == "elderly_pct":
    st.markdown('<div class="note">고령화율 색 구간은 모든 연도에서 <b>19 · 23 · 28 · 38%</b>로 고정됩니다. 경계값은 해당 숫자부터 다음 단계 색상에 포함됩니다.</div>', unsafe_allow_html=True)
else:
    st.markdown('<div class="note">유소년 비율은 지표 특성에 맞춰 <b>5 · 8 · 11 · 14%</b>의 고정 구간을 사용합니다. 연도를 바꿔도 색 구간은 변하지 않습니다.</div>', unsafe_allow_html=True)

if missing_count:
    shown_names = [n for n in missing_names if n]
    preview = ", ".join(shown_names[:18])
    if len(shown_names) > 18:
        preview += f" 외 {len(shown_names) - 18}곳"
    st.warning(
        f"경계 {missing_count}곳은 선택한 연도({year}년)에 코드가 매칭되지 않아 회색으로 표시했습니다. "
        f"이름 기준으로 억지 연결하지 않았습니다. 미매칭 지역: {preview or '지역명 확인 불가'}"
    )
else:
    st.caption(f"경계 {matched_count}곳의 코드가 인구 자료와 일치했습니다.")

# -----------------------------------------------------------------------------
# 간단한 표와 데이터 정의
# -----------------------------------------------------------------------------
with st.expander("지역별 수치 표 보기", expanded=False):
    table = year_df.copy()
    table["시도"] = table["구코드"].map(province_by_code)
    table["시군구"] = table["구코드"].map(name_by_code)
    table = table[table["시군구"].notna() & (table["시군구"] != "")]
    if province_choice != "전국":
        table = table[table["시도"] == province_choice]
    table = table[["구코드", "시도", "시군구", "total", "elderly", "youth", "elderly_pct", "youth_pct"]].copy()
    table = table.rename(columns={
        "구코드": "코드", "total": "전체 인구", "elderly": "65세 이상 인구", "youth": "0~14세 인구",
        "elderly_pct": "고령화율(%)", "youth_pct": "유소년 비율(%)",
    })
    st.dataframe(
        table.sort_values("고령화율(%)", ascending=False),
        use_container_width=True,
        hide_index=True,
        column_config={
            "코드": st.column_config.TextColumn("코드"),
            "전체 인구": st.column_config.NumberColumn(format="%,d"),
            "65세 이상 인구": st.column_config.NumberColumn(format="%,d"),
            "0~14세 인구": st.column_config.NumberColumn(format="%,d"),
            "고령화율(%)": st.column_config.NumberColumn(format="%.2f%%"),
            "유소년 비율(%)": st.column_config.NumberColumn(format="%.2f%%"),
        },
    )
    csv_bytes = table.to_csv(index=False).encode("utf-8-sig")
    st.download_button("현재 표 CSV 다운로드", data=csv_bytes, file_name=f"인구단계구분도_{year}_{metric_cfg['short']}.csv", mime="text/csv")

st.markdown("---")
st.markdown(
    '<div class="note">자료: 제공된 읍·면·동 연령별 인구 ZIP CSV 및 시군구 GeoJSON. '
    '고령화율 = 65세 이상 인구 ÷ 전체 인구 × 100. '
    '유소년 비율 = 0~14세 인구 ÷ 전체 인구 × 100. '
    '전체 인구는 이름이 <b>계_</b>로 시작하는 연령별 열만 합산하며, 남·여 열은 중복 합산하지 않습니다. '
    '지도 결합은 행정구역 코드로만 수행합니다.</div>',
    unsafe_allow_html=True,
)
