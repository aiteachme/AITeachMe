import { useEffect, type ReactElement } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Layout } from "./components/layout/Layout";
import { ToastProvider } from "./components/ui/Toast";
import { HomePage } from "./pages/HomePage";
import { LearningSpacesPage } from "./pages/LearningSpacesPage";
import { BuildPlanPage } from "./pages/BuildPlanPage";
import { ExamPaperPage, ExamsPage } from "./pages/ExamsPage";
import { ProfilePage } from "./pages/ProfilePage";
import { KnowledgeDocsPage } from "./pages/KnowledgeDocsPage";
import { KnowledgeDebugPage } from "./pages/KnowledgeDebugPage";
import { SUBJECT_ROUTE_REDIRECTS, type SubjectRouteId } from "./lib/subjectNavigation";
import { ensureSystemSettingsOverviewLoaded } from "./lib/systemSettings";

const queryClient = new QueryClient();

const SUBJECT_PAGE_ELEMENTS: Record<SubjectRouteId, ReactElement> = {
  build: <BuildPlanPage />,
  "knowledge-docs": <KnowledgeDocsPage />,
  "knowledge-debug": <KnowledgeDebugPage />,
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
  return (
    <QueryClientProvider client={queryClient}>
    <RuntimeSettingsBootstrap />
    <ToastProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Layout />}>
            <Route index element={<HomePage />} />
            <Route path="spaces" element={<LearningSpacesPage />} />
            {(Object.entries(SUBJECT_PAGE_ELEMENTS) as Array<[SubjectRouteId, ReactElement]>).map(
              ([routeId, element]) => (
                <Route key={routeId} path={`subject/:subjectId/${routeId}`} element={element} />
              ),
            )}
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
      </BrowserRouter>
    </ToastProvider>
    </QueryClientProvider>
  );
}

export default App;
