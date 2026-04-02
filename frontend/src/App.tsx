import type { ReactElement } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Layout } from "./components/layout/Layout";
import { HomePage } from "./pages/HomePage";
import { FilesPage } from "./pages/FilesPage";
import { ExamsPage } from "./pages/ExamsPage";
import { ProfilePage } from "./pages/ProfilePage";
import { KnowledgeDocsPage } from "./pages/KnowledgeDocsPage";
import { KnowledgeGraphPage } from "./pages/KnowledgeGraphPage";
import { ChatPage } from "./pages/ChatPage";
import { SUBJECT_ROUTE_REDIRECTS, type SubjectRouteId } from "./lib/subjectNavigation";

const queryClient = new QueryClient();

const SUBJECT_PAGE_ELEMENTS: Record<SubjectRouteId, ReactElement> = {
  files: <FilesPage />,
  "knowledge-docs": <KnowledgeDocsPage />,
  "knowledge-graph": <KnowledgeGraphPage />,
  chat: <ChatPage />,
  exams: <ExamsPage />,
  profile: <ProfilePage />,
};

function App() {
  return (
    <QueryClientProvider client={queryClient}>
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
    </QueryClientProvider>
  );
}

export default App;
