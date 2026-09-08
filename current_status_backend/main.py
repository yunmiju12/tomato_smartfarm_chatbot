from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import mysql.connector
import os

from mysql.connector import Error
from datetime import datetime, timedelta

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "https://yunmiju12.github.io",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ================================
# DB 연결
# ================================
def get_db_connection():
    try:
        return mysql.connector.connect(
            host=os.getenv("MYSQLHOST"),
            port=int(os.getenv("MYSQLPORT", "3306")),
            user=os.getenv("MYSQLUSER"),
            password=os.getenv("MYSQLPASSWORD"),
            database=os.getenv("MYSQLDATABASE"),
        )

    except Error as e:
        print("MySQL 연결 오류:", e)
        raise HTTPException(
            status_code=500,
            detail="MySQL 연결 실패"
        )


# ================================
# 시간대 구분
# ================================
def get_time_slot(hour: int):
    if 0 <= hour < 6:
        return "새벽"
    elif 6 <= hour < 12:
        return "오전"
    elif 12 <= hour < 18:
        return "오후"
    else:
        return "야간"


# ================================
# 시간대별 토마토 환경 기준
# ================================
TIME_SLOT_RULES = {
    "새벽": {
        "temp_min": 15,
        "temp_max": 17,
        "humidity_min": 65,
        "humidity_max": 80,
        "co2_min": 300,
        "co2_max": 1000,
    },
    "오전": {
        "temp_min": 25,
        "temp_max": 28,
        "humidity_min": 65,
        "humidity_max": 80,
        "co2_min": 350,
        "co2_max": 1000,
    },
    "오후": {
        "temp_min": 23,
        "temp_max": 25,
        "humidity_min": 60,
        "humidity_max": 80,
        "co2_min": 300,
        "co2_max": 1000,
    },
    "야간": {
        "temp_min": 15,
        "temp_max": 17,
        "humidity_min": 65,
        "humidity_max": 80,
        "co2_min": 300,
        "co2_max": 1000,
    },
}

HUMIDITY_TOLERANCE = 3

# 공공데이터는 초 단위 센서가 아니므로 15분 이내를 최신으로 판단
REALTIME_THRESHOLD_SECONDS = 900


# ================================
# 안전한 숫자 변환 함수
# None, 문자열, 빈 값이 들어와도 서버가 죽지 않도록 처리
# ================================
def safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


# ================================
# 위험도 계산
# ================================
def calculate_risk(
    temperature,
    humidity,
    co2,
    time_slot,
    rain_1h=0.0,
    precipitation_type="없음",
    wind_speed=0.0,
):
    rule = TIME_SLOT_RULES[time_slot]

    score = 0
    reasons = []
    actions = []

    # 온도 위험도
    if temperature < rule["temp_min"]:
        gap = rule["temp_min"] - temperature

        if temperature <= 10:
            score += 45
            reasons.append(f"{time_slot} 온도 10℃ 이하로 생육 정지 위험")
            actions.append("즉시 난방 또는 보온 상태를 확인하세요.")
        elif temperature <= 15:
            score += 35
            reasons.append(f"{time_slot} 온도 15℃ 이하로 생육 저하 위험")
            actions.append("난방 설정과 보온 커튼 상태를 확인하세요.")
        elif gap >= 3:
            score += 25
            reasons.append(f"{time_slot} 기준보다 온도가 많이 낮음")
            actions.append("온도 상승 여부를 확인하세요.")
        else:
            score += 15
            reasons.append(f"{time_slot} 기준보다 온도가 낮음")
            actions.append("온도 변화를 모니터링하세요.")

    elif temperature > rule["temp_max"]:
        gap = temperature - rule["temp_max"]

        if temperature >= 30:
            score += 35
            reasons.append(f"{time_slot} 온도 30℃ 이상")
            actions.append("환기, 차광, 냉방 상태를 확인하세요.")
        elif gap >= 3:
            score += 25
            reasons.append(f"{time_slot} 기준보다 온도가 많이 높음")
            actions.append("환기 상태를 확인하세요.")
        else:
            score += 15
            reasons.append(f"{time_slot} 기준보다 온도가 높음")
            actions.append("온도 상승 추이를 확인하세요.")

    # 습도 위험도
    humidity_min = rule["humidity_min"] - HUMIDITY_TOLERANCE
    humidity_max = rule["humidity_max"] + HUMIDITY_TOLERANCE

    if humidity < humidity_min:
        if humidity <= 60:
            score += 25
            reasons.append("습도 60% 이하로 건조 위험")
            actions.append("관수 상태와 건조 여부를 확인하세요.")
        else:
            score += 10
            reasons.append(f"{time_slot} 기준보다 습도가 낮음")
            actions.append("습도 변화를 모니터링하세요.")

    elif humidity > humidity_max:
        if humidity >= 90:
            score += 35
            reasons.append("습도 90% 이상 과습")
            actions.append("환기 강화 및 결로 관리를 확인하세요.")
        else:
            score += 20
            reasons.append(f"{time_slot} 기준보다 습도가 높음")
            actions.append("환기 상태를 확인하세요.")

    # CO2 위험도
    if co2 < rule["co2_min"]:
        if co2 <= 200:
            score += 35
            reasons.append("CO2 200ppm 수준으로 매우 낮음")
            actions.append("CO2 공급 또는 환기 상태를 확인하세요.")
        else:
            score += 20
            reasons.append(f"{time_slot} 기준보다 CO2가 낮음")
            actions.append("CO2 농도를 확인하세요.")

    elif co2 > rule["co2_max"]:
        score += 40
        reasons.append("CO2 1000ppm 초과로 과다")
        actions.append("CO2 공급을 중단하고 환기하세요.")

    # 시간대별 추가 위험도
    if time_slot in ["새벽", "야간"] and humidity >= 85:
        score += 15
        reasons.append(f"{time_slot} 고습으로 결로·병해 위험 증가")
        actions.append("야간 결로와 곰팡이성 병해를 예찰하세요.")

    if time_slot == "오후" and temperature >= 30:
        score += 10
        reasons.append("오후 고온 스트레스 위험 증가")
        actions.append("차광과 환기를 우선 확인하세요.")

    if time_slot == "오전" and co2 < 350:
        score += 10
        reasons.append("오전 CO2 부족으로 광합성 저하 가능")
        actions.append("CO2 공급 상태를 확인하세요.")

    # 공공데이터 기반 추가 위험도
    if precipitation_type and precipitation_type != "없음":
        score += 10
        reasons.append(f"외부 강수 상태: {precipitation_type}")
        actions.append("외부 습도 상승 가능성이 있어 환기와 결로 상태를 확인하세요.")

    if rain_1h >= 1.0:
        score += 10
        reasons.append(f"최근 1시간 강수량 {rain_1h}mm")
        actions.append("온실 주변 배수 상태를 확인하세요.")

    if wind_speed >= 7.0:
        score += 10
        reasons.append(f"외부 풍속 {wind_speed}m/s로 강한 편")
        actions.append("환기창, 측창, 비닐 고정 상태를 확인하세요.")

    # 최종 위험도 등급
    if score >= 75:
        level = "위험"
    elif score >= 45:
        level = "주의"
    elif score >= 20:
        level = "관심"
    else:
        level = "정상"

    reasons = list(dict.fromkeys(reasons))
    actions = list(dict.fromkeys(actions))

    return level, score, reasons, actions


