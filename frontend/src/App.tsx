import { Navigate, Route, Routes } from 'react-router-dom';
import { AppShell } from '@/app/AppShell';
import { UploadWorkspaceProvider } from '@/app/UploadWorkspaceContext';
import {
  AdminPage,
  ChatPage,
  DocumentsPage,
  OverviewPage,
  RetrievalPage,
  SopPage,
} from '@/pages';

export default function App() {
  return (
    <UploadWorkspaceProvider>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<OverviewPage />} />
          <Route path="documents" element={<DocumentsPage />} />
          <Route path="retrieval" element={<RetrievalPage />} />
          <Route path="chat" element={<ChatPage />} />
          <Route path="sop" element={<SopPage />} />
          <Route path="admin" element={<AdminPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </UploadWorkspaceProvider>
  );
}
