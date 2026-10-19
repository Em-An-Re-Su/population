# main.py
# 동네별 인구 피라미드 — Streamlit Cloud 배포용
# 전국 → 시도 → 시군구 → 읍·면·동 단계형 지도와 상세 인구 UI를 제공한다.

import re
import unicodedata

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
# streamlit-plotly-events2 패키지는 기존 모듈 경로를 사용한다.
try:
    from streamlit_plotly_events import plotly_events
except ImportError as exc:
    raise ImportError(
        "지도 클릭 패키지를 불러오지 못했습니다. requirements.txt에 "
        "streamlit-plotly-events2==0.0.7이 있는지 확인하고, "
        "Streamlit Cloud에서 앱을 재부팅해 주세요."
    ) from exc


# ------------------------------------------------------------
# 1. 페이지 설정 및 디자인
# ------------------------------------------------------------
st.set_page_config(
    page_title="동네별 인구 피라미드",
    page_icon="🏡",
    layout="wide",
)

BG = "#FFF9F1"
PANEL = "#FFFDF9"
INK = "#49372E"
MUTED = "#806A5B"
BORDER = "#EBD9C8"
MALE = "#C76F51"
FEMALE = "#E5AC91"
ACCENT = "#B85C3B"

st.markdown(
    f"""
    <style>
    .stApp {{ background-color: {BG}; color: {INK}; }}
    h1, h2, h3 {{ color: #704536; }}
    [data-testid="stMetric"] {{
        background: {PANEL};
        border: 1px solid {BORDER};
        border-radius: 13px;
        padding: 15px 17px;
    }}
    [data-testid="stMetricLabel"] {{ color: {MUTED}; }}
    div[data-baseweb="select"] > div {{
        background: #FFFFFF;
        border-color: #D8BBA5;
    }}
    .intro {{
        color: {MUTED};
        font-size: 1rem;
        line-height: 1.8;
    }}
    .small-note {{
        color: {MUTED};
        font-size: .88rem;
        line-height: 1.65;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

DATA_URL = (
    "https://raw.githubusercontent.com/"
    "first2022-cyber/contents/main/"
    "population_ts_yearly_gender.zip"
)
PROVINCE_GEOJSON_URL = (
    "https://raw.githubusercontent.com/"
    "KnellBalm/kr-admin-geojson/main/ctprvn.geojson"
)
DISTRICT_GEOJSON_URL = (
    "https://raw.githubusercontent.com/"
    "KnellBalm/kr-admin-geojson/main/sig.geojson"
)
NEIGHBORHOOD_GEOJSON_URL = (
    "https://raw.githubusercontent.com/"
    "KnellBalm/kr-admin-geojson/main/emd.geojson"
)


# ------------------------------------------------------------
# 2. 데이터 불러오기
# ------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner="최신 인구 데이터를 불러오는 중...")
def load_population():
    """ZIP 압축 CSV를 읽고 가장 최신 연도의 행만 남긴다."""
    errors = []
    df = None

    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            df = pd.read_csv(
                DATA_URL,
                compression="zip",
                encoding=encoding,
                low_memory=False,
            )
            break
        except Exception as exc:
            errors.append(str(exc))

    if df is None:
        raise RuntimeError("인구 CSV를 읽지 못했습니다.\n" + "\n".join(errors))

    df.columns = [str(c).strip() for c in df.columns]
    required = ["연도", "시도", "시군구", "동"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(
            f"필수 열이 없습니다: {missing}\n"
            f"실제 열 이름 일부: {df.columns.tolist()[:40]}"
        )

    df["연도"] = pd.to_numeric(df["연도"], errors="coerce")
    df = df.dropna(subset=["연도"]).copy()
    if df.empty:
        raise ValueError("연도 값이 있는 데이터가 없습니다.")

    latest_year = int(df["연도"].max())
    df = df[df["연도"] == latest_year].copy()

    for col in ["시도", "시군구", "동"]:
        df[col] = df[col].fillna("").astype(str).str.strip()

    age_pattern = re.compile(r"^[남여]_(\d+세|100세\s*이상)$")
    age_columns = [c for c in df.columns if age_pattern.match(c)]
    if not age_columns:
        raise ValueError(
            "남_0세, 여_0세, 남_100세 이상 형식의 열을 찾지 못했습니다."
        )

    def age_sort_key(label):
        if "100세" in label:
            return 100
        match = re.search(r"\d+", label)
        return int(match.group()) if match else 999

    age_labels = sorted(
        {
            age_pattern.match(c).group(1).replace(" ", "")
            for c in age_columns
        },
        key=age_sort_key,
    )

    # 라벨 표기를 통일해 실제 열 이름과 연결한다.
    for age in age_labels:
        for gender in ("남", "여"):
            expected = f"{gender}_{age}"
            if expected not in df.columns:
                alternate = f"{gender}_{age.replace('100세이상', '100세 이상')}"
                if alternate in df.columns:
                    df[expected] = df[alternate]

    age_columns = [
        f"{gender}_{age}"
        for age in age_labels
        for gender in ("남", "여")
        if f"{gender}_{age}" in df.columns
    ]

    for col in age_columns:
        df[col] = pd.to_numeric(
            df[col].astype(str).str.replace(",", "", regex=False),
            errors="coerce",
        ).fillna(0)

    return df, latest_year, age_labels, age_columns


@st.cache_data(ttl=86400, show_spinner=False)
def load_geojson(url):
    """공개 저장소에서 GeoJSON 경계 파일을 내려받는다."""
    response = requests.get(url, timeout=35)
    response.raise_for_status()
    return response.json()


def clean_name(value):
    """행정구역 이름 비교를 위해 공백과 유니코드 표기를 정리한다."""
    if value is None:
        return ""
    value = unicodedata.normalize("NFKC", str(value))
    return re.sub(r"\s+", "", value.strip())


def get_property(feature, candidates):
    props = feature.get("properties", {})
    for candidate in candidates:
        if candidate in props and props[candidate] is not None:
            return props[candidate]
    return None


def get_province_features(geojson):
    """시도 GeoJSON의 이름과 코드를 읽는다."""
    result = []
    for feature in geojson.get("features", []):
        name = get_property(feature, ["CTP_KOR_NM", "name"])
        code = get_property(feature, ["CTPRVN_CD"])
        if name is not None and code is not None:
            result.append({
                "feature": feature,
                "name": str(name).strip(),
                "code": str(code).strip(),
            })
    return result


def get_district_features(geojson, province_code):
    """선택한 시도의 시군구 경계만 반환한다."""
    result = []
    if not province_code:
        return result

    for feature in geojson.get("features", []):
        code = get_property(feature, ["SIG_CD"])
        province = get_property(feature, ["CTPRVN_CD"])
        name = get_property(feature, ["SIG_KOR_NM"])
        full_name = get_property(feature, ["FULL_NM", "SIG_KOR_NM"])

        if code is None or name is None:
            continue

        code = str(code).strip()
        province = str(province).strip() if province is not None else code[:2]

        if province == str(province_code).strip():
            result.append({
                "feature": feature,
                "name": str(name).strip(),
                "full_name": str(full_name or name).strip(),
                "code": code,
            })

    return result


def get_neighborhood_features(geojson, province_code, district_code, csv_names):
    """선택한 시군구에 속하는 읍·면·동 지도 피처를 만든다.

    EMD GeoJSON은 법정동 경계를 포함하며, HJD_NM(행정동명)도 제공한다.
    같은 행정동에 속한 법정동 조각은 같은 CSV 인구값으로 색칠하고,
    클릭하면 해당 행정동을 선택하도록 연결한다.
    """
    lookup = {clean_name(name): name for name in csv_names if str(name).strip()}
    result = []
    for feature in geojson.get("features", []):
        props = feature.get("properties", {})
        sig_code = str(props.get("SIG_CD", "")).strip()
        sido_code = str(props.get("CTPRVN_CD", sig_code[:2])).strip()
        if sig_code != str(district_code).strip():
            continue
        if province_code and sido_code and sido_code != str(province_code).strip():
            continue

        emd_code = props.get("EMD_CD")
        emd_name = props.get("EMD_KOR_NM") or props.get("name")
        admin_name = props.get("HJD_NM")
        full_name = props.get("FULL_NM") or emd_name or admin_name
        if emd_code is None or not (emd_name or admin_name):
            continue

        # 우선 행정동명(HJD_NM)을 CSV의 읍면동명과 매칭하고,
        # 없으면 법정동 이름을 사용한다.
        csv_name = lookup.get(clean_name(admin_name)) if admin_name else None
        if csv_name is None and emd_name:
            csv_name = lookup.get(clean_name(emd_name))
        if csv_name is None and full_name:
            normalized_full = clean_name(full_name)
            candidates = [
                original for normalized, original in lookup.items()
                if normalized and (normalized in normalized_full or normalized_full.endswith(normalized))
            ]
            if candidates:
                csv_name = min(candidates, key=lambda x: abs(len(clean_name(x)) - len(normalized_full)))

        result.append({
            "feature": feature,
            "name": str(admin_name or emd_name).strip(),
            "legal_name": str(emd_name or admin_name).strip(),
            "full_name": str(full_name).strip(),
            "code": str(emd_code).strip(),
            "csv_name": csv_name,
        })
    return result


# ------------------------------------------------------------
# 3. 집계와 인구 지표
# ------------------------------------------------------------
def sum_columns_for_age_labels(age_labels):
    return [
        f"{gender}_{age}"
        for age in age_labels
        for gender in ("남", "여")
        if f"{gender}_{age}" in df.columns
    ]


def aggregate_region(data, group_cols, age_labels):
    """읍면동 자료를 시군구·시도 단위로 합산한다."""
    sum_cols = [
        f"{gender}_{age}"
        for age in age_labels
        for gender in ("남", "여")
        if f"{gender}_{age}" in data.columns
    ]
    result = data.groupby(group_cols, dropna=False)[sum_cols].sum().reset_index()

    male_cols = [f"남_{age}" for age in age_labels if f"남_{age}" in result]
    female_cols = [f"여_{age}" for age in age_labels if f"여_{age}" in result]
    result["남자_총인구"] = result[male_cols].sum(axis=1)
    result["여자_총인구"] = result[female_cols].sum(axis=1)
    result["총인구"] = result["남자_총인구"] + result["여자_총인구"]
    return result


def age_number(label):
    if "100세" in str(label):
        return 100
    match = re.search(r"\d+", str(label))
    return int(match.group()) if match else 999


def population_metrics(row, age_labels):
    """선택 지역의 연령대별 비율과 인구 구조 지표를 계산한다."""
    counts = {}
    for age in age_labels:
        male = float(row.get(f"남_{age}", 0) or 0)
        female = float(row.get(f"여_{age}", 0) or 0)
        counts[age] = max(0, male + female)

    total = sum(counts.values())
    male_total = sum(float(row.get(f"남_{a}", 0) or 0) for a in age_labels)
    female_total = sum(float(row.get(f"여_{a}", 0) or 0) for a in age_labels)

    children = sum(v for a, v in counts.items() if age_number(a) <= 14)
    working = sum(v for a, v in counts.items() if 15 <= age_number(a) <= 64)
    elderly = sum(v for a, v in counts.items() if age_number(a) >= 65)
    elderly80 = sum(v for a, v in counts.items() if age_number(a) >= 80)

    sex_ratio = male_total / female_total * 100 if female_total else np.nan
    aging_index = elderly / children * 100 if children else np.nan
    dependency_ratio = (children + elderly) / working * 100 if working else np.nan

    # 각 연령 구간의 대표 나이를 이용한 근사 평균 연령이다.
    weighted_sum = sum(age_number(a) * v for a, v in counts.items())
    average_age = weighted_sum / total if total else np.nan

    top_ages = sorted(counts.items(), key=lambda item: item[1], reverse=True)[:5]

    return {
        "total": total,
        "male": male_total,
        "female": female_total,
        "children": children,
        "working": working,
        "elderly": elderly,
        "elderly80": elderly80,
        "children_share": children / total * 100 if total else 0,
        "working_share": working / total * 100 if total else 0,
        "elderly_share": elderly / total * 100 if total else 0,
        "elderly80_share": elderly80 / total * 100 if total else 0,
        "male_share": male_total / total * 100 if total else 0,
        "female_share": female_total / total * 100 if total else 0,
        "sex_ratio": sex_ratio,
        "aging_index": aging_index,
        "dependency_ratio": dependency_ratio,
        "average_age": average_age,
        "top_ages": top_ages,
        "counts": counts,
    }


def fmt_number(value):
    return f"{int(round(value)):,}"


def fmt_percent(value):
    return "자료 없음" if pd.isna(value) else f"{value:.1f}%"


def fmt_ratio(value):
    return "자료 없음" if pd.isna(value) else f"{value:.1f}"


# ------------------------------------------------------------
# 4. 인구 피라미드
# ------------------------------------------------------------
def draw_population_pyramid(row, age_labels, title):
    """남자 값은 음수, 여자 값은 양수로 표시한다."""
    male_values = [
        -float(row.get(f"남_{age}", 0) or 0)
        for age in age_labels
    ]
    female_values = [
        float(row.get(f"여_{age}", 0) or 0)
        for age in age_labels
    ]
    max_value = max([abs(v) for v in male_values + female_values] + [1])
    limit = max_value * 1.12

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="남자",
        y=age_labels,
        x=male_values,
        orientation="h",
        marker_color=MALE,
        customdata=[abs(v) for v in male_values],
        hovertemplate="나이: %{y}<br>남자: %{customdata:,.0f}명<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        name="여자",
        y=age_labels,
        x=female_values,
        orientation="h",
        marker_color=FEMALE,
        hovertemplate="나이: %{y}<br>여자: %{x:,.0f}명<extra></extra>",
    ))

    # categoryarray를 0세 → 100세 이상으로 고정한다.
    # categoryorder='array'에서 첫 항목을 맨 아래로 두기 위해
    # y축 autorange='reversed'를 사용한다. 범주 순서를 직접 고정했으므로
    # 인구수에 따른 정렬은 하지 않는다.
    fig.update_layout(
        title=dict(text=title, x=0.5, xanchor="center"),
        barmode="relative",
        bargap=0.12,
        height=max(650, len(age_labels) * 11),
        paper_bgcolor=BG,
        plot_bgcolor=BG,
        font=dict(family="Arial, sans-serif", color=INK, size=12),
        margin=dict(l=75, r=35, t=75, b=55),
        legend=dict(orientation="h", yanchor="bottom", y=1.01,
                    xanchor="center", x=0.5),
        xaxis=dict(
            title="인구 수 (명)",
            range=[-limit, limit],
            tickformat=",",
            zeroline=True,
            zerolinecolor="#BDA696",
            gridcolor="#EADDD1",
        ),
        yaxis=dict(
            title="나이",
            type="category",
            categoryorder="array",
            categoryarray=age_labels,
            autorange="reversed",
            gridcolor="#F0E5DB",
        ),
    )
    return fig


def draw_age_group_chart(row, age_labels):
    """연령대별 남녀 인구를 보기 쉬운 세로 막대그래프로 나타낸다."""
    groups = {
        "0~14세": (0, 14),
        "15~29세": (15, 29),
        "30~49세": (30, 49),
        "50~64세": (50, 64),
        "65~79세": (65, 79),
        "80세 이상": (80, 1000),
    }
    labels, males, females = [], [], []

    for group, (low, high) in groups.items():
        m = f = 0
        for age in age_labels:
            number = age_number(age)
            if low <= number <= high:
                m += float(row.get(f"남_{age}", 0) or 0)
                f += float(row.get(f"여_{age}", 0) or 0)
        labels.append(group)
        males.append(m)
        females.append(f)

    fig = go.Figure()
    fig.add_trace(go.Bar(name="남자", x=labels, y=males, marker_color=MALE))
    fig.add_trace(go.Bar(name="여자", x=labels, y=females, marker_color=FEMALE))
    fig.update_layout(
        barmode="group",
        height=390,
        paper_bgcolor=BG,
        plot_bgcolor=BG,
        font=dict(color=INK),
        margin=dict(l=15, r=15, t=25, b=15),
        yaxis=dict(title="인구 수(명)", tickformat=",", gridcolor="#EADDD1"),
        xaxis=dict(title="연령대"),
        legend=dict(orientation="h", y=1.12, x=0.5, xanchor="center"),
    )
    return fig


# ------------------------------------------------------------
# 5. 단계형 지도
# ------------------------------------------------------------
def make_map(features, value_map, title, code_property):
    """현재 단계의 지역만 표시하고 경계에 맞춰 자동 확대한다."""
    geojson = {
        "type": "FeatureCollection",
        "features": [item["feature"] for item in features],
    }
    locations = [item["code"] for item in features]
    names = [item["name"] for item in features]
    # 클릭 이벤트가 text/location 중 어떤 필드를 돌려주더라도 추적할 수 있게
    # 코드와 표시 이름을 customdata에 함께 넣는다.
    customdata = [[item["code"], item.get("csv_name") or item["name"]] for item in features]
    values = [float(value_map.get(clean_name(n), 0)) for n in names]
    max_value = max(values + [1])

    fig = go.Figure(go.Choropleth(
        geojson=geojson,
        locations=locations,
        z=values,
        featureidkey=f"properties.{code_property}",
        text=names,
        customdata=customdata,
        colorscale=[
            [0.0, "#F8E9DA"],
            [0.35, "#E8BDA0"],
            [0.7, "#D48C6D"],
            [1.0, "#A94F35"],
        ],
        zmin=0,
        zmax=max_value,
        marker_line_color="#FFF9F1",
        marker_line_width=1.1,
        colorbar=dict(title="총인구(명)", thickness=13, tickformat=","),
        hovertemplate="%{text}<br>총인구: %{z:,.0f}명<extra></extra>",
    ))
    fig.update_geos(
        fitbounds="locations",
        visible=False,
        bgcolor=BG,
        showland=True,
        landcolor=BG,
        showcountries=False,
        showcoastlines=False,
    )
    fig.update_layout(
        title=dict(text=title, x=0.5, xanchor="center"),
        height=590,
        margin=dict(l=0, r=0, t=55, b=0),
        paper_bgcolor=BG,
        plot_bgcolor=BG,
        font=dict(color=INK),
    )
    return fig


def resolve_map_click(clicks, features):
    """지도 이벤트의 반환 형식 차이를 흡수해 클릭한 경계 항목을 찾는다."""
    if not clicks or not features:
        return None
    point = clicks[0] if isinstance(clicks, list) else clicks
    if not isinstance(point, dict):
        return None

    # GeoJSON Choropleth의 표준 반환값은 location이다.
    clicked_location = point.get("location")
    if clicked_location is not None:
        clicked_location = str(clicked_location).strip()
        match = next((f for f in features if str(f.get("code", "")).strip() == clicked_location), None)
        if match:
            return match

    # 컴포넌트/Plotly 버전에 따라 customdata, text, pointIndex만 오는 경우도 처리한다.
    custom = point.get("customdata")
    if isinstance(custom, (list, tuple)) and custom:
        custom_code = str(custom[0]).strip()
        match = next((f for f in features if str(f.get("code", "")).strip() == custom_code), None)
        if match:
            return match
        custom_name = clean_name(custom[-1])
        match = next((f for f in features if clean_name(f.get("name", "")) == custom_name), None)
        if match:
            return match

    for field in ("text", "label"):
        value = point.get(field)
        if value is not None:
            cleaned = clean_name(value)
            match = next((f for f in features if clean_name(f.get("name", "")) == cleaned), None)
            if match:
                return match

    for field in ("pointIndex", "pointNumber"):
        index = point.get(field)
        try:
            index = int(index)
        except (TypeError, ValueError):
            continue
        if 0 <= index < len(features):
            return features[index]
    return None


# ------------------------------------------------------------
# 6. 앱 본문과 데이터 준비
# ------------------------------------------------------------
st.title("🏡 동네별 인구 피라미드")
st.markdown(
    """
    <p class="intro">
    우리 동네에는 어떤 연령대가 많이 살고 있을까요?
    전국 지도에서 지역을 눌러 단계적으로 확대하고,
    인구 피라미드와 다양한 인구 지표를 함께 살펴보세요.
    </p>
    """,
    unsafe_allow_html=True,
)

try:
    df, latest_year, age_labels, age_columns = load_population()
except Exception as exc:
    st.error("인구 데이터를 불러오지 못했습니다.")
    st.code(str(exc))
    st.info("원본 ZIP 주소와 CSV의 열 이름 또는 네트워크 상태를 확인해 주세요.")
    st.stop()

male_cols = [f"남_{age}" for age in age_labels if f"남_{age}" in df.columns]
female_cols = [f"여_{age}" for age in age_labels if f"여_{age}" in df.columns]

# 같은 읍면동이 중복으로 기록된 경우에는 연령별 인구를 먼저 합산한다.
province_summary = aggregate_region(df, ["시도"], age_labels)
district_summary = aggregate_region(df, ["시도", "시군구"], age_labels)
neighborhood_summary = aggregate_region(df, ["시도", "시군구", "동"], age_labels)

province_options = sorted([x for x in df["시도"].unique() if x])
if not province_options:
    st.error("시도 데이터가 없습니다.")
    st.stop()

# 지도 클릭 후 rerun 시, 위젯이 만들어지기 전에 선택값을 반영한다.
if "pending_province" in st.session_state:
    st.session_state["province_select"] = st.session_state.pop("pending_province")
if "pending_district" in st.session_state:
    st.session_state["district_select"] = st.session_state.pop("pending_district")
if "pending_neighborhood" in st.session_state:
    st.session_state["neighborhood_select"] = st.session_state.pop("pending_neighborhood")

if "province_select" not in st.session_state or st.session_state["province_select"] not in province_options:
    st.session_state["province_select"] = province_options[0]

# 최신 연도 전국 합계
national_male = int(df[male_cols].sum().sum())
national_female = int(df[female_cols].sum().sum())

st.caption(f"📅 분석 연도: {latest_year}년 · 연령 구간: {len(age_labels)}개")
n1, n2, n3 = st.columns(3)
n1.metric("전국 남자 인구", f"{national_male:,}명")
n2.metric("전국 여자 인구", f"{national_female:,}명")
n3.metric("전국 총인구", f"{national_male + national_female:,}명")


# ------------------------------------------------------------
# 7. 기존 드롭다운 선택 UI 유지
# ------------------------------------------------------------
st.divider()
st.header("📍 지역 선택")

selected_province = st.selectbox(
    "① 시도 / 광역시",
    province_options,
    key="province_select",
)

province_df = df[df["시도"] == selected_province]
district_options = sorted([x for x in province_df["시군구"].unique() if x])
if not district_options:
    district_options = [""]

if "district_select" not in st.session_state or st.session_state["district_select"] not in district_options:
    st.session_state["district_select"] = district_options[0]

selected_district = st.selectbox(
    "② 시군구",
    district_options,
    key="district_select",
)

district_df = province_df[province_df["시군구"] == selected_district]
neighborhood_options = sorted([x for x in district_df["동"].unique() if x])
if not neighborhood_options:
    neighborhood_options = [""]

if "neighborhood_select" not in st.session_state or st.session_state["neighborhood_select"] not in neighborhood_options:
    st.session_state["neighborhood_select"] = neighborhood_options[0]

selected_neighborhood = st.selectbox(
    "③ 읍·면·동",
    neighborhood_options,
    key="neighborhood_select",
)


# ------------------------------------------------------------
# 8. 선택한 동네의 인구 피라미드
# ------------------------------------------------------------
st.divider()
st.header("📊 인구 피라미드")

selected_rows = district_df[district_df["동"] == selected_neighborhood]
if selected_rows.empty:
    st.warning("선택한 지역의 인구 데이터가 없습니다.")
else:
    selected_population = selected_rows[male_cols + female_cols].sum()
    selected_metrics = population_metrics(selected_population, age_labels)

    location_title = f"{selected_province} {selected_district} {selected_neighborhood}"
    p1, p2, p3 = st.columns(3)
    p1.metric("총인구", f"{fmt_number(selected_metrics['total'])}명")
    p2.metric("남자", f"{fmt_number(selected_metrics['male'])}명")
    p3.metric("여자", f"{fmt_number(selected_metrics['female'])}명")

    pyramid_fig = draw_population_pyramid(
        selected_population,
        age_labels,
        f"{location_title} 인구 피라미드 ({latest_year}년)",
    )
    st.plotly_chart(
        pyramid_fig,
        use_container_width=True,
        config={
            "displayModeBar": True,
            "displaylogo": False,
            "toImageButtonOptions": {
                "format": "png",
                "filename": "인구_피라미드",
                "scale": 2,
            },
        },
    )
    st.caption(
        "왼쪽은 남자, 오른쪽은 여자입니다. "
        "세로축은 0세가 맨 아래, 100세 이상이 맨 위에 오도록 나이순으로 고정했습니다."
    )

    with st.expander("동네 연령별 인구 표 보기"):
        age_table = pd.DataFrame({
            "나이": age_labels,
            "남자": [int(selected_population.get(f"남_{a}", 0)) for a in age_labels],
            "여자": [int(selected_population.get(f"여_{a}", 0)) for a in age_labels],
        })
        age_table["합계"] = age_table["남자"] + age_table["여자"]
        st.dataframe(age_table, use_container_width=True, hide_index=True)


# ------------------------------------------------------------
# 9. 지도에서 전국 → 시도 확대 → 시군구 선택
# ------------------------------------------------------------
st.divider()
st.header("🗺️ 지도에서 지역 탐색하기")
st.markdown(
    "전국 지도에서 시도를 클릭하고, 확대 지도에서 시·군·구를 선택한 뒤 "
    "읍·면·동 경계까지 한 단계 더 확대해 살펴볼 수 있습니다."
)

if "map_level" not in st.session_state:
    st.session_state["map_level"] = "nation"

# 지도 파일의 시도명과 CSV 시도명 차이를 맞춘다.
province_aliases = {
    "강원도": "강원특별자치도",
    "강원특별자치도": "강원특별자치도",
    "전라북도": "전북특별자치도",
    "전북특별자치도": "전북특별자치도",
    "제주도": "제주특별자치도",
    "제주특별자치도": "제주특별자치도",
}

def canonical_province(name):
    name = str(name).strip()
    return province_aliases.get(name, name)

try:
    province_geojson = load_geojson(PROVINCE_GEOJSON_URL)
    district_geojson = load_geojson(DISTRICT_GEOJSON_URL)
    neighborhood_geojson = load_geojson(NEIGHBORHOOD_GEOJSON_URL)
    province_features = get_province_features(province_geojson)

    if not province_features:
        raise ValueError("시도 GeoJSON에서 경계 이름과 코드를 찾지 못했습니다.")

    csv_province_by_canonical = {
        clean_name(canonical_province(name)): name
        for name in province_options
    }

    if st.session_state["map_level"] == "nation":
        st.subheader("대한민국 전국 지도")

        nation_features = []
        nation_values = {}

        for item in province_features:
            copy_item = dict(item)
            copy_item["csv_name"] = csv_province_by_canonical.get(
                clean_name(canonical_province(item["name"]))
            )
            nation_features.append(copy_item)

            csv_name = copy_item["csv_name"]
            row = province_summary[province_summary["시도"] == csv_name] if csv_name else pd.DataFrame()
            nation_values[clean_name(item["name"])] = (
                float(row["총인구"].iloc[0]) if not row.empty else 0
            )

        nation_fig = make_map(
            nation_features,
            nation_values,
            "전국 시도별 총인구",
            "CTPRVN_CD",
        )
        clicks = plotly_events(
            nation_fig,
            click_event=True,
            select_event=False,
            hover_event=False,
            override_height=590,
            key="nation_drill_map",
        )

        item = resolve_map_click(clicks, nation_features)
        if item:
            csv_name = item.get("csv_name")
            if csv_name in province_options:
                # 이미 같은 지역으로 이동한 이벤트가 반복 전달되면 무한 rerun하지 않는다.
                click_signature = f"nation:{item['code']}"
                if st.session_state.get("last_map_click") != click_signature or st.session_state.get("map_level") != "district":
                    st.session_state["last_map_click"] = click_signature
                    st.session_state["pending_province"] = csv_name
                    st.session_state["pending_district"] = ""
                    st.session_state["pending_neighborhood"] = ""
                    st.session_state["map_level"] = "district"
                    st.rerun()

        st.caption("지도에서 시도를 클릭하면 그 지역의 시군구 경계 지도로 전환됩니다.")

    elif st.session_state["map_level"] == "district":
        selected_map_province = canonical_province(selected_province)
        province_code = next(
            (
                item["code"] for item in province_features
                if clean_name(canonical_province(item["name"]))
                == clean_name(selected_map_province)
            ),
            None,
        )

        back_col, heading_col = st.columns([1, 4])
        with back_col:
            if st.button("← 전국 지도", use_container_width=True):
                st.session_state["map_level"] = "nation"
                st.rerun()
        with heading_col:
            st.subheader(f"{selected_province} 확대 지도")

        if not province_code:
            st.warning("선택한 시도의 지도 코드를 찾지 못했습니다.")
        else:
            district_features = get_district_features(district_geojson, province_code)
            if not district_features:
                st.warning("해당 시도의 시군구 경계 자료가 없습니다.")
            else:
                # GeoJSON 시군구 이름을 실제 CSV 시군구와 연결한다.
                district_features_for_map = []
                district_values = {}

                # 먼저 정규화된 이름 사전과 인구 조회 사전을 만들어 반복 필터링을 줄인다.
                district_name_lookup = {clean_name(name): name for name in district_options}
                district_population_lookup = {
                    (clean_name(row["시도"]), clean_name(row["시군구"])): float(row["총인구"])
                    for _, row in district_summary[["시도", "시군구", "총인구"]].iterrows()
                }
                selected_province_key = clean_name(selected_province)

                for item in district_features:
                    copy_item = dict(item)
                    map_name = clean_name(item["name"])
                    full_name = clean_name(item["full_name"])
                    match_name = district_name_lookup.get(map_name) or district_name_lookup.get(full_name)

                    if match_name is None:
                        # 예: 지도는 시군구 전체 이름, CSV는 구/시 이름으로 기록된 경우
                        possible = [
                            candidate for normalized, candidate in district_name_lookup.items()
                            if normalized in full_name or full_name in normalized
                        ]
                        if possible:
                            match_name = min(possible, key=lambda candidate: abs(len(clean_name(candidate)) - len(full_name)))

                    copy_item["csv_name"] = match_name
                    district_features_for_map.append(copy_item)

                    if match_name:
                        district_values[map_name] = district_population_lookup.get(
                            (selected_province_key, clean_name(match_name)), 0.0
                        )
                    else:
                        district_values[map_name] = 0.0

                district_fig = make_map(
                    district_features_for_map,
                    district_values,
                    f"{selected_province} 시·군·구별 총인구",
                    "SIG_CD",
                )
                clicks = plotly_events(
                    district_fig,
                    click_event=True,
                    select_event=False,
                    hover_event=False,
                    override_height=590,
                    key="district_drill_map",
                )

                item = resolve_map_click(clicks, district_features_for_map)
                if item:
                    csv_name = item.get("csv_name")
                    if csv_name in district_options:
                        click_signature = f"district:{selected_province}:{item['code']}"
                        # 동일한 이벤트가 다시 전달되면 선택을 반복하지 않는다.
                        if st.session_state.get("last_map_click") != click_signature or selected_district != csv_name:
                            st.session_state["last_map_click"] = click_signature
                            st.session_state["pending_district"] = csv_name
                            st.session_state["pending_neighborhood"] = ""
                            st.session_state["map_level"] = "neighborhood"
                            st.session_state["selected_district_code"] = item["code"]
                            st.rerun()
                    else:
                        st.info(f"지도에서 {item['name']}을(를) 선택했지만, 인구 CSV에서 같은 이름의 시군구를 찾지 못했습니다. 위의 시군구 선택 메뉴에서 골라 주세요.")

                st.caption(
                    "시·군·구를 클릭하면 해당 지역의 읍·면·동 경계 지도로 한 단계 더 확대됩니다."
                )

    elif st.session_state["map_level"] == "neighborhood":
        selected_map_province = canonical_province(selected_province)
        province_code = next(
            (item["code"] for item in province_features
             if clean_name(canonical_province(item["name"])) == clean_name(selected_map_province)),
            None,
        )
        district_features = get_district_features(district_geojson, province_code) if province_code else []
        district_code = st.session_state.get("selected_district_code")

        # 드롭다운에서 지역을 바꿔 온 경우에는 시군구 이름으로 코드도 다시 찾는다.
        if not district_code or not any(str(x.get("code")) == str(district_code) for x in district_features):
            normalized_target = clean_name(selected_district)
            exact = [x for x in district_features
                     if clean_name(x["name"]) == normalized_target
                     or clean_name(x["full_name"]) == normalized_target]
            if not exact:
                exact = [x for x in district_features
                         if normalized_target and (normalized_target in clean_name(x["full_name"])
                                                   or clean_name(x["name"]) in normalized_target)]
            district_code = exact[0]["code"] if exact else None

        back_col, title_col, national_col = st.columns([1.25, 3, 1.25])
        with back_col:
            if st.button("← 시·군·구 지도", use_container_width=True):
                st.session_state["map_level"] = "district"
                st.rerun()
        with title_col:
            st.subheader(f"{selected_province} {selected_district} 읍·면·동 확대 지도")
        with national_col:
            if st.button("전국으로 돌아가기", use_container_width=True):
                st.session_state["map_level"] = "nation"
                st.rerun()

        if not district_code:
            st.warning("선택한 시군구의 지도 코드를 찾지 못했습니다. 시군구를 다시 선택해 주세요.")
        else:
            neighborhood_options_for_map = [x for x in neighborhood_options if x]
            neighborhood_features = get_neighborhood_features(
                neighborhood_geojson, province_code, district_code, neighborhood_options_for_map
            )
            if not neighborhood_features:
                st.warning("이 시군구의 읍·면·동 경계 자료를 찾지 못했습니다. 위의 읍·면·동 선택 메뉴는 계속 사용할 수 있습니다.")
            else:
                neighborhood_population_lookup = {
                    clean_name(row["동"]): float(row["총인구"])
                    for _, row in neighborhood_summary[
                        (neighborhood_summary["시도"] == selected_province)
                        & (neighborhood_summary["시군구"] == selected_district)
                    ][["동", "총인구"]].iterrows()
                }
                # 행정동명이 여러 법정동 경계와 연결될 수 있어 동일 인구값을 공유한다.
                neighborhood_values = {}
                for item in neighborhood_features:
                    neighborhood_values[clean_name(item["name"])] = neighborhood_population_lookup.get(
                        clean_name(item.get("csv_name") or item["name"]), 0.0
                    )

                neighborhood_fig = make_map(
                    neighborhood_features,
                    neighborhood_values,
                    f"{selected_province} {selected_district} 읍·면·동별 총인구",
                    "EMD_CD",
                )
                clicks = plotly_events(
                    neighborhood_fig,
                    click_event=True,
                    select_event=False,
                    hover_event=False,
                    override_height=640,
                    key=f"neighborhood_drill_map_{clean_name(selected_province)}_{clean_name(selected_district)}",
                )
                item = resolve_map_click(clicks, neighborhood_features)
                if item:
                    csv_name = item.get("csv_name")
                    if csv_name in neighborhood_options:
                        click_signature = f"neighborhood:{selected_province}:{selected_district}:{item['code']}"
                        if (st.session_state.get("last_map_click") != click_signature
                                or selected_neighborhood != csv_name):
                            st.session_state["last_map_click"] = click_signature
                            st.session_state["pending_neighborhood"] = csv_name
                            st.rerun()
                    else:
                        st.info(
                            f"지도 경계 '{item['legal_name']}'를 인구 CSV의 읍·면·동과 자동 연결하지 못했습니다. "
                            "위의 읍·면·동 선택 메뉴에서 지역을 선택할 수 있습니다."
                        )
                st.caption(
                    "지도에서 읍·면·동을 클릭하면 인구 피라미드와 상세 인구 지표가 해당 지역 기준으로 갱신됩니다. "
                    "경계는 법정동 단위이며, 인구값은 가능한 경우 연결된 행정동 기준으로 표시합니다."
                )

except Exception as exc:
    st.warning(
        "지도를 불러오지 못했습니다. 지역 드롭다운과 인구 피라미드는 계속 사용할 수 있습니다."
    )
    with st.expander("지도 오류 상세 정보"):
        st.code(str(exc))


# ------------------------------------------------------------
# 10. 별도 UI: 시군구 인구 상세 대시보드
# ------------------------------------------------------------
st.divider()
st.header("🏘️ 지역 인구 상세 정보")
st.markdown(
    f"<p class='small-note'>선택 지역: <b>{selected_province} {selected_district} {selected_neighborhood}</b> · 기준 연도: {latest_year}년</p>",
    unsafe_allow_html=True,
)

local_row_df = neighborhood_summary[
    (neighborhood_summary["시도"] == selected_province)
    & (neighborhood_summary["시군구"] == selected_district)
    & (neighborhood_summary["동"] == selected_neighborhood)
]
district_row_df = district_summary[
    (district_summary["시도"] == selected_province)
    & (district_summary["시군구"] == selected_district)
]

if local_row_df.empty:
    st.info("선택한 읍·면·동의 집계 정보를 찾을 수 없습니다.")
else:
    district_row = local_row_df.iloc[0]
    metrics = population_metrics(district_row, age_labels)

    # 핵심 지표를 별도 카드 형태로 표시한다.
    st.subheader("선택한 읍·면·동의 인구 현황")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("총인구", f"{fmt_number(metrics['total'])}명")
    c2.metric("남녀 성비", f"{fmt_ratio(metrics['sex_ratio'])}", help="여자 100명당 남자 수")
    c3.metric("65세 이상 비율", fmt_percent(metrics["elderly_share"]))
    c4.metric("근사 평균 연령", f"{metrics['average_age']:.1f}세" if not pd.isna(metrics["average_age"]) else "자료 없음")

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("0~14세", f"{fmt_number(metrics['children'])}명")
    c6.metric("15~64세", f"{fmt_number(metrics['working'])}명")
    c7.metric("65세 이상", f"{fmt_number(metrics['elderly'])}명")
    c8.metric("80세 이상", f"{fmt_number(metrics['elderly80'])}명")

    st.markdown("#### 지역 고령화·부양 지표")
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("고령화율 (65세 이상)", fmt_percent(metrics["elderly_share"]))
    r2.metric("유소년 비율 (0~14세)", fmt_percent(metrics["children_share"]))
    r3.metric("노령화 지수", fmt_ratio(metrics["aging_index"]), help="65세 이상 인구 ÷ 0~14세 인구 × 100")
    r4.metric("총부양비", fmt_ratio(metrics["dependency_ratio"]), help="(0~14세 + 65세 이상) ÷ 15~64세 × 100")

    if not district_row_df.empty:
        district_metrics = population_metrics(district_row_df.iloc[0], age_labels)
        st.markdown("#### 읍·면·동과 시·군·구 비교")
        compare_df = pd.DataFrame({
            "지표": ["총인구", "고령화율", "유소년 비율", "생산연령인구 비율", "80세 이상 비율", "노령화 지수", "총부양비"],
            "선택한 읍·면·동": [
                f"{fmt_number(metrics['total'])}명", fmt_percent(metrics['elderly_share']),
                fmt_percent(metrics['children_share']), fmt_percent(metrics['working_share']),
                fmt_percent(metrics['elderly80_share']), fmt_ratio(metrics['aging_index']),
                fmt_ratio(metrics['dependency_ratio']),
            ],
            "시·군·구 전체": [
                f"{fmt_number(district_metrics['total'])}명", fmt_percent(district_metrics['elderly_share']),
                fmt_percent(district_metrics['children_share']), fmt_percent(district_metrics['working_share']),
                fmt_percent(district_metrics['elderly80_share']), fmt_ratio(district_metrics['aging_index']),
                fmt_ratio(district_metrics['dependency_ratio']),
            ],
        })
        st.dataframe(compare_df, use_container_width=True, hide_index=True)

    # 탭으로 정보가 서로 섞이지 않게 분리한다.
    tab_overview, tab_age, tab_table = st.tabs(
        ["📌 인구 구조 요약", "📊 연령대별 비교", "📋 연령별 상세 표"]
    )

    with tab_overview:
        left, right = st.columns([1.1, 1])
        with left:
            st.markdown("#### 연령 구조")
            composition = pd.DataFrame({
                "연령대": ["0~14세", "15~64세", "65세 이상"],
                "인구": [
                    metrics["children"],
                    metrics["working"],
                    metrics["elderly"],
                ],
            })
            composition_fig = go.Figure(go.Pie(
                labels=composition["연령대"],
                values=composition["인구"],
                hole=0.58,
                marker=dict(colors=["#E8C7A8", "#D48C6D", "#A94F35"]),
                textinfo="label+percent",
                hovertemplate="%{label}<br>%{value:,.0f}명 (%{percent})<extra></extra>",
            ))
            composition_fig.update_layout(
                height=340,
                margin=dict(l=5, r=5, t=10, b=5),
                paper_bgcolor=PANEL,
                font=dict(color=INK),
                showlegend=False,
            )
            st.plotly_chart(composition_fig, use_container_width=True)

        with right:
            st.markdown("#### 인구 구조 지표")
            st.metric(
                "노령화 지수",
                fmt_ratio(metrics["aging_index"]),
                help="65세 이상 인구 ÷ 0~14세 인구 × 100",
            )
            st.metric(
                "부양비",
                fmt_ratio(metrics["dependency_ratio"]),
                help="(0~14세 인구 + 65세 이상 인구) ÷ 15~64세 인구 × 100",
            )
            st.metric("80세 이상 비율", fmt_percent(metrics["elderly80_share"]))
            st.markdown(
                "<p class='small-note'>평균 연령은 각 연령 구간을 대표하는 나이로 계산한 근삿값입니다. "
                "노령화 지수와 부양비는 인구 구조를 설명하는 지표이며, 지역의 경제적 상태를 직접 뜻하지는 않습니다.</p>",
                unsafe_allow_html=True,
            )

        st.markdown("#### 인구가 많은 연령 구간 TOP 5")
        top_df = pd.DataFrame(metrics["top_ages"], columns=["나이", "인구"])
        top_df["비율"] = top_df["인구"] / metrics["total"] * 100 if metrics["total"] else 0
        top_df["인구"] = top_df["인구"].map(lambda x: f"{int(x):,}명")
        top_df["비율"] = top_df["비율"].map(lambda x: f"{x:.1f}%")
        st.dataframe(top_df, use_container_width=True, hide_index=True)

    with tab_age:
        st.markdown("#### 연령대별 남녀 인구")
        age_group_fig = draw_age_group_chart(district_row, age_labels)
        st.plotly_chart(age_group_fig, use_container_width=True)

        sex_share = pd.DataFrame({
            "구분": ["남자", "여자"],
            "인구": [metrics["male"], metrics["female"]],
            "비율": [metrics["male_share"], metrics["female_share"]],
        })
        sex_share["인구"] = sex_share["인구"].map(lambda x: f"{int(x):,}명")
        sex_share["비율"] = sex_share["비율"].map(lambda x: f"{x:.1f}%")
        st.markdown("#### 성별 구성")
        st.dataframe(sex_share, use_container_width=True, hide_index=True)

    with tab_table:
        detail = pd.DataFrame({
            "나이": age_labels,
            "남자": [int(district_row.get(f"남_{a}", 0)) for a in age_labels],
            "여자": [int(district_row.get(f"여_{a}", 0)) for a in age_labels],
        })
        detail["합계"] = detail["남자"] + detail["여자"]
        detail["남녀 차이(남-여)"] = detail["남자"] - detail["여자"]
        st.dataframe(detail, use_container_width=True, hide_index=True)

        csv_bytes = detail.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "연령별 인구 표 CSV 다운로드",
            data=csv_bytes,
            file_name="지역_연령별_인구.csv",
            mime="text/csv",
        )

st.divider()
st.caption(
    "데이터: 제공된 전국 읍·면·동 인구 ZIP CSV. "
    "행정구역 경계: kr-admin-geojson 공개 GeoJSON(시도·시군구·법정동). "
    "지도 경계 이름과 인구 CSV의 행정구역 이름이 다르면 지도 클릭 연결이 일부 제한될 수 있습니다."
)
