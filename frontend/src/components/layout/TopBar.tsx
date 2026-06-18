import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import {
  Github,
  User,
} from "lucide-react";
import { cn } from "../../lib/utils";
import { apiClient } from "../../api/client";
import { buildCoursePath, getCourseIdFromPathname } from "../../lib/courseNavigation";
import { syncAnalyticsUserIdentity } from "../../lib/analytics";

type RuntimeUser = {
  user_id: string;
  email?: string | null;
  is_authenticated?: boolean;
};

type AuthSessionData = {
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

function getIdentitySubtitle(user: RuntimeUser | null): string {
  if (user?.user_id) {
    return `本地身份 ${user.user_id.slice(-6)}`;
  }

  return "当前设备上的本地身份";
}

export function TopBar({ className }: TopBarProps) {
  const location = useLocation();
  const [authUser, setAuthUser] = useState<RuntimeUser | null>(null);
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);

  const dropdownRef = useRef<HTMLDivElement>(null);
  const mobileMenuRef = useRef<HTMLDivElement>(null);

  const displayName = "本地用户";
  const identitySubtitle = getIdentitySubtitle(authUser);
  const avatarText = "本";
  const currentCourseId = useMemo(() => getCourseIdFromPathname(location.pathname), [location.pathname]);
  const profilePath = currentCourseId ? buildCoursePath(currentCourseId, "profile") : null;
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
    const fetchCurrentUser = async () => {
      try {
        const response = await apiClient<ApiResponse<AuthSessionData>>({
          url: "/api/v1/auth/user",
          method: "POST",
          data: {},
        });
        const currentUser = response.data.current_user ?? null;
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
        setAuthUser(null);
        syncAnalyticsUserIdentity(null);
      }
    };

    void fetchCurrentUser();
  }, []);

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
            <span className="hidden whitespace-nowrap lg:inline">本地</span>
          </button>

          {isDropdownOpen && (
            <div className="absolute right-0 top-full pt-2 z-50">
              <div
                className="w-[310px] bg-white dark:bg-slate-900 rounded-xl shadow-lg border border-slate-150 dark:border-slate-800 py-1"
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
                    onClick={closeMenus}
                  >
                    <User className="w-4 h-4 text-slate-400 dark:text-slate-500" />
                    <span>个人资料</span>
                  </Link>
                ) : null}

              </div>

              <div className="border-t border-slate-100 dark:border-slate-800/80 py-1">
                <a
                  href="https://github.com/aiteachme/AiTeachMe"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="w-full flex items-center gap-2.5 px-4 py-2 text-sm text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
                  onClick={closeMenus}
                >
                  <Github className="w-4 h-4 text-slate-400 dark:text-slate-500" />
                  <span>GitHub</span>
                </a>
              </div>
            </div>
            </div>
          )}
        </div>
      </div>

      <div className="sm:hidden relative" ref={mobileMenuRef}>
        <button
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
            className="absolute right-0 mt-2 w-[310px] bg-white dark:bg-slate-900 rounded-xl shadow-lg border border-slate-150 dark:border-slate-800 py-2 z-50"
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
                  onClick={closeMenus}
                >
                  <User className="w-4 h-4 text-slate-400 dark:text-slate-500" />
                  <span>个人资料</span>
                </Link>
              ) : null}

            </div>

            <div className="border-t border-slate-100 dark:border-slate-800/80 my-1" />

            <div className="py-1">
              <a
                href="https://github.com/aiteachme/AiTeachMe"
                target="_blank"
                rel="noopener noreferrer"
                className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
                onClick={closeMenus}
              >
                <Github className="w-4 h-4 text-slate-400 dark:text-slate-500" />
                <span>GitHub</span>
              </a>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
