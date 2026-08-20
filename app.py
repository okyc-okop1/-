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
    VESSELAPI_KEY = st.secrets["VESSELAPI_KEY"]
except Exception:
    OPENSANCTIONS_KEY = None
    VESSELAPI_KEY = None


def get_vessel_name(imo_number):
    """VesselAPI.com(무료 티어, 월 150회, 카드 등록 불필요)으로 IMO 번호에 대응하는
    실제 선박명을 조회한다. LLM(제미나이 등)에게 '몇 번 선박이 무슨 이름이냐'고
    묻는 방식은 실시간 선박 등록 데이터베이스가 아니라 학습된 확률 분포에서
    그럴듯한 답을 생성하는 것이라, 실제로는 존재하지만 엉뚱한 IMO 번호의
    선박명을 대답하는 '환각(hallucination)'이 발생할 수 있다.
    (예: IMO 9815604의 실제 선박명은 'IBERIAN SEA'이지만, 완전히 다른 IMO
    9850795의 선박명인 'EVER FIT'을 대답하는 식의 오류가 실제로 재현됨)
    """
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
    """OpenSanctions의 /match 엔드포인트(스크리닝 전용, 구조화된 IMO 필드 매칭)를
    사용한다. 기존 코드가 쓰던 /search 엔드포인트는 OpenSanctions 공식 문서에서
    '풀텍스트 검색이며 스크리닝용이 아니다(not for screening)'라고 명시하는
    엔드포인트라, IMO 번호로 텍스트 검색을 해도 매칭이 보장되지 않아
    실제 제재 대상을 놓치는(false negative) 위험이 있었다.
    """
    url = "https://api.opensanctions.org/match/sanctions"
    headers = {
        "Authorization": f"ApiKey {OPENSANCTIONS_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "queries": {
            "q1": {
                "schema": "Vessel",
                "properties": {"imoNumber": [str(imo_number)]},
            }
        }
    }

    try:
        response = requests.post(url, json=body, headers=headers, timeout=10)
        if response.status_code == 401:
            return "API_KEY_ERROR", []
        elif response.status_code != 200:
            return "ERROR", []

        data = response.json()
        results = data.get("responses", {}).get("q1", {}).get("results", [])
        # match=True (OpenSanctions가 자체 임계값을 넘겼다고 판단한 결과)만
        # 제재 대상으로 인정한다.
        matched_vessels = [entity for entity in results if entity.get("match")]
        return ("SANCTIONED", matched_vessels) if matched_vessels else ("CLEAN", [])
    except Exception as e:
        return "ERROR", []


st.subheader("1. 단건 실시간 검색")
imo_input = st.text_input("IMO 번호 7자리를 입력하고 엔터(Enter)를 치세요", max_chars=7)

if imo_input:
    if not imo_input.isdigit() or len(imo_input) != 7:
        st.warning("정확한 7자리 숫자 IMO 번호를 입력해주세요.")
    elif not OPENSANCTIONS_KEY or not VESSELAPI_KEY:
        st.error("⚠️ Streamlit Secrets 설정에 API 키(OPENSANCTIONS_KEY, VESSELAPI_KEY)가 등록되지 않았습니다.")
    else:
        with st.spinner("글로벌 제재 명단을 샅샅이 조회 중입니다..."):
            status, vessels = check_sanction(imo_input)

            if status == "API_KEY_ERROR":
                st.error("⚠️ 제재 DB API 키 인증에 실패했거나 한도를 초과했습니다.")
            elif status == "ERROR":
                st.error("⚠️ 데이터 서버와 통신할 수 없습니다.")
            else:
                if status == "CLEAN":
                    with st.spinner("선박명을 조회하고 있습니다..."):
                        vessel_name = get_vessel_name(imo_input)

                    st.success(f"🟢 IMO {imo_input} : 현재 주요 글로벌 제재 명단에서 발견되지 않았습니다. (안전)")
                    st.markdown(f"### 🚢 선박명: {vessel_name}")

                    col1, col2, col3, col4 = st.columns(4)
                    with col1: st.markdown("**🇺🇸 미국 재무부(OFAC)**\n\n🟢 통과")
                    with col2: st.markdown("**🇪🇺 유럽연합(EU)**\n\n🟢 통과")
                    with col3: st.markdown("**🇺🇳 국제연합(UN)**\n\n🟢 통과")
                    with col4: st.markdown("**🇰🇷 대한민국**\n\n🟢 통과")

                    st.markdown("---")
                    st.markdown("- **전체 제재 이력:** 없음")

                elif status == "SANCTIONED":
                    st.error(f"🔴 부적합 (제재 대상 선박 발견!)")

                    for vessel in vessels:
                        vessel_name = vessel.get("properties", {}).get("name", ["이름 없음"])[0]
                        datasets = vessel.get("datasets", [])

                        is_us = any("us_ofac" in ds for ds in datasets)
                        is_eu = any("eu_" in ds for ds in datasets)
                        is_un = any("un_" in ds for ds in datasets)
                        is_kr = any("kr_" in ds for ds in datasets)

                        st.markdown(f"### 🚢 선박명: {vessel_name}")

                        col1, col2, col3, col4 = st.columns(4)
                        with col1:
                            st.markdown("**🇺🇸 미국 재무부(OFAC)**")
                            if is_us: st.error("🔴 제재 대상")
                            else: st.success("🟢 통과")
                        with col2:
                            st.markdown("**🇪🇺 유럽연합(EU)**")
                            if is_eu: st.error("🔴 제재 대상")
                            else: st.success("🟢 통과")
                        with col3:
                            st.markdown("**🇺🇳 국제연합(UN)**")
                            if is_un: st.error("🔴 제재 대상")
                            else: st.success("🟢 통과")
                        with col4:
                            st.markdown("**🇰🇷 대한민국**")
                            if is_kr: st.error("🔴 제재 대상")
                            else: st.success("🟢 통과")

                        agencies = [DATASET_MAP.get(ds, ds) for ds in datasets if ds not in ["sanctions", "default"]]
                        st.markdown("---")
                        st.markdown(f"- **전체 제재 이력 (기타 국가 포함):** {', '.join(agencies) if agencies else '기타 기관'}")

                st.markdown(f"- **🇺🇸 미국 재무부 교차 검증:** [OFAC Sanctions Search](https://sanctionssearch.ofac.treas.gov/) (필요시 클릭 후 Search 칸에 IMO `{imo_input}`를 넣어 직접 재검색도 가능합니다.)")