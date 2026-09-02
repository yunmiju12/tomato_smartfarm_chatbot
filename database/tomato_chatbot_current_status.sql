-- =========================================================
-- 토마토 스마트팜 현재 상태 박스용 MySQL 초기 설정
--
-- 사용 목적
--   1. 온실별 최신 센서 데이터 저장
--   2. 현재 온도, 습도, CO2, 환기 상태 조회
--
-- 주의
--   - MySQL 사용자 계정과 비밀번호는 각자의 환경에 맞게 설정합니다.
--   - 이 파일에는 비밀번호, API 키 등 민감정보를 넣지 않습니다.
-- =========================================================


-- 1. 데이터베이스 생성 및 선택
CREATE DATABASE IF NOT EXISTS tomato_chatbot
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE tomato_chatbot;

CREATE DATABASE IF NOT EXISTS tomato_chatbot;
USE tomato_chatbot;

CREATE TABLE IF NOT EXISTS sensor_data (
    id INT AUTO_INCREMENT PRIMARY KEY,
    greenhouse_id VARCHAR(50) NOT NULL,
    measured_at DATETIME NOT NULL,
    temperature FLOAT,
    humidity FLOAT,
    co2 FLOAT,
    ventilation_status VARCHAR(50)
);


-- 2. 센서 데이터 테이블 생성
CREATE TABLE IF NOT EXISTS sensor_data (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,

    -- 온실 구분값 예: GH-01, GH-02
    greenhouse_id VARCHAR(20) NOT NULL,

    -- 센서 측정 시간
    measured_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- 현재 상태 박스에 표시할 값
    temperature DECIMAL(5, 2) NULL COMMENT '온도(섭씨)',
    humidity DECIMAL(5, 2) NULL COMMENT '상대습도(%)',
    co2 INT UNSIGNED NULL COMMENT '이산화탄소 농도(ppm)',
    ventilation_status VARCHAR(20) NULL COMMENT '환기 상태',

    -- 온실별 최신 데이터 조회 성능 개선
    INDEX idx_greenhouse_measured_at (greenhouse_id, measured_at, id)
);


-- 3. 테스트용 샘플 데이터
-- 실제 데이터 수집 프로그램을 사용한다면 이 구문은 한 번만 실행하거나 생략합니다.
INSERT INTO sensor_data (
    greenhouse_id,
    measured_at,
    temperature,
    humidity,
    co2,
    ventilation_status
)
VALUES (
    'GH-01',
    NOW(),
    28.50,
    66.00,
    650,
    '부분개방'
);


-- 4. 특정 온실의 최신 상태 조회
-- FastAPI의 현재 상태 API에서 사용할 수 있는 기본 조회문입니다.
SELECT
    id,
    greenhouse_id,
    measured_at,
    temperature,
    humidity,
    co2,
    ventilation_status
FROM sensor_data
WHERE greenhouse_id = 'GH-01'
ORDER BY measured_at DESC, id DESC
LIMIT 1;

CREATE USER IF NOT EXISTS 'tomato_user'@'localhost'
IDENTIFIED BY '본인이_사용할_비밀번호';

GRANT ALL PRIVILEGES ON tomato_chatbot.*
TO 'tomato_user'@'localhost';

FLUSH PRIVILEGES;

