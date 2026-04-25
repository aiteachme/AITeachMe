import { useEffect, type ReactElement } from "react";
import { BrowserRouter, HashRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider, THEME_STORAGE_KEY } from "./components/providers/ThemeProvider";
import { ElectronWindowFrame } from "./components/layout/ElectronWindowFrame";
import { Layout } from "./components/layout/Layout";
import { ToastProvider } from "./components/ui/Toast";
import { HomePage } from "./pages/HomePage";
import { GlobalAssistantPage } from "./pages/GlobalAssistantPage";
import { LearningSpacesPage } from "./pages/LearningSpacesPage";
import { LibraryPage } from "./pages/LibraryPage";
import { BuildPlanPage } from "./pages/BuildPlanPage";
import { ExamPaperPage, ExamsPage, QuestionTemplatesPage, QuestionTypesPage } from "./pages/ExamsPage";
import { ProfilePage } from "./pages/ProfilePage";
import { KnowledgeDocsPage } from "./pages/KnowledgeDocsPage";
import { KnowledgeInteractivePage } from "./pages/KnowledgeInteractivePage";
import { SUBJECT_ROUTE_REDIRECTS, type SubjectRouteId } from "./lib/subjectNavigation";
import { ensureSystemSettingsOverviewLoaded } from "./lib/systemSettings";
import { isElectronRuntime } from "./lib/electronRuntime";

const queryClient = new QueryClient();

const SUBJECT_PAGE_ELEMENTS: Record<SubjectRouteId, ReactElement> = {
  build: <BuildPlanPage />,
  "knowledge-docs": <KnowledgeDocsPage />,
  exams: <ExamsPage />,
  profile: <ProfilePage />,
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
          <Router>
            <ElectronWindowFrame>
              <Routes>
                <Route path="/" element={<Layout />}>
                  <Route index element={<HomePage />} />
                  <Route path="assistant" element={<GlobalAssistantPage />} />
                  <Route path="spaces" element={<LearningSpacesPage />} />
                  <Route path="library" element={<LibraryPage />} />
                  {(Object.entries(SUBJECT_PAGE_ELEMENTS) as Array<[SubjectRouteId, ReactElement]>).map(
                    ([routeId, element]) => (
                      <Route key={routeId} path={`subject/:subjectId/${routeId}`} element={element} />
                    ),
                  )}
                  <Route path="subject/:subjectId/knowledge-docs/interactive" element={<KnowledgeInteractivePage />} />
                  <Route path="subject/:subjectId/exams/question-templates" element={<QuestionTemplatesPage />} />
                  <Route path="subject/:subjectId/exams/question-types" element={<QuestionTypesPage />} />
                  <Route path="subject/:subjectId/exams/:examPaperId" element={<ExamPaperPage />} />
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
