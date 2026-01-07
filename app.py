import streamlit as st
import google.generativeai as genai
import pandas as pd
import tempfile
import json
import os
import requests
import base64
from datetime import datetime

st.set_page_config(page_title="Meeting Assistant", layout="wide")
st.title("☻ Meeting Assistant")

# ----------------------------------------------------------
# [설정] 설정 파일 관리 함수 (저장/불러오기)
# ----------------------------------------------------------
CONFIG_FILE = 'user_config.json'

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_config(google_key, notion_key, notion_page):
    config = {
        'google_api_key': google_key,
        'notion_token': notion_key,
        'notion_page_id': notion_page
    }
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f)
# ----------------------------------------------------------
# [함수] 이미지를 HTML로 보여주는 마법의 함수
# ----------------------------------------------------------
def get_img_with_text(img_path, text, img_width=30):
    with open(img_path, "rb") as f:
        img_data = f.read()
        b64_data = base64.b64encode(img_data).decode()
    
    # 👇 [수정됨] style에 'margin-bottom: 20px;' 추가!
    # 20px 숫자를 키우면 더 멀어지고, 줄이면 더 가까워집니다.
    html_code = f"""
    <div style="display: flex; align-items: center; margin-bottom: 20px;">
        <img src="data:image/png;base64,{b64_data}" style="width:{img_width}px; margin-right: 3px;">
        <h3 style="margin: 0; padding: 0;">{text}</h3>
    </div>
    """
    return html_code
# ----------------------------------------------------------
# [설정] 사이드바 (자동 저장 기능 추가됨)
# ----------------------------------------------------------
with st.sidebar:
    st.header("⚙️ 설정")
    
    # 1. 저장된 설정 불러오기
    saved_config = load_config()
    
    # 2. 입력창 (기본값으로 저장된 값을 넣어줌)
    # 구글 키
    # 2. Google API Key 처리 (수정됨: Secrets 우선 확인)
    google_api_key = None
    
    try:
        # (1) 배포된 서버의 비밀 금고(Secrets)를 먼저 확인
        google_api_key = st.secrets["GOOGLE_API_KEY"]
        st.success("✅ 서버 키 적용됨") # 입력창 대신 성공 메시지 표시
    except (FileNotFoundError, KeyError):
        # (2) 금고에 없으면 -> 입력창 띄우기 (로컬 테스트용)
        google_api_key = st.text_input(
            "Google API Key", 
            value=saved_config.get('google_api_key', ''), 
            type="password"
        )

    if google_api_key:
        genai.configure(api_key=google_api_key, transport="rest")
    
    st.divider()
    
    st.markdown(get_img_with_text("icon.png", "노션(Notion) 설정"), unsafe_allow_html=True)
    
    # 노션 토큰
    notion_token = st.text_input(
        "노션 토큰 (Secret Key)", 
        value=saved_config.get('notion_token', ''), 
        type="password"
    )
    
    # 노션 페이지 ID (자동 추출 기능 포함)
    raw_page_id_input = saved_config.get('notion_page_id', '') # 저장된 값
    
    raw_input = st.text_input(
        "노션 빈 페이지 주소(URL) 또는 ID",
        value=raw_page_id_input
    )
    
    # ID 추출 로직
    notion_page_id = None
    if raw_input:
        clean_text = raw_input.replace("[", "").replace("]", "").split("(")[0]
        notion_page_id = clean_text.split("/")[-1].split("?")[0].split("-")[-1]

    st.divider()

    # 3. [저장] 버튼
    if st.button("설정 기억하기"):
        save_config(google_api_key, notion_token, raw_input)
        st.success("설정이 저장되었습니다! 이제 새로고침해도 유지됩니다.")

# ----------------------------------------------------------
# [함수 1] 빈 페이지에 '새 데이터베이스' 만드는 함수 🆕
# ----------------------------------------------------------
def create_new_database(token, page_id):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    
    # 오늘 날짜로 표 제목 만들기
    today_str = datetime.now().strftime("%Y-%m-%d 회의 업무")
    
    payload = {
        "parent": {"type": "page_id", "page_id": page_id},
        "title": [{"type": "text", "text": {"content": today_str}}],
        "properties": {
            "업무내용": {"title": {}},     # 제목 컬럼
            "담당자": {"rich_text": {}},  # 텍스트 컬럼
            "기한": {"rich_text": {}}     # 텍스트 컬럼
        }
    }
    
    response = requests.post("https://api.notion.com/v1/databases", headers=headers, json=payload)
    
    if response.status_code == 200:
        return response.json()['id'] # 새로 만든 DB의 ID 반환
    else:
        st.error(f"DB 생성 실패: {response.text}")
        return None

