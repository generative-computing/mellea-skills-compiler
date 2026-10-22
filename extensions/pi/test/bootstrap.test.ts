import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
	COMPILER_REF,
	COMPILER_REPO,
	buildLayout,
	ensureCompiler,
	installPaths,
	type Log,
} from "../extensions/lib/bootstrap.ts";
import type { PiExecResult } from "../extensions/lib/cli.ts";

type Call = { command: string; args: string[] };
type Responder = (call: Call) => Partial<PiExecResult> | undefined;

const ok = (stdout = ""): Partial<PiExecResult> => ({ code: 0, stdout });
const fail = (code = 1, stderr = ""): Partial<PiExecResult> => ({ code, stderr });

function fakeExec(respond: Responder) {
	const calls: Call[] = [];
	const exec = async (command: string, args: string[]): Promise<PiExecResult> => {
		const call = { command, args };
		calls.push(call);
		const r = respond(call) ?? fail(127, `${command}: not found`);
		// A real clone / venv creates its target dir; mimic that on success.
		if (r.code === 0) {
			if (command === "git" && args[0] === "clone") mkdirSync(args[args.length - 1], { recursive: true });
			if (command === "uv" && args[0] === "venv") mkdirSync(args[args.length - 1], { recursive: true });
			if (args[0] === "-m" && args[1] === "venv") mkdirSync(args[2], { recursive: true });
		}
		return { stdout: "", stderr: "", code: 0, killed: false, ...r };
	};
	return { exec, calls };
}

function logRecorder() {
	const lines: { message: string; level?: string }[] = [];
	const log: Log = (message, level) => lines.push({ message, level });
	return { log, lines };
}

const newHome = () => mkdtempSync(join(tmpdir(), "mellea-bootstrap-"));
// For simulated-Windows runs on a POSIX host: a relative home keeps the
// win32-joined paths inside a temp cwd instead of the test's own folder.
function inWindowsTempCwd<T>(fn: () => Promise<T>): Promise<T> {
	const cwd = process.cwd();
	process.chdir(newHome());
	return fn().finally(() => process.chdir(cwd));
}
const clones = (calls: Call[]) => calls.filter((c) => c.command === "git" && c.args[0] === "clone");

// Happy-path toolchain: git + uv present, any built CLI reports a version.
function happyPath(extra: Responder = () => undefined): Responder {
	return (call) => {
		const r = extra(call);
		if (r) return r;
		if (call.command === "git" && call.args[0] === "--version") return ok("git version 2.50.0");
		if (call.command === "git" && call.args[0] === "clone") return ok();
		if (call.command === "uv") return ok();
		if (call.command.endsWith("/bin/mellea-skills") && call.args[0] === "version") return ok("0.3.0");
		return undefined;
	};
}

// A finished install, as left by an earlier session.
function seedInstall(home: string, id = "1-1") {
	const paths = installPaths(home);
	const build = buildLayout(join(paths.buildsDir, id));
	mkdirSync(build.repoDir, { recursive: true });
	mkdirSync(build.venvDir, { recursive: true });
	writeFileSync(paths.current, `${id}\n`);
	return { paths, build };
}

function deadPid(): number {
	const child = spawnSync("true");
	return child.pid as number;
}

test("ready install is reused without cloning", async () => {
	const home = newHome();
	const { build } = seedInstall(home);
	const { exec, calls } = fakeExec(happyPath());

	const install = await ensureCompiler(exec, logRecorder().log, { home });

	assert.deepEqual(install, { cli: build.cli, repoDir: build.repoDir });
	assert.equal(calls.some((c) => c.command === "git"), false);
});

