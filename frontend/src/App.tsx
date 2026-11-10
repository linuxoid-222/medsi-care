import { FormEvent, useEffect, useRef, useState } from "react";
import { parseObservationValue } from "./observationInput";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

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

type TrendPoint = {
  measured_at: string;
  value: number;
  baseline: number | null;
  event_ids: string[];
};

type Transcript = {
  text: string;
  language: string;
  duration_seconds: number | null;
};

type Fact = {
  category: string;
  polarity: "present" | "absent" | "uncertain";
  evidence: string;
  temporal_context?: string | null;
  confidence?: number | null;
  confirmed: boolean;
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
  source: string;
  created_at: string;
  text_revision: number;
  facts_revision: number;
  confirmed_revision: number | null;
  confirmed_at: string | null;
  facts: Fact[];
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

async function describeApiError(response: Response, fallback: string): Promise<string> {
  const payload = await response.json().catch(() => null);
  if (response.status === 403) return "Недостаточно прав для этого действия";
  if (response.status === 422) {
    const detail = payload?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg);
    return "Проверьте значения и формат данных";
  }
  return typeof payload?.detail === "string" ? payload.detail : fallback;
}

export function App() {
  const [metric, setMetric] = useState("sleep_hours");
  const [unit, setUnit] = useState("hours");
  const [value, setValue] = useState("8");
  const [text, setText] = useState("");
  const [observations, setObservations] = useState<Observation[]>([]);
  const [trendMetric, setTrendMetric] = useState("sleep_hours");
  const [trends, setTrends] = useState<TrendPoint[]>([]);
  const [demoLoad, setDemoLoad] = useState<{ anchor_date: string; timezone: string } | null>(null);
  const [loadingDemo, setLoadingDemo] = useState(false);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [error, setError] = useState("");
  const [isRecording, setIsRecording] = useState(false);
  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const [transcriptSaveStatus, setTranscriptSaveStatus] = useState<"idle" | "saving" | "saved">("idle");
  const transcriptSaveRef = useRef<Transcript | null>(null);
  const transcriptAttemptRef = useRef<{ transcript: Transcript; key: string } | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const [token, setToken] = useState(() => localStorage.getItem("medsi-care-token"));
  const [user, setUser] = useState<User | null>(null);
  const [loginId, setLoginId] = useState("demo-user");
  const [loginPassword, setLoginPassword] = useState("demo-user");
  const [loginError, setLoginError] = useState("");
  const [caregiverSummary, setCaregiverSummary] = useState<CaregiverSummary | null>(null);
  const [activeCheckIn, setActiveCheckIn] = useState<CheckIn | null>(null);
  const [factText, setFactText] = useState("");
  const [facts, setFacts] = useState<Fact[]>([]);
  const [safetyMessage, setSafetyMessage] = useState("");
  const [extractionFallback, setExtractionFallback] = useState(false);
  const [reviewDirty, setReviewDirty] = useState(false);
  const [manualCategory, setManualCategory] = useState("weakness");
  const [manualPolarity, setManualPolarity] = useState<Fact["polarity"]>("present");
  const [manualEvidence, setManualEvidence] = useState("");
  const requestEpoch = useRef(0);
  const textDirty = activeCheckIn !== null && factText.trim() !== (activeCheckIn.corrected_text ?? activeCheckIn.text);

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
    requestEpoch.current += 1;
    setActiveCheckIn(null);
    setFacts([]);
  }

  async function loadObservations() {
    const response = await apiFetch(`/api/v1/profiles/${profileId}/observations`);
    if (response.ok) setObservations(await response.json());
  }

  async function loadTrends(metricToLoad = trendMetric) {
    const response = await apiFetch(`/api/v1/profiles/${profileId}/trends?metric=${metricToLoad}&days=28`);
    if (response.ok) setTrends(await response.json());
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
    if (user.role === "user") {
      void loadObservations();
      const savedId = localStorage.getItem("medsi-care-check-in");
      if (savedId) void refreshCheckIn(savedId);
      void loadTrends();
    }
    else void apiFetch(`/api/v1/caregiver/profiles/${profileId}/summary`).then(async (response) => {
      if (response.ok) setCaregiverSummary(await response.json());
      else setError(await describeApiError(response, "Не удалось загрузить обзор доверенного лица"));
    });
  }, [user]);

  useEffect(() => {
    if (user?.role === "user") void loadTrends();
  }, [trendMetric]);

  async function loadDemo() {
    setLoadingDemo(true);
    setError("");
    try {
      const response = await apiFetch("/api/v1/demo/load-scenario", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reset: false }),
      });
      if (!response.ok) {
        setError(await describeApiError(response, "Не удалось загрузить демоданные"));
        return;
      }
      setDemoLoad(await response.json());
      setAnalysis(null);
      await Promise.all([loadObservations(), loadTrends()]);
    } catch {
      setError("Не удалось связаться с сервером при загрузке демоданных.");
    } finally {
      setLoadingDemo(false);
    }
  }

  async function submitObservation(event: FormEvent) {
    event.preventDefault();
    setError("");
    let numericValue: number;
    try {
      numericValue = parseObservationValue(value);
    } catch (error) {
      setError(error instanceof Error ? error.message : "Проверьте значение измерения");
      return;
    }
    const response = await apiFetch(`/api/v1/profiles/${profileId}/observations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        metric,
        value: numericValue,
        unit,
        measured_at: new Date().toISOString(),
      }),
    });
    if (!response.ok) {
      setError(await describeApiError(response, "Не удалось сохранить измерение"));
      return;
    }
    await loadObservations();
  }

  async function saveCheckIn(valueToSave: string, attemptKey?: string): Promise<CheckIn | null> {
    setError("");
    if (!valueToSave.trim()) {
      setError("Текст записи не должен быть пустым");
      return null;
    }
    const response = await apiFetch(`/api/v1/profiles/${profileId}/check-ins`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(attemptKey ? { "Idempotency-Key": attemptKey } : {}),
      },
      body: JSON.stringify({ text: valueToSave }),
    });
    if (!response.ok) {
      setError(await describeApiError(response, "Не удалось сохранить запись"));
      return null;
    }
    setText("");
    const saved = await response.json();
    requestEpoch.current += 1;
    localStorage.setItem("medsi-care-check-in", saved.id);
    setReviewDirty(false);
    setManualEvidence("");
    setActiveCheckIn(saved);
    setFactText(saved.corrected_text ?? saved.text);
    setFacts(saved.facts);
    setSafetyMessage("");
    setExtractionFallback(false);
    return saved;
  }

  async function submitCheckIn(event: FormEvent) {
    event.preventDefault();
    await saveCheckIn(text);
  }

  async function openLatestCheckIn() {
    const epoch = ++requestEpoch.current;
    try {
      const response = await apiFetch(`/api/v1/profiles/${profileId}/check-ins`);
      if (epoch !== requestEpoch.current) return;
      if (!response.ok) {
        setError(await describeApiError(response, "Не удалось загрузить записи"));
        return;
      }
      const records: CheckIn[] = await response.json();
      if (epoch !== requestEpoch.current) return;
      const latest = records.find((record) => record.source === "manual");
      if (!latest) {
        setError("Сохранённых записей самочувствия пока нет.");
        return;
      }
      showCheckIn(latest);
    } catch {
      if (epoch === requestEpoch.current) setError("Не удалось загрузить запись самочувствия.");
    }
  }

  async function refreshCheckIn(id = activeCheckIn?.id) {
    if (!id) return;
    const epoch = ++requestEpoch.current;
    const response = await apiFetch(`/api/v1/profiles/${profileId}/check-ins/${id}`);
    if (epoch !== requestEpoch.current) return;
    if (!response.ok) {
      setError(await describeApiError(response, "Не удалось загрузить запись"));
      return;
    }
    const saved: CheckIn = await response.json();
    if (epoch !== requestEpoch.current) return;
    showCheckIn(saved);
  }

  function showCheckIn(saved: CheckIn) {
    localStorage.setItem("medsi-care-check-in", saved.id);
    setActiveCheckIn(saved);
    setFactText(saved.corrected_text ?? saved.text);
    setFacts(saved.facts);
    setManualEvidence("");
    setSafetyMessage("");
    setExtractionFallback(false);
    setReviewDirty(false);
    setError("");
  }

  function editFacts(next: Fact[]) {
    requestEpoch.current += 1;
    setFacts(next);
    setReviewDirty(true);
  }

  function addManualFact() {
    if (!activeCheckIn || textDirty) {
      setError("Сначала сохраните текущую редакцию текста.");
      return;
    }
    const evidence = manualEvidence.trim();
    if (!evidence || !factText.includes(evidence)) {
      setError("Укажите точную цитату из текущего текста записи.");
      return;
    }
    if (facts.length >= 10) {
      setError("Можно подтвердить не более 10 фактов.");
      return;
    }
    editFacts([...facts, { category: manualCategory, polarity: manualPolarity,
      evidence, confirmed: false }]);
    setManualEvidence("");
    setError("");
  }

  async function extractFacts() {
    if (!activeCheckIn || textDirty) return;
    const epoch = ++requestEpoch.current;
    setError("");
    try {
      const response = await apiFetch(`/api/v1/profiles/${profileId}/check-ins/${activeCheckIn.id}/extract`, { method: "POST" });
      if (epoch !== requestEpoch.current) return;
      if (!response.ok) {
        setExtractionFallback(response.status === 502 || response.status === 503);
        setError(response.status === 502 || response.status === 503
          ? "Автоматическое извлечение фактов недоступно. Новые факты не сохранены."
          : await describeApiError(response, "Не удалось извлечь факты."));
        return;
      }
      const payload = await response.json();
      if (epoch !== requestEpoch.current || payload.text_revision !== activeCheckIn.text_revision) return;
      setFacts(payload.facts);
      setReviewDirty(true);
      setExtractionFallback(false);
    } catch {
      if (epoch !== requestEpoch.current) return;
      setExtractionFallback(true);
      setError("Нет связи с сервером. Проверьте подключение и повторите попытку.");
    }
  }

  async function saveCorrection() {
    if (!activeCheckIn || !factText.trim()) return;
    const epoch = ++requestEpoch.current;
    const response = await apiFetch(`/api/v1/profiles/${profileId}/check-ins/${activeCheckIn.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ corrected_text: factText, text_revision: activeCheckIn.text_revision }),
    });
    if (epoch !== requestEpoch.current) return;
    if (!response.ok) {
      setError(await describeApiError(response, "Не удалось сохранить исправленный текст"));
      return;
    }
    const saved: CheckIn = await response.json();
    if (epoch !== requestEpoch.current) return;
    setActiveCheckIn(saved);
    setFactText(saved.corrected_text ?? saved.text);
    setFacts(saved.facts);
    setReviewDirty(false);
    setError("");
  }

  async function confirmFacts() {
    if (!activeCheckIn || textDirty) return;
    const epoch = ++requestEpoch.current;
    const response = await apiFetch(`/api/v1/profiles/${profileId}/check-ins/${activeCheckIn.id}/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text_revision: activeCheckIn.text_revision,
        facts: facts.map(({ category, polarity, evidence, temporal_context, confidence }) => ({
          category, polarity, evidence, temporal_context, confidence,
        })),
      }),
    });
    if (epoch !== requestEpoch.current) return;
    if (!response.ok) {
      setError(await describeApiError(response, "Доказательство факта должно присутствовать в подтверждённом тексте"));
      return;
    }
    const payload = await response.json();
    if (epoch !== requestEpoch.current) return;
    setFacts(payload.facts);
    setActiveCheckIn({ ...activeCheckIn, status: "confirmed", facts: payload.facts,
      facts_revision: payload.facts_revision,
      confirmed_revision: payload.text_revision, confirmed_at: payload.confirmed_at });
    setReviewDirty(false);
    setSafetyMessage(payload.safety_event?.message ?? "");
    setError("");
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
    transcriptSaveRef.current = null;
    transcriptAttemptRef.current = null;
    setTranscriptSaveStatus("idle");
  }

  async function saveTranscript() {
    if (!transcript || transcriptSaveRef.current === transcript) return;
    if (transcriptAttemptRef.current?.transcript !== transcript) {
      transcriptAttemptRef.current = { transcript, key: crypto.randomUUID() };
    }
    const attemptKey = transcriptAttemptRef.current.key;
    transcriptSaveRef.current = transcript;
    setTranscriptSaveStatus("saving");
    let saved = false;
    try {
      saved = Boolean(await saveCheckIn(transcript.text, attemptKey));
    } catch {
      if (transcriptSaveRef.current === transcript) {
        setError("Не удалось сохранить транскрипт. Проверьте связь и повторите попытку.");
      }
    }
    if (transcriptSaveRef.current !== transcript) return;
    if (!saved) transcriptSaveRef.current = null;
    setTranscriptSaveStatus(saved ? "saved" : "idle");
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
    else setError(await describeApiError(response, "Для анализа нужно добавить хотя бы одно измерение"));
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
          {error && <p className="error">{error}</p>}
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
        <button type="button" onClick={loadDemo} disabled={loadingDemo}>Загрузить демоданные</button>
        {demoLoad && <p role="status">Демоданные по {demoLoad.anchor_date} ({demoLoad.timezone}).</p>}
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
            <input type="text" inputMode="decimal" value={value} onChange={(event) => setValue(event.target.value)} />
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
          <button type="button" disabled={transcriptSaveStatus === "saving"} onClick={isRecording ? stopRecording : startRecording}>
            {isRecording ? "Остановить запись" : "Записать голос"}
          </button>
          {isRecording && <p className="recording-status">Идёт запись…</p>}
          {transcript && (
            <div className="transcript">
              <strong>Распознанный текст</strong>
              <p>{transcript.text}</p>
              <small>{transcript.language} · {transcript.duration_seconds ? `${transcript.duration_seconds.toFixed(1)} с` : "длительность неизвестна"}</small>
              <button type="button" disabled={isRecording || transcriptSaveStatus !== "idle"}
                onClick={() => void saveTranscript()}>
                {transcriptSaveStatus === "saved" ? "Транскрипт сохранён" : "Сохранить транскрипт"}
              </button>
            </div>
          )}
        </section>

        <section className="card">
          <h2>Проверка фактов</h2>
          <button type="button" onClick={() => void openLatestCheckIn()}>Открыть последнюю запись</button>
          {extractionFallback && <p role="status">Резервный режим: автоматическое извлечение отключено для этой попытки. При доступном сервере ручной ввод, история и числовой анализ работают без LLM.</p>}
          {!activeCheckIn ? <p>Сначала сохраните текстовую или голосовую запись.</p> : <>
            <p role="status">{textDirty ? "Текст изменён: сохраните его и повторно проверьте факты." : reviewDirty ? "Факты изменены: требуется подтверждение." : activeCheckIn.status === "confirmed" ? `Проверено: ${facts.length} фактов. Редакция ${activeCheckIn.text_revision}.` : "Ожидает проверки фактов."}</p>
            <label>Текст для проверки<textarea value={factText} onChange={(event) => {
              requestEpoch.current += 1;
              setFactText(event.target.value);
              setManualEvidence("");
              setFacts([]);
              setReviewDirty(true);
            }} /></label>
            <div className="button-row">
              <button type="button" onClick={() => void saveCorrection()}>Сохранить исправление</button>
              <button type="button" onClick={() => void refreshCheckIn()}>Загрузить сохранённую запись</button>
              <button type="button" disabled={textDirty} onClick={() => void extractFacts()}>Извлечь факты</button>
            </div>
            <fieldset disabled={textDirty}>
              <legend>Ручной ввод фактов (без LLM)</legend>
              <p>Выберите категорию и точную цитату. Добавление создаёт черновик; затем проверьте и подтвердите факты.</p>
              <label>Категория ручного факта<select value={manualCategory} onChange={(event) => setManualCategory(event.target.value)}>
                <option value="weakness">Слабость</option><option value="sleep_problem">Проблемы сна</option><option value="cough">Кашель</option>
                <option value="chest_pain">Боль в груди</option><option value="shortness_of_breath">Затруднение дыхания</option>
                <option value="loss_of_consciousness">Потеря сознания</option><option value="stroke_signs">Указание на нарушение речи или движения</option>
                <option value="severe_bleeding">Сильное кровотечение</option>
              </select></label>
              <label>Наличие признака<select value={manualPolarity} onChange={(event) => setManualPolarity(event.target.value as Fact["polarity"])}>
                <option value="present">Есть</option><option value="absent">Явно отрицается</option><option value="uncertain">Неясно</option>
              </select></label>
              <label>Цитата для ручного факта<input value={manualEvidence} onChange={(event) => setManualEvidence(event.target.value)} /></label>
              <button type="button" onClick={addManualFact}>Добавить ручной факт</button>
            </fieldset>
            {facts.map((fact, index) => <div className="fact-row" key={`${fact.category}-${index}`}>
              <input value={fact.category} onChange={(event) => editFacts(facts.map((item, i) => i === index ? { ...item, category: event.target.value } : item))} />
              <select value={fact.polarity} onChange={(event) => editFacts(facts.map((item, i) => i === index ? { ...item, polarity: event.target.value as Fact["polarity"] } : item))}><option value="present">есть</option><option value="absent">нет</option><option value="uncertain">неясно</option></select>
              <input value={fact.evidence} onChange={(event) => editFacts(facts.map((item, i) => i === index ? { ...item, evidence: event.target.value } : item))} />
              <button type="button" onClick={() => editFacts(facts.filter((_, i) => i !== index))}>Удалить факт</button>
            </div>)}
            {safetyMessage && <div className="result result-safety"><strong>{safetyMessage}</strong></div>}
            {facts.length === 0 && <p>Пустой результат означает проверку без фактов и не отрицает все симптомы.</p>}
            <button type="button" disabled={textDirty} onClick={() => void confirmFacts()}>{facts.length ? "Подтвердить факты" : "Подтвердить пустой результат"}</button>
          </>}
        </section>
      </section>

      <section className="card">
        <div className="section-heading">
          <h2>История измерений</h2>
          <button type="button" onClick={runAnalysis}>Запустить анализ</button>
        </div>
        <label>График показателя<select value={trendMetric} onChange={(event) => setTrendMetric(event.target.value)}><option value="sleep_hours">Сон</option><option value="activity_minutes">Активность</option><option value="pulse_bpm">Пульс</option></select></label>
        {trends.length > 0 && <div className="chart"><ResponsiveContainer width="100%" height={260}><LineChart data={trends.map((item) => ({ ...item, label: new Date(item.measured_at).toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" }) }))}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="label" /><YAxis /><Tooltip /><Legend /><Line type="monotone" dataKey="value" name="Факт" stroke="#315fa8" strokeWidth={3} dot={false} /><Line type="monotone" dataKey="baseline" name="Baseline" stroke="#a35d31" strokeDasharray="5 5" dot={false} /></LineChart></ResponsiveContainer></div>}
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
