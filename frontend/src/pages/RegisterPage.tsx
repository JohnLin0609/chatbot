import { type FormEvent, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { AuthShell, Button, Input, Spinner, errorMessage } from "../components/ui";

export default function RegisterPage() {
  const { user, register } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to="/" replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await register(email, password);
      nav("/");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthShell title="Create account">
      <form onSubmit={submit} className="space-y-3">
        <Input type="email" placeholder="Email" value={email}
          onChange={(e) => setEmail(e.target.value)} required />
        <Input type="password" placeholder="Password (min 8 chars)" value={password}
          onChange={(e) => setPassword(e.target.value)} minLength={8} required />
        {error && <p className="text-sm text-red-600">{error}</p>}
        <Button type="submit" disabled={busy} className="w-full">
          {busy ? <Spinner /> : "Register"}
        </Button>
      </form>
      <p className="mt-3 text-center text-xs text-gray-400">
        The first account created becomes the admin.
      </p>
      <p className="mt-2 text-center text-sm text-gray-500">
        Have an account?{" "}
        <Link to="/login" className="text-brand hover:underline">
          Sign in
        </Link>
      </p>
    </AuthShell>
  );
}
