import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("../api/client", () => {
  let token: string | null = null;
  return {
    getToken: () => token,
    setToken: (t: string | null) => {
      token = t;
    },
    setUnauthorizedHandler: () => {},
    me: vi.fn(),
    login: vi.fn(async () => ({
      access_token: "tok",
      token_type: "bearer",
      user: { id: 1, email: "a@x.com", role: "admin" },
    })),
    register: vi.fn(),
  };
});

import { AuthProvider, useAuth } from "./AuthContext";

function Probe() {
  const { user, login, logout } = useAuth();
  return (
    <div>
      <span data-testid="user">{user ? `${user.email}:${user.role}` : "none"}</span>
      <button onClick={() => login("a@x.com", "pw")}>login</button>
      <button onClick={logout}>logout</button>
    </div>
  );
}

it("login stores the user; logout clears it", async () => {
  render(
    <AuthProvider>
      <Probe />
    </AuthProvider>,
  );
  await waitFor(() =>
    expect(screen.getByTestId("user")).toHaveTextContent("none"),
  );

  await userEvent.click(screen.getByText("login"));
  await waitFor(() =>
    expect(screen.getByTestId("user")).toHaveTextContent("a@x.com:admin"),
  );

  await userEvent.click(screen.getByText("logout"));
  expect(screen.getByTestId("user")).toHaveTextContent("none");
});
