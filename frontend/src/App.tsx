import { lazy, Suspense, useEffect, type ReactElement } from "react";
import { BrowserRouter, HashRouter, Routes, Route, Navigate, useLocation, useParams } from "react-router-dom";
import { onlineManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { apiClient, BACKEND_OFFLINE_EVENT, BACKEND_ONLINE_EVENT, isBackendOffline, isBackendOfflineError } from "./api/client";
import { ThemeProvider, THEME_STORAGE_KEY } from "./components/providers/ThemeProvider";
import { FrontendModeProvider } from "./components/providers/FrontendModeProvider";
import { RouteAnalyticsBridge } from "./components/providers/RouteAnalyticsBridge";
import { ElectronWindowFrame } from "./components/layout/ElectronWindowFrame";
import { Layout } from "./components/layout/Layout";
import { ToastProvider } from "./components/ui/Toast";
import { buildCoursePath, buildCourseSubPath, COURSE_ROUTE_REDIRECTS, type CourseRouteId } from "./lib/courseNavigation";
import { ensureSystemSettingsOverviewLoaded, getStoredSystemSettingsOverview } from "./lib/systemSettings";
import { isElectronRuntime } from "./lib/electronRuntime";
import { syncAnalyticsUserIdentity } from "./lib/analytics";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      refetchOnWindowFocus: false,
      retry: (failureCount, error) => !isBackendOfflineError(error) && failureCount < 1,
    },
  },
});

const HomePage = lazy(() => import("./pages/HomePage").then((module) => ({ default: module.HomePage })));
const GlobalAssistantPage = lazy(() =>
  import("./pages/GlobalAssistantPage").then((module) => ({ default: module.GlobalAssistantPage })),
);
const LibraryPage = lazy(() => import("./pages/LibraryPage").then((module) => ({ default: module.LibraryPage })));
const LibraryFilePage = lazy(() =>
  import("./pages/LibraryPage").then((module) => ({ default: module.LibraryFilePage })),
);
const BuildPlanPage = lazy(() =>
  import("./pages/BuildPlanPage").then((module) => ({ default: module.BuildPlanPage })),
);
const CourseDashboardPage = lazy(() =>
  import("./pages/CourseDashboardPage").then((module) => ({ default: module.CourseDashboardPage })),
);
const ExamsPage = lazy(() => import("./pages/ExamsPage").then((module) => ({ default: module.ExamsPage })));
const ExamPaperPage = lazy(() =>
  import("./pages/ExamsPage").then((module) => ({ default: module.ExamPaperPage })),
);
const MasteryDrillPage = lazy(() =>
  import("./pages/ExamsPage").then((module) => ({ default: module.MasteryDrillPage })),
);
const QuestionTemplatesPage = lazy(() =>
  import("./pages/ExamsPage").then((module) => ({ default: module.QuestionTemplatesPage })),
);
const QuestionTypesPage = lazy(() =>
  import("./pages/ExamsPage").then((module) => ({ default: module.QuestionTypesPage })),
);
const ProfilePage = lazy(() => import("./pages/ProfilePage").then((module) => ({ default: module.ProfilePage })));
const KnowledgeDocsPage = lazy(() =>
  import("./pages/KnowledgeDocsPage").then((module) => ({ default: module.KnowledgeDocsPage })),
);
const KnowledgeInteractivePage = lazy(() =>
  import("./pages/KnowledgeInteractivePage").then((module) => ({ default: module.KnowledgeInteractivePage })),
);
const DesktopUpdatePrompt = lazy(() =>
  import("./components/desktop/DesktopUpdatePrompt").then((module) => ({ default: module.DesktopUpdatePrompt })),
);

function RouteLoadingFallback() {
  return (
    <div className="flex min-h-[12rem] items-center justify-center text-sm text-zinc-500 dark:text-slate-400">
      加载中...
    </div>
  );
}

function withRouteFallback(element: ReactElement) {
  return <Suspense fallback={<RouteLoadingFallback />}>{element}</Suspense>;
}

