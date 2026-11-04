import { useCallback, useEffect, useState } from "react";
import PageHeading from "../components/PageHeading.jsx";
import { getJson, sendJson } from "../api.js";
import "../auth.css";

// Roles an administrator may hand out. Owner and Administrator are not offered.
const ASSIGNABLE = ["sales_manager", "purchase_manager", "inventory_manager", "finance"];
const ROLE_NAMES = { finance: "Finance Manager" };

export default function Access({ user, notify, onUserChanged }) {
  const [info, setInfo] = useState(null);
  const [loadError, setLoadError] = useState("");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState("");
  const [form, setForm] = useState({ full_name: "", username: "", role: "", password: "" });
  const [resetFor, setResetFor] = useState(null);
  const [newPassword, setNewPassword] = useState("");
  const [roleFor, setRoleFor] = useState(null);
  const [newRole, setNewRole] = useState("");
  const [sync, setSync] = useState(null);

  const load = useCallback(
    () => {
      getJson("/api/auth/roles").then(setInfo).catch(err => setLoadError(err.message));
      getJson("/api/sync/status").then(setSync).catch(() => {});
    }, []);
  useEffect(() => { load(); }, [load]);

  const roleName = r => ROLE_NAMES[r.id] || r.label;
  const assignable = () => (info ? info.roles.filter(r => ASSIGNABLE.includes(r.id)) : []);
  const roleLabel = id => { const r = info.roles.find(x => x.id === id); return r ? roleName(r) : id; };

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
      await sendJson("POST", "/api/users", { ...form, role: form.role || assignable()[0].id });
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
            <p className="card-label">TALLYPRIME</p>
            <h2>Demo company sync</h2>
            <p className="subtext">
              Presentation data is the full synthetic set. TallyPrime Educational only allows voucher dates
              1, 2 and 31 — push that subset into your open demo company, then click Sync TallyPrime.
            </p>
            {sync && (
              <ul className="note-list">
                <li>Gateway {sync.url}: {sync.reachable ? "reachable" : "not running"}</li>
                <li>Last sync: {sync.last ? `${sync.last.source} · ${sync.last.status} · ${sync.last.finished_at || sync.last.message}` : "never"}</li>
                <li>{sync.educational_note}</li>
                {sync.companies?.length > 0 && <li>Companies Tally reported: {sync.companies.join(", ")}</li>}
              </ul>
            )}
            <div className="report-actions" style={{ marginTop: 12 }}>
              <button className="secondary-button" disabled={busy} onClick={() => act(
                () => sendJson("POST", "/api/sync/push-educational", {}),
                "Educational vouchers sent to the open Tally company (dates 1, 2, 31)."
              )}>Push educational data into Tally</button>
              <button className="primary-button" disabled={busy} onClick={async () => {
                const ok = await act(() => sendJson("POST", "/api/sync/tally", {}),
                  "Fetched the open TallyPrime company into ArthPulse.");
                if (ok) window.location.reload();
              }}>Sync TallyPrime</button>
              <button className="secondary-button" disabled={busy} onClick={async () => {
                const ok = await act(() => sendJson("POST", "/api/sync/synthetic", {}),
                  "Reloaded the full synthetic presentation set.");
                if (ok) window.location.reload();
              }}>Reload synthetic demo</button>
            </div>
          </article>

          <article className="card" style={{ marginBottom: 18 }}>
            <p className="card-label">ADD A PERSON</p>
            <h2>New account</h2>
            <form className="user-form" onSubmit={addUser}>
              <label className="field"><span>FULL NAME</span>
                <input value={form.full_name} onChange={set("full_name")} /></label>
              <label className="field"><span>USERNAME</span>
                <input value={form.username} onChange={set("username")} placeholder="e.g. priya.iyer" autoComplete="off" /></label>
              <label className="field"><span>ROLE</span>
                <select value={form.role || assignable()[0].id} onChange={set("role")}>
                  {assignable().map(r => <option key={r.id} value={r.id}>{roleName(r)}</option>)}
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
                        <td>{roleLabel(u.role)}</td>
                        <td><span className={`status ${u.active ? "" : "risk"}`}>{u.active ? "Active" : "Disabled"}</span></td>
                        <td className="row-actions">
                          <button disabled={busy || self} onClick={() => act(
                            () => sendJson("PATCH", `/api/users/${u.username}`, { is_active: !u.active }),
                            `${u.full_name} ${u.active ? "disabled" : "re-enabled"}.`)}>
                            {u.active ? "Disable" : "Enable"}
                          </button>
                          <button disabled={busy} onClick={() => { setResetFor(resetFor === u.username ? null : u.username); setNewPassword(""); setRoleFor(null); }}>
                            Reset password
                          </button>
                          <button disabled={busy || self} title={self ? "You cannot change your own role" : ""}
                                  onClick={() => { setRoleFor(roleFor === u.username ? null : u.username);
                                                   setNewRole(ASSIGNABLE.includes(u.role) ? u.role : ASSIGNABLE[0]); setResetFor(null); }}>
                            Change Role/Job
                          </button>
                          <button className="danger" disabled={busy || self} onClick={() => remove(u)}>Delete</button>
                        </td>
                      </tr>,
                      roleFor === u.username && (
                        <tr key={u.username + "-role"} className="reset-row">
                          <td colSpan={5}>
                            <span>New role for <b>{u.full_name}</b>:</span>
                            <select className="mini-select" value={newRole} onChange={e => setNewRole(e.target.value)}>
                              {assignable().map(r => <option key={r.id} value={r.id}>{roleName(r)}</option>)}
                            </select>
                            <button className="primary-button" disabled={busy || newRole === u.role}
                                    onClick={async () => {
                                      const ok = await act(() => sendJson("PATCH", `/api/users/${u.username}`, { role: newRole }),
                                        `${u.full_name} is now ${roleLabel(newRole)}.`);
                                      if (ok) setRoleFor(null);
                                    }}>Save</button>
                            <button className="secondary-button" onClick={() => setRoleFor(null)}>Cancel</button>
                          </td>
                        </tr>
                      ),
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
              Use “Change Role/Job” to move someone between Sales, Purchase, Inventory and Finance Manager. The person sees the new menu the next time they sign in.
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
                      <td><b>{roleName(role)}</b></td>
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