test("fresh install clones pinned ref, makes venv with uv, installs -e", async () => {
	const home = newHome();
	const paths = installPaths(home);
	const { exec, calls } = fakeExec(happyPath());

	const install = await ensureCompiler(exec, logRecorder().log, { home });

	const [clone] = clones(calls);
	assert.ok(clone, "expected a git clone");
	assert.deepEqual(clone.args.slice(0, 6), ["clone", "--depth", "1", "--branch", COMPILER_REF, COMPILER_REPO]);
	const venv = calls.find((c) => c.command === "uv" && c.args[0] === "venv");
	assert.ok(venv, "expected uv venv");
	assert.deepEqual(venv.args.slice(0, 3), ["venv", "--python", ">=3.11,<3.14.4"]);
	const pip = calls.find((c) => c.command === "uv" && c.args[0] === "pip");
	assert.ok(pip?.args.includes("-e"), "expected uv pip install -e");

	const current = readFileSync(paths.current, "utf8").trim();
	assert.deepEqual(install, {
		cli: buildLayout(join(paths.buildsDir, current)).cli,
		repoDir: join(paths.buildsDir, current, "repo"),
	});
	assert.equal(clone.args[6], install.repoDir, "clone directly into the build that becomes current");
});

test("falls back to an in-range python3.x -m venv when uv is missing", async () => {
	const home = newHome();
	const { exec, calls } = fakeExec(
		happyPath((call) => {
			if (call.command === "uv") return fail(127);
			if (call.command === "python3.13" && call.args[0] === "--version") return ok("Python 3.13.1");
			if (call.command === "python3.13" && call.args[0] === "-m") return ok();
			if (call.command.endsWith("/bin/python") && call.args[0] === "-m") return ok();
			return undefined;
		}),
	);

	await ensureCompiler(exec, logRecorder().log, { home });

	assert.ok(calls.some((c) => c.command === "python3.13" && c.args.join(" ").startsWith("-m venv")));
	const pip = calls.find((c) => c.command.endsWith("/bin/python") && c.args.join(" ").startsWith("-m pip install"));
	assert.ok(pip?.args.includes("-e"), "expected venv python -m pip install -e");
});

test("rejects out-of-range pythons", async () => {
	const home = newHome();
	const { exec } = fakeExec(
		happyPath((call) => {
			if (call.command === "uv") return fail(127);
			if (call.command === "python3" && call.args[0] === "--version") return ok("Python 3.15.0");
			return undefined;
		}),
	);

	await assert.rejects(ensureCompiler(exec, logRecorder().log, { home }), /Python 3\.11 to 3\.14\.3/);
});

test("missing git on a fresh install throws a message naming git", async () => {
	const home = newHome();
	const { exec } = fakeExec(happyPath((call) => (call.command === "git" ? fail(127, "git: not found") : undefined)));

	await assert.rejects(ensureCompiler(exec, logRecorder().log, { home }), /git/);
});

test("leftover build from an interrupted install is removed", async () => {
	const home = newHome();
	const paths = installPaths(home);
	mkdirSync(join(paths.buildsDir, "0-interrupted", "repo"), { recursive: true });
	const { exec, calls } = fakeExec(happyPath());

	await ensureCompiler(exec, logRecorder().log, { home });

	assert.equal(clones(calls).length, 1);
	assert.equal(existsSync(join(paths.buildsDir, "0-interrupted")), false);
	assert.equal(readdirSync(paths.buildsDir).length, 1);
});

test("broken install is replaced, and only after the new build works", async () => {
	const home = newHome();
	const { paths, build: old } = seedInstall(home);
	const { exec, calls } = fakeExec(
		happyPath((call) => {
			if (call.command === old.cli) {
				// The old build must still be there when the new one is verified.
				assert.ok(existsSync(old.dir), "old build deleted before the new one was ready");
				return fail(1, "broken");
			}
			return undefined;
		}),
	);

	const install = await ensureCompiler(exec, logRecorder().log, { home });

	assert.equal(clones(calls).length, 1);
	assert.notEqual(install.repoDir, old.repoDir);
	assert.equal(existsSync(old.dir), false, "old build removed after the switch");
	assert.equal(readdirSync(paths.buildsDir).length, 1);
});