# ================================
# sensor_data 테이블 컬럼 확인
# dictionary=True cursor 기준
# ================================
def get_existing_columns(cursor):
    cursor.execute("SHOW COLUMNS FROM sensor_data")
    rows = cursor.fetchall()

    columns = set()

    for row in rows:
        # dictionary=True일 때
        if isinstance(row, dict):
            columns.add(row["Field"])
        # 혹시 tuple cursor로 들어와도 처리
        else:
            columns.add(row[0])

    return columns

# React와 FastAPI 연결 허용 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://192.168.0.76:5173",
        "https://yunmiju12.github.io",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def home():
    return {
        "message": "FastAPI 서버 실행 중",
        "status": "GET /api/status",
    }


@app.get("/api/status")
def get_current_status():
    conn = get_db_connection()

    # 중요: dictionary=True를 써야 row["temperature"], row.get(...) 방식이 가능함
    cursor = conn.cursor(dictionary=True)

    try:
        columns = get_existing_columns(cursor)

        optional_columns = {
            "rain_1h": "NULL AS rain_1h",
            "precipitation_type": "NULL AS precipitation_type",
            "precipitation_code": "NULL AS precipitation_code",
            "wind_speed": "NULL AS wind_speed",
            "data_source": "NULL AS data_source",
            "base_date": "NULL AS base_date",
            "base_time": "NULL AS base_time",
        }

        select_optional = []

        for column, fallback_sql in optional_columns.items():
            if column in columns:
                select_optional.append(column)
            else:
                select_optional.append(fallback_sql)

        query = f"""
            SELECT
                id,
                greenhouse_id,
                measured_at,
                temperature,
                humidity,
                co2,
                ventilation_status,
                {", ".join(select_optional)}
            FROM sensor_data
            ORDER BY measured_at DESC, id DESC
            LIMIT 1
        """

        cursor.execute(query)
        row = cursor.fetchone()

    except Error as e:
        print("SQL 실행 오류:", e)
        raise HTTPException(status_code=500, detail="센서 데이터 조회 실패")

    finally:
        cursor.close()
        conn.close()

    if row is None:
        raise HTTPException(status_code=404, detail="센서 데이터가 없습니다.")

    measured_at = row["measured_at"]

    # measured_at이 문자열로 들어오는 경우까지 대비
    if isinstance(measured_at, str):
        measured_at = datetime.fromisoformat(measured_at)

    time_slot = get_time_slot(measured_at.hour)

    temperature = safe_float(row.get("temperature"))
    humidity = safe_float(row.get("humidity"))
    co2 = safe_float(row.get("co2"), default=430.0)

    rain_1h = safe_float(row.get("rain_1h"))
    precipitation_type = row.get("precipitation_type") or "없음"
    precipitation_code = row.get("precipitation_code") or "0"
    wind_speed = safe_float(row.get("wind_speed"))

    data_source = (
        row.get("data_source")
        or row.get("ventilation_status")
        or "DB 센서 데이터"
    )

    risk_level, risk_score, reasons, actions = calculate_risk(
        temperature,
        humidity,
        co2,
        time_slot,
        rain_1h=rain_1h,
        precipitation_type=precipitation_type,
        wind_speed=wind_speed,
    )

    now = datetime.now()
    data_age_seconds = int((now - measured_at).total_seconds())
    is_realtime = data_age_seconds <= REALTIME_THRESHOLD_SECONDS

    return {
        "greenhouse_id": row.get("greenhouse_id"),
        "measured_at": measured_at,
        "server_time": now,
        "data_age_seconds": data_age_seconds,
        "is_realtime": is_realtime,
        "time_slot": time_slot,
        "temperature": temperature,
        "humidity": humidity,
        "co2": co2,
        "rain_1h": rain_1h,
        "precipitation_type": precipitation_type,
        "precipitation_code": precipitation_code,
        "wind_speed": wind_speed,
        "data_source": data_source,
        "base_date": row.get("base_date"),
        "base_time": row.get("base_time"),
        "ventilation_status": row.get("ventilation_status"),
        "risk_level": risk_level,
        "risk_score": risk_score,
        "reasons": reasons,
        "actions": actions,
    }

