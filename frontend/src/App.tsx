import { lazy, Suspense, useEffect, type ReactElement } from "react";
import { BrowserRouter, HashRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider, THEME_STORAGE_KEY } from "./components/providers/ThemeProvider";
import { ElectronWindowFrame } from "./components/layout/ElectronWindowFrame";
import { Layout } from "./components/layout/Layout";
import { ToastProvider } from "./components/ui/Toast";
import { SUBJECT_ROUTE_REDIRECTS, type SubjectRouteId } from "./lib/subjectNavigation";
import { ensureSystemSettingsOverviewLoaded } from "./lib/systemSettings";
import { isElectronRuntime } from "./lib/electronRuntime";

const queryClient = new QueryClient();

const HomePage = lazy(() => import("./pages/HomePage").then((module) => ({ default: module.HomePage })));
const GlobalAssistantPage = lazy(() =>
  import("./pages/GlobalAssistantPage").then((module) => ({ default: module.GlobalAssistantPage })),
);
const LearningSpacesPage = lazy(() =>
  import("./pages/LearningSpacesPage").then((module) => ({ default: module.LearningSpacesPage })),
);
const LibraryPage = lazy(() => import("./pages/LibraryPage").then((module) => ({ default: module.LibraryPage })));
const BuildPlanPage = lazy(() =>
  import("./pages/BuildPlanPage").then((module) => ({ default: module.BuildPlanPage })),
);
const ExamsPage = lazy(() => import("./pages/ExamsPage").then((module) => ({ default: module.ExamsPage })));
const ExamPaperPage = lazy(() =>
  import("./pages/ExamsPage").then((module) => ({ default: module.ExamPaperPage })),
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

const SUBJECT_PAGE_ELEMENTS: Record<SubjectRouteId, ReactElement> = {
  build: withRouteFallback(<BuildPlanPage />),
  "knowledge-docs": withRouteFallback(<KnowledgeDocsPage />),
  exams: withRouteFallback(<ExamsPage />),
  profile: withRouteFallback(<ProfilePage />),
};

function RuntimeSettingsBootstrap() {
  useEffect(() => {
    void ensureSystemSettingsOverviewLoaded();
  }, []);
  return null;
}

function App() {
  const Router = isElectronRuntime() ? HashRouter : BrowserRouter;

  return (
    <ThemeProvider defaultTheme="system" storageKey={THEME_STORAGE_KEY}>
      <QueryClientProvider client={queryClient}>
        <RuntimeSettingsBootstrap />
        <ToastProvider>
          <Router unstable_useTransitions={false}>
            <ElectronWindowFrame>
              <Routes>
                <Route path="/" element={<Layout />}>
                  <Route index element={withRouteFallback(<HomePage />)} />
                  <Route path="assistant" element={withRouteFallback(<GlobalAssistantPage />)} />
                  <Route path="spaces" element={withRouteFallback(<LearningSpacesPage />)} />
                  <Route path="library" element={withRouteFallback(<LibraryPage />)} />
                  {(Object.entries(SUBJECT_PAGE_ELEMENTS) as Array<[SubjectRouteId, ReactElement]>).map(
                    ([routeId, element]) => (
                      <Route key={routeId} path={`subject/:subjectId/${routeId}`} element={element} />
                    ),
                  )}
                  <Route
                    path="subject/:subjectId/knowledge-docs/interactive"
                    element={withRouteFallback(<KnowledgeInteractivePage />)}
                  />
                  <Route
                    path="subject/:subjectId/exams/question-templates"
                    element={withRouteFallback(<QuestionTemplatesPage />)}
                  />
                  <Route
                    path="subject/:subjectId/exams/question-types"
                    element={withRouteFallback(<QuestionTypesPage />)}
                  />
                  <Route
                    path="subject/:subjectId/exams/:examPaperId"
                    element={withRouteFallback(<ExamPaperPage />)}
                  />
                  {Object.entries(SUBJECT_ROUTE_REDIRECTS).map(([aliasPath, targetRoute]) => (
                    <Route
                      key={aliasPath}
                      path={`subject/:subjectId/${aliasPath}`}
                      element={<Navigate to={`../${targetRoute}`} replace />}
                    />
                  ))}
                  <Route path="*" element={<Navigate to="/" replace />} />
                </Route>
              </Routes>
            </ElectronWindowFrame>
          </Router>
        </ToastProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}

export default App;
