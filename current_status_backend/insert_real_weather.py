# 공공데이터포털 기상청 단기예보 조회서비스 - 초단기실황 저장 스크립트
# 가져오는 항목: T1H(기온), REH(습도), PTY(강수형태), RN1(1시간 강수량), WSD(풍속)

import os
import re
import time
import requests
import mysql.connector
from datetime import datetime, timedelta
from dotenv import load_dotenv
from urllib.parse import unquote
from pathlib import Path

# 이 파일과 같은 폴더의 .env를 읽음
load_dotenv(dotenv_path=Path(__file__).with_name(".env"))

KMA_SERVICE_KEY = os.getenv("KMA_SERVICE_KEY")
if KMA_SERVICE_KEY:
    KMA_SERVICE_KEY = unquote(KMA_SERVICE_KEY.strip())

# 서울 예시 격자 좌표. 프로젝트 지역에 맞게 수정 가능.
NX = 60
NY = 127

# 테스트 중 30초, 최종 발표/운영은 600초 권장
FETCH_INTERVAL_SECONDS = 30

PTY_TEXT = {
    "0": "없음",
    "1": "비",
    "2": "비/눈",
    "3": "눈",
    "5": "빗방울",
    "6": "빗방울/눈날림",
    "7": "눈날림",
}


def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("MYSQLHOST"),
        port=int(os.getenv("MYSQLPORT", "3306")),
        user=os.getenv("MYSQLUSER"),
        password=os.getenv("MYSQLPASSWORD"),
        database=os.getenv("MYSQLDATABASE"),
    )


def ensure_weather_columns():
    """
    기존 sensor_data 테이블에 공공데이터용 컬럼이 없으면 자동 추가한다.
    MySQL Workbench에서 ALTER TABLE을 따로 실행해도 되지만,
    초보자 실수 방지를 위해 스크립트 실행 시 자동 확인한다.
    """
    columns_to_add = {
        "rain_1h": "DOUBLE NULL",
        "precipitation_type": "VARCHAR(30) NULL",
        "precipitation_code": "VARCHAR(10) NULL",
        "wind_speed": "DOUBLE NULL",
        "data_source": "VARCHAR(50) NULL",
        "base_date": "VARCHAR(8) NULL",
        "base_time": "VARCHAR(4) NULL",
    }

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SHOW COLUMNS FROM sensor_data")
    existing_columns = {row[0] for row in cursor.fetchall()}

    for column_name, column_type in columns_to_add.items():
        if column_name not in existing_columns:
            cursor.execute(
                f"ALTER TABLE sensor_data ADD COLUMN {column_name} {column_type}"
            )
            print(f"[DB 컬럼 추가] sensor_data.{column_name}")

    conn.commit()
    cursor.close()
    conn.close()


def get_base_datetime():
    """
    초단기실황은 정시 기준 자료를 사용한다.
    너무 현재 시간으로 요청하면 자료가 아직 없을 수 있으므로 40분 전 기준으로 요청한다.
    """
    now = datetime.now() - timedelta(minutes=40)
    return now.strftime("%Y%m%d"), now.strftime("%H00")


def parse_rain_1h(value):
    """
    RN1 값은 숫자 문자열로 오기도 하고, '강수없음'처럼 올 수 있다.
    화면과 위험도 계산용으로 숫자 mm 값으로 변환한다.
    """
    if value is None:
        return 0.0

    text = str(value).strip()
    if text in {"", "강수없음", "없음", "-"}:
        return 0.0

    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return 0.0

    return float(match.group())


