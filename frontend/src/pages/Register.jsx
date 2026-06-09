import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { useAuth } from "../context/AuthContext";
import { ApiError } from "../lib/api";
import { AuthShell, Input } from "./Login";

export default function Register() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({
    email: "",
    password: "",
    full_name: "",
    phone: "",
    role: "rider",
  });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const set = (key) => (value) => setForm((f) => ({ ...f, [key]: value }));

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await register({
        email: form.email,
        password: form.password,
        full_name: form.full_name,
        phone: form.phone || null,
        role: form.role,
      });
      navigate("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Registration failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthShell title="Create your account">
      <form onSubmit={submit} className="space-y-3">
        <Input label="Full name" value={form.full_name} onChange={set("full_name")} />
        <Input label="Email" type="email" value={form.email} onChange={set("email")} />
        <Input label="Password (min 8 chars)" type="password" value={form.password} onChange={set("password")} />
        <Input label="Phone (optional)" value={form.phone} onChange={set("phone")} />
        <label className="block text-sm">
          <span className="text-gray-600">I want to</span>
          <select
            value={form.role}
            onChange={(e) => set("role")(e.target.value)}
            className="mt-1 w-full rounded border px-3 py-2"
          >
            <option value="rider">Ride (rider)</option>
            <option value="driver">Drive (driver)</option>
          </select>
        </label>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-lg bg-black px-4 py-2.5 font-medium text-white disabled:opacity-40"
        >
          {busy ? "Creating…" : "Create account"}
        </button>
      </form>
      <p className="mt-4 text-sm text-gray-600">
        Already have an account?{" "}
        <Link to="/login" className="font-medium underline">
          Sign in
        </Link>
      </p>
    </AuthShell>
  );
}
