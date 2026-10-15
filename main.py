# main.py
# 동네별 인구 피라미드
# Streamlit Cloud 배포용
#
# 주요 기능
# 1. CSV ZIP 파일에서 최신 연도의 인구 데이터 자동 선택
# 2. 시도 → 시군구 → 동 드롭다운
# 3. 남자는 왼쪽, 여자는 오른쪽인 인구 피라미드
# 4. 전국 시도 지도 → 시군구 지도 순서로 탐색
# 5. 지도에서 지역을 클릭하면 선택 지역의 인구 정보 표시

import json
import re
import unicodedata

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from streamlit_plotly_events import plotly_events


# --------------------------------------------------
# 1. 페이지 기본 설정과 디자인
# --------------------------------------------------

st.set_page_config(
    page_title="동네별 인구 피라미드",
    page_icon="🏡",
    layout="wide",
)

st.markdown(
    """
    <style>
    .stApp {
        background-color: #FFF9F1;
        color: #49372E;
    }

    h1, h2, h3 {
        color: #704536;
    }

    [data-testid="stMetric"] {
        background-color: #FFFFFF;
        border: 1px solid #EBD9C8;
        border-radius: 12px;
        padding: 16px;
    }

    div[data-baseweb="select"] > div {
        background-color: #FFFFFF;
        border-color: #D8BBA5;
    }

    .intro {
        color: #806A5B;
        font-size: 1rem;
        line-height: 1.8;
    }

    .section-card {
        background-color: #FFFDF9;
        border: 1px solid #EBD9C8;
        padding: 16px;
        border-radius: 12px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------
# 2. 데이터 주소
# --------------------------------------------------

# 원본 CSV가 ZIP 압축 파일이므로 pandas에서 바로 읽는다.
DATA_URL = (
    "https://raw.githubusercontent.com/"
    "first2022-cyber/contents/main/"
    "population_ts_yearly_gender.zip"
)

# 행정구역 경계 GeoJSON
PROVINCE_GEOJSON_URL = (
    "https://raw.githubusercontent.com/"
    "KnellBalm/kr-admin-geojson/main/ctprvn.geojson"
)

DISTRICT_GEOJSON_URL = (
    "https://raw.githubusercontent.com/"
    "KnellBalm/kr-admin-geojson/main/sig.geojson"
)

MALE_COLOR = "#C76F51"
FEMALE_COLOR = "#E5AC91"
MAP_COLOR = "#DDA58A"
MAP_SELECTED_COLOR = "#B85C3B"
BACKGROUND_COLOR = "#FFF9F1"
TEXT_COLOR = "#49372E"


# --------------------------------------------------
# 3. 데이터 불러오기
# --------------------------------------------------

@st.cache_data(ttl=3600, show_spinner="인구 데이터를 불러오는 중...")
def load_population():
    """ZIP 파일을 읽고 최신 연도의 데이터만 반환한다."""

    errors = []

    # 저장소 파일의 인코딩이 다를 가능성에 대비한다.
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
    else:
        raise RuntimeError(
            "인구 데이터 파일을 읽지 못했습니다.\n"
            + "\n".join(errors)
        )

    # 열 이름 앞뒤의 공백을 제거한다.
    df.columns = [str(c).strip() for c in df.columns]

    # 실제 CSV의 열 이름을 확인한다.
    required = ["연도", "시도", "시군구", "동"]
    missing = [c for c in required if c not in df.columns]

    if missing:
        raise ValueError(
            f"필수 열이 없습니다: {missing}\n"
            f"실제 열 이름: {df.columns.tolist()[:30]}"
        )

    # 연도를 숫자로 바꾸고, 가장 최신 연도만 선택한다.
    df["연도"] = pd.to_numeric(df["연도"], errors="coerce")
    df = df.dropna(subset=["연도"]).copy()

    if df.empty:
        raise ValueError("연도 정보가 있는 데이터가 없습니다.")

    latest_year = int(df["연도"].max())
    df = df[df["연도"] == latest_year].copy()

    # 지역 이름의 앞뒤 공백을 정리한다.
    for col in ["시도", "시군구", "동"]:
        df[col] = df[col].fillna("").astype(str).str.strip()

    # 남_0세, 여_0세, 남_100세 이상 등의 열을 찾는다.
    age_pattern = re.compile(r"^[남여]_(\d+세|100세\s*이상)$")

    age_columns = [
        c for c in df.columns
        if age_pattern.match(c)
    ]

    if not age_columns:
        raise ValueError(
            "연령별 남녀 인구 열을 찾지 못했습니다. "
            "CSV의 열 이름을 확인해 주세요."
        )

    # 연령 열의 정렬 기준을 만든다.
    def age_number(label):
        if "100세" in label:
            return 100
        return int(re.search(r"\d+", label).group())

    age_labels = sorted(
        {age_pattern.match(c).group(1).replace(" ", "")
         for c in age_columns},
        key=age_number,
    )

    # 모든 인구 열을 숫자로 변환한다.
    for col in age_columns:
        df[col] = pd.to_numeric(
            df[col].astype(str).str.replace(",", "", regex=False),
            errors="coerce",
        ).fillna(0)

    return df, latest_year, age_labels, age_columns


@st.cache_data(ttl=86400, show_spinner=False)
def load_geojson(url):
    """웹에 있는 GeoJSON을 불러온다."""
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.json()


# --------------------------------------------------
# 4. 지역 이름 정리 함수
# --------------------------------------------------

def clean_name(value):
    """공백과 유니코드 표기 차이를 줄여 지역명을 비교한다."""
    if value is None:
        return ""
    value = unicodedata.normalize("NFKC", str(value))
    return re.sub(r"\s+", "", value.strip())


def find_property(feature, candidates):
    """GeoJSON 속성에서 후보 이름 중 실제 존재하는 값을 찾는다."""
    properties = feature.get("properties", {})
    for candidate in candidates:
        if candidate in properties:
            return properties[candidate]
    return None


def get_province_features(geojson):
    """시도 지도에서 사용할 이름과 코드를 정리한다."""
    result = []

    for feature in geojson.get("features", []):
        props = feature.get("properties", {})

        name = find_property(
            feature,
            ["CTP_KOR_NM", "CTP_KOR_NM", "name", "NAME_1"],
        )
        code = find_property(
            feature,
            ["CTPRVN_CD", "CTPRVNCD", "code"],
        )

        if name is None or code is None:
            continue

        result.append({
            "feature": feature,
            "name": str(name).strip(),
            "code": str(code).strip(),
        })

    return result


def get_district_features(geojson, province_code):
    """선택한 시도에 속한 시군구만 추린다."""
    result = []

    for feature in geojson.get("features", []):
        props = feature.get("properties", {})

        code = find_property(
            feature,
            ["SIG_CD", "SIG_CD", "SIGCD", "code"],
        )
        province = find_property(
            feature,
            ["CTPRVN_CD", "CTPRVNCD"],
        )
        full_name = find_property(
            feature,
            ["FULL_NM", "SIG_KOR_NM", "name"],
        )
        district_name = find_property(
            feature,
            ["SIG_KOR_NM", "name", "NAME_2"],
        )

        if code is None or district_name is None:
            continue

        # 시군구 코드의 앞 두 자리는 일반적으로 시도 코드다.
        code_text = str(code).strip()
        province_text = (
            str(province).strip()
            if province is not None
            else code_text[:2]
        )

        if province_text != str(province_code).strip():
            continue

        result.append({
            "feature": feature,
            "name": str(district_name).strip(),
            "full_name": str(full_name or district_name).strip(),
            "code": code_text,
        })

    return result


# --------------------------------------------------
# 5. 인구 집계 함수
# --------------------------------------------------

def add_total_population(df, age_labels):
    """연령별 남녀 인구를 합산해 총인구 열을 추가한다."""
    df = df.copy()

    male_cols = [
        f"남_{age}" for age in age_labels
        if f"남_{age}" in df.columns
    ]
    female_cols = [
        f"여_{age}" for age in age_labels
        if f"여_{age}" in df.columns
    ]

    df["남자_총인구"] = df[male_cols].sum(axis=1)
    df["여자_총인구"] = df[female_cols].sum(axis=1)
    df["총인구"] = df["남자_총인구"] + df["여자_총인구"]

    return df


def aggregate_region(df, group_cols, age_labels):
    """여러 읍면동의 인구를 시군구 또는 시도 단위로 합산한다."""
    sum_cols = []

    for age in age_labels:
        for gender in ["남", "여"]:
            col = f"{gender}_{age}"
            if col in df.columns:
                sum_cols.append(col)

    result = (
        df.groupby(group_cols, dropna=False)[sum_cols]
        .sum()
        .reset_index()
    )

    result["남자_총인구"] = result[
        [f"남_{age}" for age in age_labels
         if f"남_{age}" in result.columns]
    ].sum(axis=1)

    result["여자_총인구"] = result[
        [f"여_{age}" for age in age_labels
         if f"여_{age}" in result.columns]
    ].sum(axis=1)

    result["총인구"] = (
        result["남자_총인구"] + result["여자_총인구"]
    )

    return result


# --------------------------------------------------
# 6. 인구 피라미드 그리기
# --------------------------------------------------

def draw_population_pyramid(row, age_labels, title):
    """남자는 음수, 여자는 양수로 그리는 가로 막대그래프."""

    male_values = []
    female_values = []

    for age in age_labels:
        male_values.append(
            -float(row.get(f"남_{age}", 0) or 0)
        )
        female_values.append(
            float(row.get(f"여_{age}", 0) or 0)
        )

    fig = go.Figure()

    fig.add_trace(
        go.Bar(
            name="남자",
            y=age_labels,
            x=male_values,
            orientation="h",
            marker_color=MALE_COLOR,
            hovertemplate=(
                "나이: %{y}<br>"
                "남자 인구: %{customdata:,}명"
                "<extra></extra>"
            ),
            customdata=[abs(v) for v in male_values],
        )
    )

    fig.add_trace(
        go.Bar(
            name="여자",
            y=age_labels,
            x=female_values,
            orientation="h",
            marker_color=FEMALE_COLOR,
            hovertemplate=(
                "나이: %{y}<br>"
                "여자 인구: %{x:,}명"
                "<extra></extra>"
            ),
        )
    )

    max_value = max(
        [abs(v) for v in male_values + female_values] + [1]
    )
    axis_limit = max_value * 1.12

    # 중요:
    # y축의 전체 방향을 뒤집지 않는다.
    # 0세부터 100세 이상까지의 라벨을 직접 지정한다.
    # Plotly의 범주축에서 첫 번째 항목이 맨 아래에 오도록
    # categoryorder=array와 categoryarray를 지정한다.
    fig.update_layout(
        title={
            "text": title,
            "x": 0.5,
            "xanchor": "center",
        },
        barmode="relative",
        bargap=0.12,
        height=max(650, len(age_labels) * 11),
        paper_bgcolor=BACKGROUND_COLOR,
        plot_bgcolor=BACKGROUND_COLOR,
        font=dict(
            family="Arial, sans-serif",
            color=TEXT_COLOR,
            size=12,
        ),
        margin=dict(l=75, r=35, t=75, b=60),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.01,
            xanchor="center",
            x=0.5,
        ),
        xaxis=dict(
            title="인구 수 (명)",
            range=[-axis_limit, axis_limit],
            tickmode="array",
            tickvals=[
                -axis_limit,
                -axis_limit / 2,
                0,
                axis_limit / 2,
                axis_limit,
            ],
            ticktext=[
                f"{axis_limit:,.0f}",
                f"{axis_limit / 2:,.0f}",
                "0",
                f"{axis_limit / 2:,.0f}",
                f"{axis_limit:,.0f}",
            ],
            zeroline=True,
            zerolinewidth=1,
            zerolinecolor="#BDA696",
            gridcolor="#EADDD1",
        ),
        yaxis=dict(
            title="나이",
            categoryorder="array",
            categoryarray=age_labels,
            autorange=True,
            type="category",
            gridcolor="#F0E5DB",
        ),
    )

    return fig


# --------------------------------------------------
# 7. 지도 그리기
# --------------------------------------------------

def make_map(features, name_key, code_key, value_map, title):
    """GeoJSON을 사용해 클릭 가능한 지역별 단계구분도를 만든다."""

    geojson = {
        "type": "FeatureCollection",
        "features": [item["feature"] for item in features],
    }

    locations = [item["code"] for item in features]
    names = [item["name"] for item in features]
    values = [
        float(value_map.get(clean_name(item["name"]), 0))
        for item in features
    ]

    # 값이 모두 같거나 0인 경우에도 지도가 표시되게 한다.
    maximum = max(values + [1])

    fig = go.Figure(
        go.Choropleth(
            geojson=geojson,
            locations=locations,
            z=values,
            featureidkey=f"properties.{code_key}",
            text=names,
            customdata=np.array(names).reshape(-1, 1),
            colorscale=[
                [0.0, "#F8E9DA"],
                [0.35, "#E8BDA0"],
                [0.7, "#D48C6D"],
                [1.0, "#A94F35"],
            ],
            zmin=0,
            zmax=maximum,
            marker_line_color="#FFF9F1",
            marker_line_width=1.0,
            colorbar=dict(
                title="총인구",
                tickformat=",",
                thickness=14,
            ),
            hovertemplate=(
                "%{text}<br>"
                "총인구: %{z:,.0f}명"
                "<extra></extra>"
            ),
        )
    )

    fig.update_geos(
        fitbounds="locations",
        visible=False,
        bgcolor=BACKGROUND_COLOR,
        showland=True,
        landcolor="#FFF9F1",
        showcountries=False,
        showcoastlines=False,
    )

    fig.update_layout(
        title=title,
        height=600,
        margin=dict(l=0, r=0, t=55, b=0),
        paper_bgcolor=BACKGROUND_COLOR,
        plot_bgcolor=BACKGROUND_COLOR,
        font=dict(color=TEXT_COLOR),
    )

    return fig


# --------------------------------------------------
# 8. 앱 시작
# --------------------------------------------------

st.title("🏡 동네별 인구 피라미드")

st.markdown(
    """
    <p class="intro">
    우리 동네에는 어떤 연령대가 많이 살고 있을까요?
    전국의 시도부터 읍·면·동까지 탐색하며
    남녀 인구 구조를 살펴보세요.
    </p>
    """,
    unsafe_allow_html=True,
)

try:
    raw_df, latest_year, age_labels, age_columns = load_population()
except Exception as exc:
    st.error("인구 데이터를 불러오는 중 문제가 발생했습니다.")
    st.code(str(exc))
    st.info(
        "원본 ZIP 주소와 CSV 열 이름을 확인해 주세요. "
        "네트워크 문제라면 잠시 후 다시 시도할 수 있습니다."
    )
    st.stop()

df = add_total_population(raw_df, age_labels)

# 연령 열 목록은 실제 CSV의 형식에 맞춰 다시 정리한다.
male_age_cols = [
    f"남_{age}" for age in age_labels
    if f"남_{age}" in df.columns
]
female_age_cols = [
    f"여_{age}" for age in age_labels
    if f"여_{age}" in df.columns
]

st.caption(
    f"📅 분석 연도: {latest_year}년 · "
    f"연령 구간: {len(age_labels)}개 · "
    "원본 인구 데이터 기준"
)

# 전국 합계는 지역별 행을 단순 합산한 값이다.
national_male = int(df[male_age_cols].sum().sum())
national_female = int(df[female_age_cols].sum().sum())

m1, m2, m3 = st.columns(3)
m1.metric("전국 남자 인구", f"{national_male:,}명")
m2.metric("전국 여자 인구", f"{national_female:,}명")
m3.metric(
    "전국 총인구",
    f"{national_male + national_female:,}명",
)

st.divider()


# --------------------------------------------------
# 9. 지역 선택 드롭다운
# --------------------------------------------------

st.header("📍 지역 선택")

province_options = sorted(
    [x for x in df["시도"].unique() if x]
)

if not province_options:
    st.error("시도 목록이 비어 있습니다.")
    st.stop()

# 지도에서 선택한 지역이 있으면 드롭다운에도 반영한다.
if "map_province" not in st.session_state:
    st.session_state.map_province = province_options[0]

if st.session_state.map_province not in province_options:
    st.session_state.map_province = province_options[0]

province_index = province_options.index(
    st.session_state.map_province
)

selected_province = st.selectbox(
    "① 시도 / 광역시",
    province_options,
    index=province_index,
    key="province_select",
)

st.session_state.map_province = selected_province

province_df = df[df["시도"] == selected_province].copy()

district_options = sorted(
    [x for x in province_df["시군구"].unique() if x]
)

if not district_options:
    district_options = [""]

if "map_district" not in st.session_state:
    st.session_state.map_district = district_options[0]

if st.session_state.map_district not in district_options:
    st.session_state.map_district = district_options[0]

district_index = district_options.index(
    st.session_state.map_district
)

selected_district = st.selectbox(
    "② 시군구",
    district_options,
    index=district_index,
    key="district_select",
)

st.session_state.map_district = selected_district

district_df = province_df[
    province_df["시군구"] == selected_district
].copy()

neighborhood_options = sorted(
    [x for x in district_df["동"].unique() if x]
)

if not neighborhood_options:
    neighborhood_options = [""]

if "map_neighborhood" not in st.session_state:
    st.session_state.map_neighborhood = neighborhood_options[0]

if st.session_state.map_neighborhood not in neighborhood_options:
    st.session_state.map_neighborhood = neighborhood_options[0]

neighborhood_index = neighborhood_options.index(
    st.session_state.map_neighborhood
)

selected_neighborhood = st.selectbox(
    "③ 읍·면·동",
    neighborhood_options,
    index=neighborhood_index,
    key="neighborhood_select",
)

st.session_state.map_neighborhood = selected_neighborhood


# --------------------------------------------------
# 10. 선택한 동네의 인구 피라미드
# --------------------------------------------------

st.divider()
st.header("📊 인구 피라미드")

selected_rows = district_df[
    district_df["동"] == selected_neighborhood
]

if selected_rows.empty:
    st.warning("선택한 지역의 인구 데이터가 없습니다.")
else:
    # 같은 동 이름이 여러 행에 있더라도 연령별로 합산한다.
    selected_population = selected_rows[
        male_age_cols + female_age_cols
    ].sum()

    total_male = int(selected_population[male_age_cols].sum())
    total_female = int(selected_population[female_age_cols].sum())
    total_population = total_male + total_female

    a, b, c = st.columns(3)
    a.metric("총인구", f"{total_population:,}명")
    b.metric("남자", f"{total_male:,}명")
    c.metric("여자", f"{total_female:,}명")

    location_title = (
        f"{selected_province} "
        f"{selected_district} "
        f"{selected_neighborhood}"
    )

    fig = draw_population_pyramid(
        selected_population,
        age_labels,
        f"{location_title} 인구 피라미드 ({latest_year}년)",
    )

    st.plotly_chart(
        fig,
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
        "읽는 법: 왼쪽은 남자, 오른쪽은 여자입니다. "
        "세로축은 0세부터 100세 이상까지 나이순으로 배열됩니다."
    )

    with st.expander("연령별 인구 표 보기"):
        age_table = pd.DataFrame({
            "나이": age_labels,
            "남자": [
                int(selected_population.get(f"남_{age}", 0))
                for age in age_labels
            ],
            "여자": [
                int(selected_population.get(f"여_{age}", 0))
                for age in age_labels
            ],
        })
        age_table["합계"] = age_table["남자"] + age_table["여자"]
        st.dataframe(
            age_table,
            use_container_width=True,
            hide_index=True,
        )


# --------------------------------------------------
# 11. 지도용 집계 데이터
# --------------------------------------------------

st.divider()
st.header("🗺️ 지도에서 지역 탐색하기")

st.markdown(
    """
    아래 지도에서 지역을 클릭해 보세요.
    먼저 전국 지도에서 시도를 선택하고,
    다음 지도에서 시군구를 선택할 수 있습니다.
    지도 경계 자료의 행정구역 명칭과 인구 CSV의 명칭이
    일치하지 않는 곳은 드롭다운으로 확인해 주세요.
    """
)

# 지도에서 사용할 시도별 인구
province_summary = aggregate_region(
    df,
    ["시도"],
    age_labels,
)

province_value_map = {
    clean_name(row["시도"]): float(row["총인구"])
    for _, row in province_summary.iterrows()
}

# 시군구별 인구
district_summary = aggregate_region(
    df,
    ["시도", "시군구"],
    age_labels,
)

district_value_map = {
    clean_name(row["시군구"]): float(row["총인구"])
    for _, row in district_summary.iterrows()
}


# --------------------------------------------------
# 12. 전국 시도 지도
# --------------------------------------------------

try:
    province_geojson = load_geojson(PROVINCE_GEOJSON_URL)
    province_features = get_province_features(province_geojson)

    if not province_features:
        raise ValueError(
            "시도 GeoJSON에서 이름이나 코드 속성을 찾지 못했습니다."
        )

    province_name_to_code = {
        clean_name(item["name"]): item["code"]
        for item in province_features
    }

    # CSV 이름과 지도 이름의 공백 차이를 줄여 매칭한다.
    province_name_map = {
        clean_name(name): name
        for name in province_options
    }

    # 지도에 표시할 값은 실제 GeoJSON의 시도 이름으로 연결한다.
    province_map_values = {}
    for item in province_features:
        key = clean_name(item["name"])
        matched_csv_name = province_name_map.get(key)
        if matched_csv_name is not None:
            province_map_values[key] = province_value_map.get(
                clean_name(matched_csv_name), 0
            )
        else:
            province_map_values[key] = 0

    province_fig = make_map(
        province_features,
        "name",
        "CTPRVN_CD",
        province_map_values,
        "전국 시도별 총인구",
    )

    province_clicks = plotly_events(
        province_fig,
        click_event=True,
        select_event=False,
        hover_event=False,
        override_height=600,
        key="province_map",
    )

    if province_clicks:
        clicked_code = str(
            province_clicks[0].get("location", "")
        )
        clicked_item = next(
            (
                item for item in province_features
                if item["code"] == clicked_code
            ),
            None,
        )

        if clicked_item:
            clicked_name = clean_name(clicked_item["name"])
            csv_name = province_name_map.get(clicked_name)

            if csv_name in province_options:
                if st.session_state.map_province != csv_name:
                    st.session_state.map_province = csv_name
                    st.session_state.map_district = ""
                    st.session_state.map_neighborhood = ""
                    st.rerun()

    st.caption(
        "지도에서 시도를 클릭하면 위쪽 지역 선택 항목이 갱신됩니다."
    )

except Exception as exc:
    st.warning(
        "전국 지도 경계 자료를 불러오지 못했습니다. "
        "위쪽 드롭다운은 계속 사용할 수 있습니다."
    )
    with st.expander("지도 오류 상세 정보"):
        st.code(str(exc))


# --------------------------------------------------
# 13. 선택한 시도의 시군구 지도
# --------------------------------------------------

st.subheader(f"📌 {selected_province} 시군구 지도")

try:
    district_geojson = load_geojson(DISTRICT_GEOJSON_URL)

    province_code = province_name_to_code.get(
        clean_name(selected_province)
    )

    if province_code is None:
        # 이름이 미세하게 다른 경우에는 정규화된 이름으로 재검색한다.
        province_code = next(
            (
                code for name, code in province_name_to_code.items()
                if name in clean_name(selected_province)
                or clean_name(selected_province) in name
            ),
            None,
        )

    if province_code is None:
        st.info(
            "선택한 시도의 지도 코드를 찾지 못했습니다. "
            "드롭다운을 이용해 지역을 선택해 주세요."
        )
    else:
        district_features = get_district_features(
            district_geojson,
            province_code,
        )

        if not district_features:
            st.info(
                "이 시도의 시군구 경계를 불러오지 못했습니다. "
                "위쪽 드롭다운에서 지역을 선택해 주세요."
            )
        else:
            # 지도에 표시하는 이름은 CSV의 시군구와 비교해 정리한다.
            csv_district_names = {
                clean_name(name): name
                for name in district_options
            }

            district_map_values = {}

            for item in district_features:
                map_name = clean_name(item["name"])
                full_name = clean_name(item["full_name"])

                matched_name = csv_district_names.get(map_name)

                if matched_name is None:
                    matched_name = csv_district_names.get(full_name)

                # 일부 경계 자료에는 시도명이 포함되어 있을 수 있다.
                if matched_name is None:
                    matched_name = next(
                        (
                            name for normalized, name
                            in csv_district_names.items()
                            if normalized in map_name
                            or map_name in normalized
                            or normalized in full_name
                            or full_name in normalized
                        ),
                        None,
                    )

                value = (
                    district_value_map.get(
                        clean_name(selected_province + matched_name),
                        None,
                    )
                    if matched_name
                    else None
                )

                if value is None and matched_name:
                    row_match = district_summary[
                        (district_summary["시도"] == selected_province)
                        & (district_summary["시군구"] == matched_name)
                    ]
                    value = (
                        float(row_match["총인구"].iloc[0])
                        if not row_match.empty
                        else 0
                    )

                district_map_values[map_name] = float(value or 0)

            district_fig = make_map(
                district_features,
                "name",
                "SIG_CD",
                district_map_values,
                f"{selected_province} 시군구별 총인구",
            )

            district_clicks = plotly_events(
                district_fig,
                click_event=True,
                select_event=False,
                hover_event=False,
                override_height=600,
                key="district_map",
            )

            if district_clicks:
                clicked_code = str(
                    district_clicks[0].get("location", "")
                )

                clicked_item = next(
                    (
                        item for item in district_features
                        if item["code"] == clicked_code
                    ),
                    None,
                )

                if clicked_item:
                    clicked_map_name = clean_name(clicked_item["name"])
                    clicked_full_name = clean_name(
                        clicked_item["full_name"]
                    )

                    matched_district = next(
                        (
                            name for name in district_options
                            if clean_name(name) == clicked_map_name
                            or clean_name(name) == clicked_full_name
                            or clean_name(name) in clicked_full_name
                            or clicked_full_name in clean_name(name)
                        ),
                        None,
                    )

                    if matched_district:
                        st.session_state.map_district = matched_district
                        st.session_state.map_neighborhood = ""
                        st.rerun()
                    else:
                        st.info(
                            f"지도에서 선택한 지역: {clicked_item['name']}. "
                            "CSV의 시군구 이름과 정확히 일치하지 않아 "
                            "드롭다운에서 선택해 주세요."
                        )

            st.caption(
                "시군구를 클릭하면 해당 시군구가 선택되고, "
                "위의 인구 피라미드와 지역 선택 항목이 갱신됩니다."
            )

except Exception as exc:
    st.warning(
        "시군구 지도를 표시하지 못했습니다. "
        "드롭다운으로 인구 정보를 확인할 수 있습니다."
    )
    with st.expander("지도 오류 상세 정보"):
        st.code(str(exc))


# --------------------------------------------------
# 14. 선택한 시군구 전체 인구 정보
# --------------------------------------------------

st.divider()
st.header("🏘️ 선택한 시군구 인구 요약")

summary_rows = district_summary[
    (district_summary["시도"] == selected_province)
    & (district_summary["시군구"] == selected_district)
]

if not summary_rows.empty:
    summary = summary_rows.iloc[0]

    s1, s2, s3 = st.columns(3)
    s1.metric("시군구 총인구", f"{int(summary['총인구']):,}명")
    s2.metric("남자 총인구", f"{int(summary['남자_총인구']):,}명")
    s3.metric("여자 총인구", f"{int(summary['여자_총인구']):,}명")

    # 시군구 단위에서도 연령별 남녀 인구 피라미드를 제공한다.
    st.subheader(
        f"{selected_province} {selected_district} 전체 인구 피라미드"
    )

    district_population = summary.copy()

    district_fig = draw_population_pyramid(
        district_population,
        age_labels,
        f"{selected_district} 전체 인구 피라미드 ({latest_year}년)",
    )

    st.plotly_chart(
        district_fig,
        use_container_width=True,
        config={"displayModeBar": True, "displaylogo": False},
    )

st.divider()

st.caption(
    "데이터 출처: 제공된 전국 읍·면·동 인구 CSV. "
    "지도 경계 출처: kr-admin-geojson 공개 저장소. "
    "집계 결과는 원본 데이터의 행정구역 단위와 범위에 따라 달라질 수 있습니다."
)