def fetch_kma_current_weather():
    if not KMA_SERVICE_KEY:
        raise ValueError("KMA_SERVICE_KEY가 없습니다. current_status_backend/.env 파일을 확인하세요.")

    base_date, base_time = get_base_datetime()

    # 현재 상태 박스용: 초단기실황 API
    url = "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtNcst"

    service_key = unquote(KMA_SERVICE_KEY.strip())

    params = {
        "serviceKey": service_key,
        "pageNo": "1",
        "numOfRows": "100",
        "dataType": "JSON",
        "base_date": base_date,
        "base_time": base_time,
        "nx": NX,
        "ny": NY,
    }

    headers = {
        "User-Agent": "Mozilla/5.0",
    }

    response = requests.get(url, params=params, headers=headers, timeout=10)

    print("요청 URL:", response.url)
    print("응답 상태코드:", response.status_code)

    if response.status_code != 200:
        print("응답 내용:", response.text[:1000])
        response.raise_for_status()

    data = response.json()

    header = data["response"]["header"]

    if header["resultCode"] != "00":
        raise RuntimeError(
            f"공공데이터 API 오류: {header['resultCode']} / {header['resultMsg']}"
        )

    items = data["response"]["body"]["items"]["item"]

    weather = {
        "temperature": None,
        "humidity": None,
        "rain_1h": 0.0,
        "precipitation_code": "0",
        "precipitation_type": "없음",
        "wind_speed": None,
    }

    pty_map = {
        "0": "없음",
        "1": "비",
        "2": "비/눈",
        "3": "눈",
        "5": "빗방울",
        "6": "빗방울눈날림",
        "7": "눈날림",
    }

    for item in items:
        category = item["category"]
        value = item["obsrValue"]

        if category == "T1H":
            weather["temperature"] = float(value)

        elif category == "REH":
            weather["humidity"] = float(value)

        elif category == "RN1":
            try:
                weather["rain_1h"] = float(value)
            except ValueError:
                weather["rain_1h"] = 0.0

        elif category == "PTY":
            code = str(value)
            weather["precipitation_code"] = code
            weather["precipitation_type"] = pty_map.get(code, "알 수 없음")

        elif category == "WSD":
            weather["wind_speed"] = float(value)

    if weather["temperature"] is None or weather["humidity"] is None:
        raise RuntimeError("공공데이터 응답에서 T1H 또는 REH 값을 찾지 못했습니다.")

    return weather, base_date, base_time


def get_latest_co2():
    """
    기상청 단기예보 조회서비스는 CO2를 제공하지 않는다.
    따라서 기존 DB의 최신 CO2 값을 재사용하고, 없으면 기본값 430ppm을 사용한다.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT co2
        FROM sensor_data
        ORDER BY measured_at DESC, id DESC
        LIMIT 1
    """)

    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if row and row[0] is not None:
        return row[0]

    return 430


def insert_weather_to_db():
    weather, base_date, base_time = fetch_kma_current_weather()
    co2 = get_latest_co2()

    conn = get_db_connection()
    cursor = conn.cursor()

    sql = """
        INSERT INTO sensor_data (
            greenhouse_id,
            measured_at,
            temperature,
            humidity,
            co2,
            ventilation_status,
            rain_1h,
            precipitation_type,
            precipitation_code,
            wind_speed,
            data_source,
            base_date,
            base_time
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """

    values = (
        "GH-SEOUL",
        datetime.now(),
        weather["temperature"],
        weather["humidity"],
        co2,
        "기상청 공공데이터",
        weather["rain_1h"],
        weather["precipitation_type"],
        weather["precipitation_code"],
        weather["wind_speed"],
        "기상청 공공데이터",
        base_date,
        base_time,
    )

    cursor.execute(sql, values)
    conn.commit()

    cursor.close()
    conn.close()

    print(
        f"[공공데이터 저장] 기준 {base_date} {base_time} | "
        f"온도 {weather['temperature']}℃ | "
        f"습도 {weather['humidity']}% | "
        f"강수 {weather['precipitation_type']} {weather['rain_1h']}mm | "
        f"풍속 {weather['wind_speed']}m/s | "
        f"CO2 {co2}ppm"
    )


if __name__ == "__main__":
    while True:
        try:
            insert_weather_to_db()
        except Exception as e:
            print("공공데이터 날씨 데이터 저장 실패:", e)

        time.sleep(FETCH_INTERVAL_SECONDS)
