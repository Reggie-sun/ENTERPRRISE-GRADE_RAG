import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { RequireAuth, useAuth } from '@/auth';
import { AppShell } from '@/app/AppShell';
import { UploadWorkspaceProvider } from '@/app/UploadWorkspaceContext';
import { HeroCard, Layout } from '@/components';
import {
  AdminPage,
  ChatPage,
  DocumentsPage,
  LoginPage,
  LogsPage,
  OpsPage,
  OverviewPage,
  RetrievalPage,
  SopPage,
} from '@/pages';
import {
  PortalChatPage,
  PortalLibraryPage,
  PortalMePage,
  PortalShell,
  PortalSopPage,
} from '@/portal';

function WorkspaceRoot() {
  return (
    <UploadWorkspaceProvider>
      <AppShell />
    </UploadWorkspaceProvider>
  );
}

function RootRedirect() {
  const { isAuthenticated, status } = useAuth();

  if (status === 'loading') {
    return (
      <Layout>
        <div className="grid min-h-[70vh] place-items-center">
          <HeroCard>
            <div className="inline-flex items-center gap-2 rounded-full bg-[rgba(182,70,47,0.09)] px-3 py-1.5 text-sm font-bold uppercase tracking-wider text-accent-deep">
              正在连接平台
            </div>
            <h1 className="m-0 mt-5 font-serif text-3xl leading-tight text-ink">
              正在恢复当前会话
            </h1>
            <p className="m-0 mt-3 max-w-[56ch] text-base leading-relaxed text-ink-soft">
              系统正在校验当前登录信息，确认后会自动进入门户首页或登录页。
            </p>
          </HeroCard>
        </div>
      </Layout>
    );
  }

  return <Navigate to={isAuthenticated ? '/portal' : '/login'} replace />;
}

function PortalChatRedirect() {
  const location = useLocation();
  return <Navigate to={{ pathname: '/portal', search: location.search }} replace />;
}

export default function App() {
  return (
    <Routes>
      <Route index element={<RootRedirect />} />
      <Route path="login" element={<LoginPage />} />

      <Route element={<RequireAuth />}>
        <Route path="portal" element={<PortalShell />}>
          <Route index element={<PortalChatPage />} />
          <Route path="chat" element={<PortalChatRedirect />} />
          <Route path="sop" element={<PortalSopPage />} />
          <Route path="library" element={<PortalLibraryPage />} />
          <Route path="me" element={<PortalMePage />} />
        </Route>
      </Route>

      <Route element={<RequireAuth allowedRoles={['department_admin', 'sys_admin']} />}>
        <Route path="workspace" element={<WorkspaceRoot />}>
          <Route index element={<OverviewPage />} />
          <Route path="documents" element={<DocumentsPage />} />
          <Route path="retrieval" element={<RetrievalPage />} />
          <Route path="chat" element={<ChatPage />} />
          <Route path="logs" element={<LogsPage />} />
          <Route path="ops" element={<OpsPage />} />
          <Route path="sop" element={<SopPage />} />
          <Route path="admin" element={<RequireAuth allowedRoles={['sys_admin']} embedded />}>
            <Route index element={<AdminPage />} />
          </Route>
        </Route>
      </Route>

      <Route path="documents" element={<Navigate to="/workspace/documents" replace />} />
      <Route path="retrieval" element={<Navigate to="/workspace/retrieval" replace />} />
      <Route path="chat" element={<Navigate to="/workspace/chat" replace />} />
      <Route path="logs" element={<Navigate to="/workspace/logs" replace />} />
      <Route path="ops" element={<Navigate to="/workspace/ops" replace />} />
      <Route path="sop" element={<Navigate to="/portal/sop" replace />} />
      <Route path="admin" element={<Navigate to="/workspace/admin" replace />} />
      <Route path="*" element={<RootRedirect />} />
    </Routes>
  );
}
