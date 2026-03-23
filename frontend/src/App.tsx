import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Layout } from "./components/layout/Layout";
import { HomePage } from "./pages/HomePage";
import { FilesPage } from "./pages/FilesPage";
import { KnowledgeGraphPage } from "./pages/KnowledgeGraphPage";
import { ExamsPage } from "./pages/ExamsPage";
import { ProfilePage } from "./pages/ProfilePage";
import { KnowledgeDocsPage } from "./pages/KnowledgeDocsPage";

const queryClient = new QueryClient();

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Layout />}>
            <Route index element={<HomePage />} />
            <Route path="subject/:subjectId/files" element={<FilesPage />} />
            <Route path="subject/:subjectId/knowledge-graph" element={<KnowledgeGraphPage />} />
            <Route path="subject/:subjectId/exams" element={<ExamsPage />} />
            <Route path="subject/:subjectId/profile" element={<ProfilePage />} />
            <Route path="subject/:subjectId/knowledge-docs" element={<KnowledgeDocsPage />} />
            <Route path="subject/:subjectId/upload" element={<Navigate to="../files" replace />} />
            <Route path="subject/:subjectId/summary" element={<Navigate to="../knowledge-graph" replace />} />
            <Route path="subject/:subjectId/exam" element={<Navigate to="../exams" replace />} />
            <Route path="subject/:subjectId/analysis" element={<Navigate to="../profile" replace />} />
            <Route path="subject/:subjectId/chat" element={<Navigate to="../knowledge-docs" replace />} />
            <Route path="subject/:subjectId/doc" element={<Navigate to="../knowledge-docs" replace />} />
            <Route path="subject/:subjectId/docs" element={<Navigate to="../knowledge-docs" replace />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

export default App;
