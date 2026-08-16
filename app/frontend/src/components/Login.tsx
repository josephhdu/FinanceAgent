import { useState, type FormEvent } from "react";
import { useAuth } from "../auth/AuthContext";

export function Login() {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");

  async function submit(e: FormEvent) {
    e.preventDefault();
    setErr("");
    try {
      const r = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (!r.ok) {
        setErr(r.status === 401 ? "Invalid username or password." : `Error ${r.status}`);
        return;
      }
      const d = await r.json();
      login(d.token, d.username);
    } catch {
      setErr("Connection error.");
    }
  }

  return (
    <div className="overlay">
      <form className="login" onSubmit={submit}>
        <h2>
          Finance<span>AI</span>
        </h2>
        <div className="sub">Sign in to your paper-trading desk</div>
        <input
          placeholder="Username"
          autoComplete="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoFocus
        />
        <input
          type="password"
          placeholder="Password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <div className="err">{err}</div>
        <button type="submit">Sign in</button>
      </form>
    </div>
  );
}
