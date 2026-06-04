import { Link, useLocation } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";

export default function NavBar() {
  const { user, logout } = useAuth();
  const loc = useLocation();

  const navLink = (to: string, label: string) => (
    <Link
      to={to}
      className={`rounded px-3 py-1.5 text-sm ${
        loc.pathname === to
          ? "bg-gray-100 font-medium text-gray-900"
          : "text-gray-600 hover:bg-gray-100"
      }`}
    >
      {label}
    </Link>
  );

  return (
    <header className="flex items-center justify-between border-b bg-white px-4 py-2">
      <div className="flex items-center gap-3">
        <span className="font-semibold">Chatbot Console</span>
        <nav className="flex gap-1">
          {navLink("/", "Chat")}
          {user?.role === "admin" && navLink("/admin", "Admin")}
        </nav>
      </div>
      <div className="flex items-center gap-3 text-sm text-gray-500">
        <span>
          {user?.email} · {user?.role}
        </span>
        <button
          onClick={logout}
          className="rounded px-2 py-1 text-gray-600 hover:bg-gray-100"
        >
          Log out
        </button>
      </div>
    </header>
  );
}