# ----------------------------------------------------------
# [함수 2] 만들어진 DB에 업무 넣는 함수
# ----------------------------------------------------------
# ----------------------------------------------------------
# [함수 2] 만들어진 DB에 업무 넣는 함수 (안전장치 추가 Ver)
# ----------------------------------------------------------
def add_tasks_to_db(token, db_id, data_list):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    
    count = 0
    for item in data_list:
        # 🌟 핵심 수정: .get('키', '기본값') 사용해서 에러 방지
        task_content = item.get('업무내용', '내용 없음')
        assignee = item.get('담당자', '미정')
        due_date = item.get('기한', '미정') # <-- 여기가 문제였음! 이제 없으면 '미정'으로 들어감

        payload = {
            "parent": {"database_id": db_id},
            "properties": {
                "업무내용": {"title": [{"text": {"content": task_content}}]},
                "담당자": {"rich_text": [{"text": {"content": assignee}}]},
                "기한": {"rich_text": [{"text": {"content": due_date}}]}
            }
        }
        res = requests.post("https://api.notion.com/v1/pages", headers=headers, json=payload)
        if res.status_code == 200:
            count += 1
        else:
            # 에러가 나면 화면에 원인을 보여줌 (디버깅용)
            st.error(f"데이터 전송 실패: {res.text}")
            
    return count

# ----------------------------------------------------------
# [메인] 실행 로직
# ----------------------------------------------------------
st.divider()
st.info("💡 Tip: 녹음이 1시간을 넘어가면 처리가 오래 걸릴 수 있어요. 50분마다 끊어서 녹음하는 것을 추천합니다!")
audio_value = st.audio_input("마이크 버튼을 눌러주세요")

if audio_value:
    st.audio(audio_value)
    
    if st.button("🚀 분석 시작"):
        if not google_api_key:
            st.error("구글 키가 없습니다.")
            st.stop()
            
        with st.spinner("분석 중..."):
            try:
                # (1) 음성 파일 저장 및 업로드
                with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
                    tmp.write(audio_value.read())
                    tmp_path = tmp.name
                
                myfile = genai.upload_file(tmp_path)
                
                # (2) Gemini 분석
                prompt = """
                회의 내용을 듣고 JSON으로 업무를 정리해줘.
                형식은 반드시 지켜야 해:
                [{"담당자": "이름", "업무내용": "할일", "기한": "날짜"}]
                
                주의사항:
                1. 담당자가 없으면 '미정', 기한이 언급 안 됐으면 '미정'이라고 꼭 적어.
                2. 항목을 아예 빼먹지 마. (빈 값이라도 채워)
                """
                model = genai.GenerativeModel("gemini-2.5-flash")
                result = model.generate_content([myfile, prompt], request_options={"timeout": 600})
                
                text_result = result.text.replace("```json", "").replace("```", "").strip()
                if not text_result: 
                    st.error("결과 없음")
                    st.stop()
                    
                st.session_state['tasks'] = json.loads(text_result)
                os.unlink(tmp_path)
                
            except Exception as e:
                st.error(f"에러: {e}")

# 결과 및 전송 버튼
if 'tasks' in st.session_state:
    st.subheader("✅ 업무 배정표")
    edited_df = st.data_editor(pd.DataFrame(st.session_state['tasks']), use_container_width=True)
    
    st.divider()
    
    # 🌟 버튼: 페이지에 새 표 만들기
    if st.button("📤 노션 페이지에 '데이터베이스'로 저장하기"):
        if not notion_token or not notion_page_id:
            st.warning("노션 토큰과 '페이지 ID'를 입력해주세요.")
        else:
            with st.spinner("1. 새 데이터베이스 생성 중..."):
                # 1. DB 생성
                new_db_id = create_new_database(notion_token, notion_page_id)
                
                if new_db_id:
                    st.success("데이터베이스 생성 완료! 업무를 등록합니다...")
                    # 2. 데이터 등록
                    final_data = edited_df.to_dict('records')
                    count = add_tasks_to_db(notion_token, new_db_id, final_data)
                    
                    if count > 0:
                        st.balloons()
                        st.success(f"완료! '{datetime.now().strftime('%Y-%m-%d')}' 제목의 표가 노션에 생성되었습니다.")