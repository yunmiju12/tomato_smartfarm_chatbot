** 전체 실행 순서
------------------
VSCode 터미널을 총 4개 사용합니다.

실행 순서:

1. 챗봇백엔드
cd .\backend_chatbot
.\.venv\Scripts\activate
python -m uvicorn smartfarm_chatbot:app --host 127.0.0.1 --port 8001
외부:python -m uvicorn smartfarm_chatbot:app --host 0.0.0.0 --port 8001

2. 상태창
cd .\current_status_backend
.\.venv\Scripts\activate
python -m uvicorn main:app --host 127.0.0.1 --port 8000
외부: python -m uvicorn main:app --host 0.0.0.0 --port 8000

3. 현상태데이터
cd .\current_status_backend
.\.venv\Scripts\activate
python insert_real_weather.py

4. 프론트엔드
cd G:\tomato_smartfarm_chatbot\frontend
npm run dev -- --host 0.0.0.0
--------------------------------------------------------------------------------------

토마토 스마트팜 챗봇 실행 방법
================================

이 문서는 압축파일을 받은 조원이 Windows 환경의 VSCode에서
프로젝트를 실행할 수 있도록 정리한 안내서입니다.

프로젝트 구성
--------------
프로젝트 폴더는 다음과 같은 구조를 기준으로 합니다.

tomato_smartfarm_chatbot
├─ frontend
├─ current_status_backend
├─ backend_chatbot
├─ database
│  └─ tomato_chatbot_current_status.sql
└─ 실행방법.txt


1. 압축파일 풀기
----------------
1) 받은 ZIP 파일에서 마우스 오른쪽 버튼을 누릅니다.
2) "압축 풀기" 또는 "모두 압축 풀기"를 선택합니다.
3) 가능하면 경로가 너무 길지 않은 곳에 풉니다.

권장 위치 예시:

C:\tomato_smartfarm_chatbot

또는

D:\tomato_smartfarm_chatbot

한글 폴더명이나 지나치게 긴 경로는 오류가 발생할 수 있으므로 피하는 것이 좋습니다.


2. 필요한 프로그램
------------------
다음 프로그램이 컴퓨터에 설치되어 있어야 합니다.

- VSCode
- Python 3.11 권장
- Node.js
- MySQL Server
- MySQL Workbench

VSCode 터미널에서 설치 여부를 확인합니다.

python --version
node --version
npm --version

버전 번호가 나오면 정상입니다.


3. VSCode로 프로젝트 열기
------------------------
1) VSCode를 실행합니다.
2) 상단 메뉴에서 "파일" → "폴더 열기"를 누릅니다.
3) 압축을 푼 tomato_smartfarm_chatbot 폴더를 선택합니다.

또는 PowerShell에서 다음처럼 실행할 수 있습니다.

cd C:\tomato_smartfarm_chatbot
code .


4. MySQL 데이터베이스 만들기
----------------------------
1) MySQL Workbench를 실행합니다.
2) MySQL 서버에 접속합니다.
3) 아래 SQL 파일을 엽니다.

database\tomato_chatbot_current_status.sql

4) SQL 전체를 선택한 뒤 번개 모양 실행 버튼을 누릅니다.
5) 아래 쿼리를 실행해 생성 여부를 확인합니다.

USE tomato_chatbot;
SHOW TABLES;
SELECT * FROM sensor_data;

sensor_data 테이블과 샘플 데이터가 보이면 정상입니다.


5. 현재 상태 백엔드 설정
-----------------------
VSCode에서 새 터미널을 엽니다.

cd current_status_backend

가상환경을 만듭니다.

python -m venv .venv

가상환경을 실행합니다.

.\.venv\Scripts\Activate.ps1

PowerShell 실행 권한 오류가 나오면 아래 명령을 먼저 실행합니다.

Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

그다음 다시 가상환경을 실행합니다.

.\.venv\Scripts\Activate.ps1

필요한 Python 모듈을 설치합니다.

python -m pip install --upgrade pip
python -m pip install -r requirements.txt


