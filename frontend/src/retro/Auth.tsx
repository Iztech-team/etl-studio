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
	login: (username: string, password: string) => boolean;
	logout: () => void;
};

const LS_AUTH = "retro-legacy.v2.auth";

const ACCOUNTS: Record<
	string,
	{ password: string; user: AuthUser }
> = {
	legacy: {
		password: "$Legacy$2026",
		user: {
			username: "legacy",
			displayName: "SYSOP",
			initials: "SY",
			role: "ROOT · ONLINE",
		},
	},
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
	const [user, setUser] = useState<AuthUser | null>(() => {
		try {
			const raw = localStorage.getItem(LS_AUTH);
			if (!raw) return null;
			const parsed = JSON.parse(raw) as AuthUser;
			if (parsed?.username && ACCOUNTS[parsed.username]) {
				return ACCOUNTS[parsed.username].user;
			}
		} catch {}
		return null;
	});

	useEffect(() => {
		if (user) localStorage.setItem(LS_AUTH, JSON.stringify(user));
		else localStorage.removeItem(LS_AUTH);
	}, [user]);

	const login = (username: string, password: string) => {
		const account = ACCOUNTS[username.trim().toLowerCase()];
		if (account && account.password === password) {
			setUser(account.user);
			return true;
		}
		return false;
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
	const [shakeKey, setShakeKey] = useState(0);

	const submit = (e: FormEvent) => {
		e.preventDefault();
		const ok = login(username, password);
		if (!ok) {
			setError("ACCESS DENIED · CHECK CREDENTIALS");
			setShakeKey((k) => k + 1);
		}
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
					Authorized operators only. Enter credentials to access the legacy
					migration system.
				</div>

				<form onSubmit={submit} noValidate>
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
							placeholder="legacy"
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
						style={{ width: "100%", justifyContent: "center", marginTop: 10 }}
					>
						SIGN IN <IArrow size={10} />
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