@app.get("/api/status/by-date")
def get_status_by_date(date: str):
    """
    선택한 날짜의 마지막 센서 데이터를 조회한다.
    예시:
    /api/status/by-date?date=2026-07-08
    """
    try:
        start_date = datetime.strptime(date, "%Y-%m-%d")
        end_date = start_date + timedelta(days=1)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="날짜 형식이 잘못되었습니다. 예: 2026-07-08",
        )

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        columns = get_existing_columns(cursor)

        optional_columns = {
            "rain_1h": "NULL AS rain_1h",
            "precipitation_type": "NULL AS precipitation_type",
            "precipitation_code": "NULL AS precipitation_code",
            "wind_speed": "NULL AS wind_speed",
            "data_source": "NULL AS data_source",
            "base_date": "NULL AS base_date",
            "base_time": "NULL AS base_time",
        }

        select_optional = []

        for column, fallback_sql in optional_columns.items():
            if column in columns:
                select_optional.append(column)
            else:
                select_optional.append(fallback_sql)

        query = f"""
            SELECT
                id,
                greenhouse_id,
                measured_at,
                temperature,
                humidity,
                co2,
                ventilation_status,
                {", ".join(select_optional)}
            FROM sensor_data
            WHERE measured_at >= %s
              AND measured_at < %s
            ORDER BY measured_at DESC, id DESC
            LIMIT 1
        """

        cursor.execute(query, (start_date, end_date))
        row = cursor.fetchone()

    except Error as e:
        print("날짜별 SQL 실행 오류:", e)
        raise HTTPException(status_code=500, detail="날짜별 센서 데이터 조회 실패")

    finally:
        cursor.close()
        conn.close()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"{date} 날짜의 센서 데이터가 없습니다.",
        )

    measured_at = row["measured_at"]

    if isinstance(measured_at, str):
        measured_at = datetime.fromisoformat(measured_at)

    time_slot = get_time_slot(measured_at.hour)

    temperature = safe_float(row.get("temperature"))
    humidity = safe_float(row.get("humidity"))
    co2 = safe_float(row.get("co2"), default=430.0)

    rain_1h = safe_float(row.get("rain_1h"))
    precipitation_type = row.get("precipitation_type") or "없음"
    precipitation_code = row.get("precipitation_code") or "0"
    wind_speed = safe_float(row.get("wind_speed"))

    data_source = (
        row.get("data_source")
        or row.get("ventilation_status")
        or "DB 센서 데이터"
    )

    risk_level, risk_score, reasons, actions = calculate_risk(
        temperature,
        humidity,
        co2,
        time_slot,
        rain_1h=rain_1h,
        precipitation_type=precipitation_type,
        wind_speed=wind_speed,
    )

    now = datetime.now()
    data_age_seconds = int((now - measured_at).total_seconds())

    return {
        "greenhouse_id": row.get("greenhouse_id"),
        "measured_at": measured_at,
        "server_time": now,
        "data_age_seconds": data_age_seconds,
        "is_realtime": False,
        "selected_date": date,
        "time_slot": time_slot,
        "temperature": temperature,
        "humidity": humidity,
        "co2": co2,
        "rain_1h": rain_1h,
        "precipitation_type": precipitation_type,
        "precipitation_code": precipitation_code,
        "wind_speed": wind_speed,
        "data_source": data_source,
        "base_date": row.get("base_date"),
        "base_time": row.get("base_time"),
        "ventilation_status": row.get("ventilation_status"),
        "risk_level": risk_level,
        "risk_score": risk_score,
        "reasons": reasons,
        "actions": actions,
    }

