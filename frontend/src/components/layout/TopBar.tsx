import { type FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { BarChart3, Github, Loader2, LogIn, LogOut, MessageSquareText, User } from "lucide-react";
import { abortActiveApiRequests, apiClient, getApiErrorMessage, notifyApiAuthChanged } from "../../api/client";
import { listCoursesApiApiV1CoursesListPost } from "../../api/generated/courses";
import { examHistoryApiV1CoursesCourseIdExamsHistoryGet } from "../../api/generated/exams";
import { listChatApiApiV1CoursesCourseIdChatsListPost } from "../../api/generated/chats";
import type { AuthSessionData, ChatMessageItem, CourseItem, ExamHistoryItem, RuntimeUser } from "../../api/generated/model";
import { resetAnalyticsIdentity, syncAnalyticsUserIdentity, trackAnalyticsEvent } from "../../lib/analytics";
import { AUTH_SESSION_QUERY_KEY, AUTH_SESSION_STALE_TIME_MS, fetchAuthSession } from "../../lib/authSession";
import {
  buildLearningActivityEvents,
  buildLearningCalendarWeeks,
  countLearningActivitySince,
  formatLearningActivityKind,
  formatLearningActivityTime,
  getLatestLearningActivity,
  getLearningActivityTileClass,
  type LearningActivityEvent,
  type LearningCalendarWeek,
} from "../../lib/learningActivity";
import { cn } from "../../lib/utils";
import { unwrapOrvalResponse } from "../../lib/unwrapOrvalResponse";
import { Modal } from "../ui/Modal";
import { FeedbackModal } from "../ui/FeedbackModal";

type SendEmailCodeData = {
  expires_in_s: number;
  resend_after_s: number;
};

type ApiResponse<T> = {
  code: number;
  message: string;
  data: T;
};

type LearningPanelData = {
  courses: CourseItem[];
  exams: ExamHistoryItem[];
  chatMessages: ChatMessageItem[];
};

interface TopBarProps {
  className?: string;
}

interface LearningActivityPanelProps {
  weeks: LearningCalendarWeek[];
  weeklyCount: number;
  latestActivity: LearningActivityEvent | null;
  isLoading: boolean;
  isError: boolean;
}

function getSafeInternalReturnTo(value: string | null): string | null {
  const normalized = value?.trim() ?? "";
  if (!normalized.startsWith("/") || normalized.startsWith("//") || normalized.includes("\\")) {
    return null;
  }
  try {
    const base = "https://aiteachme.local";
    const parsed = new URL(normalized, base);
    if (parsed.origin !== base) {
      return null;
    }
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return null;
  }
}

function getDisplayName(user: RuntimeUser | null): string {
  if (!user?.is_authenticated) {
    return user?.is_local ? "本地用户" : "游客";
  }

  const email = user.email?.trim() || "";
  if (email.includes("@")) {
    return email.split("@")[0];
  }

  return email || "用户";
}

function getIdentitySubtitle(user: RuntimeUser | null): string {
  if (user?.is_authenticated) {
    return user.email?.trim() || "已登录账号";
  }

  if (user?.user_id) {
    const identityLabel = user.is_local ? "本地身份" : "游客身份";
    return `${identityLabel} ${user.user_id.slice(-6)}`;
  }

  return user?.is_local ? "当前设备上的本地身份" : "当前浏览器的游客身份";
}

function getAvatarText(user: RuntimeUser | null): string {
  if (!user?.is_authenticated) {
    return user?.is_local ? "本" : "游";
  }

  const displayName = getDisplayName(user).trim();
  return displayName.slice(0, 1).toUpperCase() || "U";
}

function LearningActivityPanel({
  weeks,
  weeklyCount,
  latestActivity,
  isLoading,
  isError,
}: LearningActivityPanelProps) {
  const latestText = latestActivity
    ? `${formatLearningActivityKind(latestActivity.kind)} · ${formatLearningActivityTime(latestActivity.occurredAt)}`
    : "完成问答或测验后显示";

  return (
    <div className="border-b border-slate-100 px-4 py-3 dark:border-slate-800/80">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="flex items-center gap-1.5 text-xs font-semibold text-slate-800 dark:text-slate-100">
            <BarChart3 className="h-3.5 w-3.5 text-violet-500" />
            学习记录
          </p>
          <p className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">按真实问答和测验统计</p>
        </div>
        {isLoading ? (
          <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-violet-400" />
        ) : (
          <span className="shrink-0 rounded-full bg-violet-50 px-2 py-0.5 text-[10px] font-medium text-violet-600 dark:bg-violet-500/10 dark:text-violet-200">
            近 8 周
          </span>
        )}
      </div>

      <div className="mt-3 overflow-x-auto pb-1" aria-label="近 8 周真实学习记录">
        <div className="flex min-w-max gap-1">
          {weeks.map((week) => (
            <div key={week.key} className="flex flex-col gap-1">
              {week.days.map((day) => (
                <span
                  key={day.key}
                  className={cn(
                    "h-3 w-3 rounded-[3px] transition",
                    day.isPlaceholder ? "pointer-events-none opacity-0" : getLearningActivityTileClass(day.intensity),
                    day.isToday && "ring-1 ring-violet-300 dark:ring-violet-500/50",
                  )}
                  title={`${day.key}（${day.label}）· ${day.count} 条真实学习记录`}
                  aria-label={`${day.key} ${day.count} 条真实学习记录`}
                />
              ))}
            </div>
          ))}
        </div>
      </div>

      <div className="mt-2 flex items-center justify-between gap-3 text-[11px] text-slate-500 dark:text-slate-400">
        <span className="shrink-0">本周 {weeklyCount} 条</span>
        <span className={cn("min-w-0 truncate", isError && "text-amber-600 dark:text-amber-300")}>
          {isError ? "暂时无法读取记录" : latestText}
        </span>
      </div>
    </div>
  );
}

export function TopBar({ className }: TopBarProps) {
  const queryClient = useQueryClient();
  const location = useLocation();
  const navigate = useNavigate();
  const [authUser, setAuthUser] = useState<RuntimeUser | null>(null);
  const [authEnabled, setAuthEnabled] = useState<boolean | null>(null);
  const [isAuthModalOpen, setIsAuthModalOpen] = useState(false);
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [authEmail, setAuthEmail] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [authVerificationCode, setAuthVerificationCode] = useState("");
  const [authError, setAuthError] = useState<string | null>(null);
  const [isAuthSubmitting, setIsAuthSubmitting] = useState(false);
  const [isSendCodeSubmitting, setIsSendCodeSubmitting] = useState(false);
  const [sendCodeCooldownS, setSendCodeCooldownS] = useState(0);
  const [codeExpiresInS, setCodeExpiresInS] = useState<number | null>(null);
  const [sendCodeInfo, setSendCodeInfo] = useState<string | null>(null);
  const [codeSentToEmail, setCodeSentToEmail] = useState<string | null>(null);
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const [isFeedbackModalOpen, setIsFeedbackModalOpen] = useState(false);
  const authSessionQuery = useQuery({
    queryKey: AUTH_SESSION_QUERY_KEY,
    queryFn: ({ signal }) => fetchAuthSession(signal),
    staleTime: AUTH_SESSION_STALE_TIME_MS,
    retry: 1,
  });

  const dropdownRef = useRef<HTMLDivElement>(null);
  const mobileMenuRef = useRef<HTMLDivElement>(null);
  const authEntryRequestRef = useRef("");
  const authReturnToRef = useRef<string | null>(null);

  const isLoggedIn = Boolean(authUser?.is_authenticated);
  const canUseAuth = authEnabled === true;
  const displayName = getDisplayName(authUser);
  const identitySubtitle = getIdentitySubtitle(authUser);
  const avatarText = getAvatarText(authUser);
  const profilePath = "/profile";
  const shouldLoadLearningPanel = isDropdownOpen || isMobileMenuOpen;

  const learningPanelQuery = useQuery({
    queryKey: ["topbar-learning-panel", "global"],
    enabled: shouldLoadLearningPanel,
    staleTime: 60_000,
    retry: 1,
    queryFn: async ({ signal }): Promise<LearningPanelData> => {
      const coursesResponse = await listCoursesApiApiV1CoursesListPost({ page: 1, size: 20 }, { signal });
      const courses = unwrapOrvalResponse<{ items?: CourseItem[] }>(coursesResponse)?.items ?? [];
      const courseIds = courses.map((item) => item.course_id).filter(Boolean).slice(0, 8);
      const courseResults = await Promise.allSettled(
        courseIds.map(async (courseId) => {
          const [examResponse, chatResponse] = await Promise.all([
            examHistoryApiV1CoursesCourseIdExamsHistoryGet(courseId, { page: 1, size: 30 }, { signal }),
            listChatApiApiV1CoursesCourseIdChatsListPost(courseId, { page: 1, size: 80 }, { signal }),
          ]);
          return {
            exams: unwrapOrvalResponse<{ items?: ExamHistoryItem[] }>(examResponse)?.items ?? [],
            chatMessages: unwrapOrvalResponse<{ items?: ChatMessageItem[] }>(chatResponse)?.items ?? [],
          };
        }),
      );
      return {
        courses,
        exams: courseResults.flatMap((result) => (result.status === "fulfilled" ? result.value.exams : [])),
        chatMessages: courseResults.flatMap((result) => (
          result.status === "fulfilled" ? result.value.chatMessages : []
        )),
      };
    },
  });

  const learningActivityEvents = useMemo(
    () => buildLearningActivityEvents({
      chatMessages: learningPanelQuery.data?.chatMessages,
      exams: learningPanelQuery.data?.exams,
    }),
    [learningPanelQuery.data?.chatMessages, learningPanelQuery.data?.exams],
  );
  const learningActivityWeeks = useMemo(
    () => buildLearningCalendarWeeks(learningActivityEvents, { weeks: 8 }),
    [learningActivityEvents],
  );
  const weeklyActivityCount = useMemo(
    () => countLearningActivitySince(learningActivityEvents, 7),
    [learningActivityEvents],
  );
  const latestLearningActivity = useMemo(
    () => getLatestLearningActivity(learningActivityEvents),
    [learningActivityEvents],
  );

  const closeMenus = () => {
    setIsDropdownOpen(false);
    setIsMobileMenuOpen(false);
  };

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsDropdownOpen(false);
      }
      if (mobileMenuRef.current && !mobileMenuRef.current.contains(event.target as Node)) {
        setIsMobileMenuOpen(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  useEffect(() => {
    if (authSessionQuery.isSuccess) {
      const currentUser = authSessionQuery.data?.current_user ?? null;
      setAuthEnabled(Boolean(authSessionQuery.data?.auth_enabled));
      if (!currentUser?.is_authenticated) {
        const hadAccessToken = Boolean(localStorage.getItem("token"));
        localStorage.removeItem("token");
        if (hadAccessToken) {
          abortActiveApiRequests();
        }
      }
      setAuthUser(currentUser);
      syncAnalyticsUserIdentity({
        userId: currentUser?.user_id,
        email: currentUser?.email,
        isAuthenticated: currentUser?.is_authenticated,
      });
    } else if (authSessionQuery.isError) {
      setAuthEnabled(false);
      setAuthUser(null);
      syncAnalyticsUserIdentity(null);
    }
  }, [authSessionQuery.data, authSessionQuery.isError, authSessionQuery.isSuccess]);

  useEffect(() => {
    const hasTimer = sendCodeCooldownS > 0 || (codeExpiresInS ?? 0) > 0;
    if (!hasTimer) {
      return;
    }

    const timer = window.setInterval(() => {
      setSendCodeCooldownS((prev) => (prev > 0 ? prev - 1 : 0));
      setCodeExpiresInS((prev) => {
        if (prev == null) return null;
        return prev > 0 ? prev - 1 : 0;
      });
    }, 1000);

    return () => window.clearInterval(timer);
  }, [sendCodeCooldownS, codeExpiresInS]);

  useEffect(() => {
    if (authMode !== "register" || !codeSentToEmail) {
      return;
    }

    const normalizedCurrentEmail = authEmail.trim().toLowerCase();
    if (normalizedCurrentEmail && normalizedCurrentEmail === codeSentToEmail) {
      return;
    }

    setAuthVerificationCode("");
    setSendCodeCooldownS(0);
    setCodeExpiresInS(null);
    setSendCodeInfo(null);
    setCodeSentToEmail(null);
  }, [authEmail, authMode, codeSentToEmail]);

  const openAuthModal = (mode: "login" | "register" = "login") => {
    setAuthMode(mode);
    setAuthError(null);
    setAuthPassword("");
    setAuthVerificationCode("");
    setSendCodeCooldownS(0);
    setCodeExpiresInS(null);
    setSendCodeInfo(null);
    setCodeSentToEmail(null);
    setIsAuthModalOpen(true);
  };

  const closeAuthModal = () => {
    if (isAuthSubmitting || isSendCodeSubmitting) return;
    authReturnToRef.current = null;
    setIsAuthModalOpen(false);
    setAuthError(null);
    setAuthPassword("");
    setAuthVerificationCode("");
    setSendCodeCooldownS(0);
    setCodeExpiresInS(null);
    setSendCodeInfo(null);
    setCodeSentToEmail(null);
  };

  const openAuthEntry = (mode: "login" | "register") => {
    if (!canUseAuth) {
      closeMenus();
      return;
    }
    authReturnToRef.current = null;
    closeMenus();
    openAuthModal(mode);
  };

  useEffect(() => {
    if (authEnabled === null) {
      return;
    }
    const searchParams = new URLSearchParams(location.search);
    if (searchParams.get("auth") !== "login") {
      authEntryRequestRef.current = "";
      return;
    }
    const requestKey = `${location.pathname}${location.search}`;
    if (authEntryRequestRef.current === requestKey) {
      return;
    }
    authEntryRequestRef.current = requestKey;
    authReturnToRef.current = getSafeInternalReturnTo(searchParams.get("returnTo"));

    if (authEnabled) {
      setAuthMode("login");
      setAuthError(null);
      setAuthPassword("");
      setAuthVerificationCode("");
      setSendCodeCooldownS(0);
      setCodeExpiresInS(null);
      setSendCodeInfo(null);
      setCodeSentToEmail(null);
      setIsAuthModalOpen(true);
    }

    searchParams.delete("auth");
    searchParams.delete("returnTo");
    const nextSearch = searchParams.toString();
    navigate(
      {
        pathname: location.pathname,
        search: nextSearch ? `?${nextSearch}` : "",
        hash: location.hash,
      },
      { replace: true },
    );
  }, [authEnabled, location.hash, location.pathname, location.search, navigate]);

  const openFeedbackModal = () => {
    closeMenus();
    setIsFeedbackModalOpen(true);
  };

  const handleLogout = async () => {
    try {
      const response = await apiClient<ApiResponse<AuthSessionData>>({
        url: "/api/v1/auth/logout",
        method: "POST",
        data: {},
      });
      localStorage.removeItem("token");
      abortActiveApiRequests();
      const currentUser = response.data.current_user ?? null;
      queryClient.setQueryData(AUTH_SESSION_QUERY_KEY, response.data);
      trackAnalyticsEvent("auth_logout_succeeded", {
        was_authenticated: Boolean(authUser?.is_authenticated),
      });
      resetAnalyticsIdentity();
      syncAnalyticsUserIdentity({
        userId: currentUser?.user_id,
        email: currentUser?.email,
        isAuthenticated: currentUser?.is_authenticated,
      });
      setAuthUser(currentUser);
    } catch {
      localStorage.removeItem("token");
      abortActiveApiRequests();
      resetAnalyticsIdentity();
      setAuthUser(null);
    }
    closeMenus();
  };

  const handleSendVerificationCode = async () => {
    if (authMode !== "register") {
      return;
    }
    if (isSendCodeSubmitting || sendCodeCooldownS > 0) {
      return;
    }

    const emailValue = authEmail.trim();
    if (!emailValue) {
      setAuthError("请先输入邮箱，再发送验证码。");
      return;
    }

    setIsSendCodeSubmitting(true);
    setAuthError(null);
    try {
      const response = await apiClient<ApiResponse<SendEmailCodeData>>(
        {
          url: "/api/v1/auth/email/send-code",
          method: "POST",
          data: { email: emailValue },
        },
        { timeout: 0 },
      );
      const payload = response.data;
      setSendCodeCooldownS(Math.max(0, payload.resend_after_s ?? 0));
      setCodeExpiresInS(Math.max(0, payload.expires_in_s ?? 0));
      setSendCodeInfo("验证码已发送，请检查邮箱。");
      setCodeSentToEmail(emailValue.toLowerCase());
    } catch (error) {
      setAuthError(getApiErrorMessage(error, "验证码发送失败，请稍后重试。"));
    } finally {
      setIsSendCodeSubmitting(false);
    }
  };

  const handleAuthSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const emailValue = authEmail.trim();
    const passwordValue = authPassword;
    if (!emailValue || passwordValue.length < 6) {
      setAuthError("请输入有效邮箱，并确保密码至少 6 位。");
      return;
    }
    if (authMode === "register") {
      const codeValue = authVerificationCode.trim();
      if (!codeValue) {
        setAuthError("注册需要先输入邮箱验证码。");
        return;
      }
      if (codeSentToEmail !== emailValue.toLowerCase()) {
        setAuthError("邮箱已变化，请先重新发送验证码。");
        return;
      }
    }

    setIsAuthSubmitting(true);
    setAuthError(null);
    try {
      const requestData =
        authMode === "login"
          ? { email: emailValue, password: passwordValue }
          : {
              email: emailValue,
              password: passwordValue,
              verification_code: authVerificationCode.trim(),
            };
      const response = await apiClient<ApiResponse<AuthSessionData>>({
        url: authMode === "login" ? "/api/v1/auth/login" : "/api/v1/auth/register",
        method: "POST",
        data: requestData,
      });
      const token = response.data.access_token;
      if (token) {
        localStorage.setItem("token", token);
      }
      notifyApiAuthChanged();
      const currentUser = response.data.current_user ?? null;
      queryClient.setQueryData(AUTH_SESSION_QUERY_KEY, response.data);
      syncAnalyticsUserIdentity({
        userId: currentUser?.user_id,
        email: currentUser?.email,
        isAuthenticated: currentUser?.is_authenticated,
      });
      trackAnalyticsEvent(authMode === "login" ? "auth_login_succeeded" : "auth_register_succeeded", {
        is_authenticated: Boolean(currentUser?.is_authenticated),
      });
      setAuthUser(currentUser);
      setIsAuthModalOpen(false);
      setAuthPassword("");
      setAuthVerificationCode("");
      setSendCodeCooldownS(0);
      setCodeExpiresInS(null);
      setSendCodeInfo(null);
      setCodeSentToEmail(null);
      closeMenus();
      const returnTo = authReturnToRef.current;
      authReturnToRef.current = null;
      if (returnTo) {
        navigate(returnTo, { replace: true });
      }
    } catch (error) {
      setAuthError(
        getApiErrorMessage(
          error,
          authMode === "login" ? "登录失败，请检查账号密码。" : "注册失败，请稍后重试。",
        ),
      );
    } finally {
      setIsAuthSubmitting(false);
    }
  };

  return (
    <div className={cn("flex h-10 items-center gap-3", className)}>
      <div className="hidden sm:block">
        <div
          className="relative"
          ref={dropdownRef}
          onMouseEnter={() => setIsDropdownOpen(true)}
          onMouseLeave={() => setIsDropdownOpen(false)}
        >
          <button
            type="button"
            onClick={() => setIsDropdownOpen((value) => !value)}
            className="inline-flex h-9 items-center gap-2 rounded-full border border-slate-200/80 bg-white/90 px-2.5 pr-3 text-xs font-medium text-slate-600 shadow-[0_2px_10px_rgba(15,23,42,0.04)] transition-colors hover:border-slate-300 hover:bg-white hover:text-slate-900 dark:border-slate-800 dark:bg-slate-900/90 dark:text-slate-300 dark:hover:border-slate-700 dark:hover:bg-slate-900 dark:hover:text-slate-100"
            title={identitySubtitle}
            aria-label="身份菜单"
            aria-expanded={isDropdownOpen}
          >
            <span className="flex h-6 w-6 items-center justify-center rounded-full bg-slate-900 text-[11px] font-semibold text-white dark:bg-slate-100 dark:text-slate-900">
              {avatarText}
            </span>
            <span className="hidden max-w-[120px] truncate whitespace-nowrap lg:inline">
              {isLoggedIn ? displayName : authUser?.is_local ? "本地" : "游客"}
            </span>
          </button>

          {isDropdownOpen && (
            <div className="absolute right-0 top-full z-50 pt-2">
              <div
                className="w-[310px] rounded-xl border border-slate-150 bg-white py-1 shadow-lg dark:border-slate-800 dark:bg-slate-900"
                style={{ animation: "fadeIn 0.15s ease-out" }}
              >
                <div className="border-b border-slate-100 px-4 py-3 dark:border-slate-800/80">
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-full bg-gradient-to-br from-slate-700 to-slate-900 text-sm font-semibold text-white">
                      {avatarText}
                    </div>
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-slate-900 dark:text-slate-100">{displayName}</p>
                      <p className="truncate text-xs text-slate-500 dark:text-slate-400">{identitySubtitle}</p>
                    </div>
                  </div>
                </div>

                {profilePath ? (
                  <LearningActivityPanel
                    weeks={learningActivityWeeks}
                    weeklyCount={weeklyActivityCount}
                    latestActivity={latestLearningActivity}
                    isLoading={learningPanelQuery.isLoading}
                    isError={learningPanelQuery.isError}
                  />
                ) : null}

                <div className="py-1">
                  {profilePath ? (
                    <Link
                      to={profilePath}
                      className="flex w-full items-center gap-2.5 px-4 py-2 text-sm text-slate-700 transition-colors hover:bg-slate-50 dark:text-slate-300 dark:hover:bg-slate-800/50"
                      onClick={closeMenus}
                    >
                      <User className="h-4 w-4 text-slate-400 dark:text-slate-500" />
                      <span>我的学习画像</span>
                    </Link>
                  ) : null}

                  {isLoggedIn ? (
                    <button
                      type="button"
                      className="flex w-full items-center gap-2.5 px-4 py-2 text-sm text-red-600 transition-colors hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-900/20"
                      onClick={handleLogout}
                    >
                      <LogOut className="h-4 w-4" />
                      <span>退出登录</span>
                    </button>
                  ) : canUseAuth ? (
                    <>
                      <button
                        type="button"
                        className="flex w-full items-center gap-2.5 px-4 py-2 text-sm text-slate-700 transition-colors hover:bg-slate-50 dark:text-slate-300 dark:hover:bg-slate-800/50"
                        onClick={() => openAuthEntry("login")}
                      >
                        <LogIn className="h-4 w-4 text-slate-400 dark:text-slate-500" />
                        <span>登录账号</span>
                      </button>
                      <button
                        type="button"
                        className="flex w-full items-center gap-2.5 px-4 py-2 text-sm text-slate-700 transition-colors hover:bg-slate-50 dark:text-slate-300 dark:hover:bg-slate-800/50"
                        onClick={() => openAuthEntry("register")}
                      >
                        <User className="h-4 w-4 text-slate-400 dark:text-slate-500" />
                        <span>注册账号</span>
                      </button>
                    </>
                  ) : (
                    <div className="px-4 py-2 text-sm text-slate-500 dark:text-slate-400">
                      {authUser?.is_local
                        ? "本地模式无需登录，数据保存在当前设备环境中。"
                        : "当前为游客身份，登录后可将学习数据绑定到账号。"}
                    </div>
                  )}
                </div>

                <div className="border-t border-slate-100 py-1 dark:border-slate-800/80">
                  <button
                    type="button"
                    className="flex w-full items-center gap-2.5 px-4 py-2 text-sm text-slate-700 transition-colors hover:bg-slate-50 dark:text-slate-300 dark:hover:bg-slate-800/50"
                    onClick={openFeedbackModal}
                  >
                    <MessageSquareText className="h-4 w-4 text-slate-400 dark:text-slate-500" />
                    <span>意见反馈</span>
                  </button>
                  <a
                    href="https://github.com/aiteachme/AiTeachMe"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex w-full items-center gap-2.5 px-4 py-2 text-sm text-slate-700 transition-colors hover:bg-slate-50 dark:text-slate-300 dark:hover:bg-slate-800/50"
                    onClick={closeMenus}
                  >
                    <Github className="h-4 w-4 text-slate-400 dark:text-slate-500" />
                    <span>GitHub</span>
                  </a>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="relative sm:hidden" ref={mobileMenuRef}>
        <button
          type="button"
          onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
          className="flex h-9 w-9 items-center justify-center rounded-full border border-slate-200/80 bg-white/90 text-sm font-semibold text-slate-800 shadow-[0_2px_10px_rgba(15,23,42,0.04)] transition-colors hover:bg-white dark:border-slate-800 dark:bg-slate-900/90 dark:text-slate-100 dark:hover:bg-slate-900"
          title="身份菜单"
          aria-label="身份菜单"
          aria-expanded={isMobileMenuOpen}
        >
          {avatarText}
        </button>

        {isMobileMenuOpen && (
          <div
            className="absolute right-0 z-50 mt-2 w-[310px] rounded-xl border border-slate-150 bg-white py-2 shadow-lg dark:border-slate-800 dark:bg-slate-900"
            style={{ animation: "fadeIn 0.15s ease-out" }}
          >
            <div className="border-b border-slate-100 px-4 py-3 dark:border-slate-800/80">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-full bg-gradient-to-br from-slate-700 to-slate-900 text-sm font-semibold text-white">
                  {avatarText}
                </div>
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-slate-900 dark:text-slate-100">{displayName}</p>
                  <p className="truncate text-xs text-slate-500 dark:text-slate-400">{identitySubtitle}</p>
                </div>
              </div>
            </div>

            {profilePath ? (
              <LearningActivityPanel
                weeks={learningActivityWeeks}
                weeklyCount={weeklyActivityCount}
                latestActivity={latestLearningActivity}
                isLoading={learningPanelQuery.isLoading}
                isError={learningPanelQuery.isError}
              />
            ) : null}

            <div className="py-1">
              {profilePath ? (
                <Link
                  to={profilePath}
                  className="flex w-full items-center gap-3 px-4 py-2.5 text-sm text-slate-700 transition-colors hover:bg-slate-50 dark:text-slate-300 dark:hover:bg-slate-800/50"
                  onClick={closeMenus}
                >
                  <User className="h-4 w-4 text-slate-400 dark:text-slate-500" />
                  <span>我的学习画像</span>
                </Link>
              ) : null}

              {isLoggedIn ? (
                <button
                  type="button"
                  className="flex w-full items-center gap-3 px-4 py-2.5 text-sm text-red-600 transition-colors hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-900/20"
                  onClick={handleLogout}
                >
                  <LogOut className="h-4 w-4" />
                  <span>退出登录</span>
                </button>
              ) : canUseAuth ? (
                <>
                  <button
                    type="button"
                    className="flex w-full items-center gap-3 px-4 py-2.5 text-sm text-slate-700 transition-colors hover:bg-slate-50 dark:text-slate-300 dark:hover:bg-slate-800/50"
                    onClick={() => openAuthEntry("login")}
                  >
                    <LogIn className="h-4 w-4 text-slate-400 dark:text-slate-500" />
                    <span>登录账号</span>
                  </button>
                  <button
                    type="button"
                    className="flex w-full items-center gap-3 px-4 py-2.5 text-sm text-slate-700 transition-colors hover:bg-slate-50 dark:text-slate-300 dark:hover:bg-slate-800/50"
                    onClick={() => openAuthEntry("register")}
                  >
                    <User className="h-4 w-4 text-slate-400 dark:text-slate-500" />
                    <span>注册账号</span>
                  </button>
                </>
              ) : (
                <div className="px-4 py-2.5 text-sm text-slate-500 dark:text-slate-400">
                  {authUser?.is_local
                    ? "本地模式无需登录，数据保存在当前设备环境中。"
                    : "当前为游客身份，登录后可将学习数据绑定到账号。"}
                </div>
              )}
            </div>

            <div className="my-1 border-t border-slate-100 dark:border-slate-800/80" />

            <div className="py-1">
              <button
                type="button"
                className="flex w-full items-center gap-3 px-4 py-2.5 text-sm text-slate-700 transition-colors hover:bg-slate-50 dark:text-slate-300 dark:hover:bg-slate-800/50"
                onClick={openFeedbackModal}
              >
                <MessageSquareText className="h-4 w-4 text-slate-400 dark:text-slate-500" />
                <span>意见反馈</span>
              </button>
              <a
                href="https://github.com/aiteachme/AiTeachMe"
                target="_blank"
                rel="noopener noreferrer"
                className="flex w-full items-center gap-3 px-4 py-2.5 text-sm text-slate-700 transition-colors hover:bg-slate-50 dark:text-slate-300 dark:hover:bg-slate-800/50"
                onClick={closeMenus}
              >
                <Github className="h-4 w-4 text-slate-400 dark:text-slate-500" />
                <span>GitHub</span>
              </a>
            </div>
          </div>
        )}
      </div>

      <FeedbackModal open={isFeedbackModalOpen} onClose={() => setIsFeedbackModalOpen(false)} />

      <Modal
        open={canUseAuth && isAuthModalOpen}
        onClose={closeAuthModal}
        title={authMode === "login" ? "登录 AiTeachMe" : "注册 AiTeachMe"}
        className="max-w-md"
      >
        <form className="space-y-4" onSubmit={handleAuthSubmit}>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {authMode === "login"
              ? "继续使用当前身份，并开启登录态同步。"
              : `将当前${authUser?.is_local ? "本地身份" : "游客身份"}升级为邮箱账号。`}
          </p>

          <div className="space-y-1.5">
            <label className="text-sm font-medium text-slate-700 dark:text-slate-200" htmlFor="auth-email">
              邮箱
            </label>
            <input
              id="auth-email"
              type="email"
              value={authEmail}
              onChange={(event) => setAuthEmail(event.target.value)}
              autoComplete="email"
              placeholder="name@example.com"
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-200 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:placeholder:text-slate-500 dark:focus:border-slate-600 dark:focus:ring-slate-800"
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-sm font-medium text-slate-700 dark:text-slate-200" htmlFor="auth-password">
              密码
            </label>
            <input
              id="auth-password"
              type="password"
              value={authPassword}
              onChange={(event) => setAuthPassword(event.target.value)}
              autoComplete={authMode === "login" ? "current-password" : "new-password"}
              placeholder="至少 6 位"
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-200 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:placeholder:text-slate-500 dark:focus:border-slate-600 dark:focus:ring-slate-800"
            />
          </div>

          {authMode === "register" && (
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-slate-700 dark:text-slate-200" htmlFor="auth-verification-code">
                邮箱验证码
              </label>
              <div className="flex gap-2">
                <input
                  id="auth-verification-code"
                  type="text"
                  value={authVerificationCode}
                  onChange={(event) => setAuthVerificationCode(event.target.value)}
                  autoComplete="one-time-code"
                  placeholder="请输入 6 位验证码"
                  className="min-w-0 flex-1 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-200 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:placeholder:text-slate-500 dark:focus:border-slate-600 dark:focus:ring-slate-800"
                />
                <button
                  type="button"
                  onClick={handleSendVerificationCode}
                  disabled={isSendCodeSubmitting || sendCodeCooldownS > 0}
                  className="shrink-0 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
                >
                  {isSendCodeSubmitting
                    ? "发送中..."
                    : sendCodeCooldownS > 0
                      ? `${sendCodeCooldownS}s后重发`
                      : "发送验证码"}
                </button>
              </div>
              {sendCodeInfo && <p className="text-xs text-emerald-600 dark:text-emerald-300">{sendCodeInfo}</p>}
              {codeExpiresInS !== null && codeExpiresInS > 0 && (
                <p className="text-xs text-slate-500 dark:text-slate-400">验证码剩余有效期：{codeExpiresInS}s</p>
              )}
            </div>
          )}

          {authError && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
              {authError}
            </div>
          )}

          <button
            type="submit"
            disabled={isAuthSubmitting}
            className="w-full rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white"
          >
            {isAuthSubmitting ? "处理中..." : authMode === "login" ? "登录" : "注册"}
          </button>

          <div className="flex items-center justify-between text-sm">
            <button
              type="button"
              onClick={() => {
                setAuthMode(authMode === "login" ? "register" : "login");
                setAuthError(null);
                setAuthPassword("");
                setAuthVerificationCode("");
                setSendCodeCooldownS(0);
                setCodeExpiresInS(null);
                setSendCodeInfo(null);
                setCodeSentToEmail(null);
              }}
              className="text-slate-600 underline-offset-2 hover:text-slate-900 hover:underline dark:text-slate-300 dark:hover:text-slate-100"
            >
              {authMode === "login" ? "没有账号？去注册" : "已有账号？去登录"}
            </button>
            <button
              type="button"
              onClick={closeAuthModal}
              className="text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"
            >
              取消
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
