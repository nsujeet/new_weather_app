import { useState } from "react";

const inputStyle: React.CSSProperties = {
  width: "100%", padding: "9px 12px", borderRadius: 8, boxSizing: "border-box",
  border: "1px solid var(--wa-border)", background: "var(--wa-bg)",
  color: "var(--wa-text)", fontSize: 13, outline: "none",
};

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18">
      <path fill="#4285F4" d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844a4.14 4.14 0 0 1-1.796 2.716v2.259h2.908c1.702-1.567 2.684-3.875 2.684-6.615z"/>
      <path fill="#34A853" d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 0 0 9 18z"/>
      <path fill="#FBBC05" d="M3.964 10.71A5.41 5.41 0 0 1 3.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 8.996 0 0 0 0 9c0 1.452.348 2.827.957 4.042l3.007-2.332z"/>
      <path fill="#EA4335" d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 0 0 .957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z"/>
    </svg>
  );
}

interface Props {
  apiBase: string;
  onLogin: (email: string) => void;
}

export default function LoginScreen({ apiBase, onLogin }: Props) {
  const [email,    setEmail]    = useState("");
  const [password, setPassword] = useState("");
  const [error,    setError]    = useState("");
  const [loading,  setLoading]  = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const r = await fetch(`${apiBase}/auth/password-login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ email: email.trim(), password }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        setError(d.detail ?? "Invalid email or password");
      } else {
        onLogin(email.trim().toLowerCase());
      }
    } catch {
      setError("Connection error. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ height: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "var(--wa-bg)" }}>
      <div style={{ width: 360, padding: "40px 36px", background: "var(--wa-surface)", border: "1px solid var(--wa-border)", borderRadius: 12 }}>

        <h1 style={{ fontSize: 20, fontWeight: 700, color: "var(--wa-text)", margin: "0 0 6px", textAlign: "center" }}>
          Weather Analysis
        </h1>
        <p style={{ fontSize: 12, color: "var(--wa-text-dim)", textAlign: "center", margin: "0 0 28px" }}>
          Sign in to continue
        </p>

        <a
          href={`${apiBase}/auth/login`}
          style={{
            display: "flex", alignItems: "center", justifyContent: "center", gap: 10,
            padding: "10px 0", borderRadius: 8, marginBottom: 20,
            border: "1px solid var(--wa-border-2)", background: "var(--wa-surface-2)",
            color: "var(--wa-text)", fontSize: 13, fontWeight: 500, textDecoration: "none",
            transition: "border-color 0.15s",
          }}
          onMouseEnter={e => (e.currentTarget.style.borderColor = "var(--wa-accent)")}
          onMouseLeave={e => (e.currentTarget.style.borderColor = "var(--wa-border-2)")}
        >
          <GoogleIcon />
          Continue with Google
        </a>

        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 20 }}>
          <div style={{ flex: 1, height: 1, background: "var(--wa-border)" }} />
          <span style={{ fontSize: 11, color: "var(--wa-text-muted)" }}>or</span>
          <div style={{ flex: 1, height: 1, background: "var(--wa-border)" }} />
        </div>

        <form onSubmit={handleSubmit}>
          <input
            type="email" placeholder="Email" value={email} required autoComplete="email"
            onChange={e => setEmail(e.target.value)}
            style={inputStyle}
          />
          <input
            type="password" placeholder="Password" value={password} required autoComplete="current-password"
            onChange={e => setPassword(e.target.value)}
            style={{ ...inputStyle, marginTop: 10 }}
          />
          {error && (
            <p style={{ fontSize: 12, color: "#f87171", margin: "8px 0 0" }}>{error}</p>
          )}
          <button
            type="submit" disabled={loading}
            style={{
              width: "100%", padding: "10px 0", marginTop: 16, borderRadius: 8,
              background: "var(--wa-accent)", border: "none",
              color: "#fff", fontSize: 13, fontWeight: 600,
              cursor: loading ? "not-allowed" : "pointer", opacity: loading ? 0.7 : 1,
            }}
          >
            {loading ? "Signing in…" : "Sign in"}
          </button>
        </form>

      </div>
    </div>
  );
}