const COURSE_PAGE_ELEMENTS: Record<CourseRouteId, ReactElement> = {
  nav: withRouteFallback(<CourseDashboardPage />),
  build: withRouteFallback(<BuildPlanPage />),
  "knowledge-docs": withRouteFallback(<KnowledgeDocsPage />),
  exams: withRouteFallback(<ExamsPage />),
  profile: withRouteFallback(<ProfilePage />),
};

function LegacyCourseRouteRedirect({ buildPath }: { buildPath: (params: Record<string, string | undefined>) => string }) {
  const params = useParams();
  const location = useLocation();
  return (
    <Navigate
      to={`${buildPath(params)}${location.search}${location.hash}`}
      replace
      state={location.state}
    />
  );
}

function RuntimeSettingsBootstrap() {
  useEffect(() => {
    const cachedOverview = getStoredSystemSettingsOverview();
    void ensureSystemSettingsOverviewLoaded();
    if (cachedOverview && typeof window !== "undefined") {
      window.setTimeout(() => {
        void ensureSystemSettingsOverviewLoaded(true);
      }, 1200);
    }
  }, []);
  return null;
}

type RuntimeUser = {
  user_id: string;
  email?: string | null;
  is_authenticated?: boolean;
};

type AuthSessionData = {
  current_user?: RuntimeUser | null;
};

type ApiResponse<T> = {
  data: T;
};

function AnalyticsIdentityBootstrap() {
  useEffect(() => {
    let cancelled = false;

    const syncCurrentUser = async () => {
      try {
        const response = await apiClient<ApiResponse<AuthSessionData>>({
          url: "/api/v1/auth/user",
          method: "POST",
          data: {},
        });
        if (cancelled) {
          return;
        }
        const currentUser = response.data.current_user ?? null;
        syncAnalyticsUserIdentity({
          userId: currentUser?.user_id,
          email: currentUser?.email,
          isAuthenticated: currentUser?.is_authenticated,
        });
      } catch {
        if (!cancelled) {
          syncAnalyticsUserIdentity(null);
        }
      }
    };

    void syncCurrentUser();
    return () => {
      cancelled = true;
    };
  }, []);

  return null;
}

function BackendConnectivityBridge() {
  useEffect(() => {
    const markOffline = () => onlineManager.setOnline(false);
    const markOnline = () => onlineManager.setOnline(true);

    window.addEventListener(BACKEND_OFFLINE_EVENT, markOffline);
    window.addEventListener(BACKEND_ONLINE_EVENT, markOnline);
    if (isBackendOffline()) {
      markOffline();
    }
    return () => {
      window.removeEventListener(BACKEND_OFFLINE_EVENT, markOffline);
      window.removeEventListener(BACKEND_ONLINE_EVENT, markOnline);
    };
  }, []);
  return null;
}

function isDesktopUpdateRuntime(): boolean {
  return (
    typeof window !== "undefined" &&
    window.location.hostname === "tauri.localhost" &&
    window.aiteachmeDesktop?.desktopFlavor === "local"
  );
}

function DesktopUpdatePromptMount() {
  if (!isDesktopUpdateRuntime()) {
    return null;
  }
  return (
    <Suspense fallback={null}>
      <DesktopUpdatePrompt />
    </Suspense>
  );
}

