import { useCallback, useEffect, useRef, useState } from "react";
import "./App.css";
import {
  FiThermometer,
  FiDroplet,
  FiSend,
  FiAlertTriangle,
  FiCloudRain,
  FiWind,
} from "react-icons/fi";
import { BsClipboardCheck } from "react-icons/bs";
import { MdCo2 } from "react-icons/md";

import bgImage from "./assets/tomato_smartfarm_chatbot_bg.png";
import mascotImage from "./assets/tomato_mascot.svg";

const STATUS_API_BASE_URL =
  import.meta.env.VITE_STATUS_API_BASE_URL || "http://127.0.0.1:8000";
const CHAT_API_BASE_URL =
  import.meta.env.VITE_CHAT_API_BASE_URL || "http://127.0.0.1:8001";

console.log("STATUS_API_BASE_URL:", STATUS_API_BASE_URL);
console.log("CHAT_API_BASE_URL:", CHAT_API_BASE_URL);

function App() {
  const [message, setMessage] = useState("");

  const [currentTime, setCurrentTime] = useState(new Date());

  // 상태 박스에서 조회할 날짜
  // 오늘 날짜면 최신 실시간 데이터, 다른 날짜면 해당 날짜의 마지막 측정 데이터를 불러옴
  const [selectedDate, setSelectedDate] = useState(getTodayDate());

  const [chatList, setChatList] = useState([
    {
      type: "user",
      text: "1번 온실 토마토 상태 괜찮아?",
      time: "08:30",
    },
    {
      type: "bot",
      text: "현재 온실 상태는 전반적으로 괜찮지만 습도가 다소 높아요. 환기를 해주세요!",
      time: "08:30",
    },
  ]);

  const chatEndRef = useRef(null);

  // 현재 센서 상태
  const [status, setStatus] = useState(null);

  // API 연결 오류 메시지
  const [statusError, setStatusError] = useState("");

  // 채팅이 추가될 때마다 아래로 스크롤
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatList]);

  // 현재 시간 1초마다 갱신
  useEffect(() => {
    const timer = setInterval(() => {
      setCurrentTime(new Date());
    }, 1000);
  
    return () => {
      clearInterval(timer);
    };
  }, []);

  // FastAPI에서 선택한 날짜의 센서 상태 불러오기
  const loadStatus = useCallback(async () => {
    try {
      const today = getTodayDate();

      // 오늘 날짜면 최신 실시간 데이터 조회
      // 오늘이 아닌 날짜면 해당 날짜의 마지막 측정 데이터 조회
      const requestUrl =
        selectedDate === today
          ? `${STATUS_API_BASE_URL}/api/status`
          : `${STATUS_API_BASE_URL}/api/status/by-date?date=${selectedDate}`;

      const response = await fetch(requestUrl);

      if (!response.ok) {
        const errorData = await response.json();
        console.error("API 응답 오류:", errorData);
        setStatus(null);
        setStatusError(errorData.detail || "센서 데이터 불러오기 실패");
        return;
      }

      const data = await response.json();
      console.log("센서 데이터:", data);

      setStatus(data);
      setStatusError("");
    } catch (error) {
      console.error("센서 상태 불러오기 실패:", error);
      setStatus(null);
      setStatusError("FastAPI 서버 연결 실패");
    }
  }, [selectedDate]);

  // 선택한 날짜의 상태 불러오기
