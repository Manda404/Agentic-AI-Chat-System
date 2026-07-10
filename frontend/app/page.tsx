"use client";

import type { ChangeEvent, CSSProperties, KeyboardEvent, PointerEvent as ReactPointerEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  Bot,
  MessageSquare,
  User,
  Link2,
  Route,
  Zap,
  Database,
  Clock,
  Settings,
  BarChart3,
  FileText,
  Inbox,
  Wrench,
  Heart,
  Monitor,
  AlertTriangle,
  Download,
  RefreshCw,
  LogOut,
  Send,
  Keyboard
} from "lucide-react";

type AgentResult = {
  agent: string;
  output: string;
  metadata: Record<string, unknown>;
};

type ChatResponse = {
  conversation_id: string;
  route: string;
  answer: string;
  agents_used: string[];
  agent_results: AgentResult[];
  cached: boolean;
  context_messages?: number;
  plan?: string[];
  critic_feedback?: string | null;
  critic_passed?: boolean;
  critic_score?: number | null;
  retrieval_metrics?: Record<string, unknown>;
  safety_feedback?: string | null;
  safety_passed?: boolean;
  evaluation?: Record<string, unknown>;
  trace_id?: string | null;
};

type Message = {
  role: "user" | "assistant";
  content: string;
};

type AuthMode = "login" | "register";

type AuthResponse = {
  access_token: string;
  token_type: string;
  email: string;
};

type HealthResponse = {
  status: string;
  app: string;
  environment: string;
  llm_provider: string;
  redis_connected: boolean;
  elasticsearch_connected: boolean;
};

type StatusTone = "online" | "offline" | "neutral";

type ActivityLog = {
  id: string;
  time: string;
  level: "INFO" | "WARN" | "ERROR";
  message: string;
};

type ViewMode = "desktop" | "tablet" | "mobile";

const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://127.0.0.1:8000";

const TOKEN_STORAGE_KEY = "multi-agent-starter-token";
const EMAIL_STORAGE_KEY = "multi-agent-starter-email";

const quickPrompts = [
  "How does LangGraph work?",
  "Explain Redis caching",
  "What is Langfuse observability?",
];

const MAX_ACTIVITY_LOGS = 28;