function App() {
  const Router = isElectronRuntime() ? HashRouter : BrowserRouter;

  return (
    <ThemeProvider defaultTheme="system" storageKey={THEME_STORAGE_KEY}>
      <FrontendModeProvider>
        <QueryClientProvider client={queryClient}>
          <BackendConnectivityBridge />
          <RuntimeSettingsBootstrap />
          <AnalyticsIdentityBootstrap />
          <ToastProvider>
            <DesktopUpdatePromptMount />
            <Router unstable_useTransitions={false}>
              <RouteAnalyticsBridge />
              <ElectronWindowFrame>
                <Routes>
                  <Route path="/" element={<Layout />}>
                    <Route index element={withRouteFallback(<HomePage />)} />
                    <Route path="assistant" element={withRouteFallback(<GlobalAssistantPage />)} />
                    <Route path="library" element={withRouteFallback(<LibraryPage />)} />
                    <Route path="library/:fileId" element={withRouteFallback(<LibraryFilePage />)} />
                    {(Object.entries(COURSE_PAGE_ELEMENTS) as Array<[CourseRouteId, ReactElement]>).map(
                      ([routeId, element]) => (
                        <Route key={routeId} path={`courses/:courseId/${routeId}`} element={element} />
                      ),
                    )}
                    <Route
                      path="courses/:courseId/knowledge-docs/interactive"
                      element={withRouteFallback(<KnowledgeInteractivePage />)}
                    />
                    <Route
                      path="courses/:courseId/knowledge-docs/html-figure"
                      element={withRouteFallback(<KnowledgeInteractivePage />)}
                    />
                    <Route
                      path="courses/:courseId/exams/question-templates"
                      element={withRouteFallback(<QuestionTemplatesPage />)}
                    />
                    <Route
                      path="courses/:courseId/exams/question-types"
                      element={withRouteFallback(<QuestionTypesPage />)}
                    />
                    <Route
                      path="courses/:courseId/exams/mastery-drill"
                      element={withRouteFallback(<MasteryDrillPage />)}
                    />
                    <Route
                      path="courses/:courseId/exams/:examPaperId"
                      element={withRouteFallback(<ExamPaperPage />)}
                    />
                    {Object.entries(COURSE_ROUTE_REDIRECTS).map(([aliasPath, targetRoute]) => (
                      <Route
                        key={aliasPath}
                        path={`courses/:courseId/${aliasPath}`}
                        element={<Navigate to={`../${targetRoute}`} replace />}
                      />
                    ))}
                    {(Object.keys(COURSE_PAGE_ELEMENTS) as CourseRouteId[]).map((routeId) => (
                      <Route
                        key={`legacy-${routeId}`}
                        path={`course/:courseId/${routeId}`}
                        element={
                          <LegacyCourseRouteRedirect
                            buildPath={({ courseId }) => buildCoursePath(courseId ?? "", routeId)}
                          />
                        }
                      />
                    ))}
                    <Route
                      path="course/:courseId/knowledge-docs/interactive"
                      element={
                        <LegacyCourseRouteRedirect
                          buildPath={({ courseId }) => buildCourseSubPath(courseId ?? "", "knowledge-docs", "interactive")}
                        />
                      }
                    />
                    <Route
                      path="course/:courseId/knowledge-docs/html-figure"
                      element={
                        <LegacyCourseRouteRedirect
                          buildPath={({ courseId }) => buildCourseSubPath(courseId ?? "", "knowledge-docs", "html-figure")}
                        />
                      }
                    />
                    <Route
                      path="course/:courseId/exams/question-templates"
                      element={
                        <LegacyCourseRouteRedirect
                          buildPath={({ courseId }) => buildCourseSubPath(courseId ?? "", "exams", "question-templates")}
                        />
                      }
                    />
                    <Route
                      path="course/:courseId/exams/question-types"
                      element={
                        <LegacyCourseRouteRedirect
                          buildPath={({ courseId }) => buildCourseSubPath(courseId ?? "", "exams", "question-types")}
                        />
                      }
                    />
                    <Route
                      path="course/:courseId/exams/mastery-drill"
                      element={
                        <LegacyCourseRouteRedirect
                          buildPath={({ courseId }) => buildCourseSubPath(courseId ?? "", "exams", "mastery-drill")}
                        />
                      }
                    />
                    <Route
                      path="course/:courseId/exams/:examPaperId"
                      element={
                        <LegacyCourseRouteRedirect
                          buildPath={({ courseId, examPaperId }) => buildCourseSubPath(courseId ?? "", "exams", examPaperId)}
                        />
                      }
                    />
                    {Object.entries(COURSE_ROUTE_REDIRECTS).map(([aliasPath, targetRoute]) => (
                      <Route
                        key={`legacy-alias-${aliasPath}`}
                        path={`course/:courseId/${aliasPath}`}
                        element={
                          <LegacyCourseRouteRedirect
                            buildPath={({ courseId }) => buildCoursePath(courseId ?? "", targetRoute)}
                          />
                        }
                      />
                    ))}
                    <Route path="*" element={<Navigate to="/" replace />} />
                  </Route>
                </Routes>
              </ElectronWindowFrame>
            </Router>
          </ToastProvider>
        </QueryClientProvider>
      </FrontendModeProvider>
    </ThemeProvider>
  );
}

export default App;