// 오늘 날짜일 때만 3초마다 자동 갱신
useEffect(() => {
  const firstLoadTimer = setTimeout(() => {
    loadStatus();
  }, 0);

  if (selectedDate !== getTodayDate()) {
    return () => {
      clearTimeout(firstLoadTimer);
    };
  }

  const intervalTimer = setInterval(() => {
    loadStatus();
  }, 3000);

  return () => {
    clearTimeout(firstLoadTimer);
    clearInterval(intervalTimer);
  };
}, [loadStatus, selectedDate]);

  const sendMessage = async () => {
    if (!message.trim()) return;

    const userMessage = {
      type: "user",
      text: message,
      time: getCurrentTime(),
    };

    setChatList((prev) => [...prev, userMessage]);

    const currentMessage = message;
    setMessage("");

    try {
      const response = await fetch(`${CHAT_API_BASE_URL}/api/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          question: normalizeDateWordsForChat(currentMessage),
          // 연결 테스트 단계에서는 false 권장: OpenRouter/LLM 오류와 서버 연결 오류를 분리할 수 있음
          use_llm: true,
        }),
      });
      
      if (!response.ok) {
        const errorText = await response.text();
        console.error("채팅 API 오류:", response.status, errorText);
        throw new Error("채팅 API 응답 실패");
      }
      
      const data = await response.json();
      console.log("챗봇 응답:", data);
      
      const botMessage = {
        type: "bot",
        text:
          data.bot_reply ||
          data.reply ||
          data.answer ||
          "현재 상태를 분석 중입니다. 잠시만 기다려 주세요.",
        time: getCurrentTime(),
      };

      setChatList((prev) => [...prev, botMessage]);
    } catch (error) {
      console.error("채팅 요청 실패:", error);
      const botMessage = {
        type: "bot",
        text: "서버 연결에 실패했어요. FastAPI 서버가 실행 중인지 확인해주세요.",
        time: getCurrentTime(),
      };

      setChatList((prev) => [...prev, botMessage]);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter") {
      sendMessage();
    }
  };

  return (
    <div className="app" style={{ backgroundImage: `url(${bgImage})` }}>
      <div className="overlay">
        <header className="hero">
          <div className="hero-text">
            <h1>토마토</h1>
            <h2>스마트팜 챗봇</h2>
          </div>

          <img
            src={mascotImage}
            alt="토마토 마스코트"
            className="hero-mascot"
          />
        </header>

        <main className="content">
          {/* 왼쪽 상태 카드 */}
          <section className="status-panel">
            <div className="date-control-box">
              <label htmlFor="status-date">조회 날짜</label>
              <input
                id="status-date"
                type="date"
                value={selectedDate}
                max={getTodayDate()}
                onChange={(e) => setSelectedDate(e.target.value)}
              />
            </div>

            <div className="panel-card">
              <div className="panel-header">
                <div>
                  <h3 className="panel-title">
                    {selectedDate === getTodayDate() ? "현재 상태" : "선택 날짜 상태"}
                  </h3>
                  <p className="status-date-text">
                    {formatDateLabel(selectedDate)}
                  </p>
                </div>

                <span className={status?.is_realtime ? "live-badge on" : "live-badge off"}>
                  {selectedDate === getTodayDate()
                    ? status?.is_realtime
                      ? "실시간"
                      : "지연"
                    : "기록"}
                </span>
              </div>

              <div className="time-summary">
                <div>
                  <span>현재 시간</span>
                  <strong>
                    {currentTime.toLocaleTimeString("ko-KR", {
                      hour: "2-digit",
                      minute: "2-digit",
                      second: "2-digit",
                    })}
                  </strong>
                </div>

                <div>
                  <span>측정 시간</span>
                  <strong>
                    {status
                      ? new Date(status.measured_at).toLocaleTimeString("ko-KR", {
                          hour: "2-digit",
                          minute: "2-digit",
                          second: "2-digit",
                        })
                      : "--:--:--"}
                  </strong>
                </div>
              </div>

              <div className="status-list">
                <div className="status-item">
                  <div className="status-label">
                    <FiThermometer className="status-icon" />
                    <span>온도</span>
                  </div>
                  <strong>
                    {status ? `${status.temperature}℃` : "불러오는 중"}
                  </strong>
                </div>

                <div className="status-item">
                  <div className="status-label">
                    <FiDroplet className="status-icon" />
                    <span>습도</span>
                  </div>
                  <strong>
                    {status ? `${status.humidity}%` : "불러오는 중"}
                  </strong>
                </div>

                <div className="status-item">
                  <div className="status-label">
                    <MdCo2 className="status-iconco2" />
                    <span>CO₂</span>
                  </div>
                  <strong>
                    {status ? `${status.co2}ppm` : "불러오는 중"}
                  </strong>
                </div>

                <div className="status-item">
                  <div className="status-label">
                    <FiCloudRain className="status-icon" />
                    <span>강수</span>
                  </div>
                  <strong>
                    {status
                      ? `${status.precipitation_type || "없음"} / ${status.rain_1h ?? 0}mm`
                      : "불러오는 중"}
                  </strong>
                </div>
                
                <div className="status-item">
                  <div className="status-label">
                    <FiWind className="status-icon" />
                    <span>풍속</span>
                  </div>
                  <strong>
                    {status ? `${status.wind_speed ?? 0}m/s` : "불러오는 중"}
                  </strong>
                </div>

                <div className="status-item">
                  <div className="status-label">
                    <span>시간대</span>
                  </div>
                  <strong>
                    {status ? status.time_slot : "불러오는 중"}
                  </strong>
                </div>

                <div className="status-item warning">
                  <div className="status-label">
                    <FiAlertTriangle className="status-icon" />
                    <span>위험도</span>
                  </div>
                  <strong>
                    {status ? status.risk_level : "불러오는 중"}
                  </strong>
                </div>
              </div>

              {statusError && (
                <p style={{ color: "red", marginTop: "12px", fontSize: "14px" }}>
                  {statusError}
                </p>
              )}
            </div>
          </section>

          {/* 오른쪽 챗봇 영역 */}
          <section className="chat-panel">
            <div className="chat-box">
              <div className="chat-messages">
                {chatList.map((chat, index) => (
                  <div
                    key={index}
                    className={`message-row ${
                      chat.type === "user" ? "user" : "bot"
                    }`}
                  >
                    {chat.type === "bot" && (
                      <img
                        src={mascotImage}
                        alt="bot"
                        className="chat-mascot"
                      />
                    )}

                    <div
                      className={`message-bubble ${
                        chat.type === "user" ? "user-bubble" : "bot-bubble"
                      }`}
                    >
                      <p>{chat.text}</p>
                      <span className="message-time">{chat.time}</span>
                    </div>
                  </div>
                ))}

                <div ref={chatEndRef} />
              </div>

              <div className="recommend-card">
                <div className="recommend-title">
                  <BsClipboardCheck />
                  <span>권장 조치</span>
                </div>

                <ul>
                  {status && status.reasons && status.reasons.length > 0 ? (
                    status.reasons.map((reason, index) => (
                      <li key={index}>{reason}</li>
                    ))
                  ) : (
                    <li>현재 이상 조건 없음</li>
                  )}
                </ul>
              </div>

              <div className="input-wrap">
                <input
                  type="text"
                  placeholder="질문을 입력하세요..."
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  onKeyDown={handleKeyDown}
                />

                <button onClick={sendMessage}>
                  <FiSend />
                </button>
              </div>
            </div>
          </section>
        </main>
      </div>
    </div>
  );
}


function getTodayDate() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");

  return `${year}-${month}-${day}`;
}

function formatDateLabel(dateText) {
  if (!dateText) return "날짜 선택 필요";

  const date = new Date(`${dateText}T00:00:00`);

  return date.toLocaleDateString("ko-KR", {
    year: "numeric",
    month: "long",
    day: "numeric",
    weekday: "short",
  });
}

function getCurrentTime() {
  const now = new Date();
  const hour = String(now.getHours()).padStart(2, "0");
  const min = String(now.getMinutes()).padStart(2, "0");
  return `${hour}:${min}`;
}

function formatKoreanMonthDay(date) {
  const month = date.getMonth() + 1;
  const day = date.getDate();

  return `${month}월${day}일`;
}

function normalizeDateWordsForChat(text) {
  const today = new Date();

  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);

  const twoDaysAgo = new Date(today);
  twoDaysAgo.setDate(today.getDate() - 2);

  let normalizedText = text;

  if (normalizedText.includes("그제") || normalizedText.includes("그저께")) {
    normalizedText = normalizedText
      .replaceAll("그저께", formatKoreanMonthDay(twoDaysAgo))
      .replaceAll("그제", formatKoreanMonthDay(twoDaysAgo));
  }

  if (normalizedText.includes("어제") || normalizedText.includes("전날")) {
    normalizedText = normalizedText
      .replaceAll("어제", formatKoreanMonthDay(yesterday))
      .replaceAll("전날", formatKoreanMonthDay(yesterday));
  }

  if (normalizedText.includes("오늘")) {
    normalizedText = normalizedText.replaceAll(
      "오늘",
      formatKoreanMonthDay(today)
    );
  }

  return normalizedText;
}

export default App;