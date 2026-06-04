import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

const { mockAuth } = vi.hoisted(() => ({ mockAuth: vi.fn() }));
vi.mock("../auth/AuthContext", () => ({ useAuth: () => mockAuth() }));

import { AdminRoute, ProtectedRoute } from "./ProtectedRoute";

function renderAdmin(node: React.ReactNode) {
  return render(
    <MemoryRouter initialEntries={["/admin"]}>
      <Routes>
        <Route path="/login" element={<div>login page</div>} />
        <Route path="/" element={<div>home</div>} />
        <Route path="/admin" element={node} />
      </Routes>
    </MemoryRouter>,
  );
}

it("ProtectedRoute redirects unauthenticated to /login", () => {
  mockAuth.mockReturnValue({ user: null });
  renderAdmin(
    <ProtectedRoute>
      <div>secret</div>
    </ProtectedRoute>,
  );
  expect(screen.getByText("login page")).toBeInTheDocument();
});

it("AdminRoute sends a non-admin home", () => {
  mockAuth.mockReturnValue({ user: { id: 1, email: "u@x.com", role: "user" } });
  renderAdmin(
    <AdminRoute>
      <div>admin area</div>
    </AdminRoute>,
  );
  expect(screen.getByText("home")).toBeInTheDocument();
});

it("AdminRoute allows an admin", () => {
  mockAuth.mockReturnValue({ user: { id: 1, email: "a@x.com", role: "admin" } });
  renderAdmin(
    <AdminRoute>
      <div>admin area</div>
    </AdminRoute>,
  );
  expect(screen.getByText("admin area")).toBeInTheDocument();
});
