import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import Sidebar from "./components/Sidebar.jsx";
import Topbar from "./components/Topbar.jsx";
import { useAuth } from "./hooks/useAuth.js";
import Admin from "./pages/Admin.jsx";
import Agents from "./pages/Agents.jsx";
import Approvals from "./pages/Approvals.jsx";
import Chat from "./pages/Chat.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Lineage from "./pages/Lineage.jsx";
import Login from "./pages/Login.jsx";
import Monitoring from "./pages/Monitoring.jsx";
import Pipelines from "./pages/Pipelines.jsx";
import Signup from "./pages/Signup.jsx";
import Upload from "./pages/Upload.jsx";

const titles = { "/": "Dashboard", "/pipelines": "Pipelines", "/agents": "Agents", "/chat": "Aegis Chat", "/approvals": "Approvals", "/lineage": "Lineage", "/upload": "Upload Dataset", "/monitoring": "Monitoring", "/admin": "Admin" };

function Protected({ children, adminOnly = false }) {
  const { isAuthenticated, isAdmin, loading } = useAuth();
  if (loading) return <div className="flex min-h-screen items-center justify-center text-aegis-muted">Loading Aegis session...</div>;
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  if (adminOnly && !isAdmin) return <Navigate to="/" replace />;
  return children;
}

function PublicOnly({ children }) {
  const { isAuthenticated, loading } = useAuth();
  if (loading) return <div className="flex min-h-screen items-center justify-center text-aegis-muted">Loading Aegis session...</div>;
  if (isAuthenticated) return <Navigate to="/" replace />;
  return children;
}

function Shell({ children }) {
  const location = useLocation();
  return (
    <div className="min-h-screen">
      <Sidebar />
      <div className="xl:pl-[260px]">
        <Topbar title={titles[location.pathname] || "Aegis AI"} />
        <main className="mx-auto max-w-[1600px] px-4 py-6 md:px-6">{children}</main>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<PublicOnly><Login /></PublicOnly>} />
      <Route path="/signup" element={<PublicOnly><Signup /></PublicOnly>} />
      <Route path="/" element={<Protected><Shell><Dashboard /></Shell></Protected>} />
      <Route path="/pipelines" element={<Protected><Shell><Pipelines /></Shell></Protected>} />
      <Route path="/agents" element={<Protected><Shell><Agents /></Shell></Protected>} />
      <Route path="/chat" element={<Protected><Shell><Chat /></Shell></Protected>} />
      <Route path="/approvals" element={<Protected><Shell><Approvals /></Shell></Protected>} />
      <Route path="/lineage" element={<Protected><Shell><Lineage /></Shell></Protected>} />
      <Route path="/upload" element={<Protected><Shell><Upload /></Shell></Protected>} />
      <Route path="/monitoring" element={<Protected><Shell><Monitoring /></Shell></Protected>} />
      <Route path="/admin" element={<Protected adminOnly><Shell><Admin /></Shell></Protected>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
