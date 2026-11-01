import { useCallback, useEffect, useState } from "react";
import PageHeading from "../components/PageHeading.jsx";
import { getJson, sendJson } from "../api.js";
import "../auth.css";

export default function Access({ user, notify, onUserChanged }) {
  const [info, setInfo] = useState(null);
  const [loadError, setLoadError] = useState("");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState("");
  const [form, setForm] = useState({ full_name: "", username: "", role: "", password: "" });
  const [resetFor, setResetFor] = useState(null);
  const [newPassword, setNewPassword] = useState("");

  const load = useCallback(
    () => getJson("/api/auth/roles").then(setInfo).catch(err => setLoadError(err.message)), []);
  useEffect(() => { load(); }, [load]);

  const set = key => event => setForm(f => ({ ...f, [key]: event.target.value }));

  // runs an admin action, then refreshes the list; errors are shown, not thrown
  const act = async (action, successMessage) => {
    setBusy(true);
    try {
      await action();
      notify(successMessage);
      await load();
      return true;
    } catch (err) {
      notify(err.message);
      return false;
    } finally {
      setBusy(false);
    }
  };

  const addUser = async event => {
    event.preventDefault();
    setFormError("");
    setBusy(true);
    try {
      await sendJson("POST", "/api/users", { ...form, role: form.role || info.roles[0].id });
      notify(`Account created for ${form.full_name}.`);
      setForm({ full_name: "", username: "", role: form.role, password: "" });
      await load();
    } catch (err) {
      setFormError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const savePassword = async username => {
    const ok = await act(() => sendJson("POST", `/api/users/${username}/password`, { password: newPassword }),
      `Password reset for ${username}.`);
    if (ok) {
      setResetFor(null);
      setNewPassword("");
      if (username === user.username) onUserChanged?.();   // clears the default-password warning
    }
  };

  const remove = u => {
    if (window.confirm(`Delete the account for ${u.full_name} (${u.username})? This cannot be undone.`)) {
      act(() => sendJson("DELETE", `/api/users/${u.username}`), `${u.full_name} was deleted.`);
    }
  };

  return (
    <section className="page active">
      <PageHeading
        eyebrow="ADMINISTRATION / ACCESS CONTROL"
        title="People and permissions"
        subtext="Add accounts, choose each person's role, and see exactly what every role can open."
      />

      {loadError && <div className="state-banner error"><span>{loadError}</span></div>}
      {!info && !loadError && <div className="state-banner loading">Loading…</div>}

      {info && (
        <>
          <article className="card" style={{ marginBottom: 18 }}>
            <p className="card-label">ADD A PERSON</p>
            <h2>New account</h2>
            <form className="user-form" onSubmit={addUser}>
              <label className="field"><span>FULL NAME</span>
                <input value={form.full_name} onChange={set("full_name")} /></label>
              <label className="field"><span>USERNAME</span>
                <input value={form.username} onChange={set("username")} placeholder="e.g. priya.iyer" autoComplete="off" /></label>
              <label className="field"><span>ROLE</span>
                <select value={form.role || info.roles[0].id} onChange={set("role")}>
                  {info.roles.map(r => <option key={r.id} value={r.id}>{r.label}</option>)}
                </select></label>
              <label className="field"><span>TEMPORARY PASSWORD (8+ CHARACTERS)</span>
                <input type="password" value={form.password} onChange={set("password")} autoComplete="new-password" /></label>
              <button className="primary-button" type="submit"
                      disabled={busy || !form.full_name || !form.username || !form.password}>
                Create account
              </button>
            </form>
            {formError && <p className="login-error" style={{ marginTop: 12 }}>{formError}</p>}
          </article>

          <article className="card" style={{ marginBottom: 18 }}>
            <p className="card-label">ACCOUNTS</p>
            <h2>Everyone who can sign in ({info.users.length})</h2>
            <div className="table-scroll" style={{ marginTop: 14 }}>
              <table>
                <thead><tr><th>Name</th><th>Username</th><th>Role</th><th>Status</th><th>Actions</th></tr></thead>
                <tbody>
                  {info.users.map(u => {
                    const self = u.username === user.username;
                    return [
                      <tr key={u.username}>
                        <td><b>{u.full_name}</b>{self && <span className="you">you</span>}</td>
                        <td>{u.username}</td>
                        <td>
                          <select className="mini-select" value={u.role} disabled={busy || self}
                                  title={self ? "You cannot change your own role" : ""}
                                  onChange={e => act(() => sendJson("PATCH", `/api/users/${u.username}`, { role: e.target.value }),
                                                    `${u.full_name} is now ${info.roles.find(r => r.id === e.target.value).label}.`)}>
                            {info.roles.map(r => <option key={r.id} value={r.id}>{r.label}</option>)}
                          </select>
                        </td>
                        <td><span className={`status ${u.active ? "" : "risk"}`}>{u.active ? "Active" : "Disabled"}</span></td>
                        <td className="row-actions">
                          <button disabled={busy || self} onClick={() => act(
                            () => sendJson("PATCH", `/api/users/${u.username}`, { is_active: !u.active }),
                            `${u.full_name} ${u.active ? "disabled" : "re-enabled"}.`)}>
                            {u.active ? "Disable" : "Enable"}
                          </button>
                          <button disabled={busy} onClick={() => { setResetFor(resetFor === u.username ? null : u.username); setNewPassword(""); }}>
                            Reset password
                          </button>
                          <button className="danger" disabled={busy || self} onClick={() => remove(u)}>Delete</button>
                        </td>
                      </tr>,
                      resetFor === u.username && (
                        <tr key={u.username + "-reset"} className="reset-row">
                          <td colSpan={5}>
                            <span>New password for <b>{u.full_name}</b>:</span>
                            <input type="password" value={newPassword} onChange={e => setNewPassword(e.target.value)}
                                   placeholder="8+ characters" autoComplete="new-password" />
                            <button className="primary-button" disabled={busy || !newPassword} onClick={() => savePassword(u.username)}>Save</button>
                            <button className="secondary-button" onClick={() => setResetFor(null)}>Cancel</button>
                          </td>
                        </tr>
                      ),
                    ];
                  })}
                </tbody>
              </table>
            </div>
            <p className="rule-law" style={{ marginTop: 12 }}>
              You cannot change, disable or delete your own account — another administrator has to do that.
              Role changes apply to the server immediately; the person sees the new menu the next time they sign in.
            </p>
          </article>

          <article className="card">
            <p className="card-label">PERMISSION MATRIX</p>
            <h2>What each role can open</h2>
            <div className="table-scroll" style={{ marginTop: 14 }}>
              <table className="matrix">
                <thead><tr><th>Role</th>{info.areas.map(a => <th key={a.id}>{a.label}</th>)}</tr></thead>
                <tbody>
                  {info.roles.map(role => (
                    <tr key={role.id}>
                      <td><b>{role.label}</b></td>
                      {info.areas.map(a => (
                        <td key={a.id}>{role.areas.includes(a.id) ? <span className="yes">✓</span> : <span className="no">–</span>}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </article>
        </>
      )}
    </section>
  );
}