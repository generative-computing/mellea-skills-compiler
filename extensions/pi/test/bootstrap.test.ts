import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, existsSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
	COMPILER_REF,
	COMPILER_REPO,
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
		// A real clone / venv / install creates its target dir; mimic that.
		if (command === "git" && args[0] === "clone") mkdirSync(args[args.length - 1], { recursive: true });
		if (command === "uv" && args[0] === "venv") mkdirSync(args[args.length - 1], { recursive: true });
		if (args[0] === "-m" && args[1] === "venv") mkdirSync(args[2], { recursive: true });
		const r = respond(call) ?? fail(127, `${command}: not found`);
		return { stdout: "", stderr: "", code: 0, killed: false, ...r };
	};
	return { exec, calls };
}

function logRecorder() {
	const lines: { message: string; level?: string }[] = [];
	const log: Log = (message, level) => lines.push({ message, level });
	return { log, lines };
}

function newHome(): string {
	return mkdtempSync(join(tmpdir(), "mellea-bootstrap-"));
}

// Happy-path toolchain: git + uv present, built CLI reports a version.
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

test("ready install is reused without cloning", async () => {
	const home = newHome();
	const paths = installPaths(home);
	mkdirSync(paths.repoDir, { recursive: true });
	writeFileSync(paths.marker, "v0.3.0\n");
	const { exec, calls } = fakeExec(happyPath());
	const { log } = logRecorder();

	const install = await ensureCompiler(exec, log, { home });

	assert.deepEqual(install, { cli: paths.cli, repoDir: paths.repoDir });
	assert.equal(calls.some((c) => c.command === "git"), false);
});

test("fresh install clones pinned ref, makes venv with uv, installs -e", async () => {
	const home = newHome();
	const paths = installPaths(home);
	const { exec, calls } = fakeExec(happyPath());
	const { log } = logRecorder();

	const install = await ensureCompiler(exec, log, { home });

	const clone = calls.find((c) => c.command === "git" && c.args[0] === "clone");
	assert.ok(clone, "expected a git clone");
	assert.deepEqual(clone.args.slice(0, 5), ["clone", "--depth", "1", "--branch", COMPILER_REF]);
	assert.equal(clone.args[5], COMPILER_REPO);

	const venv = calls.find((c) => c.command === "uv" && c.args[0] === "venv");
	assert.ok(venv, "expected uv venv");
	assert.deepEqual(venv.args.slice(0, 3), ["venv", "--python", ">=3.11,<3.14.4"]);

	const pip = calls.find((c) => c.command === "uv" && c.args[0] === "pip");
	assert.ok(pip, "expected uv pip install");
	assert.equal(pip.args[1], "install");
	assert.ok(pip.args.includes("-e"));

	assert.equal(clone.args[6], paths.repoDir, "clone directly into the final location");
	assert.equal(venv.args[3], paths.venvDir, "venv directly in the final location");
	assert.deepEqual(install, { cli: paths.cli, repoDir: paths.repoDir });
	assert.ok(existsSync(paths.marker), "completion marker written");
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
	const { log } = logRecorder();

	await ensureCompiler(exec, log, { home });

	const venv = calls.find((c) => c.command === "python3.13" && c.args[0] === "-m");
	assert.ok(venv, "expected python3.13 -m venv");
	assert.equal(venv.args[1], "venv");
	const pip = calls.find((c) => c.command.endsWith("/bin/python") && c.args.join(" ").startsWith("-m pip install"));
	assert.ok(pip, "expected venv python -m pip install");
	assert.ok(pip.args.includes("-e"));
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
	const { log } = logRecorder();

	await assert.rejects(ensureCompiler(exec, log, { home }), /Python 3\.11 to 3\.14\.3/);
});

test("missing git throws a message naming git", async () => {
	const home = newHome();
	const { exec } = fakeExec(
		happyPath((call) => (call.command === "git" ? fail(127, "git: not found") : undefined)),
	);
	const { log } = logRecorder();

	await assert.rejects(ensureCompiler(exec, log, { home }), /git/);
});

test("interrupted install (no marker) is rebuilt, not reused", async () => {
	const home = newHome();
	const paths = installPaths(home);
	mkdirSync(paths.repoDir, { recursive: true });
	writeFileSync(join(paths.root, "leftover"), "");
	const { exec, calls } = fakeExec(happyPath());
	const { log } = logRecorder();

	await ensureCompiler(exec, log, { home });

	assert.ok(calls.some((c) => c.command === "git" && c.args[0] === "clone"), "expected a fresh clone");
	assert.equal(existsSync(join(paths.root, "leftover")), false, "partial root should be wiped first");
});

test("marker present but CLI broken is rebuilt", async () => {
	const home = newHome();
	const paths = installPaths(home);
	mkdirSync(paths.repoDir, { recursive: true });
	writeFileSync(paths.marker, "v0.3.0\n");
	let probes = 0;
	const { exec, calls } = fakeExec(
		happyPath((call) => {
			if (call.command === paths.cli && call.args[0] === "version") {
				probes++;
				return probes === 1 ? fail(1, "broken") : undefined;
			}
			return undefined;
		}),
	);
	const { log } = logRecorder();

	await ensureCompiler(exec, log, { home });

	assert.ok(calls.some((c) => c.command === "git" && c.args[0] === "clone"), "expected a fresh clone");
});

test("install failure removes the half-built root", async () => {
	const home = newHome();
	const paths = installPaths(home);
	const { exec } = fakeExec(
		happyPath((call) => (call.command === "uv" && call.args[0] === "pip" ? fail(1, "resolution failed") : undefined)),
	);
	const { log } = logRecorder();

	await assert.rejects(ensureCompiler(exec, log, { home }), /resolution failed/);
	assert.equal(existsSync(paths.root), false);
});

test("clone failure reports git's stderr and leaves no root", async () => {
	const home = newHome();
	const paths = installPaths(home);
	const { exec } = fakeExec(
		happyPath((call) =>
			call.command === "git" && call.args[0] === "clone"
				? fail(128, "fatal: Remote branch v0.3.0 not found")
				: undefined,
		),
	);
	const { log } = logRecorder();

	await assert.rejects(ensureCompiler(exec, log, { home }), /Remote branch v0\.3\.0 not found/);
	assert.equal(existsSync(paths.root), false);
});

test("concurrent first runs share one install", async () => {
	const home = newHome();
	const { exec, calls } = fakeExec(happyPath());
	const { log } = logRecorder();

	const [a, b] = await Promise.all([ensureCompiler(exec, log, { home }), ensureCompiler(exec, log, { home })]);

	assert.deepEqual(a, b);
	assert.equal(calls.filter((c) => c.command === "git" && c.args[0] === "clone").length, 1);
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
