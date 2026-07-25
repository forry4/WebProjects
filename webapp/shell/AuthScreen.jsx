/* The site's sign-in / register / guest screen.
 *
 * FIRST PIECE OF THE SHELL/GAME SPLIT. games/spender/Spender.jsx is both the site
 * shell (auth, home menu, routing to every game, Books, Puzzles) and Spender's own
 * game UI, in ONE component with 58 useState hooks. Auth is the cleanest seam in it:
 * six of those hooks (tab, name, password, guest name, error, loading) are touched by
 * nothing else in the file, and the screen's only outward effect is "a user was
 * authenticated". So it lifts out whole, with a one-callback interface.
 *
 * It lives under webapp/shell/ rather than games/spender/ deliberately: the shell is
 * not part of the Spender game, and every screen moved here is one the eventual
 * inversion (shell owns routing, each game is a sibling) no longer has to untangle.
 *
 * Owns only its own form state. It does NOT know about localStorage, routing, or the
 * session — the shell still owns identity, and `onAuthenticated(user)` hands it back.
 */
import { useState } from "react";

export default function AuthScreen({ siteName, httpBase, css, myId, onAuthenticated }) {
	const [tab, setTab] = useState("login");
	const [name, setName] = useState("");
	const [password, setPassword] = useState("");
	const [guestName, setGuestName] = useState("");
	const [error, setError] = useState("");
	const [loading, setLoading] = useState(false);

	const submit = async () => {
		if (!name.trim() || !password.trim()) {
			setError("Name and password required");
			return;
		}
		setError("");
		setLoading(true);
		try {
			const endpoint = tab === "login" ? "/auth/login" : "/auth/register";
			const res = await fetch(`${httpBase}${endpoint}`, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ name: name.trim(), password: password.trim() }),
			});
			const data = await res.json();
			if (data.ok) {
				onAuthenticated({
					id: data.user.id,
					name: data.user.name,
					is_admin: !!data.user.is_admin,
					session_token: data.session_token || null,
				});
			} else {
				// The backend returns HTTP 200 with ok:false for a rate-limited attempt
				// too, so this one branch covers bad credentials AND the throttle message.
				setError(data.message || "Something went wrong");
			}
		} catch {
			setError("Could not reach server");
		}
		setLoading(false);
	};

	const playAsGuest = () => {
		// A guest keeps the shell's existing anonymous id, so a game started before
		// signing in stays theirs.
		onAuthenticated({
			id: myId,
			name: guestName.trim() || `Guest${Math.floor(Math.random() * 9000 + 1000)}`,
			guest: true,
		});
	};

	return (
		<>
			<style>{css}</style>
			<div className="app auth-screen">
				<div className="auth-logo">{siteName}</div>
				<p className="auth-tagline">A collection of tabletop games</p>

				<div className="auth-card">
					<div className="auth-tabs">
						{["login", "register", "guest"].map(t => (
							<button key={t} className={`auth-tab${tab === t ? " active" : ""}`}
								onClick={() => { setTab(t); setError(""); }}>
								{t === "login" ? "Sign In" : t === "register" ? "Register" : "Guest"}
							</button>
						))}
					</div>

					{tab !== "guest" ? (
						<>
							{/* maxLength mirrors core.auth.validate_credentials: register is
							    capped at 16, login accepts longer legacy values. */}
							<input className="auth-field" placeholder="Name" value={name}
								onChange={e => setName(e.target.value)} maxLength={tab === "register" ? 16 : 64}
								onKeyDown={e => e.key === "Enter" && submit()} />
							<input className="auth-field" placeholder="Password" type="password" value={password}
								onChange={e => setPassword(e.target.value)} maxLength={tab === "register" ? 16 : 128}
								onKeyDown={e => e.key === "Enter" && submit()} />
							{error && <div className="auth-error">{error}</div>}
							<button className="btn btn-gold btn-full mt-8" onClick={submit} disabled={loading}>
								{loading && <span className="spinner" />}
								{tab === "login" ? "Sign In" : "Create Account"}
							</button>
						</>
					) : (
						<>
							<p style={{ color: "var(--text-dim)", fontSize: ".88rem", marginBottom: 14, lineHeight: 1.5 }}>
								Play without an account. Your game history won't be saved.
							</p>
							<div className="guest-name-row">
								<input className="auth-field" placeholder="Display name (optional)"
									value={guestName} onChange={e => setGuestName(e.target.value)} maxLength={20}
									onKeyDown={e => e.key === "Enter" && playAsGuest()} />
							</div>
							<button className="btn btn-outline btn-full mt-8" onClick={playAsGuest}>
								Play as Guest
							</button>
						</>
					)}
				</div>
			</div>
		</>
	);
}