6. 현재 상태 백엔드 .env 설정
-----------------------------
current_status_backend 폴더 안에 .env.example 파일이 있으면 복사합니다.

Copy-Item .env.example .env

.env.example 파일이 없다면 current_status_backend 폴더에
.env라는 이름의 파일을 직접 만듭니다.

예시 내용:

DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=본인의_MySQL_비밀번호
DB_NAME=tomato_chatbot

주의:
- DB_PASSWORD에는 MySQL 설치 때 설정한 본인의 비밀번호를 입력합니다.
- 실제 비밀번호가 적힌 .env 파일은 다른 사람에게 다시 공유하지 않습니다.
- Python 코드에 DB 설정이 직접 적혀 있다면 코드의 값과 본인 MySQL 설정이 일치해야 합니다.


7. 현재 상태 백엔드 실행
-----------------------
current_status_backend 폴더에서 실행합니다.

python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000

정상 실행 확인 주소:

http://127.0.0.1:8000/docs

현재 상태 API가 /api/status라면 다음 주소도 확인합니다.

http://127.0.0.1:8000/api/status

이 터미널은 종료하지 말고 그대로 둡니다.


8. 챗봇 백엔드 설정
-------------------
VSCode에서 새 터미널을 하나 더 엽니다.

프로젝트 최상위 폴더에서 다음을 실행합니다.

cd backend_chatbot

가상환경을 만듭니다.

python -m venv .venv

가상환경을 실행합니다.

.\.venv\Scripts\Activate.ps1

필요한 Python 모듈을 설치합니다.

python -m pip install --upgrade pip
python -m pip install -r requirements.txt


9. 챗봇 백엔드 .env 설정
------------------------
backend_chatbot 폴더 안에 .env.example 파일이 있으면 복사합니다.

Copy-Item .env.example .env

.env.example 파일이 없다면 backend_chatbot 폴더에
.env 파일을 직접 만듭니다.

예시 내용:

DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=본인의_MySQL_비밀번호
DB_NAME=tomato_chatbot

OPENAI_API_KEY=본인의_API_키

프로젝트에서 기상청 또는 다른 API를 사용한다면
.env.example에 표시된 환경변수도 추가로 입력합니다.

예시:

KMA_SERVICE_KEY=본인의_기상청_API_키

주의:
- API 키가 없는 경우 일부 챗봇 기능이나 날씨 기능이 작동하지 않을 수 있습니다.
- 실제 API 키가 들어간 .env 파일은 공유하지 않습니다.


10. 챗봇 백엔드 실행
--------------------
backend_chatbot 폴더에서 실행합니다.

python -m uvicorn smartfarm_chatbot:app --reload --host 127.0.0.1 --port 8001

정상 실행 확인 주소:

http://127.0.0.1:8001/docs

Swagger 화면에서 POST /api/chat을 테스트할 수 있습니다.

이 터미널도 종료하지 말고 그대로 둡니다.


11. 프론트엔드 설정
-------------------
VSCode에서 새 터미널을 하나 더 엽니다.

프로젝트 최상위 폴더에서 다음을 실행합니다.

cd frontend

필요한 모듈을 설치합니다.

npm install

frontend 폴더 안에 .env.example 파일이 있으면 복사합니다.

Copy-Item .env.example .env

.env.example 파일이 없다면 frontend 폴더에
.env 파일을 직접 만듭니다.

내용:

VITE_STATUS_API_BASE_URL=http://127.0.0.1:8000
VITE_CHAT_API_BASE_URL=http://127.0.0.1:8001


12. 프론트엔드 실행
-------------------
frontend 폴더에서 실행합니다.

npm run dev

터미널에 표시되는 주소로 접속합니다.

일반적인 주소:

http://localhost:5173

또는

http://127.0.0.1:5173


13. 처음 한 번만 하는 작업
--------------------------
다음 작업은 프로젝트를 처음 받은 후 한 번만 하면 됩니다.

- MySQL 데이터베이스 생성
- Python 가상환경 생성
- requirements.txt 모듈 설치
- npm install
- 각 폴더의 .env 파일 생성


