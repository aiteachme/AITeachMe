import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, Settings2, Box, HelpCircle } from "lucide-react";
import { useSettings, AppSettings } from "../../hooks/useSettings";

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

type TabType = "llm" | "general" | "about";

export function SettingsModal({ isOpen, onClose }: SettingsModalProps) {
  const { settings, updateSettings, resetSettings } = useSettings();
  const [localSettings, setLocalSettings] = useState<AppSettings>(settings);
  const [activeTab, setActiveTab] = useState<TabType>("llm");
  const [isSaved, setIsSaved] = useState(false);
  
  const [isTesting, setIsTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ status: 'idle' | 'success' | 'error', message?: string }>({ status: 'idle' });

  useEffect(() => {
    if (isOpen) {
      setLocalSettings(settings);
      setIsSaved(false);
      setTestResult({ status: 'idle' });
      setActiveTab("llm");
    }
  }, [isOpen, settings]);

  const handleSave = () => {
    updateSettings(localSettings);
    setIsSaved(true);
    setTimeout(() => {
      setIsSaved(false);
      onClose();
    }, 600);
  };

  const handleReset = () => {
    resetSettings();
    setLocalSettings({
      apiUrl: import.meta.env.VITE_API_URL || "http://localhost:8000",
      useMock: import.meta.env.VITE_USE_MOCK === "true",
      providerBaseUrl: "",
      providerApiKey: "",
    });
    setTestResult({ status: 'idle' });
  };

  const handleTestConnection = async () => {
    if (!localSettings.providerApiKey) return;
    setIsTesting(true);
    setTestResult({ status: 'idle' });
    
    try {
      const baseUrl = localSettings.providerBaseUrl.trim() || "https://api.openai.com/v1";
      const cleanBaseUrl = baseUrl.replace(/\/$/, "");
      
      const response = await fetch(`${cleanBaseUrl}/models`, {
        method: "GET",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${localSettings.providerApiKey.trim()}`,
        },
      });
      
      if (response.ok) {
        setTestResult({ status: 'success', message: '连接成功，API 密钥有效。' });
      } else {
        let errorMsg = `HTTP 错误 ${response.status}`;
        try {
          const errorData = await response.json();
          if (errorData?.error?.message) errorMsg = errorData.error.message;
        } catch (e) {}
        setTestResult({ status: 'error', message: errorMsg });
      }
    } catch (err: any) {
      setTestResult({ status: 'error', message: err.message || '网络通讯报错，请检查 Base URL 是否正确。' });
    } finally {
      setIsTesting(false);
    }
  };

  const tabs = [
    { id: "llm", label: "大模型配置", icon: <Box className="w-4 h-4" /> },
    { id: "general", label: "通用网络", icon: <Settings2 className="w-4 h-4" /> },
    { id: "about", label: "关于", icon: <HelpCircle className="w-4 h-4" /> },
  ] as const;

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 z-[100] bg-zinc-900/30 backdrop-blur-sm"
          />

          {/* Modal Container */}
          <div className="fixed inset-0 z-[101] flex items-center justify-center p-4 pointer-events-none">
            <motion.div
              initial={{ opacity: 0, scale: 0.98, y: 8 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.98, y: 8 }}
              transition={{ type: "spring", stiffness: 400, damping: 30 }}
              className="w-full max-w-3xl bg-white rounded-xl shadow-2xl overflow-hidden pointer-events-auto flex flex-col sm:flex-row h-[85vh] sm:h-[480px] border border-zinc-200"
            >
              {/* Sidebar */}
              <div className="w-full sm:w-52 bg-zinc-50 border-b sm:border-b-0 sm:border-r border-zinc-200 flex flex-col shrink-0 text-zinc-800">
                <div className="p-5 font-bold tracking-tight text-lg mb-2">系统设置</div>
                <div className="flex-1 px-3 space-y-1 overflow-x-auto sm:overflow-visible flex sm:flex-col">
                  {tabs.map((tab) => (
                    <button
                      key={tab.id}
                      onClick={() => setActiveTab(tab.id as TabType)}
                      title={tab.label}
                      aria-label={tab.label}
                      className={`flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors shrink-0 ${
                        activeTab === tab.id
                          ? "bg-zinc-200/60 text-zinc-900 font-medium"
                          : "text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900"
                      }`}
                    >
                      {tab.icon}
                      {tab.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Main Content */}
              <div className="flex-1 flex flex-col min-w-0 bg-white relative">
                {/* Mobile Close Button */}
                <div className="absolute top-3 right-3 sm:hidden z-10">
                  <button onClick={onClose} className="p-1.5 text-zinc-400 hover:text-zinc-600 rounded-md" aria-label="关闭">
                    <X className="w-5 h-5" />
                  </button>
                </div>

                <div className="flex-1 overflow-y-auto px-6 py-8 sm:px-10 sm:py-10">
                  <div className="max-w-xl">
                    <AnimatePresence mode="wait">
                      
                      {/* LLM TAB */}
                      {activeTab === "llm" && (
                        <motion.div
                          key="llm"
                          initial={{ opacity: 0, y: 5 }}
                          animate={{ opacity: 1, y: 0 }}
                          exit={{ opacity: 0, y: -5 }}
                          transition={{ duration: 0.15 }}
                          className="space-y-6"
                        >
                          <h3 className="text-base font-semibold text-zinc-900 mb-6 border-b border-zinc-100 pb-2">接口凭证 (BYOK)</h3>
                          <div className="space-y-5">
                            <div className="space-y-1.5">
                              <label className="text-sm font-medium text-zinc-700">代理接口 / Base URL</label>
                              <input
                                type="text"
                                spellCheck={false}
                                className="w-full px-3 py-2 bg-white border border-zinc-300 rounded-md text-sm focus:outline-none focus:ring-1 focus:ring-zinc-900 font-mono transition-shadow placeholder:text-zinc-300"
                                placeholder="https://api.openai.com/v1"
                                value={localSettings.providerBaseUrl}
                                onChange={(e) => {
                                  setLocalSettings(prev => ({ ...prev, providerBaseUrl: e.target.value }));
                                  setTestResult({ status: 'idle' });
                                }}
                              />
                            </div>
                            <div className="space-y-1.5">
                              <label className="text-sm font-medium text-zinc-700">模型密钥 / API Key</label>
                              <div className="flex gap-2">
                                <input
                                  type="password"
                                  autoComplete="off"
                                  className="flex-1 px-3 py-2 bg-white border border-zinc-300 rounded-md text-sm focus:outline-none focus:ring-1 focus:ring-zinc-900 font-mono transition-shadow placeholder:text-zinc-300"
                                  placeholder="sk-..."
                                  value={localSettings.providerApiKey}
                                  onChange={(e) => {
                                    setLocalSettings(prev => ({ ...prev, providerApiKey: e.target.value }));
                                    setTestResult({ status: 'idle' });
                                  }}
                                />
                                <button
                                  onClick={handleTestConnection}
                                  disabled={isTesting || !localSettings.providerApiKey.trim()}
                                  className="px-4 py-2 bg-zinc-100 hover:bg-zinc-200 text-zinc-800 disabled:opacity-50 text-sm font-medium rounded-md transition-colors border border-zinc-200 shrink-0 min-w-[80px]"
                                >
                                  {isTesting ? "嗅探中..." : "测试"}
                                </button>
                              </div>
                            </div>
                            
                            {/* Feedback Result */}
                            {testResult.status !== 'idle' && (
                              <div className={`px-3 py-2 rounded-md text-xs font-mono font-medium ${
                                testResult.status === 'success' 
                                  ? 'bg-emerald-50 text-emerald-700 border border-emerald-200/50' 
                                  : 'bg-red-50 text-red-700 border border-red-200/50'
                              }`}>
                                {testResult.message}
                              </div>
                            )}
                          </div>
                        </motion.div>
                      )}

                      {/* GENERAL TAB */}
                      {activeTab === "general" && (
                        <motion.div
                          key="general"
                          initial={{ opacity: 0, y: 5 }}
                          animate={{ opacity: 1, y: 0 }}
                          exit={{ opacity: 0, y: -5 }}
                          transition={{ duration: 0.15 }}
                          className="space-y-6"
                        >
                          <h3 className="text-base font-semibold text-zinc-900 mb-6 border-b border-zinc-100 pb-2">网络及联调</h3>
                          <div className="space-y-5">
                            <div className="space-y-1.5">
                              <label className="text-sm font-medium text-zinc-700">FastAPI 后端业务地址</label>
                              <input
                                type="text"
                                spellCheck={false}
                                className="w-full px-3 py-2 bg-white border border-zinc-300 rounded-md text-sm focus:outline-none focus:ring-1 focus:ring-zinc-900 font-mono transition-shadow placeholder:text-zinc-300"
                                placeholder="http://localhost:8000"
                                value={localSettings.apiUrl}
                                onChange={(e) => setLocalSettings(prev => ({ ...prev, apiUrl: e.target.value }))}
                              />
                            </div>
                            <div className="flex items-center justify-between py-2 border-t border-zinc-100 mt-4 pt-4">
                              <div className="text-sm font-medium text-zinc-800">拦截请求至本地 Mock</div>
                              <button
                                onClick={() => setLocalSettings(prev => ({ ...prev, useMock: !prev.useMock }))}
                                title="切换 Mock 状态"
                                aria-label="切换 Mock 状态"
                                className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none ${
                                  localSettings.useMock ? "bg-zinc-900" : "bg-zinc-200"
                                }`}
                              >
                                <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform shadow-sm ${localSettings.useMock ? "translate-x-4" : "translate-x-0.5"}`} />
                              </button>
                            </div>
                          </div>
                        </motion.div>
                      )}

                      {/* ABOUT TAB */}
                      {activeTab === "about" && (
                        <motion.div
                          key="about"
                          initial={{ opacity: 0, y: 5 }}
                          animate={{ opacity: 1, y: 0 }}
                          exit={{ opacity: 0, y: -5 }}
                          transition={{ duration: 0.15 }}
                          className="flex flex-col py-6"
                        >
                          <h3 className="text-base font-semibold text-zinc-900 mb-6 border-b border-zinc-100 pb-2">系统状态</h3>
                          <div className="text-sm text-zinc-600 mb-2">AITeachMe Web 客户端版 (v0.1.0)</div>
                          <div className="text-sm text-zinc-400 font-mono">本地编译环境稳定</div>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                </div>

                {/* Footer Controls */}
                <div className="px-6 py-4 bg-zinc-50 border-t border-zinc-200 flex items-center justify-between shrink-0">
                  <button
                    onClick={handleReset}
                    className="text-sm font-medium text-zinc-500 hover:text-zinc-800 transition-colors"
                  >
                    重置所有选项
                  </button>
                  <div className="flex gap-2">
                    <button
                      onClick={onClose}
                      className="px-4 py-2 text-sm font-medium text-zinc-600 hover:bg-zinc-200/50 rounded-md transition-colors"
                    >
                      不保存退出
                    </button>
                    <button
                      onClick={handleSave}
                      className="px-5 py-2 bg-zinc-900 hover:bg-zinc-800 text-white text-sm font-medium rounded-md transition-all shadow-sm active:scale-95 min-w-[80px]"
                    >
                      {isSaved ? "已保存" : "保存设置"}
                    </button>
                  </div>
                </div>
              </div>

              {/* Desktop Close Icon */}
              <button 
                onClick={onClose} 
                className="hidden sm:flex absolute top-3 right-3 p-1.5 text-zinc-400 hover:text-zinc-700 bg-transparent hover:bg-zinc-100 rounded-md transition-colors z-10"
                aria-label="关闭控件"
              >
                <X className="w-4 h-4" />
              </button>

            </motion.div>
          </div>
        </>
      )}
    </AnimatePresence>
  );
}
