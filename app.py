import streamlit as st
import requests

# 📌 페이지 기본 설정
st.set_page_config(page_title="실시간 선박 제재 검색", layout="wide")

st.title("🚢 실시간 선박 제재 자동 검색 시스템")
st.write("미국(OFAC), 유럽(EU), UN 등의 실제 제재 데이터를 실시간으로 조회합니다.")
st.divider()

DATASET_MAP = {
    "us_ofac_sdn": "미국 재무부 (OFAC SDN)",
    "us_ofac_cons": "미국 재무부 (OFAC 통합)",
    "eu_fsf": "유럽연합 (EU FSF)",
    "eu_sanctions_map": "유럽연합 (EU Sanctions Map)",
    "eu_journal_sanctions": "유럽연합 (EU Journal)",
    "un_sc_sanctions": "국제연합 (UN 안보리)",
    "kr_dprk_sanctions": "대한민국 (독자제재)",
    "gb_fcdo_sanctions": "영국 (FCDO)",
    "uk_hmts_sanc": "영국 재무부",
    "ua_war_sanctions": "우크라이나 (전쟁 제재)",
    "tokyo_mou_detention": "Tokyo MOU (억류 이력)"
}

try:
    OPENSANCTIONS_KEY = st.secrets["OPENSANCTIONS_KEY"]
except Exception:
    OPENSANCTIONS_KEY = None

try:
    VESSELAPI_KEY = st.secrets["VESSELAPI_KEY"]
except Exception:
    VESSELAPI_KEY = None


def _entity_name(entity):
    return entity.get("properties", {}).get("name", ["이름 없음"])[0]


def _opensanctions_url(entity):
    """OpenSanctions 웹사이트에서 이 엔티티(선박)의 상세 프로필 페이지 URL.
    entity id (예: NK-xxxxx)를 그대로 붙이면 된다. 이 페이지에는 어느 제재
    리스트에 근거했는지, 원본 정부 발표 문서 링크 등 상세 정보가 나온다."""
    entity_id = entity.get("id")
    return f"https://www.opensanctions.org/entities/{entity_id}/" if entity_id else None


def get_vessel_name(imo_number):
    """VesselAPI.com에서 IMO 번호로 실제 등록 선박명을 조회한다.
    키는 반드시 st.secrets(Streamlit Secrets)로만 넣는다 — 코드 파일에 키를
    직접 박아 넣으면 GitHub 등에 코드를 올릴 때 그대로 노출되기 때문이다."""
    if not VESSELAPI_KEY:
        return None

    url = f"https://api.vesselapi.com/v1/vessel/{imo_number}"
    params = {"filter.idType": "imo"}
    headers = {"Authorization": f"Bearer {VESSELAPI_KEY}"}

    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        if response.status_code == 401:
            return "VesselAPI 키 인증 실패"
        elif response.status_code == 404:
            return "선박 등록 정보 없음"
        elif response.status_code != 200:
            return f"선박명 조회 실패 (HTTP {response.status_code})"

        data = response.json()
        vessel = data.get("vessel") or {}
        name = vessel.get("name")
        return name if name else "알 수 없음"
    except Exception as e:
        return f"선박명 조회 실패 (에러: {str(e)})"


