import { useState } from "react";
import { login, setToken } from "../api.js";
import { Logo } from "../components/Kpi.jsx";
import "../auth.css";

const UNREACHABLE = "Cannot reach the backend. Is it running on port 8000?";

export default function Login({ onSignedIn }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const signIn = event => {
    event.preventDefault();
    setBusy(true);
    setError("");
    login(username.trim().toLowerCase(), password)
      .then(result => {
        setToken(result.token);
        onSignedIn(result.user);
      })
      .catch(err => {
        setError(err instanceof TypeError ? UNREACHABLE : err.message);
        setBusy(false);
      });
  };

  return (
    <div className="login-shell">
      <div className="login-card">
        <div className="login-brand"><Logo size={44} /><span>Arth</span><span>Pulse</span></div>
        <h1>Sign in</h1>
        <p className="subtext">Use the account your administrator created for you.</p>

        {error && <p className="login-error">{error}</p>}

        <form onSubmit={signIn}>
          <label className="field">
            <span>USERNAME</span>
            <input value={username} onChange={e => setUsername(e.target.value)} autoComplete="username" autoFocus />
          </label>
          <label className="field">
            <span>PASSWORD</span>
            <input type="password" value={password} onChange={e => setPassword(e.target.value)} autoComplete="current-password" />
          </label>
          <button className="primary-button" type="submit" disabled={busy || !username || !password}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <p className="rule-law" style={{ marginTop: 16 }}>Forgot your password? Ask an administrator to reset it.</p>
      </div>
    </div>
  );
}