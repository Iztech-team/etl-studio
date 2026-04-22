import {
	createContext,
	useContext,
	useEffect,
	useState,
	type ReactNode,
	type FormEvent,
} from "react";
import { IArrow } from "./icons";
import { SpriteMonitor, Sparkles } from "./Sprites";

export type AuthUser = {
	username: string;
	displayName: string;
	initials: string;
	role: string;
};

type AuthState = {
	user: AuthUser | null;
	login: (username: string, password: string) => Promise<boolean>;
	register: (
		username: string,
		password: string,
		displayName: string,
	) => Promise<string | null>;
	loginAsGuest: () => void;
	logout: () => void;
};

const LS_AUTH = "retro-legacy.v2.auth";

function makeAuthUser(data: {
	username: string;
	display_name: string;
}): AuthUser {
	const dn = data.display_name || data.username;
	return {
		username: data.username,
		displayName: dn.toUpperCase(),
		initials: dn.slice(0, 2).toUpperCase(),
		role: data.username === "__guest__" ? "GUEST · SESSION" : "USER · ONLINE",
	};
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
	const [user, setUser] = useState<AuthUser | null>(() => {
		try {
			const raw = localStorage.getItem(LS_AUTH);
			if (!raw) return null;
			return JSON.parse(raw) as AuthUser;
		} catch {
			return null;
		}
	});

	useEffect(() => {
		if (user) localStorage.setItem(LS_AUTH, JSON.stringify(user));
		else localStorage.removeItem(LS_AUTH);
	}, [user]);

	const login = async (
		username: string,
		password: string,
	): Promise<boolean> => {
		try {
			const res = await fetch("/api/auth/login", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ username, password }),
			});
			if (!res.ok) return false;
			const data = await res.json();
			setUser(makeAuthUser(data));
			return true;
		} catch {
			return false;
		}
	};

	const register = async (
		username: string,
		password: string,
		displayName: string,
	): Promise<string | null> => {
		try {
			const res = await fetch("/api/auth/register", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({
					username,
					password,
					display_name: displayName,
				}),
			});
			if (!res.ok) {
				const err = await res.json().catch(() => null);
				return err?.detail || "Registration failed";
			}
			const data = await res.json();
			setUser(makeAuthUser(data));
			return null;
		} catch {
			return "Network error";
		}
	};

	const loginAsGuest = () => {
		setUser(
			makeAuthUser({ username: "__guest__", display_name: "GUEST" }),
		);
	};

	const logout = () => setUser(null);

	return (
		<AuthContext.Provider value={{ user, login, register, loginAsGuest, logout }}>
			{children}
		</AuthContext.Provider>
	);
}

export function useAuth() {
	const ctx = useContext(AuthContext);
	if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
	return ctx;
}

type Mode = "login" | "register";

export function LoginScreen() {
	const { login, register, loginAsGuest } = useAuth();
	const [mode, setMode] = useState<Mode>("login");
	const [username, setUsername] = useState("");
	const [password, setPassword] = useState("");
	const [displayName, setDisplayName] = useState("");
	const [error, setError] = useState<string | null>(null);
	const [loading, setLoading] = useState(false);
	const [shakeKey, setShakeKey] = useState(0);

	const shake = (msg: string) => {
		setError(msg);
		setShakeKey((k) => k + 1);
	};

	const submitLogin = async (e: FormEvent) => {
		e.preventDefault();
		if (!username.trim() || !password.trim()) return;
		setLoading(true);
		setError(null);
		const ok = await login(username, password);
		setLoading(false);
		if (!ok) shake("ACCESS DENIED · CHECK CREDENTIALS");
	};

	const submitRegister = async (e: FormEvent) => {
		e.preventDefault();
		if (!username.trim() || !password.trim()) return;
		setLoading(true);
		setError(null);
		const err = await register(
			username,
			password,
			displayName || username,
		);
		setLoading(false);
		if (err) shake(err.toUpperCase());
	};

	return (
		<div className="legacy-app rl-login-shell">
			<div className="rl-login-card corners">
				<div className="corner-tl" />
				<div className="corner-tr" />
				<div className="corner-bl" />
				<div className="corner-br" />
				<Sparkles />
				<div className="rl-login-mascot">
					<SpriteMonitor size={80} />
				</div>
				<div className="rl-login-head">
					<div className="pixel rl-login-brand">LEGACY</div>
					<div className="rl-login-sub">
						ETL · {mode === "login" ? "SIGN IN" : "REGISTER"}
					</div>
				</div>
				<div
					className="mono"
					style={{
						fontSize: 11,
						color: "var(--lg-ink-mute)",
						marginBottom: 20,
						lineHeight: 1.7,
					}}
				>
					{mode === "login"
						? "Enter credentials to access the legacy migration system."
						: "Create an account to save and manage your projects."}
				</div>

				<form
					onSubmit={mode === "login" ? submitLogin : submitRegister}
					noValidate
				>
					<div className="rl-login-field">
						<label htmlFor="rl-user">USERNAME</label>
						<input
							id="rl-user"
							className="input"
							autoFocus
							autoComplete="username"
							value={username}
							onChange={(e) => {
								setUsername(e.target.value);
								setError(null);
							}}
							placeholder="username"
						/>
					</div>
					<div className="rl-login-field">
						<label htmlFor="rl-pass">PASSWORD</label>
						<input
							id="rl-pass"
							className="input"
							type="password"
							autoComplete={
								mode === "login" ? "current-password" : "new-password"
							}
							value={password}
							onChange={(e) => {
								setPassword(e.target.value);
								setError(null);
							}}
							placeholder="•••••••••••"
						/>
					</div>

					{mode === "register" && (
						<div className="rl-login-field">
							<label htmlFor="rl-display">
								DISPLAY NAME{" "}
								<span style={{ opacity: 0.5, fontSize: 9 }}>(OPTIONAL)</span>
							</label>
							<input
								id="rl-display"
								className="input"
								autoComplete="off"
								value={displayName}
								onChange={(e) => setDisplayName(e.target.value)}
								placeholder="how you want to be shown"
							/>
						</div>
					)}

					{error && (
						<div key={shakeKey} className="rl-login-error">
							{"> "} {error}
						</div>
					)}

					<button
						type="submit"
						className="btn btn-primary"
						disabled={loading}
						style={{ width: "100%", justifyContent: "center", marginTop: 10 }}
					>
						{loading
							? "..."
							: mode === "login"
								? "SIGN IN"
								: "CREATE ACCOUNT"}{" "}
						<IArrow size={10} />
					</button>
				</form>

				<div
					style={{
						display: "flex",
						justifyContent: "space-between",
						alignItems: "center",
						marginTop: 14,
					}}
				>
					<button
						type="button"
						className="link"
						style={{ fontSize: 10 }}
						onClick={() => {
							setMode(mode === "login" ? "register" : "login");
							setError(null);
						}}
					>
						{mode === "login"
							? "NO ACCOUNT? REGISTER"
							: "ALREADY REGISTERED? SIGN IN"}
					</button>
					<button
						type="button"
						className="link"
						style={{ fontSize: 10 }}
						onClick={loginAsGuest}
					>
						GUEST SESSION →
					</button>
				</div>

				<div
					className="pixel"
					style={{
						fontSize: 8,
						color: "var(--lg-ink-faint)",
						letterSpacing: "0.15em",
						marginTop: 20,
						textAlign: "center",
					}}
				>
					[ TERMINAL · LEGACY MIGRATION CONSOLE · v1 ]
				</div>
			</div>
		</div>
	);
}
