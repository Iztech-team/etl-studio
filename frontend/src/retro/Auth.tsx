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
		role: "USER · ONLINE",
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

	const logout = () => setUser(null);

	return (
		<AuthContext.Provider value={{ user, login, logout }}>
			{children}
		</AuthContext.Provider>
	);
}

export function useAuth() {
	const ctx = useContext(AuthContext);
	if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
	return ctx;
}

export function LoginScreen() {
	const { login } = useAuth();
	const [username, setUsername] = useState("");
	const [password, setPassword] = useState("");
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
					<div className="rl-login-sub">ETL · SIGN IN</div>
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
					Enter credentials to access the legacy migration system.
				</div>

				<form onSubmit={submitLogin} noValidate>
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
							autoComplete="current-password"
							value={password}
							onChange={(e) => {
								setPassword(e.target.value);
								setError(null);
							}}
							placeholder="•••••••••••"
						/>
					</div>

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
						{loading ? "..." : "SIGN IN"} <IArrow size={10} />
					</button>
				</form>

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
