import { FormEvent, useEffect, useRef, useState } from "react";

type Observation = {
  id: string;
  metric: string;
  value: number;
  unit: string;
  measured_at: string;
};

type Analysis = {
  status: string;
  message: string;
  evidence: string[];
};

type Transcript = {
  text: string;
  language: string;
  duration_seconds: number | null;
};

type User = {
  user_id: string;
  role: "user" | "caregiver";
  profile_id: string;
};

type CheckIn = {
  id: string;
  text: string;
  corrected_text: string | null;
  status: string;
  created_at: string;
};

type CaregiverSummary = {
  profile: { id: string; display_name: string; data_mode: string };
  observations: Observation[];
  check_ins: CheckIn[];
  latest_analysis: Analysis | null;
  events: MonitoringEvent[];
  notifications: Notification[];
};

type MonitoringEvent = {
  id: string;
  status: string;
  level: string;
  message: string;
  evidence: string[];
  created_at: string;
};

type Notification = {
  id: string;
  event_id: string;
  status: "unread" | "read";
  created_at: string;
};

const profileId = "profile-demo";

export function App() {
  const [metric, setMetric] = useState("sleep_hours");
  const [unit, setUnit] = useState("hours");
  const [value, setValue] = useState("8");
  const [text, setText] = useState("");
  const [observations, setObservations] = useState<Observation[]>([]);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [error, setError] = useState("");
  const [isRecording, setIsRecording] = useState(false);
  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const [token, setToken] = useState(() => localStorage.getItem("medsi-care-token"));
  const [user, setUser] = useState<User | null>(null);
  const [loginId, setLoginId] = useState("demo-user");
  const [loginPassword, setLoginPassword] = useState("demo-user");
  const [loginError, setLoginError] = useState("");
  const [caregiverSummary, setCaregiverSummary] = useState<CaregiverSummary | null>(null);

  async function apiFetch(path: string, init: RequestInit = {}) {
    const headers = new Headers(init.headers);
    if (token) headers.set("Authorization", `Bearer ${token}`);
    return fetch(path, { ...init, headers });
  }

  async function login(event: FormEvent) {
    event.preventDefault();
    setLoginError("");
    const response = await fetch("/api/v1/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: loginId, password: loginPassword }),
    });
    if (!response.ok) {
      setLoginError("Неверный демонстрационный логин или пароль");
      return;
    }
    const payload = await response.json();
    localStorage.setItem("medsi-care-token", payload.access_token);
    setToken(payload.access_token);
    setUser(payload.user);
  }

  function logout() {
    localStorage.removeItem("medsi-care-token");
    setToken(null);
    setUser(null);
    setCaregiverSummary(null);
  }

  async function loadObservations() {
    const response = await apiFetch(`/api/v1/profiles/${profileId}/observations`);
    if (response.ok) setObservations(await response.json());
  }

  useEffect(() => {
    if (!token) return;
    void apiFetch("/api/v1/me").then(async (response) => {
      if (response.ok) setUser(await response.json());
      else logout();
    });
  }, [token]);

  useEffect(() => {
    if (!user) return;
    if (user.role === "user") void loadObservations();
    else void apiFetch(`/api/v1/caregiver/profiles/${profileId}/summary`).then(async (response) => {
      if (response.ok) setCaregiverSummary(await response.json());
    });
  }, [user]);

  async function submitObservation(event: FormEvent) {
    event.preventDefault();
    setError("");
    const response = await apiFetch(`/api/v1/profiles/${profileId}/observations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        metric,
        value: Number(value),
        unit,
        measured_at: new Date().toISOString(),
      }),
    });
    if (!response.ok) {
      setError("Не удалось сохранить измерение");
      return;
    }
    await loadObservations();
  }

  async function saveCheckIn(valueToSave: string) {
    setError("");
    if (!valueToSave.trim()) {
      setError("Текст записи не должен быть пустым");
      return;
    }
    const response = await apiFetch(`/api/v1/profiles/${profileId}/check-ins`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: valueToSave }),
    });
    if (!response.ok) {
      setError("Не удалось сохранить запись");
      return;
    }
    setText("");
  }

  async function submitCheckIn(event: FormEvent) {
    event.preventDefault();
    await saveCheckIn(text);
  }

  async function uploadAudio(blob: Blob) {
    const formData = new FormData();
    const extension = blob.type.includes("webm") ? "webm" : blob.type.includes("ogg") ? "ogg" : "wav";
    formData.append("audio", blob, `recording.${extension}`);
    const response = await apiFetch(`/api/v1/profiles/${profileId}/audio/transcriptions`, {
      method: "POST",
      body: formData,
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      throw new Error(payload?.detail ?? "Не удалось распознать аудио");
    }
    setTranscript(await response.json());
  }

  async function startRecording() {
    setError("");
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setError("Браузер не поддерживает запись аудио");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const preferredMime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : "";
      const recorder = preferredMime ? new MediaRecorder(stream, { mimeType: preferredMime }) : new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
        stream.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
        void uploadAudio(blob).catch((uploadError: Error) => setError(uploadError.message));
      };
      streamRef.current = stream;
      recorderRef.current = recorder;
      recorder.start();
      setIsRecording(true);
    } catch {
      setError("Не удалось получить доступ к микрофону");
    }
  }

  function stopRecording() {
    recorderRef.current?.stop();
    recorderRef.current = null;
    setIsRecording(false);
  }

  async function runAnalysis() {
    const response = await apiFetch(`/api/v1/profiles/${profileId}/analysis`, {
      method: "POST",
    });
    if (response.ok) setAnalysis(await response.json());
    else setError("Для анализа нужно добавить хотя бы одно измерение");
  }

  async function markNotificationRead(notificationId: string) {
    const response = await apiFetch(`/api/v1/notifications/${notificationId}/read`, { method: "POST" });
    if (!response.ok || !caregiverSummary) return;
    const updated = await response.json();
    setCaregiverSummary({
      ...caregiverSummary,
      notifications: caregiverSummary.notifications.map((item) => item.id === updated.id ? updated : item),
    });
  }

  if (!user) {
    return (
      <main className="page login-page">
        <section className="card login-card">
          <p className="eyebrow">СИНТЕТИЧЕСКИЙ ПРОТОТИП</p>
          <h1>MEDSI Care</h1>
          <p>Войдите в демонстрационный профиль.</p>
          <form onSubmit={login}>
            <label>Пользователь<input value={loginId} onChange={(event) => setLoginId(event.target.value)} /></label>
            <label>Пароль<input type="password" value={loginPassword} onChange={(event) => setLoginPassword(event.target.value)} /></label>
            <button type="submit">Войти</button>
          </form>
          {loginError && <p className="error">{loginError}</p>}
          <small>Пользователь: demo-user / demo-user · Доверенное лицо: demo-caregiver / demo-caregiver</small>
        </section>
      </main>
    );
  }

  if (user.role === "caregiver") {
    return (
      <main className="page">
        <header className="section-heading">
          <div><p className="eyebrow">ДОВЕРЕННОЕ ЛИЦО</p><h1>MEDSI Care</h1></div>
          <button type="button" onClick={logout}>Выйти</button>
        </header>
        <section className="card">
          <h2>{caregiverSummary?.profile.display_name ?? "Обзор профиля"}</h2>
          <p>Режим: только просмотр · данные синтетические</p>
          {!caregiverSummary ? <p>Загрузка обзора…</p> : <>
            <h3>Последний анализ</h3>
            {caregiverSummary.latest_analysis ? <div className={`result result-${caregiverSummary.latest_analysis.status}`}><strong>{caregiverSummary.latest_analysis.message}</strong><p>{caregiverSummary.latest_analysis.evidence.join(" · ")}</p></div> : <p>Пока нет анализа.</p>}
            <h3>События мониторинга</h3>
            {caregiverSummary.events.length === 0 ? <p>Событий пока нет.</p> : <ul className="history">{caregiverSummary.events.map((event) => <li key={event.id}><strong>{event.level}</strong><span>{event.message} · {new Date(event.created_at).toLocaleString("ru-RU")}</span></li>)}</ul>}
            <h3>Уведомления</h3>
            {caregiverSummary.notifications.length === 0 ? <p>Уведомлений пока нет.</p> : <ul className="history">{caregiverSummary.notifications.map((item) => <li key={item.id}><strong>{item.status === "unread" ? "Новое" : "Прочитано"}</strong><span>{new Date(item.created_at).toLocaleString("ru-RU")}</span>{item.status === "unread" && <button type="button" onClick={() => void markNotificationRead(item.id)}>Прочитать</button>}</li>)}</ul>}
            <h3>Измерения</h3>
            <ul className="history">{caregiverSummary.observations.map((item) => <li key={item.id}><strong>{item.value} {item.unit}</strong><span>{item.metric} · {new Date(item.measured_at).toLocaleString("ru-RU")}</span></li>)}</ul>
            <h3>Записи самочувствия</h3>
            <ul className="history">{caregiverSummary.check_ins.map((item) => <li key={item.id}><strong>{item.status === "confirmed" ? "Подтверждена" : "Ожидает анализа"}</strong><span>{item.corrected_text ?? item.text}</span></li>)}</ul>
          </>}
        </section>
      </main>
    );
  }

  return (
    <main className="page">
      <header>
        <p className="eyebrow">СИНТЕТИЧЕСКИЙ ПРОТОТИП</p>
        <h1>MEDSI Care</h1>
        <p className="lead">Ручной дневник самочувствия и объяснимый анализ динамики.</p>
        <button type="button" onClick={logout}>Выйти</button>
      </header>

      <section className="grid">
        <form className="card" onSubmit={submitObservation}>
          <h2>Добавить измерение</h2>
          <label>
            Показатель
            <select value={metric} onChange={(event) => {
              const nextMetric = event.target.value;
              setMetric(nextMetric);
              setUnit(nextMetric === "sleep_hours" ? "hours" : nextMetric === "activity_minutes" ? "minutes" : nextMetric === "pulse_bpm" ? "bpm" : "mmHg");
            }}>
              <option value="sleep_hours">Сон</option>
              <option value="activity_minutes">Активность</option>
              <option value="pulse_bpm">Пульс</option>
            </select>
          </label>
          <label>
            Значение
            <input type="number" step="0.1" value={value} onChange={(event) => setValue(event.target.value)} />
          </label>
          <button type="submit">Сохранить измерение</button>
        </form>

        <form className="card" onSubmit={submitCheckIn}>
          <h2>Как вы себя чувствуете?</h2>
          <label>
            Текст записи
            <textarea value={text} onChange={(event) => setText(event.target.value)} placeholder="Например: сегодня чувствую себя обычно" />
          </label>
          <button type="submit">Сохранить запись</button>
        </form>

        <section className="card voice-card">
          <h2>Голосовая запись</h2>
          <p>Аудио обрабатывается локальным faster-whisper и сначала показывается для проверки.</p>
          <button type="button" onClick={isRecording ? stopRecording : startRecording}>
            {isRecording ? "Остановить запись" : "Записать голос"}
          </button>
          {isRecording && <p className="recording-status">Идёт запись…</p>}
          {transcript && (
            <div className="transcript">
              <strong>Распознанный текст</strong>
              <p>{transcript.text}</p>
              <small>{transcript.language} · {transcript.duration_seconds ? `${transcript.duration_seconds.toFixed(1)} с` : "длительность неизвестна"}</small>
              <button type="button" onClick={() => void saveCheckIn(transcript.text)}>Сохранить транскрипт</button>
            </div>
          )}
        </section>
      </section>

      <section className="card">
        <div className="section-heading">
          <h2>История измерений</h2>
          <button type="button" onClick={runAnalysis}>Запустить анализ</button>
        </div>
        {observations.length === 0 ? <p>Пока нет измерений.</p> : (
          <ul className="history">
            {observations.map((item) => <li key={item.id}><strong>{item.value} {item.unit}</strong><span>{item.metric} · {new Date(item.measured_at).toLocaleString("ru-RU")}</span></li>)}
          </ul>
        )}
        {analysis && <div className={`result result-${analysis.status}`}><strong>{analysis.message}</strong><p>{analysis.evidence.join(" · ")}</p></div>}
        {error && <p className="error">{error}</p>}
      </section>
    </main>
  );
}
