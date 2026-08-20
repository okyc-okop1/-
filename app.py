import streamlit as st
import requests
import google.generativeai as genai

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
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
    OPENSANCTIONS_KEY = st.secrets["OPENSANCTIONS_KEY"]
    genai.configure(api_key=GEMINI_API_KEY)
except Exception:
    GEMINI_API_KEY = None
    OPENSANCTIONS_KEY = None

def get_vessel_name_from_gemini(imo_number):
    """제미나이 AI에게 IMO 번호를 주고 선박명을 물어보는 함수"""
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = f"IMO 번호 {imo_number}를 가진 선박의 이름이 무엇인가요? 부가적인 설명 없이 오직 대문자로 된 '선박명'만 정확히 한 줄로 대답해 주세요. 만약 정말 모른다면 '알 수 없음'이라고 대답해 주세요."
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        # 🚨 [수정됨] 실제 에러 메시지를 화면에 그대로 출력합니다!
        return f"상세 에러 원인 확인: {str(e)}"

def check_sanction(imo_number):
    url = "https://api.opensanctions.org/search/sanctions"
    params = {"q": imo_number, "schema": "Vessel"}
    headers = {"Authorization": f"ApiKey {OPENSANCTIONS_KEY}"} 
    
    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        if response.status_code == 401: return "API_KEY_ERROR", []
        elif response.status_code != 200: return "ERROR", []
            
        data = response.json()
        matched_vessels = [
            entity for entity in data.get("results", []) 
            if str(imo_number) in str(entity.get("properties", {}))
        ]
        return ("SANCTIONED", matched_vessels) if matched_vessels else ("CLEAN", [])
    except Exception as e:
        return "ERROR", []

st.subheader("1. 단건 실시간 검색")
imo_input = st.text_input("IMO 번호 7자리를 입력하고 엔터(Enter)를 치세요", max_chars=7)

if imo_input:
    if not imo_input.isdigit() or len(imo_input) != 7:
        st.warning("정확한 7자리 숫자 IMO 번호를 입력해주세요.")
    elif not GEMINI_API_KEY or not OPENSANCTIONS_KEY:
        st.error("⚠️ Streamlit Secrets 설정에 API 키가 등록되지 않았습니다.")
    else:
        with st.spinner("글로벌 제재 명단을 샅샅이 조회 중입니다..."):
            status, vessels = check_sanction(imo_input)
            
            if status == "API_KEY_ERROR":
                st.error("⚠️ 제재 DB API 키 인증에 실패했거나 한도를 초과했습니다.")
            elif status == "ERROR":
                st.error("⚠️ 데이터 서버와 통신할 수 없습니다.")
            else:
                if status == "CLEAN":
                    with st.spinner("AI가 선박명을 검색하고 있습니다..."):
                        vessel_name = get_vessel_name_from_gemini(imo_input)
                    
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