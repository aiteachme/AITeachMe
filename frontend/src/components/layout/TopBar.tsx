import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import {
  ChevronDown,
  CreditCard,
  Github,
  LogIn,
  LogOut,
  User,
} from "lucide-react";
import { cn } from "../../lib/utils";
import { apiClient, getApiErrorMessage } from "../../api/client";
import { buildCoursePath, getCourseIdFromPathname } from "../../lib/courseNavigation";
import { resetAnalyticsIdentity, syncAnalyticsUserIdentity, trackAnalyticsEvent } from "../../lib/analytics";
import { Modal } from "../ui/Modal";

type RuntimeUser = {
  user_id: string;
  email?: string | null;
  is_authenticated?: boolean;
};

type AuthSessionData = {
  auth_enabled?: boolean;
  auth_ready?: boolean;
  access_token?: string | null;
  current_user?: RuntimeUser | null;
};

type SendEmailCodeData = {
  expires_in_s: number;
  resend_after_s: number;
};

type ApiResponse<T> = {
  code: number;
  message: string;
  data: T;
};

interface TopBarProps {
  className?: string;
}

function getDisplayName(user: RuntimeUser | null): string {
  if (!user?.is_authenticated) {
    return "本地用户";
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
    return `本地身份 ${user.user_id.slice(-6)}`;
  }

  return "当前设备上的本地身份";
}

function getAvatarText(user: RuntimeUser | null): string {
  if (!user?.is_authenticated) {
    return "本";
  }

  const displayName = getDisplayName(user).trim();
  return displayName.slice(0, 1).toUpperCase() || "U";
}