test("failed reinstall keeps the existing install (e.g. offline)", async () => {
	const home = newHome();
	const { paths, build: old } = seedInstall(home);
	const { exec } = fakeExec(
		happyPath((call) => {
			if (call.command === old.cli) return fail(1, "timed out");
			if (call.command === "git" && call.args[0] === "clone") return fail(128, "Could not resolve host: github.com");
			return undefined;
		}),
	);
	const { log, lines } = logRecorder();

	const install = await ensureCompiler(exec, log, { home });

	assert.deepEqual(install, { cli: old.cli, repoDir: old.repoDir });
	assert.ok(existsSync(old.repoDir), "existing install must survive a failed reinstall");
	assert.equal(readFileSync(paths.current, "utf8").trim(), "1-1");
	assert.equal(readdirSync(paths.buildsDir).length, 1, "failed build removed");
	assert.ok(lines.some((l) => l.level === "warning" && /existing install is kept/.test(l.message)));
});

test("missing git on a reinstall keeps the existing install", async () => {
	const home = newHome();
	const { build: old } = seedInstall(home);
	const { exec } = fakeExec(
		happyPath((call) => (call.command === old.cli ? fail(1) : call.command === "git" ? fail(127) : undefined)),
	);

	const install = await ensureCompiler(exec, logRecorder().log, { home });

	assert.equal(install.repoDir, old.repoDir);
	assert.ok(existsSync(old.repoDir));
});

test("install failure on a fresh install removes the half-built build", async () => {
	const home = newHome();
	const paths = installPaths(home);
	const { exec } = fakeExec(
		happyPath((call) => (call.command === "uv" && call.args[0] === "pip" ? fail(1, "resolution failed") : undefined)),
	);

	await assert.rejects(ensureCompiler(exec, logRecorder().log, { home }), /resolution failed/);
	assert.equal(existsSync(paths.current), false);
	assert.deepEqual(readdirSync(paths.buildsDir), []);
	assert.equal(existsSync(paths.lock), false, "lock released");
});

test("clone failure reports git's stderr", async () => {
	const home = newHome();
	const { exec } = fakeExec(
		happyPath((call) =>
			call.command === "git" && call.args[0] === "clone" ? fail(128, "fatal: Remote branch v0.3.0 not found") : undefined,
		),
	);

	await assert.rejects(ensureCompiler(exec, logRecorder().log, { home }), /Remote branch v0\.3\.0 not found/);
});

test("concurrent first runs in one session share one install", async () => {
	const home = newHome();
	const { exec, calls } = fakeExec(happyPath());
	const { log } = logRecorder();

	const [a, b] = await Promise.all([ensureCompiler(exec, log, { home }), ensureCompiler(exec, log, { home })]);

	assert.deepEqual(a, b);
	assert.equal(clones(calls).length, 1);
});

test("waits for another pi session's install instead of rebuilding", async () => {
	const home = newHome();
	const paths = installPaths(home);
	mkdirSync(paths.lock, { recursive: true });
	writeFileSync(join(paths.lock, "pid"), `${process.ppid}\n`); // a live process
	const { exec, calls } = fakeExec(happyPath());
	const { log, lines } = logRecorder();

	// The other session finishes its install, then releases the lock.
	setTimeout(() => {
		const id = "9-other";
		mkdirSync(buildLayout(join(paths.buildsDir, id)).repoDir, { recursive: true });
		writeFileSync(paths.current, `${id}\n`);
		rmSync(paths.lock, { recursive: true, force: true });
	}, 400);

	const install = await ensureCompiler(exec, log, { home });

	assert.equal(clones(calls).length, 0, "must not rebuild while another session installs");
	assert.equal(install.repoDir, join(paths.buildsDir, "9-other", "repo"));
	assert.ok(lines.some((l) => /Another pi session/.test(l.message)));
});

test("a lock left by a crashed session is taken over", async () => {
	const home = newHome();
	const paths = installPaths(home);
	mkdirSync(paths.lock, { recursive: true });
	writeFileSync(join(paths.lock, "pid"), `${deadPid()}\n`);
	const { exec, calls } = fakeExec(happyPath());

	await ensureCompiler(exec, logRecorder().log, { home });

	assert.equal(clones(calls).length, 1);
	assert.equal(existsSync(paths.lock), false, "lock released after install");
});