def check_sanction(imo_number):
    """제재 여부 판정은 2단계로 이루어진다.

    1) /match/sanctions (OpenSanctions 공식 스크리닝 엔드포인트) — IMO 번호를
       구조화된 imoNumber 필드로 정확히 대조한다. score가 0.7(기본 임계값)
       이상이면 match=true 로 표시되며, 이걸 '확정 제재 대상'으로 간주한다.
       (구 버전 코드는 여기 대신 풀텍스트 검색용 /search 엔드포인트를 IMO 번호로
       조회했는데, OpenSanctions 공식 문서가 /search는 "스크리닝용이 아니다"라고
       명시하고 있어 실제 제재 대상을 놓칠 위험이 있었다.)

    2) /search/sanctions (풀텍스트 검색) — 1)번은 대상 레코드에 imoNumber 필드가
       정확히 입력돼 있어야만 잡히므로, 데이터 품질 문제로 구조화 필드가
       비어 있거나 다르게 입력된 경우를 보완하기 위한 2차 안전망으로 함께 조회한다.
       여기서 나온 결과는 '확정'이 아니라 'IMO 번호가 텍스트에 등장해 수동 확인이
       필요한 후보'로만 취급한다.

    반환값: (status, confirmed, review)
      status: "SANCTIONED" | "REVIEW" | "CLEAN" | "API_KEY_ERROR" | "ERROR"
      confirmed: /match 에서 match=true 로 확정된 엔티티 목록
      review: /search 에서만 잡힌, 수동 확인이 필요한 엔티티 목록
    """
    imo_str = str(imo_number)
    common_headers = {"Authorization": f"ApiKey {OPENSANCTIONS_KEY}"}

    confirmed = []
    match_ok = False
    try:
        match_resp = requests.post(
            "https://api.opensanctions.org/match/sanctions",
            headers={**common_headers, "Content-Type": "application/json"},
            json={"queries": {"q1": {"schema": "Vessel", "properties": {"imoNumber": [imo_str]}}}},
            timeout=15,
        )
        if match_resp.status_code == 401:
            return "API_KEY_ERROR", [], []
        if match_resp.status_code == 200:
            match_ok = True
            results = match_resp.json().get("responses", {}).get("q1", {}).get("results", [])
            confirmed = [entity for entity in results if entity.get("match")]
    except Exception:
        pass

    review = []
    search_ok = False
    try:
        search_resp = requests.get(
            "https://api.opensanctions.org/search/sanctions",
            headers=common_headers,
            params={"q": imo_str, "schema": "Vessel"},
            timeout=15,
        )
        if search_resp.status_code == 401:
            return "API_KEY_ERROR", [], []
        if search_resp.status_code == 200:
            search_ok = True
            confirmed_ids = {e.get("id") for e in confirmed}
            for entity in search_resp.json().get("results", []):
                if entity.get("id") in confirmed_ids:
                    continue
                if imo_str in str(entity.get("properties", {})):
                    review.append(entity)
    except Exception:
        pass

    if not match_ok and not search_ok:
        return "ERROR", [], []

    if confirmed:
        return "SANCTIONED", confirmed, review
    if review:
        return "REVIEW", confirmed, review
    return "CLEAN", [], []


def render_country_flags(datasets):
    is_us = any("us_ofac" in ds for ds in datasets)
    is_eu = any("eu_" in ds for ds in datasets)
    is_un = any("un_" in ds for ds in datasets)
    is_kr = any("kr_" in ds for ds in datasets)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown("**🇺🇸 미국 재무부(OFAC)**")
        if is_us:
            st.error("🔴 제재 대상")
        else:
            st.success("🟢 통과")
    with col2:
        st.markdown("**🇪🇺 유럽연합(EU)**")
        if is_eu:
            st.error("🔴 제재 대상")
        else:
            st.success("🟢 통과")
    with col3:
        st.markdown("**🇺🇳 국제연합(UN)**")
        if is_un:
            st.error("🔴 제재 대상")
        else:
            st.success("🟢 통과")
    with col4:
        st.markdown("**🇰🇷 대한민국**")
        if is_kr:
            st.error("🔴 제재 대상")
        else:
            st.success("🟢 통과")


st.subheader("1. 단건 실시간 검색")
imo_input = st.text_input("IMO 번호 7자리를 입력하고 엔터(Enter)를 치세요", max_chars=7)

