import { useState, useRef, useEffect } from "react";
import { Github, MessageCircle, User, Settings, CreditCard, LogOut, LogIn, ChevronDown, Menu } from "lucide-react";
import { cn } from "../../lib/utils";

interface TopBarProps {
  className?: string;
}

export function TopBar({ className }: TopBarProps) {
  const [isLoggedIn, setIsLoggedIn] = useState(true); // Mock login state
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
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

  const handleLogout = () => {
    setIsLoggedIn(false);
    setIsDropdownOpen(false);
    setIsMobileMenuOpen(false);
  };

  const handleLogin = () => {
    setIsLoggedIn(true);
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
              <span className="hidden lg:inline font-medium text-slate-700">用户名</span>
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
                  <p className="text-sm font-medium text-slate-900">用户名</p>
                  <p className="text-xs text-slate-500 mt-0.5">user@example.com</p>
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
                      <span className="text-xs font-medium text-slate-700 bg-slate-100 px-2 py-0.5 rounded">
                        ¥100.00
                      </span>
                    </div>
                  </button>

                  <button
                    className="w-full flex items-center gap-2.5 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 transition-colors"
                    onClick={() => setIsDropdownOpen(false)}
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
            onClick={handleLogin}
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
                      <p className="text-sm font-medium text-slate-900">用户名</p>
                      <p className="text-xs text-slate-500">user@example.com</p>
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

                  <button className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-slate-700 hover:bg-slate-50 transition-colors">
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
                  onClick={handleLogin}
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
    </div>
  );
}
