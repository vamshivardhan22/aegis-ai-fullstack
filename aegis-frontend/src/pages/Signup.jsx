import { Eye, EyeOff, Lock, Mail, Shield, User } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useToast } from "../components/Toast.jsx";
import { useAuth } from "../hooks/useAuth.js";

const roles = [
  { label: "Data Engineer", value: "data_engineer" },
  { label: "Analyst", value: "analyst" },
  { label: "Viewer", value: "viewer" }
];

function validate(values) {
  const nextErrors = {};
  if (!values.full_name.trim()) nextErrors.full_name = "Full name is required.";
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(values.email)) nextErrors.email = "Enter a valid email address.";
  if (values.password.length < 8) nextErrors.password = "Password must be at least 8 characters.";
  if (values.confirmPassword !== values.password) nextErrors.confirmPassword = "Passwords must match.";
  return nextErrors;
}

function errorMessage(error) {
  if (error?.response?.status === 409) return "An account with this email already exists.";
  if (error?.response?.status === 422) return "Please check the signup details and try again.";
  return error?.message || "Registration failed. Please try again.";
}

export default function Signup() {
  const [values, setValues] = useState({ full_name: "", email: "", password: "", confirmPassword: "", role: "viewer" });
  const [errors, setErrors] = useState({});
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const { register } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();

  const update = (field) => (event) => {
    setValues((current) => ({ ...current, [field]: event.target.value }));
    setErrors((current) => ({ ...current, [field]: "" }));
  };

  const submit = async (event) => {
    event.preventDefault();
    const nextErrors = validate(values);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;

    setLoading(true);
    const result = await register({
      email: values.email,
      password: values.password,
      full_name: values.full_name.trim(),
      role: values.role
    });
    setLoading(false);

    if (result.success) {
      navigate("/");
      return;
    }
    toast.error(errorMessage(result.error));
  };

  return (
    <main className="flex min-h-screen items-center justify-center px-4 py-8">
      <form onSubmit={submit} className="panel w-full max-w-md p-7">
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-card bg-gradient-to-br from-aegis-blue to-aegis-purple">
            <Shield className="h-7 w-7 text-white" />
          </div>
          <h1 className="bg-gradient-to-r from-aegis-blue to-aegis-purple bg-clip-text text-3xl font-extrabold text-transparent">Aegis AI</h1>
          <p className="mt-2 text-sm text-aegis-muted">Create your account</p>
        </div>

        <label className="mb-4 block">
          <span className="mb-2 block text-sm font-medium text-aegis-muted">Full Name</span>
          <div className="relative">
            <User className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-aegis-muted" />
            <input className="field bg-[#111827] pl-10" type="text" value={values.full_name} onChange={update("full_name")} placeholder="Aegis Operator" />
          </div>
          {errors.full_name ? <p className="mt-2 text-xs text-aegis-red">{errors.full_name}</p> : null}
        </label>

        <label className="mb-4 block">
          <span className="mb-2 block text-sm font-medium text-aegis-muted">Email</span>
          <div className="relative">
            <Mail className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-aegis-muted" />
            <input className="field bg-[#111827] pl-10" type="email" value={values.email} onChange={update("email")} placeholder="operator@aegis.ai" />
          </div>
          {errors.email ? <p className="mt-2 text-xs text-aegis-red">{errors.email}</p> : null}
        </label>

        <label className="mb-4 block">
          <span className="mb-2 block text-sm font-medium text-aegis-muted">Password</span>
          <div className="relative">
            <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-aegis-muted" />
            <input className="field bg-[#111827] pl-10 pr-10" type={showPassword ? "text" : "password"} value={values.password} onChange={update("password")} placeholder="Minimum 8 characters" />
            <button type="button" className="absolute right-3 top-1/2 -translate-y-1/2 text-aegis-muted transition hover:text-white" onClick={() => setShowPassword((current) => !current)} aria-label={showPassword ? "Hide password" : "Show password"}>
              {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
          {errors.password ? <p className="mt-2 text-xs text-aegis-red">{errors.password}</p> : null}
        </label>

        <label className="mb-4 block">
          <span className="mb-2 block text-sm font-medium text-aegis-muted">Confirm Password</span>
          <div className="relative">
            <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-aegis-muted" />
            <input className="field bg-[#111827] pl-10 pr-10" type={showConfirmPassword ? "text" : "password"} value={values.confirmPassword} onChange={update("confirmPassword")} placeholder="Repeat password" />
            <button type="button" className="absolute right-3 top-1/2 -translate-y-1/2 text-aegis-muted transition hover:text-white" onClick={() => setShowConfirmPassword((current) => !current)} aria-label={showConfirmPassword ? "Hide confirm password" : "Show confirm password"}>
              {showConfirmPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
          {errors.confirmPassword ? <p className="mt-2 text-xs text-aegis-red">{errors.confirmPassword}</p> : null}
        </label>

        <label className="mb-6 block">
          <span className="mb-2 block text-sm font-medium text-aegis-muted">Role</span>
          <select className="field bg-[#111827]" value={values.role} onChange={update("role")}>
            {roles.map((role) => <option key={role.value} value={role.value}>{role.label}</option>)}
          </select>
        </label>

        <button className="gradient-button w-full" disabled={loading}>{loading ? "Creating Account..." : "Create Account"}</button>
        <p className="mt-5 text-center text-sm text-aegis-muted">
          Already have an account?{" "}
          <Link to="/login" className="font-semibold text-aegis-blue underline-offset-4 transition hover:text-aegis-purple hover:underline">Sign in</Link>
        </p>
      </form>
    </main>
  );
}