export default function Home() {
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      content:
        "✓ Ready. Test summary, search & multi-agent flows.",
    },
  ]);
  const [lastResponse, setLastResponse] = useState<ChatResponse | null>(null);
  const [loading, setLoading] = useState(false);

  const [authMode, setAuthMode] = useState<AuthMode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [token, setToken] = useState("");
  const [loggedInEmail, setLoggedInEmail] = useState("");
  const [authLoading, setAuthLoading] = useState(false);
  const [authMessage, setAuthMessage] = useState("Session offline.");
  const [ingestLoading, setIngestLoading] = useState(false);

  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthLoading, setHealthLoading] = useState(true);
  const [healthError, setHealthError] = useState("");
  const [lastHealthCheck, setLastHealthCheck] = useState("");
  const [clock, setClock] = useState("");
  const [viewMode, setViewMode] = useState<ViewMode>("desktop");
  const [leftPanelWidth, setLeftPanelWidth] = useState(250);
  const [rightPanelWidth, setRightPanelWidth] = useState(340);
  const resizeStateRef = useRef<{
    target: "left" | "right" | null;
    startX: number;
    startWidth: number;
  }>({
    target: null,
    startX: 0,
    startWidth: 0,
  });

  const [activityLogs, setActivityLogs] = useState<ActivityLog[]>([]);

  useEffect(() => {
    const storedToken = window.localStorage.getItem(TOKEN_STORAGE_KEY) ?? "";
    const storedEmail = window.localStorage.getItem(EMAIL_STORAGE_KEY) ?? "";
    if (storedToken) {
      setToken(storedToken);
      setLoggedInEmail(storedEmail);
      setAuthMessage(`Session live for ${storedEmail || "saved user"}.`);
      appendLog("INFO", `Recovered saved session for ${storedEmail || "saved user"}.`);
    } else {
      appendLog("WARN", "No saved session detected. Login required.");
    }
  }, []);

  useEffect(() => {
    const updateClock = () => {
      setClock(
        new Date().toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        })
      );
    };

    updateClock();
    const interval = window.setInterval(updateClock, 1000);

    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    const updateViewMode = () => {
      const width = window.innerWidth;
      if (width <= 640) {
        setViewMode("mobile");
      } else if (width <= 1180) {
        setViewMode("tablet");
      } else {
        setViewMode("desktop");
      }
    };

    updateViewMode();
    window.addEventListener("resize", updateViewMode);

    return () => window.removeEventListener("resize", updateViewMode);
  }, []);

  useEffect(() => {
    void fetchHealth("Initial health probe");
  }, []);

  const historyPayload = useMemo(
    () =>
      messages.map((message: Message) => ({
        role: message.role,
        content: message.content,
      })),
    [messages]
  );

  const isAuthenticated = Boolean(token);
  const messageCount = Math.max(messages.length - 1, 0);
  const isMobile = viewMode === "mobile";
  const isTablet = viewMode === "tablet";
  const supportsResizablePanels = !isTablet && !isMobile;

  useEffect(() => {
    if (!supportsResizablePanels) {
      return;
    }

    const onPointerMove = (event: PointerEvent) => {
      const activeResize = resizeStateRef.current;
      if (!activeResize.target) {
        return;
      }

      if (activeResize.target === "left") {
        const nextWidth = Math.min(Math.max(activeResize.startWidth + (event.clientX - activeResize.startX), 220), 360);
        setLeftPanelWidth(nextWidth);
        return;
      }

      const nextWidth = Math.min(Math.max(activeResize.startWidth - (event.clientX - activeResize.startX), 280), 460);
      setRightPanelWidth(nextWidth);
    };

    const stopResize = () => {
      resizeStateRef.current = {
        target: null,
        startX: 0,
        startWidth: 0,
      };
    };

    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", stopResize);

    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", stopResize);
    };
  }, [supportsResizablePanels]);

  function appendLog(level: ActivityLog["level"], message: string) {
    const time = new Date().toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });

    const logEntry: ActivityLog = {
      id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
      time,
      level,
      message,
    };

    setActivityLogs((current) => [logEntry, ...current].slice(0, MAX_ACTIVITY_LOGS));
  }

  async function fetchHealth(reason: string) {
    setHealthLoading(true);

    try {
      const response = await fetch(`${BACKEND_URL}/health`, {
        method: "GET",
      });

      if (!response.ok) {
        throw new Error("Health endpoint unavailable.");
      }

      const data: HealthResponse = await response.json();
      setHealth(data);
      setHealthError("");
      const checkedAt = new Date().toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
      setLastHealthCheck(checkedAt);
      appendLog(
        "INFO",
        `${reason}: backend=${data.status}, redis=${data.redis_connected ? "online" : "offline"}, elastic=${data.elasticsearch_connected ? "online" : "offline"}, provider=${data.llm_provider}.`
      );
    } catch (error) {
      setHealth(null);
      const nextError =
        error instanceof Error ? error.message : "Failed to load backend health.";
      setHealthError(nextError);
      setLastHealthCheck(
        new Date().toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        })
      );
      appendLog("ERROR", `${reason}: ${nextError}`);
    } finally {
      setHealthLoading(false);
    }
  }

  function startResize(
    target: "left" | "right",
    event: ReactPointerEvent<HTMLDivElement>
  ) {
    if (!supportsResizablePanels) {
      return;
    }

    resizeStateRef.current = {
      target,
      startX: event.clientX,
      startWidth: target === "left" ? leftPanelWidth : rightPanelWidth,
    };
  }

  function persistSession(nextToken: string, nextEmail: string) {
    window.localStorage.setItem(TOKEN_STORAGE_KEY, nextToken);
    window.localStorage.setItem(EMAIL_STORAGE_KEY, nextEmail);
    setToken(nextToken);
    setLoggedInEmail(nextEmail);
  }

  function logout() {
    window.localStorage.removeItem(TOKEN_STORAGE_KEY);
    window.localStorage.removeItem(EMAIL_STORAGE_KEY);
    setToken("");
    setLoggedInEmail("");
    setConversationId(null);
    setLastResponse(null);
    setInput("");
    setAuthMessage("Session offline.");
    setMessages([
      {
        role: "assistant",
        content: "Session cleared. Login again to reopen the chat workspace.",
      },
    ]);
    appendLog("WARN", "User logged out and local session storage was cleared.");
  }

  function handleAuthError(error: unknown, response?: Response): boolean {
    const errorMessage = error instanceof Error ? error.message : String(error);
    const isTokenExpired =
      errorMessage.includes("Invalid token") ||
      errorMessage.includes("Signature has expired") ||
      errorMessage.includes("Token has expired") ||
      (response && response.status === 401);
    
    if (isTokenExpired) {
      logout();
      appendLog("ERROR", "Session expired. Please login again.");
      return true;
    }
    return false;
  }

  async function handleAuth() {
    if (!email.trim() || !password.trim() || authLoading) {
      appendLog("WARN", "Auth attempt blocked because email or password is empty.");
      return;
    }

    setAuthLoading(true);
    setAuthMessage(authMode === "login" ? "Authorizing..." : "Creating identity...");
    appendLog(
      "INFO",
      authMode === "login"
        ? `Login requested for ${email.trim()}.`
        : `Registration requested for ${email.trim()}.`
    );

    try {
      if (authMode === "register") {
        const registerResponse = await fetch(`${BACKEND_URL}/api/v1/auth/register`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            email: email.trim(),
            password,
          }),
        });

        if (!registerResponse.ok) {
          const errorText = await registerResponse.text();
          throw new Error(errorText || "Registration failed.");
        }

        appendLog("INFO", `Registration completed for ${email.trim()}.`);
      }

      const loginResponse = await fetch(`${BACKEND_URL}/api/v1/auth/login`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          email: email.trim(),
          password,
        }),
      });

      if (!loginResponse.ok) {
        const errorText = await loginResponse.text();
        throw new Error(errorText || "Login failed.");
      }

      const data: AuthResponse = await loginResponse.json();
      persistSession(data.access_token, data.email);
      setAuthMessage(`Session live for ${data.email}.`);
      setPassword("");
      appendLog("INFO", `Authentication successful for ${data.email}.`);
    } catch (error) {
      const nextMessage =
        error instanceof Error ? error.message : "Authentication request failed.";
      setAuthMessage(nextMessage);
      appendLog("ERROR", `Authentication failure: ${nextMessage}`);
    } finally {
      setAuthLoading(false);
    }
  }

  async function ingestSampleData() {
    if (!token || ingestLoading) {
      appendLog("WARN", "Ingest request skipped because session is offline or a job is already running.");
      return;
    }

    setIngestLoading(true);
    setAuthMessage("Indexing sample documents...");
    appendLog("INFO", "Sample ingest triggered.");

    try {
      const response = await fetch(`${BACKEND_URL}/api/v1/ingest/batch`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (!response.ok) {
        const errorText = await response.text();
        if (handleAuthError(errorText, response)) {
          return;
        }
        throw new Error(errorText || "Ingest failed.");
      }

      const data = (await response.json()) as {
        total_files_processed: number;
        total_documents_indexed: number;
        index_name: string;
        files_summary: Array<{
          file_path: string;
          documents_processed: number;
          documents_indexed: number;
          status: string;
        }>;
        errors?: string[];
      };

      setAuthMessage(
        `Indexed ${data.total_documents_indexed} docs from ${data.total_files_processed} files into ${data.index_name}.`
      );
      appendLog(
        "INFO",
        `Batch ingest completed: ${data.total_documents_indexed} documents indexed from ${data.total_files_processed} files.`
      );
      void fetchHealth("Post-ingest health probe");
    } catch (error) {
      if (handleAuthError(error)) {
        return;
      }
      const nextMessage = error instanceof Error ? error.message : "Ingest failed.";
      setAuthMessage(nextMessage);
      appendLog("ERROR", `Ingest failure: ${nextMessage}`);
    } finally {
      setIngestLoading(false);
    }
  }

  async function sendMessage(promptOverride?: string) {
    if (loading || !token) {
      appendLog("WARN", "Message send skipped because session is offline or request is already running.");
      return;
    }

    const nextMessage = (promptOverride ?? input).trim();
    if (!nextMessage) {
      appendLog("WARN", "Message send skipped because the prompt was empty.");
      return;
    }

    setMessages((current: Message[]) => [
      ...current,
      { role: "user", content: nextMessage },
    ]);
    setInput("");
    setLoading(true);
    appendLog("INFO", `Chat request started: ${nextMessage.slice(0, 72)}${nextMessage.length > 72 ? "..." : ""}`);

    try {
      const response = await fetch(`${BACKEND_URL}/api/v1/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          message: nextMessage,
          conversation_id: conversationId,
          history: historyPayload,
        }),
      });

      if (!response.ok) {
        const errorText = await response.text();
        if (handleAuthError(errorText, response)) {
          return;
        }
        throw new Error(errorText || "Backend request failed.");
      }

      const data: ChatResponse = await response.json();
      setConversationId(data.conversation_id);
      setLastResponse(data);
      setMessages((current: Message[]) => [
        ...current,
        { role: "assistant", content: data.answer },
      ]);
      appendLog(
        "INFO",
        `Chat response complete: route=${data.route}, agents=${data.agents_used.join(", ") || "none"}, cached=${String(data.cached)}.`
      );
    } catch (error) {
      if (handleAuthError(error)) {
        return;
      }
      const nextMessageText =
        error instanceof Error
          ? error.message
          : "Request failed. Make sure the backend is running and you are logged in.";

      setMessages((current: Message[]) => [
        ...current,
        {
          role: "assistant",
          content: nextMessageText,
        },
      ]);
      appendLog("ERROR", `Chat failure: ${nextMessageText}`);
    } finally {
      setLoading(false);
    }
  }

  function onComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      void sendMessage();
    }
  }

  const backendTone: StatusTone = healthError
    ? "offline"
    : health?.status === "ok"
      ? "online"
      : "neutral";

  const redisTone: StatusTone = health?.redis_connected ? "online" : "offline";
  const elasticTone: StatusTone = health?.elasticsearch_connected ? "online" : "offline";
  const modelTone: StatusTone =
    health?.llm_provider === "ollama" || health?.llm_provider === "huggingface"
      ? healthError
        ? "offline"
        : "online"
      : health?.llm_provider
        ? "neutral"
        : "offline";

  const authFrameStyle: CSSProperties = {
    ...styles.authFrame,
    ...(isTablet ? styles.authFrameTablet : {}),
    ...(isMobile ? styles.authFrameMobile : {}),
  };

  const authTopBarStyle: CSSProperties = {
    ...styles.authTopBar,
    ...(isMobile ? styles.authTopBarMobile : {}),
  };

  const cornerMetaStyle: CSSProperties = {
    ...styles.cornerMeta,
    ...(isMobile ? styles.cornerMetaMobile : {}),
  };

  const authGridStyle: CSSProperties = {
    ...styles.authGrid,
    ...((isTablet || isMobile) ? styles.authGridStacked : {}),
  };

  const authTitleStyle: CSSProperties = {
    ...styles.authTitle,
    ...(isMobile ? styles.authTitleMobile : {}),
  };

  const quickInfoGridStyle: CSSProperties = {
    ...styles.quickInfoGrid,
    ...(isMobile ? styles.quickInfoGridMobile : {}),
  };

  const bottomHintsStyle: CSSProperties = {
    ...styles.bottomHints,
    ...(isMobile ? styles.bottomHintsMobile : {}),
  };

  const hintChipStyle: CSSProperties = {
    ...styles.hintChip,
    ...(isMobile ? styles.hintChipMobile : {}),
  };

  const appShellStyle: CSSProperties = {
    ...styles.appShell,
    ...(isTablet ? styles.appShellTablet : {}),
    ...(isMobile ? styles.appShellMobile : {}),
    ...(supportsResizablePanels
      ? { gridTemplateColumns: `${leftPanelWidth}px 10px minmax(0, 1fr) 10px ${rightPanelWidth}px` }
      : {}),
  };

  const leftRailStyle: CSSProperties = {
    ...styles.leftRail,
    ...((isTablet || isMobile) ? styles.leftRailFlow : styles.leftRailSticky),
  };

  const chatColumnStyle: CSSProperties = {
    ...styles.chatColumn,
    ...(isTablet ? styles.chatColumnTablet : {}),
    ...(isMobile ? styles.chatColumnMobile : {}),
  };

  const topStripStyle: CSSProperties = {
    ...styles.topStrip,
    ...(isMobile ? styles.topStripMobile : {}),
  };

  const topStripLeftStyle: CSSProperties = {
    ...styles.topStripLeft,
    ...(isMobile ? styles.topStripLeftMobile : {}),
  };

  const topStripRightStyle: CSSProperties = {
    ...styles.topStripRight,
    ...(isMobile ? styles.topStripRightMobile : {}),
  };

  const chatWindowStyle: CSSProperties = {
    ...styles.chatWindow,
    ...(isTablet ? styles.chatWindowTablet : {}),
    ...(isMobile ? styles.chatWindowMobile : {}),
  };

  const promptDockStyle: CSSProperties = {
    ...styles.promptDock,
    ...(isMobile ? styles.promptDockMobile : {}),
    ...(isAuthenticated ? styles.promptDockAuthenticated : {}),
  };

  const promptRowStyle: CSSProperties = {
    ...styles.promptRow,
    ...(isMobile ? styles.promptRowMobile : {}),
  };

  const promptChipStyle: CSSProperties = {
    ...styles.promptChip,
    ...(isMobile ? styles.promptChipMobile : {}),
  };

  const composerStyle: CSSProperties = {
    ...styles.composer,
    ...(isMobile ? styles.composerMobile : {}),
    ...(isAuthenticated ? styles.composerAuthenticated : {}),
  };

  const textareaStyle: CSSProperties = {
    ...styles.textarea,
    ...(isMobile ? styles.textareaMobile : {}),
  };

  const composerFooterStyle: CSSProperties = {
    ...styles.composerFooter,
    ...(isMobile ? styles.composerFooterMobile : {}),
  };

  const composerHintStyle: CSSProperties = {
    ...styles.composerHint,
    ...(isMobile ? styles.composerHintMobile : {}),
  };

  const rightRailStyle: CSSProperties = {
    ...styles.rightRail,
    ...((isTablet || isMobile) ? styles.rightRailFlow : styles.rightRailSticky),
  };

  const terminalCardStyle: CSSProperties = {
    ...styles.terminalCard,
    ...(isTablet ? styles.terminalCardTablet : {}),
    ...(isMobile ? styles.terminalCardMobile : {}),
  };

  const logLineStyle: CSSProperties = {
    ...styles.logLine,
    ...(isMobile ? styles.logLineMobile : {}),
  };

  const terminalLineStyle: CSSProperties = {
    ...styles.terminalLine,
    ...(isMobile ? styles.terminalLineMobile : {}),
  };

  const messageBubbleBaseStyle = (role: "user" | "assistant"): CSSProperties => ({
    ...styles.messageBubble,
    ...(isMobile ? styles.messageBubbleMobile : {}),
    ...(role === "user" ? styles.userBubble : styles.assistantBubble),
  });

  return (
    <main style={styles.page}>
      {!isAuthenticated ? (
        <section style={styles.authShell}>
          <div style={authFrameStyle}>
            <div style={authTopBarStyle}>
              <div style={styles.monoBrand}>
                <Bot size={16} style={{ display: "inline-block", verticalAlign: "middle", marginRight: 6 }} />
                multi-agent
              </div>
              <div style={cornerMetaStyle}>
                <span>{clock || "--:--:--"}</span>
                <span>health: {healthError ? "offline" : "online"}</span>
              </div>
            </div>

            <div style={authGridStyle}>
              <div style={styles.authIntro}>
                <div style={styles.sectionKicker}>multi agent starter</div>
                <h1 style={authTitleStyle}>workspace</h1>
                <p style={styles.authText}>
                  Test agents, routing, cache & retrieval
                </p>

                <div style={styles.cornerCard}>
                  <StatusDot label="backend" tone={backendTone} />
                  <StatusDot label="redis" tone={redisTone} />
                  <StatusDot label="elastic" tone={elasticTone} />
                  <StatusDot label="model" tone={modelTone} />
                </div>

                <div style={quickInfoGridStyle}>
                  <InfoMiniCard label="provider" value={health?.llm_provider ?? "unknown"} />
                  <InfoMiniCard
                    label="last check"
                    value={lastHealthCheck || "--:--:--"}
                  />
                </div>
              </div>

              <form
                style={styles.authPanel}
                onSubmit={(event) => {
                  event.preventDefault();
                  void handleAuth();
                }}
              >
                <div style={styles.modeSwitch}>
                  <button
                    type="button"
                    onClick={() => setAuthMode("login")}
                    style={{
                      ...styles.modeButton,
                      ...(authMode === "login" ? styles.modeButtonActive : {}),
                    }}
                  >
                    login
                  </button>
                  <button
                    type="button"
                    onClick={() => setAuthMode("register")}
                    style={{
                      ...styles.modeButton,
                      ...(authMode === "register" ? styles.modeButtonActive : {}),
                    }}
                  >
                    register
                  </button>
                </div>

                <label style={styles.fieldLabel}>
                  email
                  <input
                    type="email"
                    name="email"
                    autoComplete="email"
                    autoCapitalize="none"
                    autoCorrect="off"
                    spellCheck={false}
                    value={email}
                    onChange={(event: ChangeEvent<HTMLInputElement>) =>
                      setEmail(event.target.value)
                    }
                    placeholder="you@example.com"
                    style={styles.input}
                  />
                </label>

                <label style={styles.fieldLabel}>
                  password
                  <input
                    type="password"
                    name="password"
                    autoComplete={authMode === "login" ? "current-password" : "new-password"}
                    autoCapitalize="none"
                    autoCorrect="off"
                    spellCheck={false}
                    value={password}
                    onChange={(event: ChangeEvent<HTMLInputElement>) =>
                      setPassword(event.target.value)
                    }
                    placeholder="Enter password"
                    style={styles.input}
                  />
                </label>

                <button type="submit" style={styles.primaryButton} disabled={authLoading}>
                  {authLoading
                    ? authMode === "login"
                      ? "authorizing..."
                      : "creating..."
                    : authMode === "login"
                      ? "enter workspace"
                      : "create and enter"}
                </button>

                <div style={styles.authFooterText}>{authMessage}</div>
              </form>
            </div>

            <div style={bottomHintsStyle}>
              {quickPrompts.map((prompt) => (
                <div key={prompt} style={hintChipStyle}>
                  {prompt}
                </div>
              ))}
            </div>
          </div>
        </section>
      ) : (
        <section style={appShellStyle}>
          <aside style={leftRailStyle}>
            <div style={{ ...styles.railBox, ...styles.leftPanelBox }}>
              <div style={styles.railHeader}>
                <div>
                  <div style={styles.sectionKicker}>
                    <MessageSquare size={12} style={{ display: "inline-block", verticalAlign: "middle", marginRight: 4 }} />
                    session
                  </div>
                  <div style={styles.railTitle}>console</div>
                </div>
                <div style={styles.smallMono}>●</div>
              </div>

              <div style={styles.mutedList}>
                <div style={styles.metricRow}>
                  <span style={styles.metricKey}>
                    <User size={11} style={{ display: "inline-block", verticalAlign: "middle" }} />
                  </span>
                  <span style={styles.metricValue}>{loggedInEmail}</span>
                </div>
                <div style={styles.metricRow}>
                  <span style={styles.metricKey}>
                    <Link2 size={11} style={{ display: "inline-block", verticalAlign: "middle" }} />
                  </span>
                  <span style={styles.metricValue}>{conversationId ?? "new"}</span>
                </div>
                <div style={styles.metricRow}>
                  <span style={styles.metricKey}>
                    <MessageSquare size={11} style={{ display: "inline-block", verticalAlign: "middle" }} />
                  </span>
                  <span style={styles.metricValue}>{String(messageCount)}</span>
                </div>
                <div style={styles.metricRow}>
                  <span style={styles.metricKey}>
                    <Route size={11} style={{ display: "inline-block", verticalAlign: "middle" }} />
                  </span>
                  <span style={styles.metricValue}>{lastResponse?.route ?? "--"}</span>
                </div>
              </div>
            </div>

            <div style={{ ...styles.railBox, ...styles.leftPanelBox }}>
              <div style={styles.railHeader}>
                <div>
                  <div style={styles.sectionKicker}>
                    <Zap size={12} style={{ display: "inline-block", verticalAlign: "middle", marginRight: 4 }} />
                    status
                  </div>
                  <div style={styles.railTitle}>system</div>
                </div>
                <div style={styles.smallMono}>{clock || "--:--:--"}</div>
              </div>

              <div style={styles.statusStack}>
                <StatusDot label="backend" tone={backendTone} />
                <StatusDot label="redis" tone={redisTone} />
                <StatusDot label="elastic" tone={elasticTone} />
                <StatusDot label="model" tone={modelTone} />
              </div>

              <div style={styles.cornerInfo}>
                <div>
                  <Clock size={10} style={{ display: "inline-block", verticalAlign: "middle", marginRight: 4 }} />
                  {lastHealthCheck || "--:--:--"}
                </div>
                <div>
                  <Database size={10} style={{ display: "inline-block", verticalAlign: "middle", marginRight: 4 }} />
                  {lastResponse ? String(lastResponse.cached) : "--"}
                </div>
              </div>
            </div>

            <div style={{ ...styles.railBox, ...styles.leftPanelBox }}>
              <div style={styles.railHeader}>
                <div>
                  <div style={styles.sectionKicker}>
                    <Settings size={12} style={{ display: "inline-block", verticalAlign: "middle", marginRight: 4 }} />
                    actions
                  </div>
                  <div style={styles.railTitle}>controls</div>
                </div>
              </div>

              <div style={styles.actionColumn}>
                <button
                  type="button"
                  onClick={ingestSampleData}
                  style={styles.primaryButtonSquare}
                  disabled={ingestLoading}
                >
                  {ingestLoading ? (
                    <>
                      <Clock size={14} style={{ display: "inline-block", verticalAlign: "middle", marginRight: 6 }} />
                      indexing...
                    </>
                  ) : (
                    <>
                      <Download size={14} style={{ display: "inline-block", verticalAlign: "middle", marginRight: 6 }} />
                      ingest data
                    </>
                  )}
                </button>
                <button
                  type="button"
                  onClick={() => void fetchHealth("Manual health refresh")}
                  style={styles.secondaryButtonSquare}
                  disabled={healthLoading}
                >
                  {healthLoading ? (
                    <>
                      <Clock size={14} style={{ display: "inline-block", verticalAlign: "middle", marginRight: 6 }} />
                      checking...
                    </>
                  ) : (
                    <>
                      <RefreshCw size={14} style={{ display: "inline-block", verticalAlign: "middle", marginRight: 6 }} />
                      refresh
                    </>
                  )}
                </button>
                <button type="button" onClick={logout} style={styles.secondaryButtonSquare}>
                  <LogOut size={14} style={{ display: "inline-block", verticalAlign: "middle", marginRight: 6 }} />
                  logout
                </button>
              </div>

              <div style={styles.cornerInfo}>{authMessage}</div>
            </div>
          </aside>

          {supportsResizablePanels ? (
            <div
              style={styles.resizeDivider}
              onPointerDown={(event) => startResize("left", event)}
            />
          ) : null}

          <section style={chatColumnStyle}>
            <div style={{ ...topStripStyle, ...styles.chatPanelChrome }}>
              <div style={topStripLeftStyle}>
                <div style={styles.monoBrand}>
                  <MessageSquare size={14} style={{ display: "inline-block", verticalAlign: "middle", marginRight: 6 }} />
                  chat
                </div>
                <div style={styles.stripMeta}>
                  <Bot size={12} style={{ display: "inline-block", verticalAlign: "middle", marginRight: 4 }} />
                  {health?.llm_provider ?? "unknown"}
                </div>
              </div>
              <div style={topStripRightStyle}>
                <span>
                  <FileText size={12} style={{ display: "inline-block", verticalAlign: "middle", marginRight: 4 }} />
                  {lastResponse?.context_messages ?? 0}
                </span>
              </div>
            </div>

            <div style={chatWindowStyle}>
              {messages.map((message, index) => (
                <div
                  key={`${message.role}-${index}`}
                  style={{
                    ...styles.messageRow,
                    ...(message.role === "user"
                      ? styles.messageRowUser
                      : styles.messageRowAssistant),
                  }}
                >
                  <div style={styles.avatar}>{message.role === "user" ? "U" : "AI"}</div>
                  <div style={messageBubbleBaseStyle(message.role)}>
                    <div style={styles.messageMeta}>
                      {message.role === "user" ? "user" : "assistant"}
                    </div>
                    <div style={styles.messageContent}>
                      {renderRichText(message.content)}
                    </div>
                  </div>
                </div>
              ))}

              {loading ? (
                <div style={styles.messageRow}>
                  <div style={styles.avatar}>AI</div>
                  <div style={messageBubbleBaseStyle("assistant")}>
                    <div style={styles.messageMeta}>assistant</div>
                    <div style={styles.typingRow}>
                      <span style={styles.typingDot} />
                      <span style={styles.typingDot} />
                      <span style={styles.typingDot} />
                    </div>
                  </div>
                </div>
              ) : null}
            </div>

            <div style={{ ...promptDockStyle, ...styles.composerDockChrome }}>
              <div style={styles.promptDockHeader}>
                {/* <span style={styles.promptDockTitle}>
                  <Zap size={11} style={{ display: "inline-block", verticalAlign: "middle", marginRight: 4 }} />
                  quick prompts
                </span>
                <span style={styles.promptDockMeta}>tap to load</span> */}
              </div>

              <div style={styles.promptScrollArea}>
                <div style={promptRowStyle}>
                  {quickPrompts.map((prompt) => (
                    <button
                      key={prompt}
                      type="button"
                      onClick={() => setInput(prompt)}
                      style={promptChipStyle}
                    >
                      {prompt}
                    </button>
                  ))}
                </div>
              </div>

              <div style={composerStyle}>
                <textarea
                  value={input}
                  onChange={(event: ChangeEvent<HTMLTextAreaElement>) =>
                    setInput(event.target.value)
                  }
                  onKeyDown={onComposerKeyDown}
                  placeholder="Type message... Cmd/Ctrl+Enter to send"
                  style={textareaStyle}
                  rows={3}
                />
                <div style={composerFooterStyle}>
                  <div style={composerHintStyle}>
                    <Keyboard size={10} style={{ display: "inline-block", verticalAlign: "middle", marginRight: 4 }} />
                    Cmd+Enter
                  </div>
                  <button
                    type="button"
                    onClick={() => void sendMessage()}
                    style={styles.primaryButton}
                    disabled={loading}
                  >
                    {loading ? (
                      <Clock size={16} />
                    ) : (
                      <Send size={16} />
                    )}
                  </button>
                </div>
              </div>
            </div>
          </section>

          {supportsResizablePanels ? (
            <div
              style={styles.resizeDivider}
              onPointerDown={(event) => startResize("right", event)}
            />
          ) : null}

          <aside style={rightRailStyle}>
            <div style={{ ...terminalCardStyle, ...styles.logsPanelBox }}>
              <div style={styles.terminalHeader}>
                <div style={styles.terminalTitle}>
                  <BarChart3 size={12} style={{ display: "inline-block", verticalAlign: "middle", marginRight: 6 }} />
                  activity
                </div>
                <div style={styles.smallMono}>{clock || "--:--:--"}</div>
              </div>

              <div style={styles.terminalBody}>
                <div style={styles.terminalBlock}>
                  <div style={styles.terminalBlockTitle}>
                    <FileText size={10} style={{ display: "inline-block", verticalAlign: "middle", marginRight: 4 }} />
                    events
                  </div>
                  {activityLogs.length ? (
                    activityLogs.map((log) => (
                      <div key={log.id} style={logLineStyle}>
                        <span style={styles.logTime}>{log.time}</span>
                        <span
                          style={{
                            ...styles.logLevel,
                            ...(log.level === "ERROR"
                              ? styles.logLevelError
                              : log.level === "WARN"
                                ? styles.logLevelWarn
                                : styles.logLevelInfo),
                          }}
                        >
                          {log.level}
                        </span>
                        <span style={styles.logMessage}>{log.message}</span>
                      </div>
                    ))
                  ) : (
                    <div style={styles.emptyText}>No events yet.</div>
                  )}
                </div>

                <div style={styles.terminalBlock}>
                  <div style={styles.terminalBlockTitle}>
                    <Inbox size={10} style={{ display: "inline-block", verticalAlign: "middle", marginRight: 4 }} />
                    response
                  </div>
                  <TerminalLine
                    label={<Route size={11} />}
                    value={lastResponse?.route ?? "--"}
                    style={terminalLineStyle}
                  />
                  <TerminalLine
                    label={<Bot size={11} />}
                    value={
                      lastResponse?.agents_used?.length
                        ? lastResponse.agents_used.join(", ")
                        : "--"
                    }
                    style={terminalLineStyle}
                  />
                  <TerminalLine
                    label={<Database size={11} />}
                    value={lastResponse ? String(lastResponse.cached) : "--"}
                    style={terminalLineStyle}
                  />
                  <TerminalLine
                    label={<FileText size={11} />}
                    value={lastResponse?.plan?.length ? lastResponse.plan.join(" > ") : "--"}
                    style={terminalLineStyle}
                  />
                  <TerminalLine
                    label={<AlertTriangle size={11} />}
                    value={
                      lastResponse
                        ? `${String(Boolean(lastResponse.critic_passed))} ${lastResponse.critic_score ?? "--"} ${lastResponse.critic_feedback ?? ""}`.trim()
                        : "--"
                    }
                    style={terminalLineStyle}
                  />
                  <TerminalLine
                    label={<Zap size={11} />}
                    value={
                      lastResponse
                        ? `${String(Boolean(lastResponse.safety_passed))} ${lastResponse.safety_feedback ?? ""}`.trim()
                        : "--"
                    }
                    style={terminalLineStyle}
                  />
                  <TerminalLine
                    label={<Database size={11} />}
                    value={
                      lastResponse?.retrieval_metrics
                        ? JSON.stringify(lastResponse.retrieval_metrics)
                        : "--"
                    }
                    style={terminalLineStyle}
                  />
                  <TerminalLine
                    label={<Link2 size={11} />}
                    value={lastResponse?.trace_id ?? conversationId ?? "new"}
                    style={terminalLineStyle}
                  />
                </div>

                <div style={styles.terminalBlock}>
                  <div style={styles.terminalBlockTitle}>
                    <Wrench size={10} style={{ display: "inline-block", verticalAlign: "middle", marginRight: 4 }} />
                    output
                  </div>
                  {lastResponse?.agent_results?.length ? (
                    lastResponse.agent_results.map((result) => (
                      <div key={result.agent} style={styles.agentOutputCard}>
                        <div style={styles.agentOutputHeader}>
                          <span>{result.agent}</span>
                          <span style={styles.smallMono}>●</span>
                        </div>
                        <pre style={styles.pre}>{result.output}</pre>
                      </div>
                    ))
                  ) : (
                    <div style={styles.emptyText}>No output yet</div>
                  )}
                </div>

                <div style={styles.terminalBlock}>
                  <div style={styles.terminalBlockTitle}>
                    <Heart size={10} style={{ display: "inline-block", verticalAlign: "middle", marginRight: 4 }} />
                    health
                  </div>
                  <TerminalLine
                    label={<Monitor size={11} />}
                    value={healthError ? "offline" : "online"}
                    style={terminalLineStyle}
                  />
                  <TerminalLine
                    label={<Clock size={11} />}
                    value={lastHealthCheck || "--:--:--"}
                    style={terminalLineStyle}
                  />
                  <TerminalLine
                    label={<Bot size={11} />}
                    value={health?.llm_provider ?? "unknown"}
                    style={terminalLineStyle}
                  />
                  <TerminalLine
                    label={<AlertTriangle size={11} />}
                    value={healthError || "--"}
                    style={terminalLineStyle}
                  />
                </div>
              </div>
            </div>
          </aside>
        </section>
      )}
    </main>
  );
}

function StatusDot({
  label,
  tone,
  compact = false,
}: {
  label: string;
  tone: StatusTone;
  compact?: boolean;
}) {
  const isOnline = tone === "online";
  const isOffline = tone === "offline";

  return (
    <div
      style={{
        ...styles.statusDotRow,
        ...(compact ? styles.statusDotRowCompact : {}),
      }}
    >
      <span
        style={{
          ...styles.statusDot,
          ...(isOnline
            ? styles.statusDotOnline
            : isOffline
              ? styles.statusDotOffline
              : styles.statusDotNeutral),
        }}
      />
      <span style={styles.statusLabel}>{label}</span>
      <span
        style={{
          ...styles.statusValue,
          ...(isOnline
            ? styles.statusValueOnline
            : isOffline
              ? styles.statusValueOffline
              : styles.statusValueNeutral),
        }}
      >
        {isOnline ? "online" : isOffline ? "offline" : "idle"}
      </span>
    </div>
  );
}

function InfoMiniCard({ label, value }: { label: string; value: string }) {
  return (
    <div style={styles.infoMiniCard}>
      <div style={styles.infoMiniLabel}>
        {label === "provider" ? (
          <Bot size={10} style={{ display: "inline-block", verticalAlign: "middle", marginRight: 4 }} />
        ) : (
          <Clock size={10} style={{ display: "inline-block", verticalAlign: "middle", marginRight: 4 }} />
        )}
        {label}
      </div>
      <div style={styles.infoMiniValue}>{value}</div>
    </div>
  );
}

function TerminalLine({
  label,
  value,
  style,
}: {
  label: React.ReactNode;
  value: string;
  style?: CSSProperties;
}) {
  return (
    <div style={{ ...styles.terminalLine, ...(style ?? {}) }}>
      <span style={styles.terminalKey}>{label}</span>
      <span style={styles.terminalValue}>{value}</span>
    </div>
  );
}

function renderRichText(text: string) {
  const lines = text.split("\n");

  return (
    <div style={styles.richTextContainer}>
      {lines.map((line, index) => {
        const trimmed = line.trim();

        if (!trimmed) {
          return <div key={`space-${index}`} style={styles.richSpacer} />;
        }

        if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
          return (
            <div key={`bullet-${index}`} style={styles.richBulletRow}>
              <span style={styles.richBullet}>▸</span>
              <span>{trimmed.slice(2)}</span>
            </div>
          );
        }

        if (/^\d+\.\s/.test(trimmed)) {
          const [marker, ...rest] = trimmed.split(" ");
          return (
            <div key={`number-${index}`} style={styles.richBulletRow}>
              <span style={styles.richNumber}>{marker}</span>
              <span>{rest.join(" ")}</span>
            </div>
          );
        }

        return (
          <p key={`paragraph-${index}`} style={styles.richParagraph}>
            {renderInlineFormatting(trimmed)}
          </p>
        );
      })}
    </div>
  );
}

function renderInlineFormatting(text: string) {
  const parts = text.split(/(`[^`]+`)/g);

  return parts.map((part, index) => {
    if (part.startsWith("`") && part.endsWith("`")) {
      return (
        <code key={`code-${index}`} style={styles.inlineCode}>
          {part.slice(1, -1)}
        </code>
      );
    }

    return <span key={`text-${index}`}>{part}</span>;
  });
}

const monoFont =
  'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace';

const styles: Record<string, CSSProperties> = {
  page: {
    minHeight: "100vh",
    background:
      "radial-gradient(circle at top left, rgba(22, 163, 74, 0.12), transparent 28%), radial-gradient(circle at top right, rgba(74, 222, 128, 0.08), transparent 22%), #020403",
    color: "#d1fae5",
    fontFamily: monoFont,
    overflowX: "hidden",
  },
  authShell: {
    minHeight: "100vh",
    padding: 20,
    display: "grid",
    placeItems: "center",
  },
  authFrame: {
    width: "100%",
    maxWidth: 1180,
    border: "1px solid rgba(34, 197, 94, 0.18)",
    background: "rgba(2, 8, 4, 0.92)",
    borderRadius: 22,
    padding: 22,
    boxShadow: "0 0 0 1px rgba(34, 197, 94, 0.04), 0 24px 80px rgba(0, 0, 0, 0.5)",
    display: "grid",
    gap: 20,
  },
  authFrameTablet: {
    maxWidth: 900,
  },
  authFrameMobile: {
    padding: 14,
    borderRadius: 16,
  },
  authTopBar: {
    display: "flex",
    justifyContent: "space-between",
    gap: 16,
    alignItems: "center",
    fontSize: 11,
    color: "#86efac",
    letterSpacing: "0.08em",
    textTransform: "lowercase",
  },
  monoBrand: {
    color: "#22c55e",
    fontSize: 12,
    letterSpacing: "0.16em",
    textTransform: "uppercase",
  },
  cornerMeta: {
    display: "flex",
    gap: 16,
    color: "#6ee7b7",
    fontSize: 11,
  },
  cornerMetaMobile: {
    flexDirection: "column",
    gap: 6,
  },
  authGrid: {
    display: "grid",
    gridTemplateColumns: "1.2fr 0.85fr",
    gap: 22,
    alignItems: "start",
  },
  authGridStacked: {
    gridTemplateColumns: "1fr",
  },
  authIntro: {
    display: "grid",
    gap: 14,
    alignContent: "start",
    padding: "8px 6px",
  },
  sectionKicker: {
    color: "#4ade80",
    fontSize: 11,
    letterSpacing: "0.14em",
    textTransform: "uppercase",
  },
  authTitle: {
    margin: 0,
    fontSize: 38,
    lineHeight: 1.05,
    color: "#f0fdf4",
    textTransform: "lowercase",
  },
  authTitleMobile: {
    fontSize: 28,
  },
  authText: {
    margin: 0,
    fontSize: 14,
    lineHeight: 1.9,
    color: "#a7f3d0",
    maxWidth: 620,
  },
  cornerCard: {
    display: "grid",
    gap: 10,
    padding: 14,
    maxWidth: 360,
    borderRadius: 16,
    border: "1px solid rgba(34, 197, 94, 0.12)",
    background: "rgba(3, 12, 6, 0.8)",
  },
  quickInfoGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
    gap: 10,
    maxWidth: 560,
  },
  quickInfoGridMobile: {
    gridTemplateColumns: "1fr",
  },
  infoMiniCard: {
    borderRadius: 14,
    padding: 12,
    border: "1px solid rgba(34, 197, 94, 0.1)",
    background: "rgba(3, 12, 6, 0.74)",
    display: "grid",
    gap: 8,
  },
  infoMiniLabel: {
    color: "#86efac",
    fontSize: 10,
    textTransform: "uppercase",
    letterSpacing: "0.12em",
  },
  infoMiniValue: {
    color: "#f0fdf4",
    fontSize: 12,
    wordBreak: "break-word",
  },
  authPanel: {
    borderRadius: 18,
    border: "1px solid rgba(34, 197, 94, 0.14)",
    background: "rgba(3, 12, 6, 0.82)",
    padding: 18,
    display: "grid",
    gap: 14,
  },
  modeSwitch: {
    display: "grid",
    gridTemplateColumns: "1fr 1fr",
    gap: 8,
  },
  modeButton: {
    minHeight: 42,
    borderRadius: 12,
    border: "1px solid rgba(34, 197, 94, 0.16)",
    background: "rgba(2, 10, 4, 0.95)",
    color: "#bbf7d0",
    fontFamily: monoFont,
    fontSize: 13,
    textTransform: "lowercase",
    cursor: "pointer",
  },
  modeButtonActive: {
    background: "rgba(20, 83, 45, 0.86)",
    color: "#f0fdf4",
    boxShadow: "0 0 18px rgba(34, 197, 94, 0.16)",
  },
  fieldLabel: {
    display: "grid",
    gap: 8,
    fontSize: 12,
    color: "#86efac",
    textTransform: "lowercase",
  },
  input: {
    width: "100%",
    minHeight: 46,
    borderRadius: 12,
    border: "1px solid rgba(34, 197, 94, 0.16)",
    background: "#031007",
    color: "#ecfdf5",
    padding: "0 12px",
    boxSizing: "border-box",
    outline: "none",
    fontFamily: monoFont,
    fontSize: 13,
  },
  primaryButton: {
    minHeight: 44,
    borderRadius: 8,
    border: "1px solid rgba(74, 222, 128, 0.3)",
    background: "linear-gradient(180deg, rgba(16, 72, 40, 0.98), rgba(18, 108, 54, 0.94))",
    color: "#f0fdf4",
    fontFamily: monoFont,
    fontSize: 12,
    letterSpacing: "0.08em",
    textTransform: "uppercase",
    cursor: "pointer",
    padding: "0 14px",
    boxShadow: "0 0 18px rgba(34, 197, 94, 0.1)",
  },
  primaryButtonSquare: {
    minHeight: 44,
    borderRadius: 4,
    border: "1px solid rgba(74, 222, 128, 0.32)",
    background: "linear-gradient(180deg, rgba(8, 44, 24, 0.98), rgba(13, 84, 42, 0.96))",
    color: "#f0fdf4",
    fontFamily: monoFont,
    fontSize: 12,
    letterSpacing: "0.1em",
    textTransform: "uppercase",
    cursor: "pointer",
    padding: "0 14px",
    boxShadow: "inset 0 0 0 1px rgba(134, 239, 172, 0.06), 0 0 16px rgba(34, 197, 94, 0.1)",
  },
  secondaryButton: {
    minHeight: 42,
    borderRadius: 8,
    border: "1px solid rgba(34, 197, 94, 0.14)",
    background: "rgba(2, 10, 4, 0.95)",
    color: "#bbf7d0",
    fontFamily: monoFont,
    fontSize: 12,
    textTransform: "lowercase",
    cursor: "pointer",
    padding: "0 14px",
  },
  secondaryButtonSquare: {
    minHeight: 42,
    borderRadius: 4,
    border: "1px solid rgba(34, 197, 94, 0.18)",
    background: "linear-gradient(180deg, rgba(1, 9, 4, 0.98), rgba(2, 14, 6, 0.96))",
    color: "#bbf7d0",
    fontFamily: monoFont,
    fontSize: 11,
    letterSpacing: "0.08em",
    textTransform: "uppercase",
    cursor: "pointer",
    padding: "0 14px",
    boxShadow: "inset 0 0 0 1px rgba(34, 197, 94, 0.04)",
  },
  authFooterText: {
    fontSize: 12,
    color: "#a7f3d0",
    lineHeight: 1.7,
    minHeight: 20,
  },
  bottomHints: {
    display: "flex",
    gap: 10,
    flexWrap: "wrap",
  },
  bottomHintsMobile: {
    flexDirection: "column",
  },
  hintChip: {
    padding: "9px 12px",
    borderRadius: 999,
    border: "1px solid rgba(34, 197, 94, 0.1)",
    background: "rgba(3, 12, 6, 0.7)",
    color: "#86efac",
    fontSize: 11,
    maxWidth: 340,
  },
  hintChipMobile: {
    maxWidth: "100%",
    width: "100%",
    boxSizing: "border-box",
  },
  appShell: {
    minHeight: "100vh",
    height: "100vh",
    display: "grid",
    gridTemplateColumns: "250px 10px minmax(0, 1fr) 10px 340px",
    gap: 0,
    padding: 14,
    boxSizing: "border-box",
    alignItems: "stretch",
    background:
      "linear-gradient(180deg, rgba(0, 8, 4, 0.96), rgba(0, 4, 2, 0.98))",
  },
  appShellTablet: {
    height: "auto",
    gridTemplateColumns: "220px minmax(0, 1fr)",
    gap: 12,
  },
  appShellMobile: {
    gridTemplateColumns: "1fr",
    minHeight: "auto",
    height: "auto",
    padding: 10,
    gap: 10,
  },
  leftRail: {
    display: "grid",
    gap: 12,
    alignContent: "start",
    minWidth: 0,
  },
  leftRailSticky: {
    position: "sticky",
    top: 14,
  },
  leftRailFlow: {
    position: "static",
  },
  railBox: {
    borderRadius: 0,
    border: "1px solid rgba(0, 255, 102, 0.18)",
    background:
      "linear-gradient(180deg, rgba(0, 10, 4, 0.96), rgba(0, 5, 2, 0.98))",
    padding: 14,
    display: "grid",
    gap: 12,
    boxShadow: "inset 0 0 0 1px rgba(0, 255, 102, 0.03), 0 0 24px rgba(0, 0, 0, 0.22)",
  },
  resizeDivider: {
    width: 10,
    cursor: "col-resize",
    position: "relative",
    background:
      "linear-gradient(180deg, rgba(0, 255, 102, 0.08), rgba(0, 255, 102, 0.02))",
    borderLeft: "1px solid rgba(0, 255, 102, 0.22)",
    borderRight: "1px solid rgba(0, 255, 102, 0.14)",
  },
  railHeader: {
    display: "flex",
    justifyContent: "space-between",
    gap: 10,
    alignItems: "start",
  },
  railTitle: {
    color: "#ecfdf5",
    fontSize: 15,
    textTransform: "lowercase",
  },
  smallMono: {
    color: "#4ade80",
    fontSize: 11,
    textTransform: "uppercase",
    letterSpacing: "0.08em",
  },
  mutedList: {
    display: "grid",
    gap: 8,
  },
  metricRow: {
    display: "flex",
    justifyContent: "space-between",
    gap: 10,
    alignItems: "start",
  },
  metricKey: {
    fontSize: 13,
    color: "#86efac",
    textTransform: "lowercase",
  },
  metricValue: {
    fontSize: 10,
    color: "#9ca3af",
    textAlign: "right",
    wordBreak: "break-word",
    maxWidth: 120,
  },
  statusStack: {
    display: "grid",
    gap: 10,
  },
  statusDotRow: {
    display: "grid",
    gridTemplateColumns: "10px 1fr auto",
    alignItems: "center",
    gap: 10,
  },
  statusDotRowCompact: {
    gridTemplateColumns: "10px auto auto",
    gap: 8,
  },
  statusDot: {
    width: 8,
    height: 8,
    borderRadius: "50%",
    display: "inline-block",
  },
  statusDotOnline: {
    background: "#4ade80",
    boxShadow: "0 0 10px #22c55e, 0 0 18px rgba(34, 197, 94, 0.6)",
  },
  statusDotOffline: {
    background: "#f43f5e",
    boxShadow: "0 0 10px #f43f5e, 0 0 18px rgba(244, 63, 94, 0.5)",
  },
  statusDotNeutral: {
    background: "#facc15",
    boxShadow: "0 0 10px #facc15, 0 0 18px rgba(250, 204, 21, 0.5)",
  },
  statusLabel: {
    color: "#bbf7d0",
    fontSize: 10,
    textTransform: "lowercase",
  },
  statusValue: {
    fontSize: 9,
    textTransform: "lowercase",
  },
  statusValueOnline: {
    color: "#4ade80",
  },
  statusValueOffline: {
    color: "#fb7185",
  },
  statusValueNeutral: {
    color: "#fde047",
  },
  cornerInfo: {
    color: "#6b7280",
    fontSize: 9,
    lineHeight: 1.7,
  },
  actionColumn: {
    display: "grid",
    gap: 10,
  },
  chatColumn: {
    display: "grid",
    gridTemplateRows: "auto minmax(0, 1fr) auto",
    gap: 0,
    minWidth: 0,
    minHeight: 0,
    height: "calc(100vh - 28px)",
    maxHeight: "calc(100vh - 28px)",
    overflow: "hidden",
    borderLeft: "1px solid rgba(0, 255, 102, 0.18)",
    borderRight: "1px solid rgba(0, 255, 102, 0.18)",
    background:
      "radial-gradient(circle at top, rgba(0, 255, 102, 0.06), transparent 18%), linear-gradient(180deg, rgba(0, 7, 3, 0.98), rgba(0, 3, 1, 0.99))",
  },
  chatColumnTablet: {
    minHeight: 0,
    height: "calc(100vh - 28px)",
    maxHeight: "calc(100vh - 28px)",
  },
  chatColumnMobile: {
    minHeight: 0,
    height: "72vh",
    maxHeight: "72vh",
  },
  topStrip: {
    display: "flex",
    justifyContent: "space-between",
    gap: 12,
    alignItems: "center",
    padding: "12px 16px",
    borderRadius: 0,
    borderBottom: "1px solid rgba(0, 255, 102, 0.18)",
    background:
      "linear-gradient(180deg, rgba(0, 12, 5, 0.98), rgba(0, 8, 4, 0.94))",
    fontSize: 11,
    color: "#86efac",
  },
  topStripMobile: {
    flexDirection: "column",
    alignItems: "flex-start",
  },
  topStripLeft: {
    display: "flex",
    gap: 12,
    alignItems: "center",
  },
  topStripLeftMobile: {
    flexDirection: "column",
    alignItems: "flex-start",
    gap: 4,
  },
  stripMeta: {
    color: "#6b7280",
    fontSize: 10,
  },
  topStripRight: {
    display: "flex",
    gap: 12,
    alignItems: "center",
  },
  topStripRightMobile: {
    gap: 8,
    flexWrap: "wrap",
  },
  chatWindow: {
    minHeight: 0,
    height: "100%",
    maxHeight: "100%",
    overflowY: "auto",
    padding: 18,
    borderRadius: 0,
    border: "none",
    background:
      "linear-gradient(180deg, rgba(0, 7, 3, 0.95), rgba(0, 4, 2, 0.99))",
    boxShadow:
      "inset 0 0 0 1px rgba(0, 255, 102, 0.02), inset 0 0 60px rgba(0, 255, 102, 0.025)",
    display: "flex",
    flexDirection: "column",
    gap: 12,
    scrollBehavior: "smooth",
  },
  chatWindowTablet: {
    minHeight: 0,
  },
  chatWindowMobile: {
    minHeight: 0,
    height: "100%",
    maxHeight: "none",
    padding: 10,
  },
  messageRow: {
    display: "flex",
    gap: 10,
    alignItems: "flex-start",
  },
  messageRowUser: {
    justifyContent: "flex-end",
  },
  messageRowAssistant: {
    justifyContent: "flex-start",
  },
  avatar: {
    width: 28,
    height: 28,
    borderRadius: 9,
    display: "grid",
    placeItems: "center",
    background: "rgba(20, 83, 45, 0.82)",
    border: "1px solid rgba(34, 197, 94, 0.12)",
    color: "#f0fdf4",
    fontSize: 10,
    flexShrink: 0,
  },
  messageBubble: {
    maxWidth: "82%",
    borderRadius: 6,
    padding: 13,
    fontSize: 13,
    lineHeight: 1.75,
    wordBreak: "break-word",
    boxShadow: "0 0 0 1px rgba(0, 255, 102, 0.05)",
  },
  messageBubbleMobile: {
    maxWidth: "100%",
    fontSize: 12,
    padding: 11,
  },
  userBubble: {
    background: "linear-gradient(180deg, rgba(0, 84, 34, 0.72), rgba(0, 52, 22, 0.88))",
    color: "#f0fdf4",
    border: "1px solid rgba(0, 255, 102, 0.22)",
    borderTopRightRadius: 2,
  },
  assistantBubble: {
    background: "linear-gradient(180deg, rgba(0, 12, 5, 0.96), rgba(0, 7, 3, 0.98))",
    color: "#d1fae5",
    border: "1px solid rgba(0, 255, 102, 0.16)",
    borderTopLeftRadius: 2,
  },
  messageMeta: {
    marginBottom: 6,
    fontSize: 9,
    color: "#6b7280",
    textTransform: "uppercase",
    letterSpacing: "0.08em",
  },
  messageContent: {
    fontSize: 13,
  },
  richTextContainer: {
    display: "grid",
    gap: 8,
  },
  richParagraph: {
    margin: 0,
    lineHeight: 1.8,
  },
  richSpacer: {
    height: 3,
  },
  richBulletRow: {
    display: "grid",
    gridTemplateColumns: "18px 1fr",
    gap: 8,
    alignItems: "start",
  },
  richBullet: {
    color: "#4ade80",
  },
  richNumber: {
    color: "#4ade80",
  },
  inlineCode: {
    display: "inline-block",
    padding: "2px 6px",
    borderRadius: 8,
    border: "1px solid rgba(34, 197, 94, 0.12)",
    background: "#031007",
    color: "#86efac",
    fontSize: 12,
    fontFamily: monoFont,
  },
  typingRow: {
    display: "flex",
    gap: 8,
    alignItems: "center",
    minHeight: 14,
  },
  typingDot: {
    width: 6,
    height: 6,
    borderRadius: "50%",
    background: "#4ade80",
    boxShadow: "0 0 10px rgba(34, 197, 94, 0.55)",
  },
  promptDock: {
    display: "grid",
    gridTemplateRows: "auto auto auto",
    gap: 10,
    minHeight: 0,
    flexShrink: 0,
    position: "sticky",
    bottom: 0,
    padding: "10px 14px 14px",
    borderTop: "1px solid rgba(0, 255, 102, 0.18)",
    background:
      "linear-gradient(180deg, rgba(0, 10, 4, 0.96), rgba(0, 5, 2, 0.99))",
    boxShadow: "0 -18px 44px rgba(0, 0, 0, 0.34)",
  },
  promptDockHeader: {
    display: "flex",
    justifyContent: "space-between",
    gap: 10,
    alignItems: "center",
  },
  promptDockTitle: {
    color: "#00ff66",
    fontSize: 11,
    textTransform: "uppercase",
    letterSpacing: "0.14em",
  },
  promptDockMeta: {
    color: "#6b7280",
    fontSize: 9,
  },
  promptScrollArea: {
    overflowX: "auto",
    overflowY: "hidden",
    paddingBottom: 2,
  },
  promptDockAuthenticated: {
    alignSelf: "end",
  },
  promptDockMobile: {
    gap: 8,
  },
  promptRow: {
    display: "flex",
    gap: 8,
    flexWrap: "nowrap",
    minWidth: "max-content",
  },
  promptRowMobile: {
    flexDirection: "column",
  },
  promptChip: {
    borderRadius: 4,
    border: "1px solid rgba(0, 255, 102, 0.18)",
    background: "linear-gradient(180deg, rgba(0, 16, 7, 0.96), rgba(0, 10, 4, 0.98))",
    color: "#86efac",
    fontFamily: monoFont,
    fontSize: 11,
    padding: "8px 11px",
    cursor: "pointer",
    textAlign: "left",
    whiteSpace: "nowrap",
    boxShadow: "0 0 0 1px rgba(0, 255, 102, 0.03)",
  },
  promptChipMobile: {
    width: "100%",
    maxWidth: "100%",
  },
  composer: {
    borderRadius: 6,
    border: "1px solid rgba(0, 255, 102, 0.18)",
    background: "linear-gradient(180deg, rgba(0, 11, 5, 0.98), rgba(0, 7, 3, 0.99))",
    padding: 10,
    display: "grid",
    gap: 8,
    boxShadow: "0 10px 22px rgba(0, 0, 0, 0.18)",
  },
  composerAuthenticated: {
    maxWidth: "100%",
  },
  composerMobile: {
    gap: 8,
  },
  textarea: {
    width: "100%",
    minHeight: 72,
    maxHeight: 120,
    resize: "none",
    overflowY: "auto",
    borderRadius: 12,
    border: "1px solid rgba(34, 197, 94, 0.12)",
    background: "#031007",
    color: "#ecfdf5",
    fontFamily: monoFont,
    fontSize: 12,
    lineHeight: 1.6,
    padding: 10,
    boxSizing: "border-box",
    outline: "none",
  },
  textareaMobile: {
    minHeight: 64,
    maxHeight: 104,
  },
  composerFooter: {
    display: "flex",
    justifyContent: "space-between",
    gap: 10,
    alignItems: "center",
    flexWrap: "wrap",
  },
  composerFooterMobile: {
    alignItems: "stretch",
  },
  composerHint: {
    color: "#6b7280",
    fontSize: 9,
  },
  composerHintMobile: {
    width: "100%",
  },
  rightRail: {
    minWidth: 0,
  },
  rightRailSticky: {
    position: "sticky",
    top: 14,
    maxHeight: "calc(100vh - 28px)",
  },
  rightRailFlow: {
    position: "static",
    maxHeight: "none",
  },
  terminalCard: {
    minHeight: "calc(100vh - 28px)",
    maxHeight: "calc(100vh - 28px)",
    borderRadius: 0,
    border: "1px solid rgba(0, 255, 102, 0.18)",
    background: "linear-gradient(180deg, rgba(0, 9, 4, 0.98), rgba(0, 4, 2, 0.99))",
    display: "grid",
    gridTemplateRows: "auto 1fr",
    overflow: "hidden",
    boxShadow: "0 14px 34px rgba(0, 0, 0, 0.26)",
  },
  terminalCardTablet: {
    minHeight: 420,
    maxHeight: 420,
  },
  terminalCardMobile: {
    minHeight: 340,
    maxHeight: 340,
  },
  terminalHeader: {
    display: "flex",
    justifyContent: "space-between",
    gap: 12,
    alignItems: "center",
    padding: "14px 16px",
    borderBottom: "1px solid rgba(34, 197, 94, 0.1)",
  },
  terminalTitle: {
    color: "#4ade80",
    fontSize: 12,
    letterSpacing: "0.08em",
    textTransform: "uppercase",
  },
  inlineStatusRow: {
    display: "flex",
    gap: 14,
    flexWrap: "wrap",
  },
  terminalSection: {
    padding: "10px 16px 0",
  },
  terminalBody: {
    overflowY: "auto",
    padding: 16,
    display: "grid",
    gap: 14,
  },
  terminalBlock: {
    borderRadius: 14,
    border: "1px solid rgba(34, 197, 94, 0.08)",
    background: "rgba(2, 10, 4, 0.72)",
    padding: 12,
    display: "grid",
    gap: 10,
  },
  terminalBlockTitle: {
    color: "#86efac",
    fontSize: 10,
    letterSpacing: "0.1em",
    textTransform: "uppercase",
    fontWeight: 600,
  },
  logLine: {
    display: "grid",
    gridTemplateColumns: "50px 42px 1fr",
    gap: 8,
    alignItems: "start",
    fontSize: 10,
    lineHeight: 1.6,
  },
  logLineMobile: {
    gridTemplateColumns: "1fr",
    gap: 2,
  },
  logTime: {
    color: "#6b7280",
    fontSize: 9,
  },
  logLevel: {
    fontSize: 9,
    letterSpacing: "0.08em",
    textTransform: "uppercase",
  },
  logLevelInfo: {
    color: "#4ade80",
  },
  logLevelWarn: {
    color: "#fde047",
  },
  logLevelError: {
    color: "#fb7185",
  },
  logMessage: {
    color: "#d1fae5",
    wordBreak: "break-word",
  },
  terminalLine: {
    display: "grid",
    gridTemplateColumns: "32px 1fr",
    gap: 8,
    alignItems: "start",
    fontSize: 10,
    lineHeight: 1.6,
  },
  terminalLineMobile: {
    gridTemplateColumns: "1fr",
    gap: 2,
  },
  terminalKey: {
    color: "#86efac",
    fontSize: 11,
  },
  terminalValue: {
    color: "#9ca3af",
    wordBreak: "break-word",
    fontSize: 10,
  },
  agentOutputCard: {
    borderRadius: 12,
    border: "1px solid rgba(34, 197, 94, 0.08)",
    background: "#031007",
    padding: 10,
    display: "grid",
    gap: 8,
  },
  agentOutputHeader: {
    display: "flex",
    justifyContent: "space-between",
    gap: 10,
    alignItems: "center",
    color: "#bbf7d0",
    fontSize: 10,
  },
  pre: {
    margin: 0,
    whiteSpace: "pre-wrap",
    color: "#9ca3af",
    fontSize: 10,
    lineHeight: 1.6,
    fontFamily: monoFont,
  },
  emptyText: {
    color: "#6b7280",
    fontSize: 10,
  },
};
