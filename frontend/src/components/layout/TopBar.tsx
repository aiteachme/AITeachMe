import { useState, useRef, useEffect } from "react";
import { Github, MessageCircle, User, Settings, CreditCard, LogOut, LogIn, ChevronDown, Menu } from "lucide-react";
import { cn } from "../../lib/utils";
import { SettingsModal } from "../settings/SettingsModal";
import { apiClient, getApiErrorMessage } from "../../api/client";
import { Modal } from "../ui/Modal";

type RuntimeUser = {
  user_id: string;
  email?: string | null;
  is_authenticated?: boolean;
};

type AuthSessionData = {
  access_token?: string | null;
  current_user?: RuntimeUser | null;
};

type ApiResponse<T> = {
  code: number;
  message: string;
  data: T;
};

interface TopBarProps {
  className?: string;
}

export function TopBar({ className }: TopBarProps) {
  const [authUser, setAuthUser] = useState<RuntimeUser | null>(null);
  const isLoggedIn = Boolean(authUser?.is_authenticated);
  const email = authUser?.email?.trim() || "未登录";
  const displayName = email.includes("@") ? email.split("@")[0] : "访客";
  const [isAuthModalOpen, setIsAuthModalOpen] = useState(false);
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [authEmail, setAuthEmail] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [authError, setAuthError] = useState<string | null>(null);
  const [isAuthSubmitting, setIsAuthSubmitting] = useState(false);
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const [isSettingsModalOpen, setIsSettingsModalOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const mobileMenuRef = useRef<HTMLDivElement>(null);

  // Close dropdown when clicking outside
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
        setAuthUser(response.data.current_user ?? null);
      } catch {
        setAuthUser(null);
      }
    };
    void fetchCurrentUser();
  }, []);

  const handleLogout = async () => {
    localStorage.removeItem("token");
    try {
      const response = await apiClient<ApiResponse<AuthSessionData>>({
        url: "/api/v1/auth/logout",
        method: "POST",
        data: {},
      });
      setAuthUser(response.data.current_user ?? null);
    } catch {
      setAuthUser(null);
    }
    setIsDropdownOpen(false);
    setIsMobileMenuOpen(false);
  };

  const openAuthModal = (mode: "login" | "register" = "login") => {
    setAuthMode(mode);
    setAuthError(null);
    setAuthPassword("");
    setIsAuthModalOpen(true);
  };

  const closeAuthModal = () => {
    if (isAuthSubmitting) return;
    setIsAuthModalOpen(false);
    setAuthError(null);
    setAuthPassword("");
  };

  const handleAuthSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const emailValue = authEmail.trim();
    const passwordValue = authPassword.trim();
    if (!emailValue || passwordValue.length < 6) {
      setAuthError("请输入有效邮箱，且密码至少 6 位。");
      return;
    }

    setIsAuthSubmitting(true);
    setAuthError(null);
    try {
      const response = await apiClient<ApiResponse<AuthSessionData>>({
        url: authMode === "login" ? "/api/v1/auth/login" : "/api/v1/auth/register",
        method: "POST",
        data: { email: emailValue, password: passwordValue },
      });
      const token = response.data.access_token;
      if (token) {
        localStorage.setItem("token", token);
      }
      setAuthUser(response.data.current_user ?? null);
      setIsAuthModalOpen(false);
      setAuthPassword("");
      setIsMobileMenuOpen(false);
      setIsDropdownOpen(false);
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
      {/* Desktop Actions */}
      <div className="hidden sm:flex items-center gap-1">
        {/* GitHub Link */}
        <a
          href="https://github.com/aiteachme/AiTeachMe"
          target="_blank"
          rel="noopener noreferrer"
          className="p-2 text-slate-500 hover:text-slate-700 hover:bg-slate-50 rounded-lg transition-colors"
          title="GitHub"
        >
          <Github className="w-4 h-4" />
        </a>

        <button
          className="p-2 text-slate-500 hover:text-slate-700 hover:bg-slate-50 rounded-lg transition-colors"
          onClick={() => alert("这里会弹出反馈表单")}
          title="意见反馈"
        >
          <MessageCircle className="w-4 h-4" />
        </button>
      </div>

      {/* User Account Section - Desktop */}
      <div className="hidden sm:block">
        {isLoggedIn ? (
          <div className="relative" ref={dropdownRef}>
            <button
              onClick={() => setIsDropdownOpen(!isDropdownOpen)}
              className="flex items-center gap-2 pl-2 pr-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 rounded-full transition-colors border border-slate-200"
            >
              {/* Avatar */}
              <div className="w-7 h-7 rounded-full bg-gradient-to-br from-slate-700 to-slate-900 flex items-center justify-center text-white text-xs font-medium">
                我
              </div>
              <span className="hidden lg:inline font-medium text-slate-700">{displayName}</span>
              <ChevronDown
                className={cn(
                  "w-3.5 h-3.5 text-slate-400 transition-transform duration-200",
                  isDropdownOpen && "rotate-180"
                )}
              />
            </button>

            {/* Dropdown Menu */}
            {isDropdownOpen && (
              <div
                className="absolute right-0 mt-2 w-56 bg-white rounded-lg shadow-lg border border-slate-200 py-1 z-50"
                style={{
                  animation: "fadeIn 0.15s ease-out"
                }}
              >
                {/* User Info Header */}
                <div className="px-3 py-2 border-b border-slate-100">
                  <p className="text-sm font-medium text-slate-900">{displayName}</p>
                  <p className="text-xs text-slate-500 mt-0.5">{email}</p>
                </div>

                {/* Menu Items */}
                <div className="py-1">
                  <button
                    className="w-full flex items-center gap-2.5 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 transition-colors"
                    onClick={() => setIsDropdownOpen(false)}
                  >
                    <User className="w-4 h-4 text-slate-400" />
                    <span>个人资料</span>
                  </button>

                  <button
                    className="w-full flex items-center gap-2.5 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 transition-colors"
                    onClick={() => setIsDropdownOpen(false)}
                  >
                    <CreditCard className="w-4 h-4 text-slate-400" />
                    <div className="flex items-center justify-between flex-1">
                      <span>余额</span>
                      <span className="text-xs font-medium text-blue-600 bg-blue-50 px-2 py-0.5 rounded">
                        ¥100.00
                      </span>
                    </div>
                  </button>

                  <button
                    className="w-full flex items-center gap-2.5 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 transition-colors"
                    onClick={() => {
                      setIsDropdownOpen(false);
                      setIsSettingsModalOpen(true);
                    }}
                  >
                    <Settings className="w-4 h-4 text-slate-400" />
                    <span>设置</span>
                  </button>
                </div>

                {/* Logout */}
                <div className="border-t border-slate-100 pt-1">
                  <button
                    className="w-full flex items-center gap-2.5 px-3 py-2 text-sm text-red-600 hover:bg-red-50 transition-colors"
                    onClick={handleLogout}
                  >
                    <LogOut className="w-4 h-4" />
                    <span>退出登录</span>
                  </button>
                </div>
              </div>
            )}
          </div>
        ) : (
          <button
            onClick={() => openAuthModal("login")}
            className="flex items-center gap-2 px-4 py-1.5 text-sm font-medium text-white bg-slate-900 hover:bg-slate-800 rounded-lg transition-colors"
          >
            <LogIn className="w-4 h-4" />
            <span>登录</span>
          </button>
        )}
      </div>

      {/* Mobile Menu Button */}
      <div className="sm:hidden relative" ref={mobileMenuRef}>
        <button
          onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
          className="p-2 text-slate-600 hover:text-slate-900 hover:bg-slate-100 rounded-lg transition-colors"
          title="菜单"
        >
          <Menu className="w-5 h-5" />
        </button>

        {/* Mobile Dropdown */}
        {isMobileMenuOpen && (
          <div
            className="absolute right-0 mt-2 w-64 bg-white rounded-xl shadow-lg border border-slate-200 py-2 z-50"
            style={{
              animation: "fadeIn 0.15s ease-out"
            }}
          >
            {isLoggedIn ? (
              <>
                {/* User Info */}
                <div className="px-4 py-3 border-b border-slate-100">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center text-white font-medium">
                      我
                    </div>
                    <div>
                      <p className="text-sm font-medium text-slate-900">{displayName}</p>
                      <p className="text-xs text-slate-500">{email}</p>
                    </div>
                  </div>
                </div>

                {/* Actions */}
                <div className="py-1">
                  <button className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-slate-700 hover:bg-slate-50 transition-colors">
                    <User className="w-4 h-4 text-slate-400" />
                    <span>个人资料</span>
                  </button>

                  <button className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-slate-700 hover:bg-slate-50 transition-colors">
                    <CreditCard className="w-4 h-4 text-slate-400" />
                    <div className="flex items-center justify-between flex-1">
                      <span>余额</span>
                      <span className="text-xs font-medium text-blue-600 bg-blue-50 px-2 py-0.5 rounded">
                        ¥100.00
                      </span>
                    </div>
                  </button>

                  <button 
                    className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-slate-700 hover:bg-slate-50 transition-colors"
                    onClick={() => {
                      setIsMobileMenuOpen(false);
                      setIsSettingsModalOpen(true);
                    }}
                  >
                    <Settings className="w-4 h-4 text-slate-400" />
                    <span>设置</span>
                  </button>
                </div>

                <div className="border-t border-slate-100 my-1" />

                {/* External Links */}
                <div className="py-1">
                  <a
                    href="https://github.com/aiteachme/AiTeachMe"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-slate-700 hover:bg-slate-50 transition-colors"
                  >
                    <Github className="w-4 h-4 text-slate-400" />
                    <span>GitHub</span>
                  </a>

                  <button className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-slate-700 hover:bg-slate-50 transition-colors">
                    <MessageCircle className="w-4 h-4 text-slate-400" />
                    <span>意见反馈</span>
                  </button>
                </div>

                {/* Logout */}
                <div className="border-t border-slate-100 pt-1 pb-1">
                  <button
                    className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-red-600 hover:bg-red-50 transition-colors"
                    onClick={handleLogout}
                  >
                    <LogOut className="w-4 h-4" />
                    <span>退出登录</span>
                  </button>
                </div>
              </>
            ) : (
              <div className="p-2">
                <button
                  onClick={() => {
                    setIsMobileMenuOpen(false);
                    openAuthModal("login");
                  }}
                  className="w-full flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-medium text-white bg-slate-900 hover:bg-slate-800 rounded-lg transition-colors"
                >
                  <LogIn className="w-4 h-4" />
                  <span>登录</span>
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      <Modal
        open={isAuthModalOpen}
        onClose={closeAuthModal}
        title={authMode === "login" ? "登录 AiTeachMe" : "注册 AiTeachMe"}
        className="max-w-md"
      >
        <form className="space-y-4" onSubmit={handleAuthSubmit}>
          <p className="text-sm text-slate-500">
            {authMode === "login"
              ? "继续使用当前设备身份，并开启登录态同步。"
              : "将当前设备身份升级为邮箱账号。"}
          </p>

          <div className="space-y-1.5">
            <label className="text-sm font-medium text-slate-700" htmlFor="auth-email">
              邮箱
            </label>
            <input
              id="auth-email"
              type="email"
              value={authEmail}
              onChange={(event) => setAuthEmail(event.target.value)}
              autoComplete="email"
              placeholder="name@example.com"
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-900 outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-200"
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-sm font-medium text-slate-700" htmlFor="auth-password">
              密码
            </label>
            <input
              id="auth-password"
              type="password"
              value={authPassword}
              onChange={(event) => setAuthPassword(event.target.value)}
              autoComplete={authMode === "login" ? "current-password" : "new-password"}
              placeholder="至少 6 位"
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-900 outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-200"
            />
          </div>

          {authError && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {authError}
            </div>
          )}

          <button
            type="submit"
            disabled={isAuthSubmitting}
            className="w-full rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isAuthSubmitting ? "处理中..." : authMode === "login" ? "登录" : "注册"}
          </button>

          <div className="flex items-center justify-between text-sm">
            <button
              type="button"
              onClick={() => {
                setAuthMode(authMode === "login" ? "register" : "login");
                setAuthError(null);
              }}
              className="text-slate-600 underline-offset-2 hover:text-slate-900 hover:underline"
            >
              {authMode === "login" ? "没有账号？去注册" : "已有账号？去登录"}
            </button>
            <button
              type="button"
              onClick={closeAuthModal}
              className="text-slate-500 hover:text-slate-800"
            >
              取消
            </button>
          </div>
        </form>
      </Modal>

      {/* Settings Modal */}
      <SettingsModal 
        isOpen={isSettingsModalOpen} 
        onClose={() => setIsSettingsModalOpen(false)} 
      />
    </div>
  );
}
