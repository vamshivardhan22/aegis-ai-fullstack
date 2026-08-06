import { Shield } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth.js";
import { useToast } from "../components/Toast.jsx";

export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const submit = async (event) => {
    event.preventDefault();
    if (!email.includes("@") || password.length < 6) {
      toast.error("Enter a valid email and a password with at least 6 characters.");
      return;
    }
    setLoading(true);
    try {
      await login({ email, password });
      navigate("/");
    } catch {
      toast.error("Invalid credentials or authentication service unavailable.");
    } finally {
      setLoading(false);
    }
  };
  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <form onSubmit={submit} className="panel w-full max-w-md p-7">
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-card bg-gradient-to-br from-aegis-blue to-aegis-purple"><Shield className="h-7 w-7 text-white" /></div>
          <h1 className="bg-gradient-to-r from-aegis-blue to-aegis-purple bg-clip-text text-3xl font-extrabold text-transparent">Aegis AI</h1>
          <p className="mt-2 text-sm text-aegis-muted">Sign in to the v2.0 operations console</p>
        </div>
        <label className="mb-4 block">
          <span className="mb-2 block text-sm font-medium text-aegis-muted">Email</span>
          <input className="field" type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="operator@aegis.ai" />
        </label>
        <label className="mb-6 block">
          <span className="mb-2 block text-sm font-medium text-aegis-muted">Password</span>
          <input className="field" type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="Minimum 6 characters" />
        </label>
        <button className="gradient-button w-full" disabled={loading}>{loading ? "Authenticating..." : "Login"}</button>
        <p className="mt-5 text-center text-sm text-aegis-muted">
          Don&apos;t have an account?{" "}
          <Link to="/signup" className="font-semibold text-aegis-blue underline-offset-4 transition hover:text-aegis-purple hover:underline">Create one</Link>
        </p>
      </form>
    </main>
  );
}