test("windows: venv uses Scripts\\ and .exe paths", () => {
	const build = buildLayout("C:\\cache\\builds\\1", "win32");
	assert.equal(build.cli, "C:\\cache\\builds\\1\\venv\\Scripts\\mellea-skills.exe");
	assert.equal(build.python, "C:\\cache\\builds\\1\\venv\\Scripts\\python.exe");
});

test("windows: fresh install with uv points pip at Scripts\\python.exe", () =>
	inWindowsTempCwd(async () => {
		const { exec, calls } = fakeExec(
			happyPath((call) => (call.command.endsWith("mellea-skills.exe") && call.args[0] === "version" ? ok("0.3.0") : undefined)),
		);

		const install = await ensureCompiler(exec, logRecorder().log, { home: "home", platform: "win32" });

		assert.match(install.cli, /venv\\Scripts\\mellea-skills\.exe$/);
		const pip = calls.find((c) => c.command === "uv" && c.args[0] === "pip");
		assert.match(pip?.args[3] ?? "", /venv\\Scripts\\python\.exe$/);
	}));

test("windows: falls back to the py launcher when uv is missing", () => inWindowsTempCwd(async () => {
	const home = "home";
	const { exec, calls } = fakeExec(
		happyPath((call) => {
			if (call.command === "uv") return fail(127);
			if (call.command === "py" && call.args.join(" ") === "-3.12 --version") return ok("Python 3.12.9");
			if (call.command === "py" && call.args[0] === "-3.12" && call.args[1] === "-m") return ok();
			if (call.command.endsWith("python.exe") && call.args[0] === "-m") return ok();
			if (call.command.endsWith("mellea-skills.exe")) return ok("0.3.0");
			return undefined;
		}),
	);

	await ensureCompiler(exec, logRecorder().log, { home, platform: "win32" });

	assert.ok(calls.some((c) => c.command === "py" && c.args.join(" ").startsWith("-3.12 -m venv")));
	assert.equal(calls.some((c) => c.command.startsWith("python3")), false, "no POSIX python names on windows");
}));

test("old build that can't be deleted (file in use) doesn't fail the install", async () => {
	const home = newHome();
	const { paths, build: old } = seedInstall(home);
	const { exec } = fakeExec(happyPath((call) => (call.command === old.cli ? fail(1) : undefined)));
	const attempted: string[] = [];
	const removeDir = (dir: string) => {
		attempted.push(dir);
		if (dir === old.dir) throw Object.assign(new Error("EBUSY: resource busy or locked"), { code: "EBUSY" });
		rmSync(dir, { recursive: true, force: true });
	};

	const install = await ensureCompiler(exec, logRecorder().log, { home, removeDir });

	assert.ok(attempted.includes(old.dir), "tried to remove the old build");
	assert.notEqual(install.repoDir, old.repoDir);
	assert.notEqual(readFileSync(paths.current, "utf8").trim(), "1-1", "switched to the new build");
	assert.ok(existsSync(old.dir), "busy build is left for a later run to clean up");
});

test("a busy leftover build is cleaned up on a later install", async () => {
	const home = newHome();
	const { paths, build: old } = seedInstall(home);
	mkdirSync(join(paths.buildsDir, "0-busy-leftover"), { recursive: true });
	const { exec } = fakeExec(happyPath((call) => (call.command === old.cli ? fail(1) : undefined)));

	await ensureCompiler(exec, logRecorder().log, { home });

	assert.equal(existsSync(join(paths.buildsDir, "0-busy-leftover")), false);
});

test("logs one line per step", async () => {
	const home = newHome();
	const { exec } = fakeExec(happyPath());
	const { log, lines } = logRecorder();

	await ensureCompiler(exec, log, { home });

	const text = lines.map((l) => l.message).join("\n");
	for (const pattern of [/first run/, /Cloning/, /Creating Python environment/, /Installing mellea-skills/, /ready at/]) {
		assert.match(text, pattern);
	}
});