export function TopBar({ className }: TopBarProps) {
  const location = useLocation();
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

  const dropdownRef = useRef<HTMLDivElement>(null);
  const mobileMenuRef = useRef<HTMLDivElement>(null);

  const isLoggedIn = Boolean(authUser?.is_authenticated);
  const canUseAuth = authEnabled === true;
  const displayName = getDisplayName(authUser);
  const identitySubtitle = getIdentitySubtitle(authUser);
  const avatarText = getAvatarText(authUser);
  const currentCourseId = useMemo(() => getCourseIdFromPathname(location.pathname), [location.pathname]);
  const profilePath = currentCourseId ? buildCoursePath(currentCourseId, "profile") : null;

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
    const fetchCurrentUser = async () => {
      try {
        const response = await apiClient<ApiResponse<AuthSessionData>>({
          url: "/api/v1/auth/user",
          method: "POST",
          data: {},
        });
        const currentUser = response.data.current_user ?? null;
        setAuthEnabled(Boolean(response.data.auth_enabled));
        if (!currentUser?.is_authenticated) {
          localStorage.removeItem("token");
        }
        setAuthUser(currentUser);
        syncAnalyticsUserIdentity({
          userId: currentUser?.user_id,
          email: currentUser?.email,
          isAuthenticated: currentUser?.is_authenticated,
        });
      } catch {
        setAuthEnabled(false);
        setAuthUser(null);
        syncAnalyticsUserIdentity(null);
      }
    };

    void fetchCurrentUser();
  }, []);

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
    setIsAuthModalOpen(false);
    setAuthError(null);
    setAuthPassword("");
    setAuthVerificationCode("");
    setSendCodeCooldownS(0);
    setCodeExpiresInS(null);
    setSendCodeInfo(null);
    setCodeSentToEmail(null);
  };

  const closeMenus = () => {
    setIsDropdownOpen(false);
    setIsMobileMenuOpen(false);
  };

  const openAuthEntry = (mode: "login" | "register") => {
    if (!canUseAuth) {
      closeMenus();
      return;
    }
    closeMenus();
    openAuthModal(mode);
  };

  const handleLogout = async () => {
    localStorage.removeItem("token");
    try {
      const response = await apiClient<ApiResponse<AuthSessionData>>({
        url: "/api/v1/auth/logout",
        method: "POST",
        data: {},
      });
      const currentUser = response.data.current_user ?? null;
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

  const handleAuthSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const emailValue = authEmail.trim();
    const passwordValue = authPassword.trim();
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
      const currentUser = response.data.current_user ?? null;
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
    <div className={cn("flex items-center gap-3", className)}>
      <div className="hidden sm:block">
        <div 
          className="relative" 
          ref={dropdownRef}
          onMouseEnter={() => setIsDropdownOpen(true)}
          onMouseLeave={() => setIsDropdownOpen(false)}
        >
          <button
            className="flex items-center gap-2 rounded-full border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900 pl-2 pr-3 py-1.5 text-sm text-slate-700 dark:text-slate-300 transition-colors hover:bg-slate-50 dark:hover:bg-slate-800"
          >
            <div className="flex h-7 w-7 items-center justify-center rounded-full bg-gradient-to-br from-slate-700 to-slate-900 text-xs font-medium text-white">
              {avatarText}
            </div>
            <div className="hidden min-w-0 text-left lg:block">
              <div className="max-w-[120px] truncate font-medium text-slate-700 dark:text-slate-300">{displayName}</div>
              <div className="max-w-[120px] truncate text-[12px] text-slate-400 dark:text-slate-500">
                {isLoggedIn ? "已登录" : "本地身份"}
              </div>
            </div>
            <ChevronDown
              className={cn(
                "w-3.5 h-3.5 text-slate-400 transition-transform duration-200",
                isDropdownOpen && "rotate-180",
              )}
            />
          </button>

          {isDropdownOpen && (
            <div className="absolute right-0 top-full pt-2 z-50">
              <div
                className="w-64 bg-white dark:bg-slate-900 rounded-xl shadow-lg border border-slate-200 dark:border-slate-800 py-1"
                style={{
                  animation: "fadeIn 0.15s ease-out",
                }}
              >
                <div className="px-4 py-3 border-b border-slate-100 dark:border-slate-800/80">
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

              <div className="py-1">
                {profilePath ? (
                  <Link
                    to={profilePath}
                    className="w-full flex items-center gap-2.5 px-4 py-2 text-sm text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
                    onClick={() => setIsDropdownOpen(false)}
                  >
                    <User className="w-4 h-4 text-slate-400 dark:text-slate-500" />
                    <span>学习画像</span>
                  </Link>
                ) : null}

                {isLoggedIn ? (
                  <>
                    <button
                      className="w-full flex items-center gap-2.5 px-4 py-2 text-sm text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
                      onClick={() => setIsDropdownOpen(false)}
                    >
                      <CreditCard className="w-4 h-4 text-slate-400 dark:text-slate-500" />
                      <div className="flex items-center justify-between flex-1">
                        <span>余额</span>
                        <span className="text-xs font-medium text-indigo-600 dark:text-indigo-300 bg-indigo-50 dark:bg-indigo-500/10 px-2 py-0.5 rounded">
                          ￥100.00
                        </span>
                      </div>
                    </button>
                  </>
                ) : canUseAuth ? (
                  <>
                    <button
                      className="w-full flex items-center gap-2.5 px-4 py-2 text-sm text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
                      onClick={() => openAuthEntry("login")}
                    >
                      <LogIn className="w-4 h-4 text-slate-400 dark:text-slate-500" />
                      <span>登录账号</span>
                    </button>

                    <button
                      className="w-full flex items-center gap-2.5 px-4 py-2 text-sm text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
                      onClick={() => openAuthEntry("register")}
                    >
                      <User className="w-4 h-4 text-slate-400 dark:text-slate-500" />
                      <span>注册账号</span>
                    </button>
                  </>
                ) : (
                  <div className="px-4 py-2 text-sm text-slate-500 dark:text-slate-400">
                    本地模式无需登录，数据保存在当前设备环境中。
                  </div>
                )}

              </div>

              <div className="border-t border-slate-100 dark:border-slate-800/80 py-1">
                <a
                  href="https://github.com/aiteachme/AiTeachMe"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="w-full flex items-center gap-2.5 px-4 py-2 text-sm text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
                  onClick={() => setIsDropdownOpen(false)}
                >
                  <Github className="w-4 h-4 text-slate-400 dark:text-slate-500" />
                  <span>GitHub</span>
                </a>
              </div>

              {isLoggedIn && (
                <div className="border-t border-slate-100 dark:border-slate-800/80 pt-1">
                  <button
                    className="w-full flex items-center gap-2.5 px-4 py-2 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                    onClick={handleLogout}
                  >
                    <LogOut className="w-4 h-4" />
                    <span>退出登录</span>
                  </button>
                </div>
              )}
            </div>
            </div>
          )}
        </div>
      </div>

      <div className="sm:hidden relative" ref={mobileMenuRef}>
        <button
          onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
          className="flex h-11 items-center gap-2 rounded-full border border-slate-200 bg-white px-2 text-slate-700 transition-colors hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
          title="身份菜单"
        >
          <div className="flex h-7 w-7 items-center justify-center rounded-full bg-gradient-to-br from-slate-700 to-slate-900 text-xs font-medium text-white">
            {avatarText}
          </div>
          <ChevronDown
            className={cn(
              "w-3.5 h-3.5 text-slate-400 transition-transform duration-200",
              isMobileMenuOpen && "rotate-180",
            )}
          />
        </button>

        {isMobileMenuOpen && (
          <div
            className="absolute right-0 mt-2 w-64 bg-white dark:bg-slate-900 rounded-xl shadow-lg border border-slate-200 dark:border-slate-800 py-2 z-50"
            style={{
              animation: "fadeIn 0.15s ease-out",
            }}
          >
            <div className="px-4 py-3 border-b border-slate-100 dark:border-slate-800/80">
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

            <div className="py-1">
              {profilePath ? (
                <Link
                  to={profilePath}
                  className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
                  onClick={() => setIsMobileMenuOpen(false)}
                >
                  <User className="w-4 h-4 text-slate-400 dark:text-slate-500" />
                  <span>学习画像</span>
                </Link>
              ) : null}

              {isLoggedIn ? (
                <>
                  <button className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors">
                    <CreditCard className="w-4 h-4 text-slate-400 dark:text-slate-500" />
                    <div className="flex items-center justify-between flex-1">
                      <span>余额</span>
                      <span className="text-xs font-medium text-indigo-600 dark:text-indigo-300 bg-indigo-50 dark:bg-indigo-500/10 px-2 py-0.5 rounded">
                        ￥100.00
                      </span>
                    </div>
                  </button>
                </>
              ) : canUseAuth ? (
                <>
                  <button
                    className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
                    onClick={() => openAuthEntry("login")}
                  >
                    <LogIn className="w-4 h-4 text-slate-400 dark:text-slate-500" />
                    <span>登录账号</span>
                  </button>

                  <button
                    className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
                    onClick={() => openAuthEntry("register")}
                  >
                    <User className="w-4 h-4 text-slate-400 dark:text-slate-500" />
                    <span>注册账号</span>
                  </button>
                </>
              ) : (
                <div className="px-4 py-2.5 text-sm text-slate-500 dark:text-slate-400">
                  本地模式无需登录，数据保存在当前设备环境中。
                </div>
              )}

            </div>

            <div className="border-t border-slate-100 dark:border-slate-800/80 my-1" />

            <div className="py-1">
              <a
                href="https://github.com/aiteachme/AiTeachMe"
                target="_blank"
                rel="noopener noreferrer"
                className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
              >
                <Github className="w-4 h-4 text-slate-400 dark:text-slate-500" />
                <span>GitHub</span>
              </a>
            </div>

            {isLoggedIn && (
              <div className="border-t border-slate-100 dark:border-slate-800/80 pt-1 pb-1">
                <button
                  className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                  onClick={handleLogout}
                >
                  <LogOut className="w-4 h-4" />
                  <span>退出登录</span>
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      <Modal
        open={canUseAuth && isAuthModalOpen}
        onClose={closeAuthModal}
        title={authMode === "login" ? "登录 AiTeachMe" : "注册 AiTeachMe"}
        className="max-w-md"
      >
        <form className="space-y-4" onSubmit={handleAuthSubmit}>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {authMode === "login"
              ? "继续使用当前设备身份，并开启登录态同步。"
              : "将当前本地身份升级为邮箱账号。"}
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
