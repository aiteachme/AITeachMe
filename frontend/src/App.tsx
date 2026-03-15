import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Layout } from "./components/Layout";
import { HomePage } from "./components/pages/HomePage";
import { UploadPage } from "./components/pages/UploadPage";
import { SummaryPage } from "./components/pages/SummaryPage";
import { ChatPage } from "./components/pages/ChatPage";
import { ExamPage } from "./components/pages/ExamPage";
import { AnalysisPage } from "./components/pages/AnalysisPage";

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<HomePage />} />
          <Route path="subject/:subjectId/upload" element={<UploadPage />} />
          <Route path="subject/:subjectId/summary" element={<SummaryPage />} />
          <Route path="subject/:subjectId/chat" element={<ChatPage />} />
          <Route path="subject/:subjectId/exam" element={<ExamPage />} />
          <Route path="subject/:subjectId/analysis" element={<AnalysisPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;