14. 다음 실행부터 하는 작업
--------------------------
컴퓨터를 다시 켠 뒤에는 아래만 실행하면 됩니다.

1) MySQL 실행
2) 현재 상태 백엔드 가상환경 실행 후 uvicorn 실행
3) 챗봇 백엔드 가상환경 실행 후 uvicorn 실행
4) frontend에서 npm run dev 실행


15. 자주 발생하는 오류
----------------------

[오류 1]
python 명령을 찾을 수 없습니다.

해결:
Python을 설치하고 설치 과정에서
"Add Python to PATH"를 체크합니다.
설치 후 VSCode를 완전히 종료했다가 다시 실행합니다.


[오류 2]
npm 명령을 찾을 수 없습니다.

해결:
Node.js를 설치한 뒤 VSCode를 완전히 종료했다가 다시 실행합니다.


[오류 3]
ModuleNotFoundError가 발생합니다.

해결:

.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt


[오류 4]
Could not import module "main"

해결:
main.py가 있는 current_status_backend 폴더에서 실행해야 합니다.

cd current_status_backend
dir
python -m uvicorn main:app --reload --port 8000


[오류 5]
Could not import module "smartfarm_chatbot"

해결:
smartfarm_chatbot.py가 있는 backend_chatbot 폴더에서 실행해야 합니다.

cd backend_chatbot
dir
python -m uvicorn smartfarm_chatbot:app --reload --port 8001


[오류 6]
Access denied for user

해결:
.env의 MySQL 아이디 또는 비밀번호가 틀린 경우입니다.

DB_USER=root
DB_PASSWORD=본인의_MySQL_비밀번호

MySQL Workbench에 접속할 때 사용하는 정보와 일치해야 합니다.


[오류 7]
Unknown database 'tomato_chatbot'

해결:
database\tomato_chatbot_current_status.sql 파일을
MySQL Workbench에서 먼저 실행합니다.


[오류 8]
OPTIONS /api/chat 405 Method Not Allowed

해결:
챗봇 FastAPI에 CORS 설정이 필요합니다.
프로젝트 코드에 CORSMiddleware가 적용되어 있는지 확인합니다.


[오류 9]
프론트 화면에 FastAPI 서버 연결 실패가 표시됩니다.

확인할 사항:

- 8000 포트 현재 상태 서버가 실행 중인지 확인
- 8001 포트 챗봇 서버가 실행 중인지 확인
- frontend\.env 주소가 정확한지 확인
- .env를 수정한 뒤 npm run dev를 껐다가 다시 실행


[오류 10]
포트가 이미 사용 중입니다.

해결:
기존에 실행 중인 같은 서버가 있는지 확인하고 종료합니다.

PowerShell에서 포트 확인 예시:

netstat -ano | findstr :8000
netstat -ano | findstr :8001
netstat -ano | findstr :5173


16. 압축파일을 보내는 사람이 확인할 사항
---------------------------------------
압축파일에는 다음 파일이 포함되어 있어야 합니다.

- frontend 폴더
- current_status_backend 폴더
- backend_chatbot 폴더
- database 폴더
- requirements.txt
- package.json
- package-lock.json
- .env.example
- 실행방법.txt
- 챗봇 실행에 필요한 정제 문서 또는 VectorDB 파일

다음 파일은 일반적으로 압축파일에서 제외하는 것이 좋습니다.

- node_modules
- .venv
- __pycache__
- 실제 비밀번호가 들어간 .env
- 실제 API 키가 들어간 파일

node_modules와 .venv를 제외하면 압축파일 용량이 크게 줄어듭니다.
받는 사람은 이 안내서에 따라 npm install과
pip install -r requirements.txt를 실행하면 됩니다.


17. 최종 확인
-------------
브라우저에서 아래 주소가 모두 열리면 정상입니다.

현재 상태 백엔드:
http://127.0.0.1:8000/docs

챗봇 백엔드:
http://127.0.0.1:8001/docs

프론트엔드:
http://localhost:5173

세 서버가 모두 실행된 상태에서 프론트 화면의
현재 상태 박스와 챗봇 기능을 확인합니다.