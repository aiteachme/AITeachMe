import type { ReactElement } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Layout } from "./components/layout/Layout";
import { ToastProvider } from "./components/ui/Toast";
import { HomePage } from "./pages/HomePage";
import { BuildPlanPage } from "./pages/BuildPlanPage";
import { ExamsPage } from "./pages/ExamsPage";
import { ProfilePage } from "./pages/ProfilePage";
import { KnowledgeDocsPage } from "./pages/KnowledgeDocsPage";
import { KnowledgeDebugPage } from "./pages/KnowledgeDebugPage";
import { SUBJECT_ROUTE_REDIRECTS, type SubjectRouteId } from "./lib/subjectNavigation";

const queryClient = new QueryClient();

const SUBJECT_PAGE_ELEMENTS: Record<SubjectRouteId, ReactElement> = {
  build: <BuildPlanPage />,
  "knowledge-docs": <KnowledgeDocsPage />,
  "knowledge-debug": <KnowledgeDebugPage />,
  exams: <ExamsPage />,
  profile: <ProfilePage />,
};

function App() {
  return (
    <QueryClientProvider client={queryClient}>
    <ToastProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Layout />}>
            <Route index element={<HomePage />} />
            {(Object.entries(SUBJECT_PAGE_ELEMENTS) as Array<[SubjectRouteId, ReactElement]>).map(
              ([routeId, element]) => (
                <Route key={routeId} path={`subject/:subjectId/${routeId}`} element={element} />
              ),
            )}
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
