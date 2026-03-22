import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Layout } from "./components/layout/Layout";
import { HomePage } from "./pages/HomePage";
import { UploadPage } from "./pages/UploadPage";
import { SummaryPage } from "./pages/SummaryPage";
import { ExamPage } from "./pages/ExamPage";
import { AnalysisPage } from "./pages/AnalysisPage";
import { DocPage } from "./pages/DocPage";

const queryClient = new QueryClient();

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Layout />}>
            <Route index element={<HomePage />} />
            <Route path="subject/:subjectId/upload" element={<UploadPage />} />
            <Route path="subject/:subjectId/summary" element={<SummaryPage />} />
            <Route path="subject/:subjectId/chat" element={<Navigate to="../doc" replace />} />
            <Route path="subject/:subjectId/exam" element={<ExamPage />} />
            <Route path="subject/:subjectId/analysis" element={<AnalysisPage />} />
            <Route path="subject/:subjectId/doc" element={<DocPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

export default App;