if imo_input:
    if not imo_input.isdigit() or len(imo_input) != 7:
        st.warning("정확한 7자리 숫자 IMO 번호를 입력해주세요.")
    elif not OPENSANCTIONS_KEY:
        st.error("⚠️ Streamlit Secrets 설정에 API 키(OPENSANCTIONS_KEY)가 등록되지 않았습니다.")
    else:
        with st.spinner("글로벌 제재 명단을 샅샅이 조회 중입니다..."):
            status, confirmed, review = check_sanction(imo_input)

        if status in ("CLEAN", "REVIEW"):
            with st.spinner("선박명을 조회하고 있습니다..."):
                vessel_name = get_vessel_name(imo_input)
            if vessel_name:
                st.markdown(f"### 🚢 선박명: {vessel_name}")
            elif not VESSELAPI_KEY:
                st.caption("ℹ️ VESSELAPI_KEY가 등록되지 않아 선박명 조회는 생략합니다.")

        if status == "API_KEY_ERROR":
            st.error("⚠️ 제재 DB API 키 인증에 실패했거나 한도를 초과했습니다.")
        elif status == "ERROR":
            st.error("⚠️ 데이터 서버와 통신할 수 없습니다. 잠시 후 다시 시도해주세요.")
        else:
            if status == "CLEAN":
                st.success(f"🟢 IMO {imo_input} : 현재 주요 글로벌 제재 명단에서 발견되지 않았습니다. (안전)")
                render_country_flags([])
                st.markdown("---")
                st.markdown("- **전체 제재 이력:** 없음")

            elif status == "REVIEW":
                st.warning(
                    f"🟡 IMO {imo_input} : 제재 명단에 구조화된 필드로는 확정 매칭되지 않았지만, "
                    f"IMO 번호가 언급된 레코드가 있어 자동 판정이 불확실합니다. 수동 확인이 필요합니다."
                )
                for entity in review:
                    score = entity.get("score")
                    score_txt = f" (유사도 점수: {score:.2f})" if isinstance(score, (int, float)) else ""
                    st.markdown(f"### 🚧 확인 필요 레코드: {_entity_name(entity)}{score_txt}")
                    datasets = entity.get("datasets", [])
                    agencies = [DATASET_MAP.get(ds, ds) for ds in datasets if ds not in ["sanctions", "default"]]
                    st.markdown(f"- **관련 데이터셋:** {', '.join(agencies) if agencies else '기타 기관'}")
                    review_url = _opensanctions_url(entity)
                    if review_url:
                        st.link_button(
                            "🔗 OpenSanctions 상세 페이지로 이동", review_url,
                            key=f"review_link_{entity.get('id')}",
                        )
                st.markdown("---")

            elif status == "SANCTIONED":
                st.error("🔴 부적합 (제재 대상 선박 발견!)")

                if VESSELAPI_KEY:
                    with st.spinner("선박명을 교차 확인하고 있습니다..."):
                        cross_check_name = get_vessel_name(imo_input)
                    if cross_check_name:
                        st.caption(f"ℹ️ VesselAPI 등록명(교차 확인용): {cross_check_name}")

                for vessel in confirmed:
                    datasets = vessel.get("datasets", [])
                    st.markdown(f"### 🚢 선박명: {_entity_name(vessel)}")
                    render_country_flags(datasets)

                    agencies = [DATASET_MAP.get(ds, ds) for ds in datasets if ds not in ["sanctions", "default"]]
                    st.markdown("---")
                    st.markdown(f"- **전체 제재 이력 (기타 국가 포함):** {', '.join(agencies) if agencies else '기타 기관'}")

                    vessel_url = _opensanctions_url(vessel)
                    if vessel_url:
                        st.link_button(
                            "🔗 제재 상세 페이지 바로가기 (OpenSanctions)", vessel_url,
                            key=f"sanctioned_link_{vessel.get('id')}",
                        )
                    st.markdown("")

                if review:
                    st.markdown("#### 참고: 추가로 확인이 필요한 레코드")
                    for entity in review:
                        review_url = _opensanctions_url(entity)
                        link_txt = f" — [상세보기]({review_url})" if review_url else ""
                        st.markdown(f"- {_entity_name(entity)} ({', '.join(entity.get('datasets', [])) or '기타 기관'}){link_txt}")

            st.markdown(
                f"- **🇺🇸 미국 재무부 교차 검증:** [OFAC Sanctions Search](https://sanctionssearch.ofac.treas.gov/) "
                f"(필요시 클릭 후 Search 칸에 IMO `{imo_input}`를 넣어 직접 재검색도 가능합니다.)"
            )