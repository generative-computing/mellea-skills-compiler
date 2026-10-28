import { existsSync, mkdirSync, readdirSync, readFileSync, renameSync, rmSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";
import type { PiExec, PiExecResult } from "./cli.ts";

// Until the compiler is on PyPI with its instruction files packaged, the
// compile agent needs a full checkout (it reads .claude/, .pi/prompts/ and
// docs/dialects/ relative to its working directory).
export const COMPILER_REF = "v0.3.1";
export const COMPILER_REPO = "https://github.com/generative-computing/mellea-skills-compiler.git";

const PYTHON_RANGE = ">=3.11,<3.14.4";
// Windows has no python3.x names; the `py` launcher selects a version instead.
const PYTHON_CANDIDATES: Record<"posix" | "win32", { command: string; args: string[] }[]> = {
	posix: ["python3.13", "python3.12", "python3.11", "python3"].map((command) => ({ command, args: [] })),
	win32: [
		...["-3.13", "-3.12", "-3.11"].map((v) => ({ command: "py", args: [v] })),
		{ command: "python", args: [] },
	],
};
const SLOW_STEP_TIMEOUT_MS = 600_000;
const VERSION_CHECK_TIMEOUT_MS = 120_000;
const LOCK_POLL_MS = 250;
// Longer than the slowest possible install (three 10-minute steps).
const STALE_LOCK_MS = 40 * 60_000;

export type CompilerInstall = { cli: string; repoDir: string };
export type Log = (message: string, level?: "info" | "warning" | "error") => void;
export type Platform = NodeJS.Platform;

type Options = {
	home: string;
	ref?: string;
	platform?: Platform;
	removeDir?: (dir: string) => void;
};

// Layout: <root>/builds/<id>/{repo,venv} per install attempt, <root>/current
// names the build in use, <root>/.lock serialises installs across pi sessions.
// Venv scripts and the editable install embed absolute paths, so a build
// can't be moved; instead a new build sits beside the old one and `current`
// is switched only once it works.
export function installPaths(home: string, ref: string = COMPILER_REF, platform: Platform = process.platform) {
	const { join } = pathFor(platform);
	const root = join(home, ".cache", "mellea-skills-compiler", ref);
	return { root, buildsDir: join(root, "builds"), current: join(root, "current"), lock: join(root, ".lock") };
}

export function buildLayout(buildDir: string, platform: Platform = process.platform) {
	const { join } = pathFor(platform);
	const windows = platform === "win32";
	const bin = join(buildDir, "venv", windows ? "Scripts" : "bin");
	return {
		dir: buildDir,
		repoDir: join(buildDir, "repo"),
		venvDir: join(buildDir, "venv"),
		python: join(bin, windows ? "python.exe" : "python"),
		cli: join(bin, windows ? "mellea-skills.exe" : "mellea-skills"),
	};
}

function pathFor(platform: Platform) {
	return platform === "win32" ? path.win32 : path.posix;
}

type Paths = ReturnType<typeof installPaths>;
type Build = ReturnType<typeof buildLayout>;
type Context = Required<Pick<Options, "platform" | "removeDir">> & { exec: PiExec; log: Log; ref: string };

const inFlight = new Map<string, Promise<CompilerInstall>>();

export function ensureCompiler(exec: PiExec, log: Log, opts: Options): Promise<CompilerInstall> {
	const ctx: Context = {
		exec,
		log,
		ref: opts.ref ?? COMPILER_REF,
		platform: opts.platform ?? process.platform,
		removeDir: opts.removeDir ?? ((dir) => rmSync(dir, { recursive: true, force: true })),
	};
	const paths = installPaths(opts.home, ctx.ref, ctx.platform);
	// Commands started together in one pi session share a single install.
	const pending = inFlight.get(paths.root);
	if (pending) return pending;
	const install = ensureCompilerOnce(ctx, paths).finally(() => inFlight.delete(paths.root));
	inFlight.set(paths.root, install);
	return install;
}

async function ensureCompilerOnce(ctx: Context, paths: Paths): Promise<CompilerInstall> {
	const existing = readCurrent(paths, ctx.platform);
	if (existing && (await isWorkingCli(ctx.exec, existing.cli))) return toInstall(existing);

	mkdirSync(paths.root, { recursive: true });
	const release = await acquireLock(paths.lock, ctx.log);
	try {
		// Another pi session may have finished an install while we waited.
		const latest = readCurrent(paths, ctx.platform);
		if (latest && latest.dir !== existing?.dir && (await isWorkingCli(ctx.exec, latest.cli))) {
			return toInstall(latest);
		}
		return await install(ctx, paths, latest);
	} finally {
		release();
	}
}

async function install(ctx: Context, paths: Paths, previous?: Build): Promise<CompilerInstall> {
	const { exec, log, ref, platform } = ctx;
	log(
		previous
			? `The mellea-skills compiler at ${previous.dir} isn't responding; reinstalling ${ref} beside it…`
			: `Setting up the mellea-skills compiler ${ref} (first run only, this can take a few minutes)…`,
	);
	removeLeftoverBuilds(ctx, paths, previous);

	const build = buildLayout(pathFor(platform).join(paths.buildsDir, `${Date.now()}-${process.pid}`), platform);
	try {
		await requireTool(exec, "git", ["--version"], "git is required to download the compiler. Install git and try again.");
		const python = await findPythonToolchain(exec, platform);
		mkdirSync(build.dir, { recursive: true });
		await step(log, `Cloning ${COMPILER_REPO} @ ${ref}`, () =>
			run(exec, "git", ["clone", "--depth", "1", "--branch", ref, COMPILER_REPO, build.repoDir]),
		);
		await step(log, "Creating Python environment", () => python.createVenv(build.venvDir));
		await step(log, "Installing mellea-skills (this can take a few minutes)", () =>
			python.installEditable(build.python, build.repoDir),
		);
		if (!(await isWorkingCli(exec, build.cli))) {
			throw new Error(`The compiler was installed but \`${build.cli} version\` failed. Try again.`);
		}
	} catch (err) {
		tryRemove(ctx, build.dir);
		if (previous) {
			log(`Couldn't reinstall the compiler, so the existing install is kept. ${errorMessage(err)}`, "warning");
			return toInstall(previous);
		}
		throw err;
	}

	writeCurrent(paths, build.dir, platform);
	// On Windows the old build can still be locked by a running command; a
	// later install removes it as a leftover instead.
	if (previous) tryRemove(ctx, previous.dir);
	log(`mellea-skills compiler ready at ${build.dir}`);
	return toInstall(build);
}

function readCurrent(paths: Paths, platform: Platform): Build | undefined {
	if (!existsSync(paths.current)) return undefined;
	const { join, basename } = pathFor(platform);
	const dir = join(paths.buildsDir, basename(readFileSync(paths.current, "utf8").trim()));
	return existsSync(dir) ? buildLayout(dir, platform) : undefined;
}

function writeCurrent(paths: Paths, buildDir: string, platform: Platform): void {
	const tmp = `${paths.current}.${process.pid}.tmp`;
	writeFileSync(tmp, `${pathFor(platform).basename(buildDir)}\n`);
	renameSync(tmp, paths.current);
}

// Only called while holding the lock, so no other session is mid-build; any
// build other than the one in use is left over from an interrupted install.
function removeLeftoverBuilds(ctx: Context, paths: Paths, keep?: Build): void {
	if (!existsSync(paths.buildsDir)) return;
	const { join, basename } = pathFor(ctx.platform);
	for (const entry of readdirSync(paths.buildsDir)) {
		if (entry !== (keep && basename(keep.dir))) tryRemove(ctx, join(paths.buildsDir, entry));
	}
}

function tryRemove(ctx: Context, dir: string): void {
	try {
		ctx.removeDir(dir);
	} catch {
		// Busy (e.g. a Windows file still open); retried as a leftover next install.
	}
}

async function acquireLock(lockDir: string, log: Log): Promise<() => void> {
	let announced = false;
	for (;;) {
		try {
			mkdirSync(lockDir);
		} catch (err) {
			if ((err as NodeJS.ErrnoException).code !== "EEXIST") throw err;
			const holder = lockHolder(lockDir);
			if (isStaleLock(lockDir, holder)) {
				// Re-check right before removing, so we don't drop a lock another
				// waiter has just taken over.
				if (lockHolder(lockDir) === holder) rmSync(lockDir, { recursive: true, force: true });
				continue;
			}
			if (!announced) {
				log("Another pi session is setting up the mellea-skills compiler; waiting for it to finish…");
				announced = true;
			}
			await new Promise((resolve) => setTimeout(resolve, LOCK_POLL_MS));
			continue;
		}
		const release = () => rmSync(lockDir, { recursive: true, force: true });
		try {
			writeFileSync(lockPidFile(lockDir), `${process.pid}\n`);
		} catch (err) {
			release();
			throw err;
		}
		return release;
	}
}

// The lock lives in the user's real filesystem, so the host's path module is right here.
function lockPidFile(lockDir: string): string {
	return path.join(lockDir, "pid");
}

function lockHolder(lockDir: string): number | undefined {
	try {
		return Number(readFileSync(lockPidFile(lockDir), "utf8")) || undefined;
	} catch {
		return undefined;
	}
}

function isStaleLock(lockDir: string, holder: number | undefined): boolean {
	if (holder !== undefined && !isAlive(holder)) return true;
	try {
		return Date.now() - statSync(lockDir).mtimeMs > STALE_LOCK_MS;
	} catch {
		return false;
	}
}

function isAlive(pid: number): boolean {
	try {
		process.kill(pid, 0);
		return true;
	} catch (err) {
		return (err as NodeJS.ErrnoException).code === "EPERM";
	}
}

function toInstall(build: Build): CompilerInstall {
	return { cli: build.cli, repoDir: build.repoDir };
}

type PythonToolchain = {
	createVenv(venvDir: string): Promise<void>;
	installEditable(venvPython: string, repoDir: string): Promise<void>;
};

async function findPythonToolchain(exec: PiExec, platform: Platform): Promise<PythonToolchain> {
	if ((await exec("uv", ["--version"])).code === 0) {
		return {
			createVenv: (venvDir) => run(exec, "uv", ["venv", "--python", PYTHON_RANGE, venvDir]),
			installEditable: (venvPython, repoDir) =>
				run(exec, "uv", ["pip", "install", "--python", venvPython, "-e", repoDir]),
		};
	}

	const candidates = PYTHON_CANDIDATES[platform === "win32" ? "win32" : "posix"];
	for (const { command, args } of candidates) {
		const result = await exec(command, [...args, "--version"]);
		if (result.code === 0 && isSupportedPython(`${result.stdout} ${result.stderr}`)) {
			return {
				createVenv: (venvDir) => run(exec, command, [...args, "-m", "venv", venvDir]),
				installEditable: (venvPython, repoDir) => run(exec, venvPython, ["-m", "pip", "install", "-e", repoDir]),
			};
		}
	}

	const tried = candidates.map(({ command, args }) => [command, ...args].join(" ")).join(", ");
	throw new Error(
		`The compiler needs Python 3.11 to 3.14.3, and none was found (tried uv, ${tried}). ` +
			"Install uv (https://docs.astral.sh/uv/) or a supported Python and try again.",
	);
}

function isSupportedPython(versionOutput: string): boolean {
	const match = versionOutput.match(/Python (\d+)\.(\d+)\.(\d+)/);
	if (!match) return false;
	const [major, minor, patch] = match.slice(1).map(Number);
	if (major !== 3 || minor < 11) return false;
	return minor < 14 || (minor === 14 && patch < 4);
}

async function isWorkingCli(exec: PiExec, cli: string): Promise<boolean> {
	return (await exec(cli, ["version"], { timeout: VERSION_CHECK_TIMEOUT_MS })).code === 0;
}

async function requireTool(exec: PiExec, command: string, args: string[], message: string): Promise<void> {
	if ((await exec(command, args)).code !== 0) throw new Error(message);
}

async function step(log: Log, label: string, action: () => Promise<void>): Promise<void> {
	log(`${label}…`);
	const started = Date.now();
	await action();
	log(`${label}: done (${Math.round((Date.now() - started) / 1000)}s)`);
}

async function run(exec: PiExec, command: string, args: string[]): Promise<void> {
	const result: PiExecResult = await exec(command, args, { timeout: SLOW_STEP_TIMEOUT_MS });
	if (result.code !== 0) {
		const output = (result.stderr || result.stdout).trim().split("\n").slice(-20).join("\n");
		const reason = result.killed ? "timed out" : `exited with code ${result.code}`;
		throw new Error(`Compiler setup failed: \`${command} ${args.join(" ")}\` ${reason}.\n${output}`);
	}
}

function errorMessage(err: unknown): string {
	return err instanceof Error ? err.message : String(err);
}
