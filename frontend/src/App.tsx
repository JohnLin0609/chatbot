import { Navigate, Route, Routes } from "react-router-dom";

import { useAuth } from "./auth/AuthContext";
import { AdminRoute, ProtectedRoute } from "./routes/ProtectedRoute";
import LoginPage from "./pages/LoginPage";
import RegisterPage from "./pages/RegisterPage";
import ChatPage from "./pages/ChatPage";
import AdminPage from "./pages/AdminPage";
import SystemPromptPage from "./pages/SystemPromptPage";
import GoldenPage from "./pages/GoldenPage";
import DashboardPage from "./pages/DashboardPage";
import TracesPage from "./pages/TracesPage";
import TraceDetailPage from "./pages/TraceDetailPage";

export default function App() {
  const { loading } = useAuth();
  if (loading) {
    return (
      <div className="flex h-full items-center justify-center text-gray-400">
        Loading…
      </div>
    );
  }
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <ChatPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/admin"
        element={
          <AdminRoute>
            <AdminPage />
          </AdminRoute>
        }
      />
      <Route
        path="/admin/system-prompt"
        element={
          <AdminRoute>
            <SystemPromptPage />
          </AdminRoute>
        }
      />
      <Route
        path="/admin/golden"
        element={
          <AdminRoute>
            <GoldenPage />
          </AdminRoute>
        }
      />
      <Route
        path="/admin/dashboard"
        element={
          <AdminRoute>
            <DashboardPage />
          </AdminRoute>
        }
      />
      <Route
        path="/admin/eval/traces"
        element={
          <AdminRoute>
            <TracesPage />
          </AdminRoute>
        }
      />
      <Route
        path="/admin/eval/traces/:id"
        element={
          <AdminRoute>
            <TraceDetailPage />
          </AdminRoute>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
